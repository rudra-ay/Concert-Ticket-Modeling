"""PATH part 2 + 3: data-readiness schedule for the forward Ticketmaster panel, and the
watchlist-expansion scenarios.

Definitions
- A complete h-day path = daily snapshots from h days before the show through show day
  (days_until_show = h ... 0), i.e. the event was first snapshotted >= h days out, and at
  most floor(0.1 * (h + 1)) of those h + 1 days are missing (FORWARD_COLLECTOR.md section 4).
  It completes on the show's local date.
- "priced" = the path also has a valid face-value range (min > 0). For events already on the
  watchlist we use the latest snapshot; for simulated additions we use the candidate's
  has_price_ranges flag times (1 - the observed share of $0.00 placeholder ranges).
- Expected counts: each event contributes P(complete) = P(Binomial(h + 1, p_miss) <= allowed),
  using p_miss = the observed per-event daily miss rate (days already missed are counted
  exactly). Whole-day outages (Mac off all day) are not in p_miss; see the sensitivity table.

Scenarios simulate the collector's own selection (forward_collector.select_panel, option (b))
day by day from 2026-10-22, topping the active watchlist up to `target` from the candidate
pool already in discover_candidates. The pool only contains events seen by discover so far
(shows up to ~2027-02-18), so top-ups after mid-January are undercounted, which makes later
dates conservative (too late, never too early).

Outputs: reports/path_tables/readiness_*.csv, readiness_summary.json,
reports/charts/path_readiness.png. Read-only on the panel; no API calls.
Run: .venv/bin/python src/analysis/path_readiness.py
"""
from __future__ import annotations

import json
import math
import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import forward_collector as fc  # noqa: E402  (pure functions only: select_panel, EXCLUDE_NAME_RE)
from analysis.path_common import INK2, MUTED, S1, S2, S3, TABLES, connect_ro, plt, save  # noqa: E402

HORIZONS = [7, 14, 30, 60]
THRESHOLDS = [200, 500, 1000]
SIM_START = date(2026, 10, 22)
SIM_END = date(2027, 6, 30)
SCENARIOS = {  # name -> (target from SIM_START, far_share, new day-120 arrivals simulated)
    "A status quo (3,000, far 60%)": (3000, 0.6, True),
    "B expand to 4,000 (far 60%)": (4000, 0.6, True),
    "C expand to 4,000 (far 30%)": (4000, 0.3, True),
    "A0 status quo, known pool only": (3000, 0.6, False),
    "B0 expand to 4,000, known pool only": (4000, 0.6, False),
}


def allowed_misses(h: int) -> int:
    return math.floor(0.1 * (h + 1))


def p_complete(days_left: int, misses_so_far: int, h: int, p_miss: float) -> float:
    """P(total misses <= allowed) when days_left future days each miss with prob p_miss."""
    budget = allowed_misses(h) - misses_so_far
    if budget < 0:
        return 0.0
    n = max(days_left, 0)
    return float(sum(math.comb(n, k) * p_miss ** k * (1 - p_miss) ** (n - k) for k in range(0, min(budget, n) + 1)))


