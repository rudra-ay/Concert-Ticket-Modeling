"""Shared data prep for the LEVEL analysis (task 6)."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from analysis.data_dictionary import LEAK_COL  # noqa: E402
from analysis.targets import ROOT  # noqa: E402

OUT_TABLES = ROOT / "reports/level_tables"
CHARTS = ROOT / "reports/charts"
FORBIDDEN = {"EXPOST", "OUTCOME", "TARGET", "SHOWDAY", "POST_ONSALE", "ID"}

# Predictive feature whitelist. Every entry must carry no forbidden leakage code
# (checked in `predictive_features`). SNAPSHOT features are allowed.
NUMERIC = [
    "year", "month", "day_of_week", "is_fri_sat", "is_sunday", "is_dec_holiday_period", "is_public_holiday",
    "is_holiday_eve", "is_long_weekend", "is_us_holiday_weekend", "is_us_summer_break_proxy", "is_us",
    "metro_log_population", "metro_median_hh_income", "metro_college_share", "lat", "lon",
    "capacity", "capacity_max", "venue_age", "career_start_year", "years_active_at_show",
    "n_tours_started_before_show_year", "log_lb_listens", "log_lb_users", "n_headliners",
    "n_openers", "co_headliner_flag", "festival_flag", "tour_show_number", "days_since_tour_start",
    "days_since_prev_show_artist", "is_first_show_of_tour",
]
CATEGORICAL = ["country_final", "continent", "venue_type", "indoor_outdoor", "genre_coarse_final", "artist_type",
               "artist_country_iso2", "season_local"]
DERIVED_SOURCES = {  # derived predictive features -> the columns they are built from
    "venue_age": ["year", "opening_year"],
    "log_lb_listens": ["lb_total_listen_count"],
    "log_lb_users": ["lb_total_user_count"],
}


def load_sample() -> pd.DataFrame:
    d = pd.read_parquet(ROOT / "data/shows.parquet")
    s = d[d["analysis_sample"]].copy()
    s["y"] = s["log_avg_price_real"]
    s["year"] = s["show_date"].dt.year
    s["tour"] = s["tour_unit"].fillna(s["artist_id"] + "::" + s["tour_title"].fillna(""))
    s["not_split_tour"] = s["tour_unit"].eq(s["tour_key"])
    s["single"] = s["aggregate_n_shows"].eq(1)
    s["post2015"] = s["year"].ge(2016)
    s["us"] = s["country_final"].eq("US")
    s["usd_ok"] = ~s["usd_assumed_non_us"]
    for c in ["is_fri_sat", "is_sunday", "is_holiday_eve", "is_long_weekend", "is_aggregate_unit",
              "co_headliner_flag", "festival_flag", "is_first_show_of_tour", "is_public_holiday",
              "is_dec_holiday_period", "is_us_holiday_weekend", "is_us_summer_break_proxy", "is_us"]:
        if c in s:
            s[c] = s[c].astype("Float64").astype(float)
    s["holiday"] = ((s["is_holiday_eve"] == 1) | (s["is_long_weekend"] == 1)).astype(float).where(
        s["holiday_calendar_available"].fillna(False).astype(bool))
    s["later_leg"] = (s["leg_number"] > 1).astype(float)
    s["multi_night"] = s["is_aggregate_unit"]
    s["log_cap_sold"] = np.log(s["tickets_available_per_show"].where(s["tickets_available_per_show"] > 0))
    s["log_metro_income"] = np.log(s["metro_median_hh_income"])
    s["log_metro_pop"] = s["metro_log_population"]
    s["log_pv365"] = np.log1p(s["pv_mean_365d"])
    s["fan_per_seat"] = s["log_pv365"] - s["log_cap_sold"]
    s["venue_age"] = (s["year"] - s["opening_year"]).where(s["opening_year"].notna()).astype(float)
    s["log_lb_listens"] = np.log1p(s["lb_total_listen_count"].astype(float))
    s["log_lb_users"] = np.log1p(s["lb_total_user_count"].astype(float))
    if "capacity" in s:
        s["log_capacity_wd"] = np.log(s["capacity"].astype(float).where(s["capacity"] > 0))
    if "indoor_outdoor" in s:
        s["outdoor"] = s["indoor_outdoor"].eq("outdoor").astype(float).where(s["indoor_outdoor"].notna())
    sw = ROOT / "data/selection_weights.parquet"
    if sw.exists():
        w = pd.read_parquet(sw)[["show_id", "ipw", "tour_coverage"]]
        s = s.merge(w, on="show_id", how="left")
        s["cov80"] = s["tour_coverage"].ge(0.8)
    for c in ["co_headliner_flag", "farewell_flag", "reunion_flag", "festival_flag"]:
        if c in s:
            s[c] = s[c].astype("Float64").astype(float)
    if "n_openers" in s:
        s["n_openers_f"] = s["n_openers"].astype("Float64").astype(float)
    if "opener_pv_mean_90d_max" in s:
        s["log_opener_pv"] = np.log1p(s["opener_pv_mean_90d_max"].astype(float))
    if "wx_eve_precip_mm" in s:
        wx_ok = s["wx_status"].eq("ok")
        s["rain_eve"] = (s["wx_eve_precip_mm"] >= 1).astype(float).where(wx_ok)
        s["rain_outdoor"] = (s["rain_eve"] * s["outdoor"]).where(s["outdoor"].notna())
        s["single_wx"] = s["single"] & wx_ok & s["outdoor"].notna()
    s["metro_label"] = np.where(s["cbsa_title"].notna(), s["cbsa_title"],
                                s["city"].fillna("") + ", " + s["country_iso2"].fillna("?"))
    return s


def predictive_features(s: pd.DataFrame) -> tuple[list[str], list[str]]:
    num = [c for c in NUMERIC if c in s.columns]
    cat = [c for c in CATEGORICAL if c in s.columns]
    for c in num + cat:
        for src in DERIVED_SOURCES.get(c, [c]):
            code = LEAK_COL.get(src, "")
            if code in FORBIDDEN:
                raise AssertionError(f"predictive feature {c} uses {src} coded {code}")
    return num, cat
