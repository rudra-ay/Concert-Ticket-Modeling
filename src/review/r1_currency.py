"""Skeptic review 1: does the AU/NZ/CA premium vs the same tour's US median move with the USD exchange rate era?

No FX table exists locally, so eras are coarse buckets where the local dollar was
strong (near parity) vs weak. Under '$ = local currency' contamination the measured
premium is inflated by log(LCU per USD): near zero at parity, +0.3 to +0.4 when weak.
Comparison: GB/DE rows (their '$' cannot be local currency), same construction.
"""
import numpy as np
import pandas as pd

d = pd.read_parquet("data/shows.parquet")
s = d[d.analysis_sample].copy()
s["tour"] = s.artist_key.astype(str) + "|" + s.tour_title
us = s[s.country_iso2.isin(["US"])].groupby("tour").log_avg_price_real.median().rename("us_med")
s = s.join(us, on="tour")
s = s[s.us_med.notna()]
s["rel_us"] = s.log_avg_price_real - s.us_med
y = s.show_date.dt.year
# AUD and CAD both near parity 2010-2013; both weak 2015-2025 and 1998-2003
s["era"] = np.select([y.between(2010, 2013), y.between(2015, 2025) | y.between(1998, 2003)], ["parity", "weak"], "other")
grp = {"AU+NZ": ["AU", "NZ"], "CA": ["CA"], "GB+DE (control)": ["GB", "DE"], "JP": ["JP"]}
rows = []
for g, cc in grp.items():
    t = s[s.country_iso2.isin(cc)]
    for e in ["parity", "weak"]:
        z = t[t.era == e]
        rows.append(dict(group=g, era=e, n=len(z), tours=z.tour.nunique(), median_rel_us=round(float(z.rel_us.median()), 3) if len(z) else np.nan))
r = pd.DataFrame(rows).pivot(index="group", columns="era", values=["n", "tours", "median_rel_us"])
print(r.to_string())
# tour-level paired: within a tour, AU-vs-US premium by era (one value per tour)
tp = s[s.country_iso2.isin(["AU", "NZ"])].groupby(["tour", "era"]).rel_us.median().reset_index()
print("\nAU/NZ tour-level premium by era (tours):")
print(tp.groupby("era").rel_us.describe()[["count", "mean", "50%"]].round(3).to_string())
tc = s[s.country_iso2.isin(["CA"])].groupby(["tour", "era"]).rel_us.median().reset_index()
print("\nCA tour-level premium by era (tours):")
print(tc.groupby("era").rel_us.describe()[["count", "mean", "50%"]].round(3).to_string())
