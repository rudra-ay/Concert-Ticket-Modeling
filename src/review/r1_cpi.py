"""Skeptic review 1: CPI deflation checks."""
import sys
import numpy as np
import pandas as pd
sys.path.insert(0, "src")
from analysis.targets import load_cpi, BLS_RAW

c = pd.read_parquet("data/interim/cpi.parquet").set_index("month_start").sort_index()
print(c.tail(14)[["cpi_u_nsa_filled", "cpi_u_nsa_imputed"]].to_string())
print("imputed months:", list(c.index[c.cpi_u_nsa_imputed].strftime("%Y-%m")))
raw = pd.read_csv(BLS_RAW, sep="\t", dtype=str)
raw.columns = [x.strip() for x in raw.columns]
raw = raw[(raw.series_id.str.strip() == "CUUR0000SA0") & raw.period.str.match(r"M(0[1-9]|1[0-2])$")]
raw.index = pd.to_datetime(raw.year.str.strip() + "-" + raw.period.str[1:] + "-01")
rv = pd.to_numeric(raw.value.str.strip(), errors="coerce")
ov = c.cpi_u_nsa_filled.reindex(rv.index).dropna()
print("splice: max |parquet - raw| over overlap:", float((ov - rv.reindex(ov.index)).abs().max()), "n", len(ov))
print("raw has 2025-10?", "2025-10-01" in rv.dropna().index.strftime("%Y-%m-%d"), "| raw last:", rv.dropna().index.max())
print("Sep-2025, Nov-2025 raw:", rv.get(pd.Timestamp("2025-09-01")), rv.get(pd.Timestamp("2025-11-01")),
      "| parquet Oct-2025:", c.cpi_u_nsa_filled.get(pd.Timestamp("2025-10-01")))
cpi, imp = load_cpi()
print("load_cpi monotone index? gaps:", int((cpi.index.to_series().diff().dt.days > 31).sum()), "first:", cpi.index.min())
d = pd.read_parquet("data/shows.parquet")
s = d[d.analysis_sample]
print("sample rows in imputed months:", int(s.cpi_month_imputed.fillna(False).sum()))
print("sample rows pre-1980:", int((s.show_date < "1980-01-01").sum()))
# independent deflation check
base = cpi.loc["2026-09-01"]
m = s.show_date.dt.to_period("M").dt.to_timestamp()
mine = s.avg_price_usd * base / m.map(cpi)
print("deflation max rel err:", float(((mine - s.avg_price_real) / s.avg_price_real).abs().max()))
# dates in the future / after base month with prices
print("priced rows dated after 2026-09-30:", int((d.avg_price_usd.notna() & (d.show_date > "2026-09-30")).sum()),
      "| after today 2026-10-19:", int((d.avg_price_usd.notna() & (d.show_date > "2026-10-19")).sum()),
      "| in sample after today:", int((s.show_date > "2026-10-19").sum()))
print(d.loc[d.avg_price_usd.notna() & (d.show_date > "2026-10-19"), ["show_id", "analysis_exclusion_reason", "aggregate_n_shows"]].head(10).to_string())
# long-span aggregates: deflation at first month vs midpoint
u = s[s.is_aggregate_unit & s.agg_span_days.gt(60)]
for _, r in u.iterrows():
    mid = (r.show_date + (r.agg_last_date - r.show_date) / 2).to_period("M").to_timestamp()
    print(r.show_id, r.agg_span_days, "first-month CPI vs mid-month CPI ratio:", round(cpi[mid] / cpi[r.show_date.to_period('M').to_timestamp()], 3))
