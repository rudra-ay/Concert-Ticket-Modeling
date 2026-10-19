"""Target construction shared by the join (build_shows.py) and the modelling code.

Everything here is a pure function of a DataFrame, so it can be re-applied
inside training folds (see `artist_relative_target`).
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
CPI_PARQUET = ROOT / "data/interim/cpi.parquet"
BLS_RAW = ROOT / "data/raw/bls_cpi/cu.data.1.AllItems"

SPLIT_SALT = "seatprice-v1"
SPLIT_SHARES = (("train", 0.70), ("valid", 0.15), ("test", 0.15))


def load_cpi() -> tuple[pd.Series, pd.Series]:
    """Monthly CPI-U NSA indexed by month_start, plus an 'imputed' flag series.

    cpi.parquet starts at 1980-01. Earlier months (1970s shows) come from the
    same BLS series (CUUR0000SA0) in the locally cached raw flat file, if present.
    """
    c = pd.read_parquet(CPI_PARQUET).set_index("month_start").sort_index()
    cpi = c["cpi_u_nsa_filled"].astype(float)
    imputed = c["cpi_u_nsa_imputed"].astype(bool)
    if BLS_RAW.exists():
        raw = pd.read_csv(BLS_RAW, sep="\t", dtype=str)
        raw.columns = [x.strip() for x in raw.columns]
        raw = raw[(raw.series_id.str.strip() == "CUUR0000SA0") & raw.period.str.match(r"M(0[1-9]|1[0-2])$")]
        raw = raw.assign(
            month_start=pd.to_datetime(raw.year.str.strip() + "-" + raw.period.str[1:] + "-01"),
            value=pd.to_numeric(raw.value.str.strip(), errors="coerce"),
        )
        early = raw[raw.month_start < cpi.index.min()].set_index("month_start")["value"].dropna()
        cpi = pd.concat([early, cpi]).sort_index()
        imputed = pd.concat([pd.Series(False, index=early.index), imputed]).sort_index()
    return cpi, imputed


def deflate(nominal: pd.Series, dates: pd.Series, cpi: pd.Series, base_month: pd.Timestamp) -> tuple[pd.Series, pd.Series]:
    """Return (real value in base-month dollars, cpi month used). NaN where the month has no CPI."""
    months = dates.dt.to_period("M").dt.to_timestamp()
    idx = months.map(cpi)
    real = nominal * cpi.loc[base_month] / idx
    return real, idx


def artist_keys(df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """(split_key, artist_key) for each row.

    artist_key: for single-headliner acts, the performer's Wikidata QID, else the
    artist slug with "List of ..." page wording stripped (merges aliases like
    P!nk/Pink); for co-headline acts the artist_id (a package is its own product).
    split_key: connected component of artist_ids that share a performer, i.e. an
    artist_key or any headliner link in `artist_wikilink` (so "Elton John and
    Billy Joel", "Elton John" and "Billy Joel" land in the same split). Named by
    the component's alphabetically first artist_key.
    """
    slug = (df["artist_id"]
            .str.replace(r"^list-of-(\d{4}-)?", "", regex=True)
            .str.replace(r"-(live-performances|concerts|concert-tours-and-festivals|festival-shows|finalists)$", "", regex=True))
    qid_by_slug = df.dropna(subset=["artist_qid"]).groupby("artist_id")["artist_qid"].first()
    qid = df["artist_qid"].fillna(slug.map(qid_by_slug))
    performer = qid.fillna("slug:" + slug)
    solo = df["n_headliners"].fillna(1).eq(1) if "n_headliners" in df else pd.Series(True, index=df.index)
    artist_key = performer.where(solo, "act:" + df["artist_id"]).astype("string")

    parent: dict[str, str] = {}

    def find(x: str) -> str:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)

    links = df.get("artist_wikilink", pd.Series(pd.NA, index=df.index))
    for aid, perf, ak, lk in zip(df["artist_id"], performer, artist_key, links):
        node = f"id:{aid}"
        union(node, f"p:{perf}")
        union(node, f"k:{ak}")
        if isinstance(lk, str):
            for target in lk.split(" | "):
                if target.strip():
                    union(node, "w:" + target.strip().replace("_", " ").lower())
    # name each component by its first artist_key (stable, human-readable)
    comp_name: dict[str, str] = {}
    for aid, ak in sorted(zip(df["artist_id"], artist_key), key=lambda x: str(x[1])):
        comp_name.setdefault(find(f"id:{aid}"), str(ak))
    split_key = df["artist_id"].map(lambda a: comp_name[find(f"id:{a}")]).astype("string")
    return split_key, artist_key


def artist_split(artist_id: pd.Series) -> pd.Series:
    """Deterministic train/valid/test assignment (md5 of salt + key); pass split_key."""
    def one(a: str) -> str:
        u = int(hashlib.md5(f"{SPLIT_SALT}:{a}".encode()).hexdigest()[:12], 16) / 16**12
        acc = 0.0
        for name, share in SPLIT_SHARES:
            acc += share
            if u < acc:
                return name
        return SPLIT_SHARES[-1][0]
    return artist_id.map(one).astype("string")


def artist_median(df: pd.DataFrame, fit_mask: pd.Series, col: str = "log_avg_price_real",
                  key: str = "artist_key") -> pd.Series:
    """Median of `col` per artist key, using only rows in `fit_mask` (e.g. a training fold)."""
    return df.loc[fit_mask].groupby(key)[col].median()


def artist_relative_target(df: pd.DataFrame, fit_mask: pd.Series, col: str = "log_avg_price_real",
                           key: str = "artist_key") -> pd.Series:
    """`col` minus the artist's median computed on `fit_mask` rows only.

    Rows whose artist has no rows in `fit_mask` get NaN. Pass the training fold as
    `fit_mask` when the target is used inside cross-validation; the version stored
    in shows.parquet uses the whole analysis sample (see DATA_DICTIONARY.md, leakage).
    """
    med = artist_median(df, fit_mask, col, key)
    return df[col] - df[key].map(med)


def finite(s: pd.Series) -> pd.Series:
    return pd.Series(np.isfinite(s.astype(float)), index=s.index)
