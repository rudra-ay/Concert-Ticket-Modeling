"""Show-day weather per show from the Open-Meteo historical archive API (A7)
-> data/interim/features_weather.parquet.

Open-Meteo's archive API is the one robots.txt exception approved in DECISIONS.md (weather only).
Free tier, non-commercial use only; data CC BY 4.0, "Weather data by Open-Meteo.com".

Coordinates, in order of preference:
  1. features_venue.parquet (collector-features, Wikidata venue coordinates);
  2. Census Gazetteer internal point of the venue's matched US place (venue_metro.parquet, features_metro.py).
Non-US venues without venue coordinates get no weather.

Requests: one HTTP request per show date for up to BATCH_LOCATIONS venues (Open-Meteo accepts coordinate
lists), >= 5 s apart, hours venue-local (timezone=auto). Each venue-day is cached as its own file in
data/raw/open_meteo/ and never refetched. Quota pacing keeps us inside the free tier (600/min, 5,000/h,
10,000/day): see QuotaLedger. A 403/429/challenge, or 3 consecutive network failures, stops the run;
partial results are still written and the next run resumes from cache.
"""
from __future__ import annotations

import collections
import datetime as dt
import json
import time
import zipfile

import numpy as np
import pandas as pd
import requests

from features_metro import PLACE_COORD_OVERRIDES
from features_metro import _haversine_km
from context_http import RAW, BlockedError, NetworkDown, TransientError, load_spine, load_venue_coords, out_dir, polite_get, write_atomic

API = "https://archive-api.open-meteo.com/v1/archive"
CACHE = RAW / "open_meteo"
ARCHIVE_LAG_DAYS = 6  # the archive lags real time by about 5 days
EVENING_HOURS = range(18, 24)  # 18:00-23:00 local, inclusive
# Exactly 10 variables and <= 14 days per location, so each location counts as 1.0 API call.
DAILY = ["temperature_2m_max", "temperature_2m_min", "precipitation_sum", "precipitation_hours",
         "wind_speed_10m_max", "weather_code"]
HOURLY = ["temperature_2m", "precipitation", "wind_speed_10m", "weather_code"]
# A cached response for the same venue within this distance is reused (e.g. after a switch from a city
# centroid to Wikidata venue coordinates). The reanalysis grid is ~9-25 km, so this changes nothing material.
REUSE_KM = 5.0
BATCH_LOCATIONS = 20  # 40-venue x 14-day requests timed out ~5% of the time
WINDOW_DAYS = 14  # requests cover fixed 14-day windows: all venues with a show in the window, one call each
WINDOW_EPOCH = dt.date(1970, 1, 5)
MAX_CONSECUTIVE_FAILURES = 3
# Free-tier limits are 600/min, 5,000/h, 10,000/day; stay at 80%.
QUOTA_PER_MIN, QUOTA_PER_HOUR, QUOTA_PER_DAY = 480, 4000, 8000
SNOW_CODES = {71, 73, 75, 77, 85, 86}


class QuotaExhausted(RuntimeError):
    pass


