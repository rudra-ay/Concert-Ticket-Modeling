"""Skeptic review 1, round 3: verify item 5 (tour_unit split, price_rel_tour, price_rel_artist_era)."""
import numpy as np
import pandas as pd
d = pd.read_parquet("data/shows.parquet")
s = d[d.analysis_sample].copy()
print("sample", len(s))
yr = s.show_date.dt.year + s.show_date.dt.dayofyear / 366
n = s.groupby("tour_unit").size()
span = s.groupby("tour_unit").show_date.agg(lambda x: (x.max() - x.min()).days / 365.25)
print("units>=5 spanning >3y:", int(((span > 3) & (n >= 5)).sum()), "| max span (>=5):", round(float(span[n >= 5].max()), 2),
      "| p90:", round(float(span[n >= 5].quantile(.9)), 2))
print("tour_keys split:", int(s.groupby("tour_key").tour_unit.nunique().gt(1).sum()), "rows in split keys:",
      int(s.tour_key.isin(s.groupby("tour_key").tour_unit.nunique().pipe(lambda x: x[x > 1].index)).sum()))
# independent recompute of price_rel_tour
nu = s.groupby("tour_unit").show_id.transform("size")
mine = (s.log_avg_price_real - s.groupby("tour_unit").log_avg_price_real.transform("median")).where(nu >= 5)
print("price_rel_tour non-null", int(s.price_rel_tour.notna().sum()), "| mine", int(mine.notna().sum()),
      "| max|diff|", float((mine - s.price_rel_tour).abs().max()))
yw = yr - yr.groupby(s.tour_unit).transform("median")
m = s.price_rel_tour.notna()
print("corr(price_rel_tour, year - tour_unit median year): %.3f" % np.corrcoef(s.price_rel_tour[m], yw[m])[0, 1])
# does any unit straddle splits/artists?
print("units spanning >1 artist_key:", int(s.groupby("tour_unit").artist_key.nunique().gt(1).sum()),
      "| >1 split:", int(s.groupby("tour_unit").artist_split.nunique().gt(1).sum()))
# leg contrast preserved? tours (unit) with later_leg variation
ll = (s.leg_number > 1)
print("units with leg variation:", int(s.assign(l=ll).groupby("tour_unit").l.nunique().gt(1).sum()),
      "| tour_keys with leg variation:", int(s.assign(l=ll).groupby("tour_key").l.nunique().gt(1).sum()))
# era target
print("year_bucket_5 constant within tour_unit:", bool(s.groupby("tour_unit").year_bucket_5.nunique().eq(1).all()))
cell = s.artist_key.astype(str) + "|" + s.year_bucket_5.astype(str)
nc = s.groupby(cell).show_id.transform("size"); na = s.groupby("artist_key").show_id.transform("size")
mine2 = (s.log_avg_price_real - s.groupby(cell).log_avg_price_real.transform("median")).where((nc >= 5) & (na >= 5))
print("price_rel_artist_era non-null", int(s.price_rel_artist_era.notna().sum()), "| mine", int(mine2.notna().sum()),
      "| max|diff|", float((mine2 - s.price_rel_artist_era).abs().max()))
yc = yr - yr.groupby(cell).transform("median"); mm = s.price_rel_artist_era.notna()
print("corr(era target, year - cell median year): %.3f" % np.corrcoef(s.price_rel_artist_era[mm], yc[mm])[0, 1])