def load_current(today: date) -> tuple[pd.DataFrame, float, float]:
    con = connect_ro()
    w = pd.read_sql("SELECT event_id, event_date, active, deactivated_why, source, selected_for_ranges, "
                    "selection_prob, stratum FROM watchlist", con)
    s = pd.read_sql("SELECT event_id, snap_date, has_price_ranges, price_min FROM snapshots WHERE http_status=200",
                    con)
    con.close()
    s["valid"] = (s.has_price_ranges == 1) & (s.price_min > 0)
    placeholder_share = float(((s.has_price_ranges == 1) & ~s.valid).sum() / max((s.has_price_ranges == 1).sum(), 1))
    first = s.groupby("event_id").snap_date.min().rename("first_snap")
    last = s.sort_values("snap_date").groupby("event_id").valid.last().rename("priced")
    days = s.groupby("event_id").snap_date.apply(set).rename("days")
    w = w.join(first, on="event_id").join(last, on="event_id").join(days, on="event_id")
    w = w[w.first_snap.notna() & (w.deactivated_why.fillna("") != "cancelled")].copy()
    w["event_date"] = pd.to_datetime(w.event_date).dt.date
    w["first_snap"] = pd.to_datetime(w.first_snap).dt.date
    # per-event daily miss rate on days after an event's first snapshot (active, show not passed)
    exp = obs = 0
    for _, r in w.iterrows():
        d = r.first_snap + timedelta(days=1)
        while d <= min(today, r.event_date):
            exp += 1
            obs += d.isoformat() in r.days
            d += timedelta(days=1)
    p_miss = 1 - obs / exp if exp else 0.0
    return w, p_miss, placeholder_share


def misses_in_window(r, h: int, today: date) -> int:
    start = max(r.first_snap, r.event_date - timedelta(days=h))
    m, d = 0, start
    while d <= min(today, r.event_date):
        m += d.isoformat() not in r.days
        d += timedelta(days=1)
    return m


def load_candidates() -> list[dict]:
    con = connect_ro()
    cols = ["event_id", "name", "local_date", "event_status", "segment", "genre", "venue_id", "state",
            "attraction_ids", "has_price_ranges", "first_seen_on", "first_has_ranges", "ranges_seen_on"]
    c = pd.read_sql(f"SELECT {','.join(cols)} FROM discover_candidates WHERE event_id NOT IN "
                    "(SELECT event_id FROM watchlist) AND COALESCE(event_status,'') != 'cancelled' "
                    "AND COALESCE(segment,'Music') = 'Music'", con)
    con.close()
    c = c[~c.name.fillna("").map(lambda n: bool(fc.EXCLUDE_NAME_RE.search(n)))]
    c = c.astype(object).where(c.notna(), None)
    return c.to_dict("records")


def load_existing() -> list[tuple]:
    """(event_date, venue_id, attraction_ids) of active watchlist events; discover() seeds its
    diversity caps with the active ones."""
    con = connect_ro()
    rows = con.execute("SELECT w.event_date, c.venue_id, c.attraction_ids FROM watchlist w "
                       "JOIN discover_candidates c USING(event_id) WHERE w.active=1").fetchall()
    con.close()
    return [(date.fromisoformat(d), v, a) for d, v, a in rows if d]


def arrival_template() -> tuple[list[dict], float]:
    """Events 90-120 days out in the first full scan (2026-10-19), all of them (watchlisted or not):
    the mix a new day-120 slice brings. Returns (template rows, arrivals per day)."""
    con = connect_ro()
    cols = ["event_id", "name", "local_date", "event_status", "segment", "genre", "venue_id", "state",
            "attraction_ids", "has_price_ranges"]
    t = pd.read_sql(f"SELECT {','.join(cols)} FROM discover_candidates WHERE local_date BETWEEN "
                    "'2027-01-17' AND '2027-02-16' AND COALESCE(event_status,'') != 'cancelled' "
                    "AND COALESCE(segment,'Music') = 'Music'", con)
    con.close()
    t = t[~t.name.fillna("").map(lambda n: bool(fc.EXCLUDE_NAME_RE.search(n)))]
    t = t.astype(object).where(t.notna(), None)
    return t.to_dict("records"), len(t) / 31