class QuotaLedger:
    """Location-call ledger shared by every process: per UTC day in _quota.json ({date: count}, the format the
    watchdog reads) and the rolling minute/hour windows in _quota_recent.json. Every check-and-update happens
    under an exclusive flock and re-reads the files first, so concurrent or restarted processes can't lose or
    double-count each other's calls."""

    def __init__(self, path=CACHE / "_quota.json"):
        self.path = path
        self.recent_path = path.with_name("_quota_recent.json")
        self.lock_path = path.with_name("_quota.lock")
        self.recent: collections.deque[tuple[float, int]] = collections.deque()  # last acquire, for refund()
        self.days = self._read(self.path, {})

    @staticmethod
    def _today() -> str:
        return dt.datetime.now(dt.timezone.utc).date().isoformat()

    @staticmethod
    def _read(path, default):
        try:
            return json.loads(path.read_text())
        except (FileNotFoundError, ValueError):
            return default

    def _locked(self):
        import contextlib
        import fcntl

        @contextlib.contextmanager
        def cm():
            with open(self.lock_path, "a+") as lk:
                fcntl.flock(lk, fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    fcntl.flock(lk, fcntl.LOCK_UN)
        return cm()

    def acquire(self, n: int) -> None:
        while True:
            with self._locked():
                days = self._read(self.path, {})
                now = time.time()
                recent = [(t, k) for t, k in self._read(self.recent_path, []) if now - t < 3600]
                if days.get(self._today(), 0) + n > QUOTA_PER_DAY:
                    self.days = days
                    raise QuotaExhausted(f"daily budget {QUOTA_PER_DAY} reached; rerun after 00:00 UTC to continue")
                per_min = sum(k for t, k in recent if now - t < 60)
                per_hour = sum(k for _, k in recent)
                if per_min + n <= QUOTA_PER_MIN and per_hour + n <= QUOTA_PER_HOUR:
                    days[self._today()] = days.get(self._today(), 0) + n
                    recent.append((now, n))
                    write_atomic(self.path, json.dumps(days).encode())
                    write_atomic(self.recent_path, json.dumps(recent).encode())
                    self.days = days
                    self.recent.append((now, n))
                    return
            wait = 60 if per_hour + n <= QUOTA_PER_HOUR else 300
            print(f"  quota pacing: sleeping {wait}s", flush=True)
            time.sleep(wait)

    def refund(self, n: int) -> None:
        """Undo this process's latest acquire(n) for a request that never reached the server."""
        with self._locked():
            days = self._read(self.path, {})
            recent = self._read(self.recent_path, [])
            if self.recent and self.recent[-1][1] == n:
                t, _ = self.recent.pop()
                for i in range(len(recent) - 1, -1, -1):
                    if recent[i][0] == t and recent[i][1] == n:
                        recent.pop(i)
                        break
            days[self._today()] = max(0, days.get(self._today(), 0) - n)
            write_atomic(self.path, json.dumps(days).encode())
            write_atomic(self.recent_path, json.dumps(recent).encode())
            self.days = days


def venue_coordinates(spine: pd.DataFrame) -> pd.DataFrame:
    venues = spine[["venue_id"]].drop_duplicates()
    parts = []
    v = load_venue_coords(spine)
    if v is not None:
        vm_conf = out_dir() / "venue_metro.parquet"
        if vm_conf.exists():  # backstop: venue coords > 40 km from the tour table's same-state city
            vmc = pd.read_parquet(vm_conf)
            if "coord_conflict_km" in vmc:
                v = v[~v.venue_id.isin(vmc.loc[vmc.coord_conflict_km.notna(), "venue_id"])]
        parts.append(v[["venue_id", "lat", "lon"]].dropna().assign(coord_source="venue_wikidata"))
    vm_path = out_dir() / "venue_metro.parquet"
    gaz_path = RAW / "census_acs" / "gazetteer" / "2024_Gaz_place_national.zip"
    if vm_path.exists() and gaz_path.exists():
        vm = pd.read_parquet(vm_path)[["venue_id", "place_geoid"]].dropna()
        with zipfile.ZipFile(gaz_path) as z:
            gaz = pd.read_csv(z.open(z.namelist()[0]), sep="\t", dtype={"GEOID": str})
        gaz.columns = [c.strip() for c in gaz.columns]
        g = vm.merge(gaz[["GEOID", "INTPTLAT", "INTPTLONG"]], left_on="place_geoid", right_on="GEOID")
        for geoid, (la, lo) in PLACE_COORD_OVERRIDES.items():
            g.loc[g.GEOID == geoid, ["INTPTLAT", "INTPTLONG"]] = [la, lo]
        parts.append(g.rename(columns={"INTPTLAT": "lat", "INTPTLONG": "lon"})[["venue_id", "lat", "lon"]]
                     .assign(coord_source="census_place_centroid"))
    if not parts:
        return venues.assign(lat=np.nan, lon=np.nan, coord_source=pd.NA)
    coords = pd.concat(parts).drop_duplicates("venue_id", keep="first")  # venue coords win
    return venues.merge(coords, on="venue_id", how="left")


def _coord_key(lat: float, lon: float) -> str:
    return f"{lat:.3f}_{lon:.3f}"


def cache_index() -> dict[str, list[tuple[float, float, dt.date, dt.date, str]]]:
    """venue_id -> [(lat, lon, start, end, path)] for every cached response (single- or multi-day)."""
    idx: dict = collections.defaultdict(list)
    for p in CACHE.glob("*.json"):
        if p.name.startswith("_"):
            continue
        try:
            venue_id, coords, start, end = p.stem.rsplit("__", 3)
            la, lo = (float(x) for x in coords.rsplit("_", 1))
            idx[venue_id].append((la, lo, dt.date.fromisoformat(start), dt.date.fromisoformat(end), str(p)))
        except ValueError:
            continue
    return idx


def cached_path(idx, venue_id: str, lat: float, lon: float, day: dt.date) -> tuple[str | None, float | None]:
    """Closest cached response for this venue covering `day`, if within REUSE_KM of (lat, lon)."""
    best: tuple[float, str] | None = None
    for la, lo, start, end, path in idx.get(venue_id, []):
        if start <= day <= end:
            km = float(_haversine_km(lat, lon, la, lo))
            if km <= REUSE_KM and (best is None or km < best[0]):
                best = (km, path)
    return (best[1], best[0]) if best else (None, None)


def window_of(day: dt.date, last_available: dt.date) -> tuple[dt.date, dt.date]:
    k = (day - WINDOW_EPOCH).days // WINDOW_DAYS
    start = WINDOW_EPOCH + dt.timedelta(days=k * WINDOW_DAYS)
    return start, min(start + dt.timedelta(days=WINDOW_DAYS - 1), last_available)


def fetch_batch(start: dt.date, end: dt.date, locs: pd.DataFrame, ledger: QuotaLedger, state: dict) -> None:
    """Fetch one window for up to BATCH_LOCATIONS venues; write one cache file per venue."""
    day = f"{start}..{end}"
    ledger.acquire(len(locs))
    params = {"latitude": ",".join(f"{x:.4f}" for x in locs.lat), "longitude": ",".join(f"{x:.4f}" for x in locs.lon),
              "start_date": str(start), "end_date": str(end), "daily": ",".join(DAILY), "hourly": ",".join(HOURLY),
              "timezone": "auto", "wind_speed_unit": "kmh"}
    try:
        body = json.loads(polite_get(API, params=params, expect_json=True))
    except requests.HTTPError as e:
        print(f"  skip {day} ({len(locs)} venues): {e}", flush=True)
        return
    except (requests.Timeout, requests.ConnectionError, TransientError) as e:
        # Transient (timeout, connection error, 5xx, empty body): skip this batch without retrying it now; it stays
        # uncached, so a later pass picks it up. Back off 60 s, 120 s; three in a row -> NetworkDown.
        state["failures"] += 1
        print(f"  transient failure {state['failures']}/{MAX_CONSECUTIVE_FAILURES} on {day}: "
              f"{type(e).__name__}: {str(e)[:160]}", flush=True)
        if state["failures"] >= MAX_CONSECUTIVE_FAILURES:
            raise NetworkDown(f"{state['failures']} consecutive transient failures from Open-Meteo") from e
        time.sleep(60 * 2 ** (state["failures"] - 1))
        return
    state["failures"] = 0
    results = body if isinstance(body, list) else [body]
    if len(results) != len(locs):
        print(f"  skip {day}: got {len(results)} results for {len(locs)} locations", flush=True)
        return
    for loc, res in zip(locs.itertuples(index=False), results):
        write_atomic(CACHE / f"{loc.venue_id}__{_coord_key(loc.lat, loc.lon)}__{start}__{end}.json",
                     json.dumps(res).encode())
    state["fetched"] += len(locs)


def summarise(resp: dict, day: dt.date) -> dict:
    rec: dict = {"wx_grid_lat": resp.get("latitude"), "wx_grid_lon": resp.get("longitude"),
                 "wx_timezone": resp.get("timezone"), "wx_elevation_m": resp.get("elevation")}
    daily = pd.DataFrame(resp["daily"])
    row = daily[daily.time == str(day)]
    if row.empty:
        return rec
    r = row.iloc[0]
    rec.update(
        wx_temp_max_c=r.temperature_2m_max, wx_temp_min_c=r.temperature_2m_min,
        wx_precip_mm=r.precipitation_sum, wx_precip_hours=r.precipitation_hours,
        wx_wind_max_kmh=r.wind_speed_10m_max, wx_weather_code=r.weather_code,
        wx_snow_day=(int(r.weather_code) in SNOW_CODES) if pd.notna(r.weather_code) else None,
    )
    hourly = pd.DataFrame(resp["hourly"])
    hourly["time"] = pd.to_datetime(hourly.time)
    ev = hourly[(hourly.time.dt.date == day) & hourly.time.dt.hour.isin(EVENING_HOURS)]
    if len(ev):
        rec.update(
            wx_eve_temp_mean_c=ev.temperature_2m.mean(),
            wx_eve_precip_mm=ev.precipitation.sum(min_count=1),
            wx_eve_precip_hours=int((ev.precipitation >= 0.1).sum()),
            wx_eve_wind_max_kmh=ev.wind_speed_10m.max(),
            wx_eve_weather_code_max=ev.weather_code.max(),
            wx_eve_thunderstorm=bool((ev.weather_code >= 95).any()),
            wx_eve_hours_covered=len(ev),
        )
    return rec


def _table(shows: pd.DataFrame, last_available: dt.date, unfetched: str) -> pd.DataFrame:
    idx = cache_index()
    rows = []
    for s in shows.itertuples(index=False):
        rec = {"show_id": s.show_id, "wx_priced_show": s.priced, "wx_coord_source": s.coord_source,
               "wx_query_lat": s.lat, "wx_query_lon": s.lon}
        if pd.isna(s.day):
            rec["wx_status"] = "no_date"
        elif pd.isna(s.lat):
            rec["wx_status"] = "no_coordinates"
        elif s.day > last_available:
            rec["wx_status"] = "not_yet_in_archive"
        else:
            path, km = cached_path(idx, s.venue_id, s.lat, s.lon, s.day)
            if path is None:
                rec["wx_status"] = unfetched
            else:
                rec["wx_coord_reuse_km"] = round(km, 2)
                with open(path) as f:
                    rec.update(summarise(json.load(f), s.day))
                rec["wx_status"] = "ok" if "wx_temp_max_c" in rec else "date_missing_in_response"
        rows.append(rec)
    out = pd.DataFrame(rows)
    out["wx_known_at_purchase"] = False  # show-day weather: context variable, not a purchase-time feature
    for c in ["wx_eve_precip_hours", "wx_eve_hours_covered"]:
        if c in out:
            out[c] = out[c].astype("Int16")
    for c in ["wx_eve_thunderstorm", "wx_snow_day", "wx_priced_show"]:
        if c in out:
            out[c] = out[c].astype("boolean")
    return out


def write_table(out: pd.DataFrame, label: str) -> None:
    path = out_dir() / "features_weather.parquet"
    out.to_parquet(path, index=False)
    priced = out[out.wx_priced_show.fillna(False)]
    print(f"wrote {path} [{label}]: {len(out)} rows; priced shows ok "
          f"{(priced.wx_status == 'ok').mean():.1%} of {len(priced)}", flush=True)
    print(out.wx_status.value_counts().to_string(), flush=True)


def build(spine: pd.DataFrame, today: dt.date | None = None) -> tuple[pd.DataFrame, str | None]:
    """Fetch priced shows' venue-windows first, write a checkpoint table, then the rest."""
    today = today or dt.date.today()
    last_available = today - dt.timedelta(days=ARCHIVE_LAG_DAYS)
    price = spine["avg_price_usd"] if "avg_price_usd" in spine else pd.Series(np.nan, index=spine.index)
    shows = spine[["show_id", "venue_id", "date"]].assign(priced=price.notna().values)
    shows = shows.merge(venue_coordinates(spine), on="venue_id", how="left")
    shows["day"] = shows.date.dt.date
    need = shows.dropna(subset=["lat", "lon", "day"])
    need = need[need.day <= last_available]
    need = need.groupby(["venue_id", "day"], as_index=False).agg(
        lat=("lat", "first"), lon=("lon", "first"), priced=("priced", "max"))

    idx = cache_index()
    need["path"] = [cached_path(idx, r.venue_id, r.lat, r.lon, r.day)[0] for r in need.itertuples()]
    todo = need[need.path.isna()].copy()
    win = [window_of(d, last_available) for d in todo.day]
    todo["w_start"], todo["w_end"] = [w[0] for w in win], [w[1] for w in win]
    todo = todo.groupby(["venue_id", "w_start", "w_end"], as_index=False).agg(
        lat=("lat", "first"), lon=("lon", "first"), priced=("priced", "max"))
    n_pri = int(todo.priced.sum())
    print(f"{len(need)} venue-days with coordinates; {len(todo)} venue-windows to fetch "
          f"({n_pri} with a priced show first, then {len(todo) - n_pri})", flush=True)

    stop_reason = None
    ledger, state = QuotaLedger(), {"failures": 0, "fetched": 0}
    try:
        for phase, part in (("priced", todo[todo.priced]), ("unpriced", todo[~todo.priced])):
            for i, ((w_start, w_end), g) in enumerate(part.sort_values("w_start").groupby(["w_start", "w_end"])):
                for k in range(0, len(g), BATCH_LOCATIONS):
                    fetch_batch(w_start, w_end, g.iloc[k:k + BATCH_LOCATIONS], ledger, state)
                if i % 50 == 0:
                    print(f"  [{phase}] {i} windows done, {state['fetched']} venue-windows fetched this run", flush=True)
            if phase == "priced":
                write_table(_table(shows, last_available, "pending"), "checkpoint: priced slice complete")
                print("PRIORITY SLICE DONE", flush=True)
    except (QuotaExhausted, BlockedError, NetworkDown) as e:
        stop_reason = f"{type(e).__name__}: {e}"
        print(f"STOPPED: {stop_reason}", flush=True)

    return _table(shows, last_available, "pending" if stop_reason else "request_failed"), stop_reason


def run_once() -> str | None:
    out, stop_reason = build(load_spine())
    write_table(out, "PARTIAL: rerun to resume" if stop_reason else "pass complete")
    return stop_reason


def main() -> None:
    """`--until-done`: after a daily-quota stop, wait for 00:05 UTC and continue (rereads the current spine)."""
    import sys

    until_done = "--until-done" in sys.argv
    while True:
        stop_reason = run_once()
        if stop_reason and stop_reason.startswith("BlockedError"):
            print("EXIT context_http.BlockedError", flush=True)
            raise SystemExit(2)  # pushback: a human should look before the next run
        if stop_reason and stop_reason.startswith("NetworkDown"):
            print("EXIT context_http.NetworkDown", flush=True)
            raise SystemExit(4)  # the supervisor restarts once the host resolves again
        if not (until_done and stop_reason and stop_reason.startswith("QuotaExhausted")):
            return
        now = dt.datetime.now(dt.timezone.utc)
        resume = dt.datetime.combine(now.date() + dt.timedelta(days=1), dt.time(0, 5), dt.timezone.utc)
        print(f"waiting until {resume:%Y-%m-%d %H:%M} UTC for the next daily budget", flush=True)
        time.sleep((resume - now).total_seconds())


if __name__ == "__main__":
    main()
