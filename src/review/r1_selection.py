"""Skeptic review 1: recompute selection diagnostics with aggregate members counted as covered,
venue size from Wikidata (not from the attendance figure itself), and within-tour comparisons."""
import numpy as np
import pandas as pd
import statsmodels.formula.api as smf

d = pd.read_parquet("data/shows.parquet")
nc = d[~d.is_cancelled_spine & (d.show_date <= "2026-10-12")].copy()
priced_groups = set(d.loc[d.avg_price_usd.notna() & d.agg_group_id.notna(), "agg_group_id"])
nc["covered"] = nc.avg_price_usd.notna() | nc.agg_group_id.isin(priced_groups)
print("priced share (report def):", round(nc.avg_price_usd.notna().mean(), 3), "| covered share:", round(nc.covered.mean(), 3))
# tours with at least one priced show
nc["tour"] = nc.artist_id + "|" + nc.tour_title
tp = nc.groupby("tour").covered.transform("any")
t = nc[tp].copy()
bins = pd.cut(t.tour_progress, [-0.01, .2, .4, .6, .8, 1.0])
print("\nby tour position (tours with >=1 priced), report-def vs covered, and NA-only covered:")
print(pd.DataFrame({
    "priced": t.groupby(bins, observed=True).avg_price_usd.apply(lambda x: x.notna().mean()),
    "covered": t.groupby(bins, observed=True).covered.mean(),
    "covered_NA_only": t[t.continent.eq("north_america")].groupby(bins[t.continent.eq("north_america")], observed=True).covered.mean(),
}).round(3).to_string())
print("\ncovered share by continent (tours with >=1 priced):")
print(t.groupby("continent").covered.agg(["mean", "size"]).round(3).to_string())
# venue size from Wikidata capacity (available regardless of reporting)
cap = t.capacity.astype(float)
cb = pd.cut(cap, [0, 3000, 8000, 25000, 1e7], labels=["<3k", "3-8k", "8-25k", "25k+"])
print("\ncovered share by Wikidata capacity:")
print(t.groupby(cb, observed=True).covered.agg(["mean", "size"]).round(3).to_string())
print("rows with Wikidata capacity:", int(cap.notna().sum()), "of", len(t))
# within-tour LPM: what predicts coverage? tour FE via demeaning
t["is_fri_sat_f"] = t.is_fri_sat.astype(float)
t["log_cap"] = np.log(cap)
t["log_pop"] = t.metro_log_population.astype(float)
t["na"] = t.continent.eq("north_america").astype(float)
t["cov"] = t.covered.astype(float)
for xs in [["is_fri_sat_f", "na", "tour_progress"], ["log_cap", "is_fri_sat_f", "tour_progress"], ["log_pop", "is_fri_sat_f", "tour_progress"]]:
    z = t.dropna(subset=xs + ["cov"]).copy()
    for c in xs + ["cov"]:
        z[c] = z[c] - z.groupby("tour")[c].transform("mean")
    r = smf.ols("cov ~ " + " + ".join(xs) + " - 1", z).fit(cov_type="cluster", cov_kwds={"groups": pd.factorize(z.artist_id)[0]})
    print("\nwithin-tour LPM of coverage, n=", len(z))
    print(pd.DataFrame({"coef": r.params, "se": r.bse}).round(4).to_string())
# does price (where known) predict being reported in later legs? compare first-leg vs later-leg price for tours with both
s = d[d.analysis_sample]
