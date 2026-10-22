"""PATH panel for the as-of checks: one row per (event, snapshot) from the forward TM panel.

Writes data/forward/path_panel.parquet (gitignored with the rest of data/forward/; Ticketmaster
row-level data is never committed) and reports/path_tables/path_spec.json (the skeptic's
autocheck contract) plus panel_summary.json (aggregates only).

- show_time = Ticketmaster's UTC start (dates.start.dateTime). When it is missing (time TBA),
  the start of the show's local date in the venue time zone is used, which is conservative:
  any show-day snapshot of such an event is treated as at/after the show.
- Snapshots at or after show_time are excluded from the panel (they cannot be inputs to a
  path that ends at the show).
- No predictive model is fitted in task 8, so `features` is empty and `split` is null; no
  out-of-sample claim is made. The planned walk-forward design (time-ordered, grouped by
  artist) is described in reports/path_findings.md and will be registered before any fit.
Run: .venv/bin/python src/analysis/path_panel.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from analysis.path_common import TABLES, connect_ro  # noqa: E402
from analysis.targets import ROOT  # noqa: E402

PANEL = ROOT / "data/forward/path_panel.parquet"


def build() -> pd.DataFrame:
    con = connect_ro()
    s = pd.read_sql("SELECT s.event_id, s.snap_date, s.snapshot_ts, s.start_utc, s.local_date, s.event_timezone, "
                    "s.days_until_show, s.event_status, s.genre, s.state, s.venue_id, s.attraction_ids, "
                    "s.has_price_ranges, s.price_min, s.price_max, s.public_sale_start, s.presales_json, s.hours_until_show, "
                    "w.selected_for_ranges, w.selection_prob, w.source, w.added_at "
                    "FROM snapshots s JOIN watchlist w USING(event_id) WHERE s.http_status = 200", con)
    con.close()

    def show_time(r) -> pd.Timestamp:
        if r.start_utc:
            return pd.Timestamp(r.start_utc).tz_convert("UTC") if pd.Timestamp(r.start_utc).tzinfo \
                else pd.Timestamp(r.start_utc, tz="UTC")
        tz = ZoneInfo(r.event_timezone) if r.event_timezone else ZoneInfo("America/New_York")
        return pd.Timestamp(r.local_date).tz_localize(tz).tz_convert("UTC")

    s["show_time"] = s.apply(show_time, axis=1)
    s["snapshot_time"] = pd.to_datetime(s.snapshot_ts, utc=True)
    s["artist"] = s.attraction_ids.fillna("").str.split(",").str[0].replace("", None)
    n0 = len(s)
    s = s[s.snapshot_time < s.show_time].copy()
    s["valid_range"] = (s.has_price_ranges == 1) & (s.price_min > 0)
    PANEL.parent.mkdir(parents=True, exist_ok=True)
    s.drop(columns=["start_utc"]).to_parquet(PANEL, index=False)
    summary = {"panel_rows": len(s), "panel_events": int(s.event_id.nunique()),
               "excluded_at_or_after_show": n0 - len(s), "rows_before_exclusion": n0,
               "artists": int(s.artist.nunique()), "snap_days": int(s.snap_date.nunique())}
    spec = {"panel": str(PANEL.relative_to(ROOT)), "entity": "event_id", "artist": "artist", "split": None,
            "snapshot_time": "snapshot_time", "show_time": "show_time", "feature_time_cols": [],
            "target_time_col": None, "features": [],
            "forbidden_features": ["price_min", "price_max", "event_status", "days_until_show"],
            "note": "No model is fitted in task 8 (no out-of-sample claim). Before any walk-forward fit, "
                    "features, split (time-ordered, grouped by artist) and target time are registered here."}
    pw = TABLES / "power.json"
    if pw.exists():  # F4: MDEs registered before any test (path_power.py)
        pj = json.loads(pw.read_text())
        spec["preregistration"] = {"mde_pp": pj["mde_pp"], "powered": pj["powered"], "rule": pj["rule"],
                                   "n_test_paths": pj["n_test"], "moved_out_of_family": pj["moved_out_of_family"],
                                   "seen_through": "2026-10-21", "test_code": "src/analysis/path_hypotheses.py"}
    TABLES.mkdir(parents=True, exist_ok=True)
    (TABLES / "path_spec.json").write_text(json.dumps(spec, indent=2))
    (TABLES / "panel_summary.json").write_text(json.dumps(summary, indent=2))
    print(summary)
    return s


if __name__ == "__main__":
    build()