def simulate(cur: pd.DataFrame, cands: list[dict], target: int, far_share: float,
             arrivals: bool) -> pd.DataFrame:
    """Day-by-day top-up with the collector's selection. Returns added events with path start.

    arrivals=True adds, for each day whose day-120 slice has not been scanned yet, synthetic
    events resampled from the observed 90-120-day mix at the observed rate (seeded)."""
    import bisect
    import random
    active_dates = sorted(cur.loc[cur.event_date >= SIM_START, "event_date"].tolist())
    pool = {c["event_id"]: c for c in cands}
    existing = load_existing()
    template, rate = arrival_template()
    rng = random.Random("arrivals")
    last_scanned = max(date.fromisoformat(c["local_date"]) for c in cands)
    added = []
    d = SIM_START
    carry = 0.0
    while d <= SIM_END:
        new_slice = d + timedelta(days=120)
        if arrivals and new_slice > last_scanned:
            carry += rate
            k, carry = int(carry), carry - int(carry)
            for i in range(k):
                c = dict(rng.choice(template))
                c["event_id"] = f"synthetic-{new_slice.isoformat()}-{i}"
                c["local_date"] = new_slice.isoformat()
                pool[c["event_id"]] = c
        # events whose show date has passed drop off; adds stay until their show date
        active = len(active_dates) - bisect.bisect_left(active_dates, d)
        slots = max(0, target - active)
        if slots:
            window = [c for c in pool.values()
                      if 1 <= (date.fromisoformat(c["local_date"]) - d).days <= 120]
            ex = [(v, a) for ed, v, a in existing if ed >= d]
            chosen = fc.select_panel(window, slots, d, far_share, seed=d.isoformat(), existing=ex)
            for p in chosen:
                c = pool.pop(p["event_id"])
                ed = date.fromisoformat(c["local_date"])
                bisect.insort(active_dates, ed)
                existing.append((ed, c.get("venue_id"), c.get("attraction_ids")))
                added.append({"event_id": p["event_id"], "event_date": ed, "first_snap": d,
                              "has_ranges": int(bool(c.get("has_price_ranges"))),
                              "synthetic": p["event_id"].startswith("synthetic-"),
                              "selection_prob": p["selection_prob"], "selected_for_ranges": p["selected_for_ranges"]})
        d += timedelta(days=1)
    return pd.DataFrame(added)


def expected_paths(cur: pd.DataFrame, add: pd.DataFrame, today: date, p_miss: float, placeholder: float,
                   h: int) -> pd.DataFrame:
    """One row per event with an h-day path possible: completion date, P(complete), P(priced)."""
    rows = []
    for _, r in cur.iterrows():
        if (r.event_date - r.first_snap).days < h or r.event_date <= today:
            continue
        m = misses_in_window(r, h, today)
        start = max(r.first_snap, r.event_date - timedelta(days=h))
        left = (r.event_date - max(today + timedelta(days=1), start)).days + 1
        pc = p_complete(left, m, h, p_miss)
        rows.append((r.event_date, pc, pc * float(bool(r.priced)), r.selection_prob if r.source != "discover-pilot"
                     else np.nan))
    for _, r in add.iterrows() if len(add) else []:
        if (r.event_date - r.first_snap).days < h:
            continue
        pc = p_complete(h + 1, 0, h, p_miss)
        rows.append((r.event_date, pc, pc * r.has_ranges * (1 - placeholder), r.selection_prob))
    return pd.DataFrame(rows, columns=["date", "p", "p_priced", "selection_prob"])


def first_date(paths: pd.DataFrame, col: str, n: int) -> str:
    if paths.empty:
        return "never"
    t = paths.groupby("date")[col].sum().sort_index().cumsum()
    hit = t[t >= n]
    return hit.index[0].isoformat() if len(hit) else f"after {SIM_END.isoformat()}"


def ess(paths: pd.DataFrame, by: date) -> dict:
    q = paths[(paths.date <= by) & paths.selection_prob.notna() & (paths.selection_prob > 0)]
    w = (1 / q.selection_prob) * q.p
    if w.sum() == 0:
        return {"n_expected": 0, "kish_ess": 0, "weight_cv": None}
    return {"n_expected": round(float(q.p.sum()), 1), "kish_ess": round(float(w.sum() ** 2 / (w ** 2).sum()), 1),
            "weight_cv": round(float(np.sqrt(np.cov(1 / q.selection_prob, aweights=q.p)) /
                                     np.average(1 / q.selection_prob, weights=q.p)), 3)}


