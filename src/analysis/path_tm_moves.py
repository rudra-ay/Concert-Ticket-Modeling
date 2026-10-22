"""PATH part 1: what the forward Ticketmaster panel shows so far about PRIMARY face-value moves.

Unit: a day-pair = the same event snapshotted on two consecutive UTC days (both HTTP 200).
A snapshot "has a valid range" when priceRanges is present and min > 0 (the panel contains
$0.00 placeholder ranges; a 0 -> price step is a range appearing, not a repricing).
A "move" = |change| > $0.005 in the event's min or max face value between the two days.

Breakdowns: days to show (at the later snapshot), Ticketmaster genre, selection pool
("fill": events picked because they publish priceRanges vs. the random no-ranges draw;
the TM panel has no sell-through data), and event status.

Outputs (aggregates only): reports/path_tables/tm_moves_*.csv and tm_moves_summary.json,
charts reports/charts/path_tm_moves_by_daysout.png and path_tm_moves_by_genre.png.
Run: .venv/bin/python src/analysis/path_tm_moves.py
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from analysis.path_panel import PANEL  # noqa: E402
from analysis.path_common import (DAYS_BUCKETS, INK2, NEUTRAL, S1, S2, TABLES, connect_ro,  # noqa: E402
                                  days_bucket, plt, save, wilson)

EPS = 0.005


def load() -> pd.DataFrame:
    con = connect_ro()
    s = pd.read_sql(
        "SELECT s.event_id, s.snap_date, s.http_status, s.event_status, s.days_until_show, s.genre, "
        "s.has_price_ranges, s.price_min, s.price_max, "
        "(SELECT COUNT(*) FROM price_ranges p WHERE p.event_id=s.event_id AND p.snap_date=s.snap_date) AS n_ranges, "
        "(SELECT COUNT(*) FROM price_ranges p WHERE p.event_id=s.event_id AND p.snap_date=s.snap_date "
        "  AND p.type != 'standard') AS n_nonstandard, "
        "w.source, w.selected_for_ranges "
        "FROM snapshots s JOIN watchlist w USING(event_id) WHERE s.http_status = 200", con)
    con.close()
    # same exclusion as the PATH panel (path_panel.py): only snapshots taken before the show starts
    keys = pd.read_parquet(PANEL, columns=["event_id", "snap_date"]).assign(in_panel=True)
    s = s.merge(keys, on=["event_id", "snap_date"], how="left")
    s["in_panel"] = s.in_panel.eq(True)
    s["valid"] = (s.has_price_ranges == 1) & (s.price_min > 0) & (s.price_max > 0)
    s["zero_placeholder"] = (s.has_price_ranges == 1) & ~s.valid
    s["pool"] = np.select([s.source == "discover-pilot", s.selected_for_ranges == 1],
                          ["pilot (unweighted)", "ranges pool"], "random no-ranges draw")
    return s


def pairs(s: pd.DataFrame) -> pd.DataFrame:
    s = s.sort_values(["event_id", "snap_date"]).copy()
    g = s.groupby("event_id")
    for c in ("snap_date", "valid", "price_min", "price_max", "event_status", "n_ranges"):
        s["prev_" + c] = g[c].shift()
    p = s[s.prev_snap_date.notna()].copy()
    gap = (pd.to_datetime(p.snap_date) - pd.to_datetime(p.prev_snap_date)).dt.days
    p = p[gap == 1].copy()
    p["prev_valid"] = p.prev_valid.astype(bool)
    both = p.valid & p.prev_valid
    p["both_valid"] = both
    p["min_moved"] = both & ((p.price_min - p.prev_price_min).abs() > EPS)
    p["max_moved"] = both & ((p.price_max - p.prev_price_max).abs() > EPS)
    p["moved"] = p.min_moved | p.max_moved
    p["appeared"] = ~p.prev_valid & p.valid
    p["disappeared"] = p.prev_valid & ~p.valid
    p["status_changed"] = p.event_status != p.prev_event_status
    p["tiers_changed"] = both & (p.n_ranges != p.prev_n_ranges)
    p["bucket"] = p.days_until_show.map(days_bucket)
    return p


def rate_table(p: pd.DataFrame, by: str, order: list[str] | None = None) -> pd.DataFrame:
    rows = []
    groups = order if order is not None else sorted(p[by].dropna().unique())
    for k in groups:
        q = p[p[by] == k]
        bv = q[q.both_valid]
        n, m = len(bv), int(bv.moved.sum())
        lo, hi = wilson(m, n)
        prev_missing = q[~q.prev_valid]
        rows.append({by: k, "day_pairs": len(q), "pairs_both_priced": n, "moves": m,
                     "move_rate_pct": round(100 * m / n, 2) if n else None,
                     "ci95_lo_pct": round(100 * lo, 2) if n else None, "ci95_hi_pct": round(100 * hi, 2) if n else None,
                     "min_moves": int(bv.min_moved.sum()), "max_moves": int(bv.max_moved.sum()),
                     "ranges_appeared": int(q.appeared.sum()), "pairs_unpriced_before": len(prev_missing),
                     "ranges_disappeared": int(q.disappeared.sum()), "status_changes": int(q.status_changed.sum())})
    return pd.DataFrame(rows)


def chart_rates(t: pd.DataFrame, by: str, title: str, fname: str, horizontal: bool = False) -> str:
    t = t[t.pairs_both_priced > 0]
    fig, ax = plt.subplots(figsize=(7.2, 3.6 if not horizontal else 0.32 * len(t) + 1.4))
    x = np.arange(len(t))
    rate = t.move_rate_pct.values
    err = np.vstack([rate - t.ci95_lo_pct.values, t.ci95_hi_pct.values - rate])
    labels = [f"{k}\n(n={n:,})" if not horizontal else f"{k} (n={n:,})"
              for k, n in zip(t[by], t.pairs_both_priced)]
    if horizontal:
        ax.barh(x, rate, color=S1, height=0.6)
        ax.errorbar(rate, x, xerr=err, fmt="none", ecolor=INK2, elinewidth=1, capsize=2)
        ax.set_yticks(x, labels, fontsize=8)
        ax.invert_yaxis()
        ax.set_xlabel("% of day-pairs where min or max face value moved (95% Wilson CI)")
    else:
        ax.bar(x, rate, color=S1, width=0.6)
        ax.errorbar(x, rate, yerr=err, fmt="none", ecolor=INK2, elinewidth=1, capsize=3)
        ax.set_xticks(x, labels, fontsize=8)
        ax.set_ylabel("% of day-pairs with a move")
        ax.set_xlabel("days to show (later snapshot)")
    ax.set_title(title)
    return save(fig, fname)


def main() -> dict:
    TABLES.mkdir(parents=True, exist_ok=True)
    s_all = load()
    started_pairs = int(pairs(s_all).both_valid.sum())  # incl. snapshots taken after the show started
    s = s_all[s_all.in_panel].copy()
    p = pairs(s)
    snap_days = sorted(s.snap_date.unique())
    bv = p[p.both_valid]
    ev = bv.groupby("event_id").moved.any()
    moved_pairs = bv[bv.moved].copy()
    for c in ("min", "max"):
        moved_pairs[f"{c}_pct"] = 100 * (moved_pairs[f"price_{c}"] / moved_pairs[f"prev_price_{c}"] - 1)
    ups = int(((moved_pairs.price_min > moved_pairs.prev_price_min + EPS) |
               (moved_pairs.price_max > moved_pairs.prev_price_max + EPS)).sum())
    downs = int(((moved_pairs.price_min < moved_pairs.prev_price_min - EPS) |
                 (moved_pairs.price_max < moved_pairs.prev_price_max - EPS)).sum())

    order_b = [lab for _, _, lab in DAYS_BUCKETS]
    t_days = rate_table(p, "bucket", order_b)
    top_genres = bv.genre.value_counts()
    keep = list(top_genres[top_genres >= 100].index)
    p["genre_g"] = p.genre.where(p.genre.isin(keep), "other genres (<100 priced pairs)")
    t_genre = rate_table(p, "genre_g", keep + ["other genres (<100 priced pairs)"])
    t_pool = rate_table(p, "pool", ["ranges pool", "random no-ranges draw", "pilot (unweighted)"])
    p["status_g"] = p.prev_event_status.fillna("?")
    t_status = rate_table(p, "status_g")
    trans = (p[p.status_changed].groupby(["prev_event_status", "event_status"]).size()
             .rename("n").reset_index().sort_values("n", ascending=False))

    for name, t in (("days", t_days), ("genre", t_genre), ("pool", t_pool), ("status", t_status),
                    ("status_transitions", trans)):
        t.to_csv(TABLES / f"tm_moves_{name}.csv", index=False)

    k, n = int(bv.moved.sum()), len(bv)
    lo, hi = wilson(k, n)
    ek, en = int(ev.sum()), len(ev)
    elo, ehi = wilson(ek, en)
    summary = {
        "generated": date.today().isoformat(),
        "snap_days": snap_days, "n_snap_days": len(snap_days),
        "snapshots_200": len(s), "events": int(s.event_id.nunique()),
        "range_types": sorted(pd.read_sql("SELECT DISTINCT type || ' / ' || currency AS t FROM price_ranges",
                                          connect_ro()).t.tolist()),
        "snapshots_with_ranges": int((s.has_price_ranges == 1).sum()),
        "zero_placeholder_snapshots": int(s.zero_placeholder.sum()),
        "day_pairs": len(p), "pairs_both_priced": n, "pairs_moved": k,
        "move_rate_pct": round(100 * k / n, 2), "move_rate_ci95_pct": [round(100 * lo, 2), round(100 * hi, 2)],
        "min_moves": int(bv.min_moved.sum()), "max_moves": int(bv.max_moved.sum()),
        "moves_up": ups, "moves_down": downs,
        "tiers_changed": int(bv.tiers_changed.sum()),
        "median_abs_pct_min_change": round(float(moved_pairs.loc[moved_pairs.min_moved, "min_pct"].abs().median()), 1)
        if moved_pairs.min_moved.any() else None,
        "median_abs_pct_max_change": round(float(moved_pairs.loc[moved_pairs.max_moved, "max_pct"].abs().median()), 1)
        if moved_pairs.max_moved.any() else None,
        "events_with_2plus_priced_days": en, "events_moved": ek,
        "event_move_rate_pct": round(100 * ek / en, 2), "event_move_rate_ci95_pct": [round(100 * elo, 2),
                                                                                    round(100 * ehi, 2)],
        "ranges_appeared": int(p.appeared.sum()), "ranges_disappeared": int(p.disappeared.sum()),
        "pairs_unpriced_before": int((~p.prev_valid).sum()),
        "status_changes": int(p.status_changed.sum()),
        "pairs_both_priced_incl_started_shows": started_pairs,
        "pairs_excluded_show_started": started_pairs - int(p.both_valid.sum()),
        "priced_pairs_ranges_pool_pct": round(100 * float((bv.pool == "ranges pool").mean()), 1),
        "priced_pairs_30plus_days_pct": round(100 * float((bv.days_until_show >= 30).mean()), 1),
        "max_moves_per_event": int(bv[bv.moved].groupby("event_id").size().max()) if k else 0,
        "median_days_to_show_of_moves": float(bv.loc[bv.moved, "days_until_show"].median()) if k else None,
        "last_snapshot_seen_before_registration": max(snap_days),
        "charts": [chart_rates(t_days, "bucket", "Primary face value: daily move rate by days to show",
                               "path_tm_moves_by_daysout.png"),
                   chart_rates(t_genre, "genre_g", "Primary face value: daily move rate by genre",
                               "path_tm_moves_by_genre.png", horizontal=True)],
    }
    (TABLES / "tm_moves_summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps({k: v for k, v in summary.items() if k != "charts"}, indent=1))
    print(t_days.to_string(index=False))
    print(t_pool.to_string(index=False))
    return summary


if __name__ == "__main__":
    main()
