"""Sanity checks for data/shows.parquet (run src/analysis/build_shows.py first)."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from analysis.targets import artist_relative_target, artist_split  # noqa: E402

SHOWS = ROOT / "data/shows.parquet"
BASE = ROOT / "data/interim/shows_base.parquet"

pytestmark = pytest.mark.skipif(not SHOWS.exists(), reason="data/shows.parquet not built")


@pytest.fixture(scope="module")
def shows() -> pd.DataFrame:
    return pd.read_parquet(SHOWS)


@pytest.fixture(scope="module")
def base() -> pd.DataFrame:
    return pd.read_parquet(BASE, columns=["show_id", "avg_price_usd"])


def test_no_duplicate_show_id(shows):
    assert shows["show_id"].notna().all()
    assert not shows["show_id"].duplicated().any()


def test_join_does_not_multiply_rows(shows, base):
    assert len(shows) == len(base)
    assert set(shows["show_id"]) == set(base["show_id"])


def test_nominal_prices_unchanged(shows, base):
    m = shows.set_index("show_id")["avg_price_usd"].reindex(base["show_id"]).to_numpy()
    assert np.allclose(m, base["avg_price_usd"].to_numpy(), equal_nan=True)


def test_targets_finite_in_analysis_sample(shows):
    s = shows[shows["analysis_sample"]]
    assert len(s) > 0
    for col in ["log_avg_price_real", "price_rel_artist_median", "avg_price_real"]:
        assert np.isfinite(s[col].astype(float)).all(), col


def test_analysis_sample_rules(shows):
    s = shows[shows["analysis_sample"]]
    assert s["avg_price_flag"].isna().all()
    assert (s["gross_currency"] == "USD").all()
    assert not s["dup_boxoffice_drop"].any()
    assert not s["is_cancelled_spine"].any()


def test_artist_split_is_by_artist_and_deterministic(shows):
    assert (shows.groupby("artist_id")["artist_split"].nunique() == 1).all()
    assert (shows.groupby("split_key")["artist_split"].nunique() == 1).all()
    assert set(shows["artist_split"].dropna()) <= {"train", "valid", "test"}
    keys = shows.drop_duplicates("split_key").head(50)
    assert artist_split(keys["split_key"]).tolist() == keys["artist_split"].tolist()


def test_no_performer_in_two_splits(shows):
    q = shows.dropna(subset=["artist_qid"]).groupby("artist_qid")["artist_split"].nunique()
    assert (q == 1).all(), q[q > 1]
    k = shows.groupby("artist_key")["artist_split"].nunique()
    assert (k == 1).all()


def test_relative_target_matches_recompute(shows):
    s = shows["analysis_sample"]
    recomputed = artist_relative_target(shows, s).where(s)
    assert np.allclose(recomputed[s], shows.loc[s, "price_rel_artist_median"])
    med = shows.loc[s].groupby("artist_key")["price_rel_artist_median"].median()
    assert np.allclose(med, 0, atol=1e-9)  # median(x - median(x)) == 0 per artist


def test_deflation_base_month(shows):
    s = shows[shows["analysis_sample"] & (shows["show_date"].dt.strftime("%Y-%m") == "2026-09")]
    if len(s):
        assert np.allclose(s["avg_price_real"], s["avg_price_usd"])