def quota_math(target: int) -> dict:
    con = connect_ro()
    a = pd.read_sql("SELECT a.day, a.calls, (SELECT COUNT(*) FROM snapshots s WHERE s.snap_date=a.day) AS snaps "
                    "FROM api_calls a", con)
    runs = pd.read_sql("SELECT snap_date, command, calls_used FROM runs", con)
    con.close()
    disc = runs[runs.command == "discover"].groupby("snap_date").calls_used.sum()
    con = connect_ro()
    big = con.execute("SELECT calls_used, (julianday(finished_at) - julianday(started_at)) * 1440 FROM runs "
                      "WHERE command = 'daily' AND finished_at IS NOT NULL ORDER BY calls_used DESC LIMIT 1").fetchone()
    con.close()
    calls_per_min = big[0] / big[1]
    steady = a[a.day > "2026-10-19"]  # day 1 included the pilot and the first full discover
    overhead = float(((steady.calls - steady.snaps - disc.reindex(steady.day).fillna(0).values) / steady.snaps).max())
    rescan = int(disc.max())
    rescan_reserve = 250
    retry_margin = max(overhead, 0.03)
    worst = math.ceil(target * (1 + retry_margin) + rescan_reserve)
    return {"target": target, "observed_overhead_max_pct": round(100 * overhead, 2), "retry_margin_pct": round(100 * retry_margin, 1),
            "observed_full_rescan_calls": rescan, "rescan_reserve": rescan_reserve,
            "worst_case_day_calls": worst, "budget": fc.DEFAULT_BUDGET, "headroom": fc.DEFAULT_BUDGET - worst,
            "max_safe_target": math.floor((fc.DEFAULT_BUDGET - rescan_reserve) / (1 + retry_margin)),
            # TM's quota is a rolling 24 h window (collector-path, 2026-10-21): a catch-up run less than
            # 24 h before the next scheduled run leaves this many calls for the second run until the
            # first run's calls age out
            "back_to_back_second_run_calls_available": max(0, fc.DEFAULT_BUDGET - math.ceil(target * (1 + retry_margin))),
            "observed_calls_per_min": round(calls_per_min, 1),
            "est_run_minutes_observed_rate": round(worst / calls_per_min)}


