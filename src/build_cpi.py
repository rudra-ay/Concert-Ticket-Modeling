"""Monthly CPI-U from the BLS flat files (A9) -> data/interim/cpi.parquet (+ cpi.md).

Route: download.bls.gov/pub/time.series/cu/ flat files (not api.bls.gov, per DECISIONS.md).
"""
from __future__ import annotations

import pandas as pd

from context_http import INTERIM, RAW, fetch_cached

BASE = "https://download.bls.gov/pub/time.series/cu/"
FILES = ["cu.series", "cu.data.1.AllItems", "cu.area"]

# All items, all urban consumers. NSA is the standard deflator; SA is included for reference.
SERIES = {
    "CUUR0000SA0": "cpi_u_nsa",
    "CUSR0000SA0": "cpi_u_sa",
    "CUUR0100SA0": "cpi_u_nsa_northeast",
    "CUUR0200SA0": "cpi_u_nsa_midwest",
    "CUUR0300SA0": "cpi_u_nsa_south",
    "CUUR0400SA0": "cpi_u_nsa_west",
}


def main() -> None:
    paths = {f: fetch_cached(BASE + f, RAW / "bls_cpi" / f) for f in FILES}
    d = pd.read_csv(paths["cu.data.1.AllItems"], sep="\t", dtype=str)
    d.columns = [c.strip() for c in d.columns]
    d = d.apply(lambda c: c.str.strip())
    d = d[d.series_id.isin(SERIES) & d.period.str.match(r"M(0[1-9]|1[0-2])$")]
    d = d[d.year.astype(int) >= 1980]
    d["value"] = pd.to_numeric(d.value, errors="coerce")
    d["year"] = d.year.astype(int)
    d["month"] = d.period.str[1:].astype(int)
    wide = d.pivot_table(index=["year", "month"], columns="series_id", values="value").rename(columns=SERIES)
    wide = wide.reset_index()
    wide.columns.name = None
    wide.insert(2, "month_start", pd.to_datetime(dict(year=wide.year, month=wide.month, day=1)))
    wide = wide[["year", "month", "month_start", *SERIES.values()]].sort_values("month_start")
    # BLS did not collect October 2025 (shutdown; footnote X). Keep every month as a row,
    # and give the analyst a filled deflator with an explicit imputation flag.
    full = pd.date_range(wide.month_start.min(), wide.month_start.max(), freq="MS")
    wide = wide.set_index("month_start").reindex(full).rename_axis("month_start").reset_index()
    wide["year"] = wide.month_start.dt.year
    wide["month"] = wide.month_start.dt.month
    wide = wide[["year", "month", "month_start", *SERIES.values()]]
    wide["cpi_u_nsa_imputed"] = wide.cpi_u_nsa.isna()
    wide["cpi_u_nsa_filled"] = wide.cpi_u_nsa.interpolate(method="linear", limit_area="inside")
    out = INTERIM / "cpi.parquet"
    wide.to_parquet(out, index=False)
    last = wide.dropna(subset=["cpi_u_nsa"]).iloc[-1]
    print(f"wrote {out}: {len(wide)} months, {wide.month_start.min():%Y-%m} .. {last.month_start:%Y-%m}")


if __name__ == "__main__":
    main()
