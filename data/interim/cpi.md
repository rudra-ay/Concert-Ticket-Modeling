# cpi.parquet

Monthly CPI-U (all items, 1982-84 = 100), 1980-01 through the latest BLS release. Built by `src/build_cpi.py` from the BLS flat files at `download.bls.gov/pub/time.series/cu/` (`cu.data.1.AllItems`, `cu.series`, `cu.area`), cached in `data/raw/bls_cpi/`. Source: U.S. Bureau of Labor Statistics. Public domain (US government work, assumed); cite BLS.

One row per calendar month. Key: `month_start`.

| column | type | unit | source | null meaning |
|---|---|---|---|---|
| year | int | | derived | never null |
| month | int | 1-12 | derived | never null |
| month_start | datetime | first day of month | derived | never null |
| cpi_u_nsa | float | index | CUUR0000SA0 (U.S. city average, not seasonally adjusted) | not published (only 2025-10) |
| cpi_u_sa | float | index | CUSR0000SA0 (seasonally adjusted) | not published |
| cpi_u_nsa_northeast | float | index | CUUR0100SA0 | not published |
| cpi_u_nsa_midwest | float | index | CUUR0200SA0 | not published |
| cpi_u_nsa_south | float | index | CUUR0300SA0 | not published |
| cpi_u_nsa_west | float | index | CUUR0400SA0 | not published |
| cpi_u_nsa_imputed | bool | | derived | True where `cpi_u_nsa` was missing and `cpi_u_nsa_filled` is interpolated |
| cpi_u_nsa_filled | float | index | `cpi_u_nsa`, linearly interpolated across interior gaps | never null |

## Notes
- **October 2025 is missing at the source.** BLS did not collect it during the federal shutdown (footnote code `X`). The row is kept; `cpi_u_nsa_filled` holds the midpoint of September and November 2025, with `cpi_u_nsa_imputed = True`.
- **How to deflate:** `real_usd = nominal_usd * cpi_u_nsa_filled[ref_month] / cpi_u_nsa_filled[show_month]`. Use the NSA series (the BLS-recommended deflator); SA is for reference only.
- Regional series are Census regions. Use them only for US shows.
- Non-US prices: convert to USD first (collector-prices keeps the original currency). Applying US CPI to foreign prices is an approximation.