def main() -> dict:
    TABLES.mkdir(parents=True, exist_ok=True)
    today = SIM_START - timedelta(days=1)
    cur, p_miss, placeholder = load_current(today)
    cands = load_candidates()
    out: dict = {"today": today.isoformat(), "p_miss_per_event_day": round(p_miss, 4),
                 "placeholder_share": round(placeholder, 3), "current_events": len(cur),
                 "candidates_not_on_watchlist": len(cands),
                 "candidate_max_date": max(c["local_date"] for c in cands), "scenarios": {}}
    sched_rows, curve = [], {}
    template, rate = arrival_template()
    out["arrivals_per_day"] = round(rate, 1)
    out["arrival_template_ranges_share"] = round(float(np.mean([bool(t["has_price_ranges"]) for t in template])), 3)
    for name, (target, far, arr) in SCENARIOS.items():
        add = simulate(cur, cands, target, far, arr)
        sc = {"target": target, "far_share": far, "arrivals": arr, "added_events": len(add),
              "added_synthetic": int(add.synthetic.sum()) if len(add) else 0,
              "added_with_ranges": int(add.has_ranges.sum()) if len(add) else 0,
              "added_by_2026_10_22": int((add.first_snap == SIM_START).sum()) if len(add) else 0,
              "quota": quota_math(target), "dates": {}, "ipw": {}}
        for h in HORIZONS:
            paths = expected_paths(cur, add, today, p_miss, placeholder, h)
            for n in THRESHOLDS:
                for col, lab in (("p", "all"), ("p_priced", "priced")):
                    dt = first_date(paths, col, n)
                    sc["dates"][f"h{h}_N{n}_{lab}"] = dt
                    sched_rows.append({"scenario": name, "horizon_days": h, "N": n, "paths": lab, "date": dt})
            milestone = {7: date(2026, 11, 30), 14: date(2026, 12, 18), 30: date(2027, 1, 15),
                         60: date(2027, 2, 16)}[h]
            sc["ipw"][f"h{h}_by_{milestone.isoformat()}"] = ess(paths, milestone)
            if name.split()[0] in ("A", "C"):
                curve[(name[0], h)] = paths.groupby("date").p_priced.sum().sort_index().cumsum()
        out["scenarios"][name] = sc
        print(name, json.dumps({k: v for k, v in sc.items() if k not in ("dates",)}, default=str)[:600])
    sched = pd.DataFrame(sched_rows)
    sched.to_csv(TABLES / "readiness_schedule.csv", index=False)
    wide = sched.pivot_table(index=["horizon_days", "N"], columns=["scenario", "paths"], values="date",
                             aggfunc="first")
    wide.to_csv(TABLES / "readiness_schedule_wide.csv")
    # sensitivity: a whole-day outage resets every in-progress path that has no miss allowance left
    out["allowed_misses"] = {h: allowed_misses(h) for h in HORIZONS}
    out["p_complete_fresh"] = {h: round(p_complete(h + 1, 0, h, p_miss), 3) for h in HORIZONS}
    # whole-day outage: every 7-day path whose window contains that day is lost (0 misses allowed);
    # 14-day paths use up their single allowance. Average over November days, current watchlist only.
    lost = []
    for i in range(30):
        x = date(2026, 11, 1) + timedelta(days=i)
        q = cur[(cur.event_date >= x) & (cur.event_date <= x + timedelta(days=7)) &
                ((cur.event_date - cur.first_snap).map(lambda t: t.days) >= 7)]
        lost.append((len(q), int(q.priced.astype(bool).sum())))
    out["outage_one_day_h7_paths_lost_nov_mean"] = round(float(np.mean([a for a, _ in lost])), 1)
    out["outage_one_day_h7_priced_paths_lost_nov_mean"] = round(float(np.mean([b for _, b in lost])), 1)
    con = connect_ro()
    stop = con.execute("SELECT calls_used FROM runs WHERE stopped_reason LIKE 'daily call budget%' "
                       "ORDER BY run_id LIMIT 1").fetchone()
    con.close()
    out["first_budget_stop_calls"] = stop[0] if stop else None
    out["chart"] = chart(curve)
    (TABLES / "readiness_summary.json").write_text(json.dumps(out, indent=2, default=str))
    print(wide.to_string())
    return out


def chart(curve: dict) -> str:
    fig, axes = plt.subplots(1, 4, figsize=(12, 3.4), sharey=False)
    for ax, h in zip(axes, HORIZONS):
        for (sc, hh), ser in curve.items():
            if hh != h:
                continue
            ax.plot(pd.to_datetime(ser.index), ser.values, color=S1 if sc == "A" else S2, linewidth=2,
                    label="old target 3,000 (far 60%)" if sc == "A" else "in force: 4,000 (far 30%)")
        for n in THRESHOLDS:
            ax.axhline(n, color=MUTED, linewidth=0.8, linestyle="--")
        ax.set_title(f"{h}-day paths", fontsize=11)
        ax.tick_params(axis="x", labelrotation=45, labelsize=7)
        ax.set_ylim(0, 2600)
    axes[0].set_ylabel("expected complete priced paths\n(cumulative)", color=INK2)
    axes[0].legend(fontsize=8, loc="upper left")
    fig.suptitle("Forward panel readiness: complete PRIMARY face-value paths by show date", x=0.01, ha="left",
                 fontweight="bold", fontsize=12)
    return save(fig, "path_readiness.png")


if __name__ == "__main__":
    main()
