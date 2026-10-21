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


# --- review 1 fixes ----------------------------------------------------------------

SKEPTIC_PAIRS = [
    ("the-carters", "beyonce"), ("the-carters", "jay-z"), ("nsync", "justin-timberlake"),
    ("one-direction", "niall-horan"), ("one-direction", "harry-styles"), ("one-direction", "louis-tomlinson"),
    ("bts", "jin"), ("bts", "suga"), ("fleetwood-mac", "stevie-nicks"), ("genesis", "phil-collins"),
    ("pink-floyd", "roger-waters"), ("take-that", "robbie-williams"), ("michael-jackson", "the-jacksons"),
    ("queen", "queen-adam-lambert"), ("queen", "adam-lambert"), ("jonas-brothers", "demi-lovato-and-nick-jonas"),
    ("the-eagles", "eagles"), ("selena-gomez-the-scene", "selena-gomez"),
]


def test_band_member_pairs_share_split(shows):
    sk = shows.drop_duplicates("artist_id").set_index("artist_id")["split_key"]
    bad = [(a, b) for a, b in SKEPTIC_PAIRS if a in sk.index and b in sk.index and sk[a] != sk[b]]
    assert not bad, bad


def test_alias_merged_in_artist_key(shows):
    ak = shows.drop_duplicates("artist_id").set_index("artist_id")["artist_key"]
    assert ak["the-eagles"] == ak["eagles"]


def test_every_duplicate_group_reviewed(shows):
    assert not shows["dup_unreviewed"].any()


def test_known_duplicate_decisions(shows):
    s = shows.set_index("show_id")
    assert s.at["foo-fighters__2015-06-05__zeppelinfeld", "dup_boxoffice_drop"]
    assert s.at["marilyn-manson__2015-06-05__rock-im-ring", "dup_boxoffice_drop"]
    assert not s.at["black-sabbath__1978-09-04__cape-cod-coliseum", "dup_boxoffice_drop"]
    assert s.at["van-halen__1978-09-04__cape-cod-coliseum", "dup_boxoffice_drop"]
    # no two sample rows on one date share a gross
    smp = shows[shows["analysis_sample"] & shows["gross_usd"].gt(10_000)]
    assert not smp.duplicated(["show_date", "gross_usd"]).any()


def test_non_performers_excluded(shows):
    assert not shows.loc[shows["analysis_sample"], "non_performer"].any()


def test_target_derived_columns_coded():
    from analysis.data_dictionary import LEAK_COL
    for c in ["tour_infobox_gross", "tour_infobox_attendance"]:
        assert LEAK_COL[c] == "TARGET"
    for c in ["n_priced_shows", "artist_n_analysis", "has_venue", "has_weather"]:
        assert LEAK_COL[c] == "OUTCOME"
    assert LEAK_COL["tour_page_id"] == "ID"
    assert LEAK_COL["n_tours_started_by_show_year"] == "EXPOST"
    assert LEAK_COL["venue_run_position"] == "EXPOST"


def test_predictive_features_clean(shows):
    from analysis.level_data import load_sample, predictive_features
    predictive_features(load_sample())  # raises on any forbidden code


def test_country_final_fills_spine_gaps(shows):
    s = shows[shows["analysis_sample"]]
    assert s["country_final"].isna().mean() < 0.005
    assert (s.loc[s["country_final"].ne("US") & s["country_final"].notna(), "usd_assumed_non_us"]).all()


def test_relative_targets_detrended(shows):
    s = shows[shows["analysis_sample"]]
    rely = s["show_date"].dt.year - s.groupby("artist_key")["show_date"].transform(lambda x: x.dt.year.median())
    for c in ["price_rel_tour", "price_rel_artist_era"]:
        m = s[c].notna()
        assert m.mean() > 0.9
        assert np.isfinite(s.loc[m, c]).all()
        assert abs(np.corrcoef(s.loc[m, c], rely[m])[0, 1]) < 0.1
