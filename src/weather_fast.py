"""Faster show-day weather: same cache, same table, far fewer requests than features_weather.py.

Usage:
  .venv/bin/python src/weather_fast.py --plan          # count what is left; no requests
  .venv/bin/python src/weather_fast.py --until-done    # fetch priced shows, wait for quota resets
  add --all to include unpriced shows (not used by the LEVEL analysis)

What changed vs features_weather.py:
- Per-location dates. Open-Meteo accepts start_date/end_date as comma lists (one per coordinate; verified
  2026-10-20), so a request carries BATCH_LOCATIONS venue-windows from any dates, not just the venues that
  share one fixed 14-day window. Before, most requests held ~2 locations and the 5 s spacing was the
  bottleneck; now the quota is.
- Fewer calls. Each venue's uncached show days are covered greedily with windows of <= 14 days that start
  at a show day, instead of fixed calendar windows, so a run of nights split by a window boundary costs 1
  call, not 2.
- Quota at 95% of the free tier (9,500/day, 4,750/h, 570/min), up from 80%.
Unchanged: >= 5 s end-to-start spacing and stop-on-pushback (polite_get), cache file format (the table is
built by features_weather._table), CC BY 4.0 attribution.
"""
from __future__ import annotations

import datetime as dt
import json
import sys
import time

import pandas as pd
import requests

import features_weather as fw
import sticky_dns  # noqa: F401  (patches socket.getaddrinfo: flaky campus DNS)
from context_http import BlockedError, NetworkDown, TransientError, load_spine, polite_get, write_atomic

fw.QUOTA_PER_MIN, fw.QUOTA_PER_HOUR, fw.QUOTA_PER_DAY = 570, 4750, 9500  # read by QuotaLedger at call time
BATCH_LOCATIONS = 10  # 20 stalled now and then; at 10, 5 s spacing still outpaces the 4,750/h quota
REQUEST_DEADLINE_S = 60  # typical response 1-2 s; a stuck stream is abandoned and retried on a later pass


def plan(spine: pd.DataFrame, include_unpriced: bool, today: dt.date | None = None):
    """-> (shows table for _table, segments to fetch: venue_id, lat, lon, start, end, priced)."""
    today = today or dt.date.today()
    last_available = today - dt.timedelta(days=fw.ARCHIVE_LAG_DAYS)
    price = spine["avg_price_usd"] if "avg_price_usd" in spine else pd.Series(float("nan"), index=spine.index)
    shows = spine[["show_id", "venue_id", "date"]].assign(priced=price.notna().values)
    shows = shows.merge(fw.venue_coordinates(spine), on="venue_id", how="left")
    shows["day"] = shows.date.dt.date
    need = shows.dropna(subset=["lat", "lon", "day"])
    need = need[need.day <= last_available]
    if not include_unpriced:
        need = need[need.priced]
    need = need.groupby(["venue_id", "day"], as_index=False).agg(
        lat=("lat", "first"), lon=("lon", "first"), priced=("priced", "max"))
    idx = fw.cache_index()
    cached = [fw.cached_path(idx, r.venue_id, r.lat, r.lon, r.day)[0] is not None for r in need.itertuples()]
    todo = need[~pd.Series(cached, index=need.index)].sort_values(["venue_id", "day"])
    segs = []
    for venue_id, g in todo.groupby("venue_id", sort=False):
        days, lat, lon = list(g.day), g.lat.iat[0], g.lon.iat[0]
        i = 0
        while i < len(days):
            start, j = days[i], i
            while j + 1 < len(days) and (days[j + 1] - start).days < fw.WINDOW_DAYS:
                j += 1
            segs.append({"venue_id": venue_id, "lat": lat, "lon": lon, "start": start, "end": days[j],
                         "priced": bool(g.priced.iloc[i:j + 1].any())})
            i = j + 1
    segs = pd.DataFrame(segs, columns=["venue_id", "lat", "lon", "start", "end", "priced"])
    # Priced first, then by date so the requests group similar eras (smaller responses vary less).
    segs = segs.sort_values(["priced", "start"], ascending=[False, True], ignore_index=True)
    return shows, last_available, segs


