"""Skeptic review 1: tour infobox gross/attendance is target-derived (tour avg price includes the row)."""
import re
import numpy as np
import pandas as pd

d = pd.read_parquet("data/shows.parquet")
s = d[d.analysis_sample].copy()


def num(t):
    if not isinstance(t, str):
        return np.nan
    t = t.replace(",", "")
    m = re.search(r"(\d+(?:\.\d+)?)\s*(million|billion)?", t, re.I)
    if not m:
        return np.nan
    v = float(m.group(1))
    return v * {"million": 1e6, "billion": 1e9}.get((m.group(2) or "").lower(), 1)


s["ig"] = s.tour_infobox_gross.map(num)
s["ia"] = s.tour_infobox_attendance.map(num)
s["tour_avg"] = np.log(s.ig / s.ia)
ok = s.tour_avg.between(np.log(5), np.log(3000))
print("rows with parsable infobox gross & attendance:", int(ok.sum()))
print("corr(log tour gross/attendance, log_avg_price_nominal):", round(float(s.loc[ok, ["tour_avg", "log_avg_price_nominal"]].corr().iloc[0, 1]), 3))
print("corr with price_rel_artist_median:", round(float(s.loc[ok, ["tour_avg", "price_rel_artist_median"]].corr().iloc[0, 1]), 3))
