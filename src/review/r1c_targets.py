"""Skeptic review 1c: evaluate the analyst's proposed price_rel_tour and price_rel_artist_era."""
import numpy as np
import pandas as pd
d = pd.read_parquet("data/shows.parquet")
s = d[d.analysis_sample].copy()
s["yr"] = s.show_date.dt.year + s.show_date.dt.dayofyear / 366
y = s.log_avg_price_real
# tour target
n_t = s.groupby("tour_key").show_id.transform("size")
s["rel_tour"] = (y - y.groupby(s.tour_key).transform("median")).where(n_t >= 5)
span = s.groupby("tour_key").yr.agg(lambda t: t.max() - t.min())
print("rows with rel_tour:", int(s.rel_tour.notna().sum()), "of", len(s), "| tours>=5:", int((s.groupby('tour_key').size() >= 5).sum()))
print("tour span (yrs) among tours>=5: p50 %.2f p90 %.2f p99 %.2f max %.1f" % tuple(span[s.groupby('tour_key').size() >= 5].quantile([.5, .9, .99, 1]).values))
long = span[(span > 3) & (s.groupby("tour_key").size() >= 5)].sort_values(ascending=False)
print("tours>=5 spanning >3y:", len(long), "rows:", int(s.tour_key.isin(long.index).sum()))
print(long.head(12).round(1).to_dict())
yw = s.yr - s.groupby("tour_key").yr.transform("median")
m = s.rel_tour.notna()
print("corr(rel_tour, yr - tour median yr): %.3f" % np.corrcoef(s.rel_tour[m], yw[m])[0, 1])
m2 = m & ~s.tour_key.isin(long.index)
print("  excluding >3y tours: %.3f" % np.corrcoef(s.rel_tour[m2], yw[m2])[0, 1])
# era target: calendar bucket vs tour-start-year bucket
for name, b in [("calendar show year", (s.show_date.dt.year // 5) * 5),
                ("tour start year", (s.groupby("tour_key").show_date.transform("min").dt.year // 5) * 5)]:
    cell = s.artist_key.astype(str) + "|" + b.astype(str)
    nc = s.groupby(cell).show_id.transform("size")
    na = s.groupby("artist_key").show_id.transform("size")
    rel = (y - y.groupby(cell).transform("median")).where((nc >= 5) & (na >= 5))
    yc = s.yr - s.groupby(cell).yr.transform("median")
    mm = rel.notna()
    split_tours = int((s.assign(c=cell).groupby("tour_key").c.nunique() > 1).sum())
    print(f"era[{name}]: rows {int(mm.sum())}, tours split across cells {split_tours}, corr(rel, yr - cell median yr) {np.corrcoef(rel[mm], yc[mm])[0, 1]:.3f}")