def fetch(batch: pd.DataFrame, ledger: fw.QuotaLedger, state: dict) -> None:
    ledger.acquire(len(batch))
    params = {"latitude": ",".join(f"{x:.4f}" for x in batch.lat),
              "longitude": ",".join(f"{x:.4f}" for x in batch.lon),
              "start_date": ",".join(str(d) for d in batch.start), "end_date": ",".join(str(d) for d in batch.end),
              "daily": ",".join(fw.DAILY), "hourly": ",".join(fw.HOURLY), "timezone": "auto",
              "wind_speed_unit": "kmh"}
    try:
        body = json.loads(polite_get(fw.API, params=params, expect_json=True, deadline=REQUEST_DEADLINE_S))
    except requests.HTTPError as e:
        print(f"  skip batch ({len(batch)}): {e}", flush=True)
        return
    except (requests.Timeout, requests.ConnectionError, TransientError) as e:
        state["failures"] += 1
        print(f"  transient failure {state['failures']}/{fw.MAX_CONSECUTIVE_FAILURES}: "
              f"{type(e).__name__}: {str(e)[:160]}", flush=True)
        if state["failures"] >= fw.MAX_CONSECUTIVE_FAILURES:
            raise NetworkDown(f"{state['failures']} consecutive transient failures from Open-Meteo") from e
        time.sleep(15 * 2 ** (state["failures"] - 1))
        return
    state["failures"] = 0
    results = body if isinstance(body, list) else [body]
    if len(results) != len(batch):
        print(f"  skip batch: got {len(results)} results for {len(batch)} locations", flush=True)
        return
    for s, res in zip(batch.itertuples(index=False), results):
        write_atomic(fw.CACHE / f"{s.venue_id}__{fw._coord_key(s.lat, s.lon)}__{s.start}__{s.end}.json",
                     json.dumps(res).encode())
    state["fetched"] += len(batch)


def run_once(include_unpriced: bool) -> str | None:
    shows, last_available, segs = plan(load_spine(), include_unpriced)
    print(f"{len(segs)} venue-windows to fetch ({int(segs.priced.sum())} priced); "
          f"{BATCH_LOCATIONS} per request", flush=True)
    ledger, state, stop_reason = fw.QuotaLedger(), {"failures": 0, "fetched": 0}, None
    try:
        for k in range(0, len(segs), BATCH_LOCATIONS):
            fetch(segs.iloc[k:k + BATCH_LOCATIONS], ledger, state)
            if (k // BATCH_LOCATIONS) % 25 == 0:
                print(f"  {k + BATCH_LOCATIONS}/{len(segs)} sent, {state['fetched']} fetched this run", flush=True)
            if (k // BATCH_LOCATIONS) % 250 == 249:  # checkpoint table about every 5,000 venue-windows
                fw.write_table(fw._table(shows, last_available, "pending"), "checkpoint")
    except (fw.QuotaExhausted, BlockedError, NetworkDown) as e:
        stop_reason = f"{type(e).__name__}: {e}"
        print(f"STOPPED: {stop_reason}", flush=True)
    label = "PARTIAL: rerun to resume" if stop_reason else "pass complete"
    fw.write_table(fw._table(shows, last_available, "pending" if stop_reason else "request_failed"), label)
    return stop_reason


def main() -> None:
    include_unpriced = "--all" in sys.argv
    if "--plan" in sys.argv:
        _, _, segs = plan(load_spine(), include_unpriced)
        pri = int(segs.priced.sum())
        print(f"to fetch: {len(segs)} venue-windows = {len(segs)} API calls ({pri} priced, {len(segs) - pri} unpriced); "
              f"{-(-len(segs) // BATCH_LOCATIONS)} requests")
        return
    while True:
        stop_reason = run_once(include_unpriced)
        if stop_reason and stop_reason.startswith("BlockedError"):
            print("EXIT context_http.BlockedError", flush=True)
            raise SystemExit(2)
        if stop_reason and stop_reason.startswith("NetworkDown"):
            print("EXIT context_http.NetworkDown", flush=True)
            raise SystemExit(4)
        if not ("--until-done" in sys.argv and stop_reason and stop_reason.startswith("QuotaExhausted")):
            return
        now = dt.datetime.now(dt.timezone.utc)
        resume = dt.datetime.combine(now.date() + dt.timedelta(days=1), dt.time(0, 5), dt.timezone.utc)
        print(f"waiting until {resume:%Y-%m-%d %H:%M} UTC for the next daily budget", flush=True)
        time.sleep((resume - now).total_seconds())


if __name__ == "__main__":
    main()
