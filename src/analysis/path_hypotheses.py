"""PATH hypothesis family (declared before any test statistic is computed) and hypotheses.csv.

The forward panel is PRIMARY face value (Ticketmaster priceRanges), not resale. Only hypotheses
about primary face-value dynamics can be tested from it; resale PATH hypotheses are excluded
with a reason. Every family member is PENDING: it enters BH at p = 1 until its pre-specified
test date, when the test below is run once on the data then available.

Disclosure: the family was declared on 2026-10-21 after the 3-day descriptive move rates
(path_tm_moves.py) had been computed; no estimate of any family member existed.

Writes reports/path_tables/bh_family.json and hypotheses.csv.
Run: .venv/bin/python src/analysis/path_hypotheses.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from analysis.path_common import TABLES  # noqa: E402

COMMON = ("Sample: events with a complete priced 30-day path (first snapshot >= 30 days out, valid range on "
          "the path's first day, at most 3 of 31 days missing). Unit: event-day pairs (consecutive days, both "
          "priced). move = |change| > $0.005 in min or max face value. Weights: none in base; 1/selection_prob in "
          "'IPW (selection)'. SE clustered by artist (first attraction id); p and 95% CI from t(G_eff - 1); "
          "null-imposed wild cluster bootstrap (Webb, 1,999 draws) and leave-one-artist-out range if G_eff < 30.")
TEST_DATE = ("first daily run on or after the date the panel reaches N >= 500 complete priced 30-day paths "
             "(readiness_schedule.csv, scenario in force; 2026-12-22 under the status quo), run once")

FAMILY = {
    "H20a": {"claim": "Primary face-value repricing becomes more frequent as the show approaches.",
             "test": "LPM: move ~ 1[0-6 days] + 1[7-13] + 1[14-29] (reference 30+ days) + event FE + snapshot-date FE "
                     "(absorbs year). One-sided test that the 0-6-day coefficient > 0.",
             "fe": "event + snapshot date (year)", "source": "LITERATURE H20 (CMA 2025: tier releases)"},
    "H20b": {"claim": "Primary face-value changes are steps, not continuous drift: on a typical day the face "
                      "range does not change.",
             "test": "Intercept-only regression of move on the event-day pairs (snapshot-date FE, year); H0: daily "
                     "move rate >= 5% (drift-like), one-sided; reject if the upper 95% bound < 5%.",
             "fe": "snapshot date (year)", "source": "LITERATURE H20"},
    "H9p": {"claim": "Events with wide primary price spreads (max/min >= 3 on the path's first day, a proxy for "
                     "platinum/tiered pricing) reprice more often.",
            "test": "LPM: move ~ wide_spread + days-to-show bucket dummies + snapshot-date FE (year); two-sided test "
                    "on wide_spread. wide_spread is measured as of the first path day (no look-ahead).",
            "fe": "days bucket + snapshot date (year)", "source": "LITERATURE H9, primary side"},
}
RESALE = "resale-price hypothesis: the forward panel is PRIMARY face value; needs Rebrowser StubHub/Gametime or marketplace data"
EXCLUDED = {
    "H1": RESALE, "H2": RESALE, "H3": RESALE + " (listing-level)", "H4": RESALE, "H5": RESALE + " and sell-out status",
    "H7": RESALE + " (transaction volume)", "H9r": "resale half of H9 (resale premium/path flatness): " + RESALE,
    "H10": RESALE, "H11": RESALE, "H12": RESALE + " plus weather join", "H13": RESALE,
    "H14": RESALE + " at hourly resolution (the collector is daily)", "H17": RESALE + " (price variance)",
    "H18": "needs listing-format (auction vs fixed) data, which no approved source has",
    "H21": RESALE,
}
LEVEL_ONLY = {"excl. $ outside US": "n/a: TM panel is US-only USD",
              "excl. aggregates": "n/a: LEVEL concept (multi-night box office aggregates)",
              "weighted by nights": "n/a: LEVEL concept",
              "tours ≥ 80% covered": "n/a: LEVEL concept (Wikipedia tour coverage)",
              "excl. split pseudo-tours": "n/a: LEVEL concept"}
SENS = ["base", "US only", "excl. $ outside US", "2016+", "excl. aggregates", "weighted by nights", "IPW (selection)",
        "tours ≥ 80% covered", "excl. split pseudo-tours", "ranges pool only", "excl. pilot events", "60-day paths"]


def main() -> None:
    TABLES.mkdir(parents=True, exist_ok=True)
    fam = sorted(FAMILY)
    pending = {h: f"PENDING, enters BH at p = 1 until: {TEST_DATE}" for h in fam}
    q = {h: 1.0 for h in fam}  # BH over all-ones p
    (TABLES / "bh_family.json").write_text(json.dumps({
        "family": fam, "excluded": EXCLUDED, "pending_p1": pending, "q": q,
        "definitions": FAMILY, "common": COMMON, "declared_on": "2026-10-21",
        "disclosure": "declared after the 3-day descriptive move rates were computed; no estimate of any member existed",
    }, indent=2, ensure_ascii=False))
    rows = []
    for h in fam:
        for s in SENS:
            if s in LEVEL_ONLY:
                status = LEVEL_ONLY[s]
            elif s in ("US only", "2016+"):
                status = "same as base (panel is US-only, 2026-27)"
            else:
                status = "pending (test date not reached)"
            rows.append({"hid": h, "sens": s, "status": status, "fe": FAMILY[h]["fe"], "coef": np.nan, "se": np.nan,
                         "ci_lo": np.nan, "ci_hi": np.nan, "p": np.nan, "p_wild": np.nan, "p_used": 1.0 if s == "base"
                         else np.nan, "effective_clusters": np.nan, "clusters": np.nan, "cluster2": "",
                         "in_family": s == "base", "descriptive": False, "q": 1.0 if s == "base" else np.nan,
                         "label": "SNAPSHOT", "loo_min": np.nan})
    # descriptive context from part 1 (not a test, not in the family)
    summ = json.loads((TABLES / "tm_moves_summary.json").read_text())
    rows.append({"hid": "H20-desc", "sens": "base", "status": "descriptive (3 snapshot days; not a test)",
                 "fe": "", "coef": summ["move_rate_pct"] / 100, "se": np.nan,
                 "ci_lo": summ["move_rate_ci95_pct"][0] / 100, "ci_hi": summ["move_rate_ci95_pct"][1] / 100,
                 "p": np.nan, "p_wild": np.nan, "p_used": np.nan, "effective_clusters": np.nan,
                 "clusters": np.nan, "cluster2": "", "in_family": False, "descriptive": True, "q": np.nan,
                 "label": "SNAPSHOT", "loo_min": np.nan})
    pd.DataFrame(rows).to_csv(TABLES / "hypotheses.csv", index=False)
    print(f"family {fam}; excluded {len(EXCLUDED)}; rows {len(rows)}")


if __name__ == "__main__":
    main()
