"""F21 scope check (review 3, E5): how much of the unseen-artist accuracy comes from 2026 snapshot features?

`.venv/bin/python src/analysis/level_ablation.py` -> reports/level_tables/ablation.csv. VALID split only;
the test split is never read. Uses the hyperparameters of the logged final touch (frozen spec).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from analysis.level_data import OUT_TABLES, load_sample, predictive_features  # noqa: E402
from analysis.level_model import SEED, Encoder  # noqa: E402

LB = ["log_lb_listens", "log_lb_users"]
CAREER = ["career_start_year", "years_active_at_show", "n_tours_started_before_show_year"]


def main() -> pd.DataFrame:
    s = load_sample()
    num, cat = predictive_features(s)
    log = [json.loads(x) for x in (OUT_TABLES / "test_touch_log.jsonl").read_text().splitlines() if x.strip()]
    params = next(e for e in log if e.get("kind") == "final")["params"]["y"]
    tr, va = s[s.artist_split == "train"], s[s.artist_split == "valid"]
    rows = []
    for name, drop in [("all features", []), ("without ListenBrainz", LB), ("without ListenBrainz and career variables", LB + CAREER)]:
        n_, c_ = [c for c in num if c not in drop], [c for c in cat if c not in drop]
        enc = Encoder(n_, c_).fit(tr)
        m = HistGradientBoostingRegressor(random_state=SEED, early_stopping=False, **params).fit(enc.transform(tr), tr.y)
        e = np.abs(m.predict(enc.transform(va)) - va.y)
        rows.append({"features": name, "n_features": len(n_) + len(c_), "valid_mae_log": float(e.mean()), "n_valid": len(va)})
    t = pd.DataFrame(rows)
    t.to_csv(OUT_TABLES / "ablation.csv", index=False)
    return t


if __name__ == "__main__":
    print(main().round(4).to_string())
