"""Monthly FX rates, units of foreign currency per USD, 1971 on (A12) -> data/interim/fx_monthly.parquet.

Sources (Federal Reserve Board, public domain: "information on Board's website is in the public domain and may be
copied and distributed without permission. Please cite to the Board"; www.federalreserve.gov has no robots.txt):
1. G.5 monthly averages from the G.5/H.10 Data Download Program bulk file (one SDMX/ZIP, all history):
   https://www.federalreserve.gov/datadownload/Output.aspx?rel=H10&filetype=zip
2. Euro-legacy currencies (discontinued in G.5): H.10 historical daily noon buying rates, plain-text files
   releases/h10/hist/dat89_<cc>.txt (1971-1989) and dat96_<cc>.txt (1990-1998), averaged by month
   (the G.5 method). Greece also uses dat00_gr.txt (1999-2000; it joined the euro on 2001-01-01).
3. ECB euro foreign exchange reference rates (A13), full history bulk CSV
   https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist.zip, used ONLY for currencies the Fed doesn't
   publish, from 1999 on. Crossed through the same day's USD/EUR rate, then averaged by month. That is a
   modification of ECB data, which the ECB's terms require us to state (fx_monthly.md does).
Everything is cached in data/raw/fx/ and data/raw/fx_ecb/ and never refetched.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
import zipfile

import numpy as np
import pandas as pd

from context_http import INTERIM, RAW, fetch_cached

CACHE = RAW / "fx"
DDP_ZIP = "https://www.federalreserve.gov/datadownload/Output.aspx?rel=H10&filetype=zip"
HIST = "https://www.federalreserve.gov/releases/h10/hist/"

# Legacy file code -> (ISO code, euro conversion rate per EUR, Council Regulation 2866/98 and 1478/2000)
LEGACY = {
    "ge": ("DEM", 1.95583), "fr": ("FRF", 6.55957), "it": ("ITL", 1936.27), "sp": ("ESP", 166.386),
    "ne": ("NLG", 2.20371), "be": ("BEF", 40.3399), "au": ("ATS", 13.7603), "po": ("PTE", 200.482),
    "fn": ("FIM", 5.94573), "ir": ("IEP", 0.787564), "gr": ("GRD", 340.750),
}
LEGACY_FILES = {cc: ["dat89", "dat96"] + (["dat00"] if cc == "gr" else []) for cc in LEGACY}
VALIDATE_CC = ("ja", "JPY")
ECB_ZIP = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist.zip"
ECB_CACHE = RAW / "fx_ecb"
# Validation currencies present in both the Fed and the ECB.
ECB_VALIDATE = ["JPY", "GBP", "CAD", "AUD", "CHF", "SEK", "KRW", "MXN"]  # recomputed from daily files and compared with G.5 monthly


def load_g5() -> pd.DataFrame:
    zpath = fetch_cached(DDP_ZIP, CACHE / "FRB_H10.zip", timeout=300)
    with zipfile.ZipFile(zpath) as z:
        name = next(n for n in z.namelist() if n.endswith("_data.xml"))
        root_iter = ET.iterparse(z.open(name), events=("start",))
        rows, series = [], None
        for _, el in root_iter:
            tag = el.tag.rsplit("}", 1)[-1]
            if tag == "Series":
                series = dict(el.attrib)
            elif tag == "Obs" and series and series.get("FREQ") == "129" and series.get("UNIT", "").startswith("Currency"):
                rows.append({**series, "TIME_PERIOD": el.attrib.get("TIME_PERIOD"), "OBS_VALUE": el.attrib.get("OBS_VALUE"),
                             "OBS_STATUS": el.attrib.get("OBS_STATUS")})
    d = pd.DataFrame(rows)
    d["value"] = pd.to_numeric(d.OBS_VALUE, errors="coerce")
    d.loc[d.OBS_STATUS.fillna("A") != "A", "value"] = np.nan  # ND / NC observations
    d["month_start"] = pd.to_datetime(d.TIME_PERIOD).dt.to_period("M").dt.to_timestamp()
    usd_per_unit = d.UNIT.str.startswith("Currency:_Per_") & ~d.UNIT.eq("Currency:_Per_USD")
    # AUD, NZD, GBP, EUR are quoted as USD per unit; invert to units per USD. (UNIT_MULT on GBP is a
    # display artefact in the file: the values are dollars per pound, e.g. ~1.3 in 2024.)
    d["units_per_usd"] = np.where(usd_per_unit, 1.0 / d.value, d.value)
    d["currency"] = d.FX.replace({"ZAL": "ZAR"})
    return pd.DataFrame({
        "currency": d.currency, "month_start": d.month_start, "units_per_usd": d.units_per_usd,
        "source": "FRB G.5 monthly average", "series_id": d.SERIES_NAME,
        "quoted_as": np.where(usd_per_unit, "USD per unit (inverted)", "units per USD"),
    })


def _parse_daily(text: str) -> tuple[str, pd.Series]:
    header = next((ln.strip() for ln in text.splitlines() if "EXCHANGE RATE" in ln), "")
    pts = re.findall(r"^\s*(\d{1,2}-[A-Za-z]{3}-\d{2})\s+(\S+)\s*$", text, flags=re.M)
    s = pd.Series({pd.to_datetime(d, format="%d-%b-%y"): v for d, v in pts})
    s.index = s.index.map(lambda t: t if t.year <= 2030 else t.replace(year=t.year - 100))
    return header, pd.to_numeric(s, errors="coerce")  # "ND" (no data) -> NaN


def daily_to_monthly(cc: str, files: list[str]) -> tuple[pd.DataFrame, list[str]]:
    parts, headers = [], []
    for f in files:
        name = f"{f}_{cc}.txt"
        header, s = _parse_daily(fetch_cached(HIST + name, CACHE / "hist" / name).read_text(errors="ignore"))
        headers.append(f"{name}: {header}")
        parts.append(s)
    daily = pd.concat(parts).sort_index()
    daily = daily[~daily.index.duplicated(keep="last")]
    # Quote direction from the header, e.g. "DM/US$" (units per USD) vs "US$/IR£" (USD per unit).
    usd_per_unit = bool(re.search(r"(US\$|\$US)\s*/", headers[0]))
    m = daily.groupby(daily.index.to_period("M")).agg(["mean", "count"])
    m = m[m["count"] > 0]
    out = pd.DataFrame({"month_start": m.index.to_timestamp(),
                        "units_per_usd": (1.0 / m["mean"] if usd_per_unit else m["mean"]).values,
                        "n_daily_obs": m["count"].values})
    return out, headers


def load_ecb_daily_cross() -> pd.DataFrame:
    """Daily units per USD for every ECB currency: (X per EUR) / (USD per EUR), same day."""
    zpath = fetch_cached(ECB_ZIP, ECB_CACHE / "eurofxref-hist.zip", timeout=300)
    with zipfile.ZipFile(zpath) as z:
        d = pd.read_csv(z.open(z.namelist()[0]), na_values=["N/A"])
    d = d.loc[:, ~d.columns.str.startswith("Unnamed")]
    d["Date"] = pd.to_datetime(d.Date)
    d = d.set_index("Date").sort_index().apply(pd.to_numeric, errors="coerce")
    cross = d.drop(columns="USD").div(d["USD"], axis=0)
    cross["EUR"] = 1.0 / d["USD"]
    return cross


def ecb_monthly(cross: pd.DataFrame, currencies: list[str]) -> pd.DataFrame:
    rows = []
    for c in currencies:
        s = cross[c].dropna()
        m = s.groupby(s.index.to_period("M")).agg(["mean", "count"])
        rows.append(pd.DataFrame({"currency": c, "month_start": m.index.to_timestamp(),
                                  "units_per_usd": m["mean"].values, "n_daily_obs": m["count"].values}))
    return pd.concat(rows, ignore_index=True)


def build() -> pd.DataFrame:
    g5 = load_g5()
    legacy = []
    for cc, (iso, fixed) in LEGACY.items():
        m, headers = daily_to_monthly(cc, LEGACY_FILES[cc])
        print(f"{iso}: {m.month_start.min():%Y-%m}..{m.month_start.max():%Y-%m}  [{headers[0]}]")
        legacy.append(m.assign(currency=iso, source="FRB H.10 historical daily, monthly mean",
                               series_id=",".join(f"{f}_{cc}" for f in LEGACY_FILES[cc]),
                               quoted_as="units per USD", eur_fixed_rate=fixed))
    cross = load_ecb_daily_cross()
    fed_currencies = set(g5.currency) | {v[0] for v in LEGACY.values()}
    ecb_only = sorted(c for c in cross.columns if c not in fed_currencies)
    ecb = ecb_monthly(cross, ecb_only).assign(
        source="ECB euro reference rate crossed via USD/EUR, monthly mean",
        series_id=lambda x: "ECB eurofxref-hist: " + x.currency + "/EUR ÷ USD/EUR", quoted_as="units per USD (cross)")
    ecb = ecb[ecb.month_start < pd.Timestamp.today().to_period("M").to_timestamp()]  # drop the partial month
    print(f"ECB fills {len(ecb_only)} currencies the Fed lacks: {', '.join(ecb_only)}")
    fx = pd.concat([g5, *legacy, ecb], ignore_index=True)
    fx["is_cross_rate"] = fx.source.str.startswith("ECB")
    fx["is_euro_legacy"] = fx.currency.isin([v[0] for v in LEGACY.values()])
    fx = fx.dropna(subset=["units_per_usd"]).sort_values(["currency", "month_start"]).reset_index(drop=True)
    fx["year"] = fx.month_start.dt.year
    fx["month"] = fx.month_start.dt.month
    cols = ["currency", "month_start", "year", "month", "units_per_usd", "source", "series_id", "quoted_as",
            "is_euro_legacy", "is_cross_rate", "eur_fixed_rate", "n_daily_obs"]
    return fx[cols]


def validate(fx: pd.DataFrame) -> float:
    """Max relative gap between our monthly mean of daily JPY rates and the published G.5 monthly JPY."""
    cc, iso = VALIDATE_CC
    ours, _ = daily_to_monthly(cc, ["dat89", "dat96"])
    pub = fx[(fx.currency == iso) & (fx.source.str.startswith("FRB G.5"))][["month_start", "units_per_usd"]]
    j = ours.merge(pub, on="month_start", suffixes=("_ours", "_g5"))
    gap = ((j.units_per_usd_ours - j.units_per_usd_g5).abs() / j.units_per_usd_g5).max()
    print(f"validation {iso}: {len(j)} months compared, max relative gap {gap:.5%}")
    return gap


def validate_ecb(fx: pd.DataFrame) -> pd.DataFrame:
    """How far an ECB cross sits from the Fed's G.5 monthly average for currencies both publish."""
    m = ecb_monthly(load_ecb_daily_cross(), ECB_VALIDATE)
    pub = fx[fx.source.str.startswith("FRB G.5")][["currency", "month_start", "units_per_usd"]]
    j = m.merge(pub, on=["currency", "month_start"], suffixes=("_ecb", "_fed"))
    j["rel_gap"] = (j.units_per_usd_ecb / j.units_per_usd_fed - 1).abs()
    out = j.groupby("currency").rel_gap.agg(["count", "median", "max"])
    print("ECB cross vs Fed G.5 (relative gap):\n" + out.to_string(float_format=lambda v: f"{v:.4%}"))
    return out


def main() -> None:
    fx = build()
    validate(fx)
    validate_ecb(fx)
    out = INTERIM / "fx_monthly.parquet"
    fx.to_parquet(out, index=False)
    print(f"wrote {out}: {len(fx)} rows, {fx.currency.nunique()} currencies")
    print(fx.groupby("currency").month_start.agg(["min", "max", "count"]).to_string())


if __name__ == "__main__":
    main()
