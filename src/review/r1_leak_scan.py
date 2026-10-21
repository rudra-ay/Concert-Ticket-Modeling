"""Skeptic review 1: scan numeric/bool columns for suspiciously high within-artist correlation with the target."""
import json
import numpy as np
import pandas as pd

d = pd.read_parquet("data/shows.parquet")
s = d[d.analysis_sample]
y = s.log_avg_price_real
yw = y - y.groupby(s.artist_key).transform("mean")
codes = {}
for line in open("data/DATA_DICTIONARY.md"):
    if line.startswith("| `"):
        p = [x.strip() for x in line.split("|")]
        codes[p[1].strip("`")] = p[8]
out = []
for c in s.columns:
    if not (pd.api.types.is_numeric_dtype(s[c]) or pd.api.types.is_bool_dtype(s[c])):
        continue
    x = pd.to_numeric(s[c], errors="coerce").astype(float)
    if x.notna().sum() < 500 or x.nunique() < 2:
        continue
    xw = x - x.groupby(s.artist_key).transform("mean")
    m = xw.notna() & yw.notna()
    r_w = np.corrcoef(xw[m], yw[m])[0, 1]
    r = np.corrcoef(x[m], y[m])[0, 1]
    out.append((c, codes.get(c, "?"), round(r, 3), round(r_w, 3)))
o = pd.DataFrame(out, columns=["col", "code", "r", "r_within_artist"])
o = o[~o.code.str.startswith(("TARGET", "OUTCOME"))]
print(o.reindex(o.r_within_artist.abs().sort_values(ascending=False).index).head(25).to_string(index=False))
