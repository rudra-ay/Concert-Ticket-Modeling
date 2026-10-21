"""Skeptic review 1: independent recompute of price_rel_artist_median and its properties."""
import sys
import numpy as np
import pandas as pd
sys.path.insert(0, "src")
from analysis.targets import artist_relative_target

d = pd.read_parquet("data/shows.parquet")
s = d.analysis_sample
x = d[s]
# independent recompute (no shared code)
med = x.groupby("artist_key").log_avg_price_real.median()
mine = x.log_avg_price_real - x.artist_key.map(med)
print("max |diff| stored vs independent:", float((mine - x.price_rel_artist_median).abs().max()))
# artist_key nested in split_key?
print("artist_keys spanning >1 split_key:", int(x.groupby("artist_key").split_key.nunique().gt(1).sum()))
print("artist_keys spanning >1 split:", int(x.groupby("artist_key").artist_split.nunique().gt(1).sum()))
# in-fold: train mask gives NaN for valid/test (expected), and equals stored for train rows
tr = s & d.artist_split.eq("train")
f = artist_relative_target(d, tr)
print("train rows equal stored:", np.allclose(f[tr], d.loc[tr, "price_rel_artist_median"]),
      "| non-train rows non-NaN:", int(f[s & ~tr].notna().sum()))
# within-artist time-based fold: median from rows before 2015 applied to 2015+ rows
early = s & (d.show_date.dt.year < 2015)
g = artist_relative_target(d, early)
late = s & ~early
print("2015+ rows with an early-median:", int(g[late].notna().sum()), "of", int(late.sum()),
      "; mean rel (ex-ante median) =", round(float(g[late].mean()), 3),
      "vs stored", round(float(d.loc[late & g.notna(), "price_rel_artist_median"].mean()), 3))
# degenerate small artists
n = x.groupby("artist_key").size()
print("artist_keys with n=1:", int((n == 1).sum()), "n=2:", int((n == 2).sum()), "n<5:", int((n < 5).sum()),
      "rows in n<5:", int(n[n < 5].sum()))
print("rows with rel exactly 0:", int((x.price_rel_artist_median == 0).sum()))
# time confounding: within-artist correlation of rel with year
r = x[["price_rel_artist_median"]].assign(yr=x.show_date.dt.year - x.groupby("artist_key").show_date.transform(lambda t: t.dt.year.median()))
print("corr(rel, year - artist median year):", round(float(r.corr().iloc[0, 1]), 3))
span = x.groupby("artist_key").show_date.agg(lambda t: t.dt.year.max() - t.dt.year.min())
print("artist career span in sample (yrs): median", float(span.median()), "p90", float(span.quantile(.9)),
      "| rows from artists spanning >=20y:", int(x.artist_key.map(span).ge(20).sum()))
# weighting: aggregates count once; does weighting by unit_n_shows change the median?
wm = x.groupby("artist_key").apply(lambda g: np.repeat(g.log_avg_price_real.values, g.unit_n_shows.astype(int).values).__array__())
wmed = wm.map(np.median)
print("|weighted-unweighted artist median| > 0.05 for", int(((wmed - med).abs() > 0.05).sum()), "of", len(med), "artist_keys")
