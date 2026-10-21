"""Skeptic review 1b: probe fx_monthly.parquet and the untestable-country gap."""
import numpy as np
import pandas as pd
f = pd.read_parquet("data/interim/fx_monthly.parquet")
print("dup keys:", int(f.duplicated(["currency", "month_start"]).sum()), "| nonpositive:", int((f.units_per_usd <= 0).sum()))
chk = {("AUD", "2011-07-01"): (0.90, 0.97), ("CAD", "2007-11-01"): (0.92, 1.0), ("GBP", "2024-06-01"): (0.77, 0.81),
       ("JPY", "2012-01-01"): (75, 79), ("EUR", "2008-07-01"): (0.62, 0.65), ("MXN", "2008-07-01"): (10, 10.5),
       ("DEM", "1985-02-01"): (3.2, 3.4), ("NZD", "2001-10-01"): (2.3, 2.5), ("CHF", "2015-02-01"): (0.9, 0.97)}
for (c, m), (lo, hi) in chk.items():
    v = f.loc[(f.currency == c) & (f.month_start == m), "units_per_usd"]
    print(c, m, None if v.empty else round(float(v.iloc[0]), 4), "OK" if (not v.empty and lo <= v.iloc[0] <= hi) else "CHECK")
# month gaps inside each series
g = f.sort_values("month_start").groupby("currency").month_start.apply(lambda s: int((s.diff().dt.days > 31).sum()))
print("interior gaps:", g[g > 0].to_dict())
# untestable countries: how big are they and do their '$' rows look like unit errors?
d = pd.read_parquet("data/shows.parquet")
s = d[d.analysis_sample]
for cc in ["AR", "CL", "CO", "PL", "CZ", "PH", "ID", "RU", "UY", "PE"]:
    z = s[s.country_iso2 == cc]
    if len(z):
        print(cc, len(z), "rows | median price_rel", round(float(z.price_rel_artist_median.median()), 3),
              "| p90", round(float(z.price_rel_artist_median.quantile(.9)), 3), "| years", z.show_date.dt.year.min(), "-", z.show_date.dt.year.max())
# Argentina: peso pegged 1:1 to USD 1991-04..2001-12 -> mislabel harmless; 2002+ ARS ~3-4 per USD would NOT trip the 4x tour_outlier flag
ar = s[s.country_iso2 == "AR"]
print("AR by era median rel:", ar.groupby(pd.cut(ar.show_date.dt.year, [1990, 2001, 2010, 2030])).price_rel_artist_median.agg(["size", "median"]).round(3).to_dict())
# flagged/excluded rows (implausible, tour_outlier) by untestable country
x = d[d.avg_price_flag.notna()]
print("flagged rows in untestable countries:", x[x.country_iso2.isin(["AR", "CL", "CO", "VE", "PE", "UY", "PL", "CZ"])].groupby(["country_iso2", "avg_price_flag"]).size().to_dict())
