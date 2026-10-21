"""Selection into the priced sample: coverage stats, a within-tour LPM, and IPW weights.

`.venv/bin/python src/analysis/selection.py` writes data/selection_weights.parquet
(show_id, covered, p_covered, ipw, tour_coverage) and reports/level_tables/selection.json.

"Covered" = the show's figures are reported: the row is priced, or it is a member of a
multi-night aggregate whose figure row is priced (review 1, item 6a). Universe: played
(not cancelled) shows up to 2026-10-12 in tours with at least one covered show.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from analysis.fe import demean, fe_ols  # noqa: E402
from analysis.targets import ROOT  # noqa: E402

OUT = ROOT / "data/selection_weights.parquet"
OUT_JSON = ROOT / "reports/level_tables/selection.json"
CUTOFF = pd.Timestamp("2026-10-12")
TRIM_Q = 0.99


def universe(d: pd.DataFrame) -> pd.DataFrame:
    priced_units = set(d.loc[d.avg_price_usd.notna(), "show_id"])
    unit_priced = d["agg_group_id"].isin(priced_units)
    d = d.assign(covered=(d.avg_price_usd.notna() | unit_priced).astype(float))
    u = d[~d.is_cancelled_spine & (d.show_date <= CUTOFF) & d.tour_unit.notna()].copy()
    u["tour_coverage"] = u.groupby("tour_unit").covered.transform("mean")
    u = u[u.tour_coverage > 0]
    u["prog_q"] = pd.cut(u.tour_progress, [-0.01, 0.2, 0.4, 0.6, 0.8, 1.0],
                         labels=["0–20%", "20–40%", "40–60%", "60–80%", "80–100%"])
    u["log_metro_pop_f"] = u.metro_log_population.fillna(0)
    u["metro_missing"] = u.metro_log_population.isna().astype(float)
    cap = u.capacity.astype(float)
    u["log_cap_wd_f"] = np.log(cap.where(cap > 0)).fillna(0)
    u["cap_missing"] = cap.isna().astype(float)
    u["fri_sat"] = u.is_fri_sat.astype("Float64").astype(float).fillna(0)
    u["sunday"] = u.is_sunday.astype("Float64").astype(float).fillna(0)
    u["us_f"] = u.country_final.eq("US").astype(float)
    for c in ["latin_america", "europe", "asia", "oceania", "mea"]:
        u[f"cont_{c}"] = u.continent.eq(c).astype(float)
    return u


def main() -> dict:
    d = pd.read_parquet(ROOT / "data/shows.parquet")
    u = universe(d)
    res: dict = {"universe_shows": int(len(u)), "tours": int(u.tour_unit.nunique())}
    # (a) coverage counting aggregate members through their unit
    res["coverage_all"] = float(u.covered.mean())
    res["coverage_priced_rows_only"] = float(u.avg_price_usd.notna().mean())
    # (c) by tour position, overall and North America
    res["by_progress"] = u.groupby("prog_q", observed=True).covered.mean().round(3).to_dict()
    res["by_progress_na"] = u[u.continent.eq("north_america")].groupby("prog_q", observed=True).covered.mean().round(3).to_dict()
    res["by_continent"] = u.groupby("continent").covered.mean().round(3).to_dict()
    # (b) by Wikidata capacity bucket on resolved venues (resolution itself is priced-first)
    capb = pd.cut(u.capacity.astype(float), [0, 3000, 8000, 25000, 1e7], labels=["<3k", "3k–8k", "8k–25k", "25k+"])
    res["by_wikidata_capacity"] = u.groupby(capb, observed=True).covered.mean().round(3).to_dict()
    res["wikidata_capacity_known_share"] = float(u.capacity.notna().mean())
    # within-tour LPM
    xs = ["tour_progress", "fri_sat", "sunday", "log_metro_pop_f", "metro_missing", "log_cap_wd_f", "cap_missing",
          "cont_latin_america", "cont_europe", "cont_asia", "cont_oceania", "cont_mea"]
    lpm = fe_ols(u.assign(tour_progress=u.tour_progress.fillna(0.5)), "covered", xs, ["tour_unit"], "split_key")
    res["lpm"] = {x: {"b": float(lpm.coef[x]), "se": float(lpm.se[x])} for x in xs}
    res["lpm_n"], res["lpm_clusters"] = lpm.n, lpm.n_clusters
    # (d) "strong nights": among NA reported shows, outcome vs tour coverage share (year FE)
    na = d[d.analysis_sample & d.continent.eq("north_america")].merge(
        u[["show_id", "tour_coverage"]], on="show_id", how="inner")
    na["year"] = na.show_date.dt.year
    r1 = fe_ols(na.assign(y=na.sellout_ratio.clip(upper=1.2)), "y", ["tour_coverage"], ["year"], "split_key")
    r2 = fe_ols(na.assign(y=na.price_rel_artist_era), "y", ["tour_coverage"], ["year"], "split_key")
    res["strong_nights"] = {
        "sellout_on_tour_coverage": {"b": float(r1.coef.iloc[0]), "se": float(r1.se.iloc[0]), "n": r1.n},
        "price_rel_artist_era_on_tour_coverage": {"b": float(r2.coef.iloc[0]), "se": float(r2.se.iloc[0]), "n": r2.n},
    }
    # IPW from the LPM fitted values: tour mean + within-tour slope part, clipped
    uu = u.assign(tour_progress=u.tour_progress.fillna(0.5))
    xw = demean(uu, xs, ["tour_unit"])
    fitted_within = xw.to_numpy() @ lpm.coef.to_numpy()
    p = (uu.groupby("tour_unit").covered.transform("mean") + fitted_within).clip(0.05, 1.0)
    w = 1 / p
    w = w.clip(upper=w.quantile(TRIM_Q))
    out = pd.DataFrame({"show_id": u.show_id, "covered": u.covered, "p_covered": p, "ipw": w,
                        "tour_coverage": u.tour_coverage})
    out.to_parquet(OUT, index=False)
    res["ipw"] = {"trim_quantile": TRIM_Q, "max_weight": float(w.max()), "mean_weight_covered": float(w[u.covered == 1].mean())}
    res["tours_cov80_shows_in_sample"] = int(d.analysis_sample[d.show_id.isin(out.show_id[out.tour_coverage >= 0.8])].sum())
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(res, indent=2, default=float))
    return res


if __name__ == "__main__":
    r = main()
    print(json.dumps(r, indent=1, default=float))
