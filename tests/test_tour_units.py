"""build_shows.tour_units: split only long tour_keys, at > 90-day gaps, then by year."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from analysis.build_shows import tour_units  # noqa: E402


def _df(key: str, dates: list[str]) -> pd.DataFrame:
    return pd.DataFrame({"tour_key": key, "show_date": pd.to_datetime(dates)})


def test_short_tour_with_leg_break_stays_whole():
    d = _df("a::t", ["2019-01-01", "2019-02-01", "2019-08-01", "2019-09-01"])  # 6-month break, < 2 years
    assert tour_units(d).nunique() == 1
    assert (tour_units(d) == "a::t").all()


def test_long_key_split_at_gap():
    d = _df("b::t", ["2015-01-01", "2015-03-01", "2017-06-01", "2017-07-01"])
    u = tour_units(d)
    assert u.nunique() == 2
    assert u.iloc[0] == u.iloc[1] != u.iloc[2] == u.iloc[3]


def test_residency_split_by_year():
    dates = pd.date_range("2014-01-15", "2017-12-15", freq="MS").strftime("%Y-%m-%d").tolist()  # monthly, no gaps
    u = tour_units(_df("c::res", dates))
    assert u.nunique() == 4  # one unit per calendar year
