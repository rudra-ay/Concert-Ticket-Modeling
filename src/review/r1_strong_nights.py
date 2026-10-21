"""Skeptic review 1: is there evidence that reported shows are 'stronger nights'?
If promoters report selectively, reported shows in low-coverage tours should look stronger
(sellout ratio) than reported shows in near-complete tours at the same tour position."""
import numpy as np
import pandas as pd
import statsmodels.formula.api as smf

d = pd.read_parquet("data/shows.parquet")
nc = d[~d.is_cancelled_spine & (d.show_date <= "2026-10-12")].copy()
pg = set(d.loc[d.avg_price_usd.notna() & d.agg_group_id.notna(), "agg_group_id"])
nc["covered"] = nc.avg_price_usd.notna() | nc.agg_group_id.isin(pg)
nc["tour"] = nc.artist_id + "|" + nc.tour_title
nc = nc[nc.continent.eq("north_america")]
cov = nc.groupby("tour").covered.mean().rename("tour_cov")
s = d[d.analysis_sample & d.continent.eq("north_america")].copy()
s["tour"] = s.artist_id + "|" + s.tour_title
s = s.join(cov, on="tour")
s = s[s.sellout_ratio.between(0.05, 1.5)]
s["yr"] = s.show_date.dt.year
s = s.dropna(subset=["sellout_ratio", "tour_cov", "tour_progress", "price_rel_artist_median"])
r = smf.ols("sellout_ratio ~ tour_cov + tour_progress + C(yr)", s).fit(cov_type="cluster", cov_kwds={"groups": pd.factorize(s.split_key)[0]})
print("NA reported shows: sellout_ratio on tour coverage share (artist-cluster SE), n=", len(s))
print(r.params[["tour_cov", "tour_progress"]].round(4).to_dict(), r.bse[["tour_cov", "tour_progress"]].round(4).to_dict())
r2 = smf.ols("price_rel_artist_median ~ tour_cov + tour_progress + C(yr)", s).fit(cov_type="cluster", cov_kwds={"groups": pd.factorize(s.split_key)[0]})
print("price_rel on tour coverage:", r2.params[["tour_cov"]].round(4).to_dict(), r2.bse[["tour_cov"]].round(4).to_dict())
print(pd.cut(s.tour_cov, [0, .5, .8, .95, 1]).value_counts().sort_index().to_dict())
print(s.groupby(pd.cut(s.tour_cov, [0, .5, .8, .95, 1]), observed=True).sellout_ratio.median().round(3).to_dict())
