"""Rerun the LEVEL pipeline: [join with --rebuild] -> data quality + selection -> currency test -> hypotheses -> genre -> model (valid only) -> report.

`.venv/bin/python src/analysis/level.py [--final --note "..."]`. Only --final evaluates the
test split (logged in reports/level_tables/test_touch_log.jsonl).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from analysis import build_shows, currency_test, data_quality, level_genre, level_hypotheses, level_model, level_report  # noqa: E402

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--final", action="store_true")
    ap.add_argument("--note", default="")
    ap.add_argument("--skip-model", action="store_true", help="reuse the last model outputs")
    ap.add_argument("--rebuild", action="store_true",
                    help="rebuild data/shows.parquet first; this changes the build stamp in the frozen model spec, "
                         "so after the final test touch it makes the spec check fail")
    a = ap.parse_args()
    if a.rebuild:
        build_shows.main()
    data_quality.main()  # also runs selection.main() (IPW weights)
    currency_test.main()
    level_hypotheses.main()
    level_genre.main()
    if not a.skip_model:
        level_model.main(final=a.final, note=a.note)
    level_report.main()
