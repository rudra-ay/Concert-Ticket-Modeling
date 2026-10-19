"""Join the show spine with every feature table -> data/shows.parquet.

Rerunnable: `.venv/bin/python src/analysis/build_shows.py`. Missing or partial
feature tables are joined as they are; their coverage is recorded in
data/shows_join_coverage.json and in DATA_DICTIONARY.md. Rerun when a feature
table is rebuilt.

Decisions (see DATA_DICTIONARY.md for details):
- Prices are deflated with CPI-U NSA to constant **September 2026** dollars
  (the latest published month; pre-1980 months come from the raw BLS file).
- Multi-show aggregate figures are one unit of analysis: the row carrying the
  figure (aggregate_is_first) is the observation; its avg price is already a
  per-ticket average over the stand. Other nights of the stand stay in the
  table, unpriced. Aggregates spanning more than one venue are excluded.
- Box-office figures repeated on two artists' tour articles (opener/co-bill)
  are kept once.
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from analysis.targets import (  # noqa: E402
    ROOT,
    artist_keys,
    artist_relative_target,
    artist_split,
    deflate,
    load_cpi,
)

INTERIM = ROOT / "data/interim"
OUT = ROOT / "data/shows.parquet"
COVERAGE = ROOT / "data/shows_join_coverage.json"
CPI_BASE_MONTH = pd.Timestamp("2026-09-01")

# name, file, join key, prefix used only on column-name collisions, columns to drop
# (spine copies), columns to keep (None = all).
TABLES = [
    ("artist", "features_artist.parquet", "artist_id", "artist", ["artist_name"], None),
    ("artist_show", "features_artist_show.parquet", "show_id", "as", ["artist_id"], None),
    ("venue", "features_venue.parquet", "venue_id", "venue", ["venue_name", "city", "country"], None),
    ("metro", "features_metro.parquet", "venue_id", "metro", [], None),
    ("venue_metro", "venue_metro.parquet", "venue_id", "vm", [], ["state_usps"]),
    ("calendar", "features_calendar.parquet", "show_id", "cal", [], None),
    ("tour_context", "features_tour_context.parquet", "show_id", "tour", [], None),
    ("bill", "features_bill.parquet", "show_id", "bill", [], None),
    ("weather", "features_weather.parquet", "show_id", "wx", [], None),
]

# Optional per-table definition of "row actually filled" for partial builds.
PROCESSED = {
    "venue": lambda d: d["venue_link_source"].notna(),
    "weather": lambda d: d["wx_status"].eq("ok"),
    # bill flags come from the spine and are always present; pageview and Wikidata
    # (album) lookups fill later
    "bill": lambda d: (d["opener_pv_status"].eq("done") if "opener_pv_status" in d else True)
    & (d["wikidata_status"].eq("done") if "wikidata_status" in d else True),
}


def _norm(s: object) -> str:
    return re.sub(r"[^a-z0-9]", "", str(s).lower()) if isinstance(s, str) else ""


def aggregate_groups(b: pd.DataFrame) -> pd.Series:
    """show_id of the aggregate's first row, for every row in a multi-show aggregate.

    Groups are rebuilt from spine row order: the first row is followed by its
    aggregate_n_shows - 1 member rows from the same page and table. Members that
    can't be placed get NA (they carry no figures).
    """
    gid = [None] * len(b)
    cur, left = None, 0
    first = b["aggregate_is_first"].to_numpy()
    n = b["aggregate_n_shows"].to_numpy()
    page = b["tour_page_id"].to_numpy()
    tab = b["table_index"].to_numpy()
    sid = b["show_id"].to_numpy()
    for i in range(len(b)):
        if n[i] <= 1:
            continue
        if first[i]:
            cur, left = i, n[i] - 1
            gid[i] = sid[i]
        elif cur is not None and left > 0 and page[i] == page[cur] and tab[i] == tab[cur]:
            gid[i] = sid[cur]
            left -= 1
    return pd.Series(gid, index=b.index, dtype="string")


def boxoffice_duplicates(b: pd.DataFrame) -> pd.DataFrame:
    """Flag priced rows whose gross is repeated for another artist at the same venue and date.

    Keep the headliner: the row whose opening-act cell names the other artist(s).
    Otherwise keep the artist with the most priced shows (ties: artist_id order).
    """
    out = pd.DataFrame(index=b.index, data={"dup_boxoffice_group": pd.NA, "dup_boxoffice_drop": False,
                                             "dup_boxoffice_resolved": pd.NA})
    out["dup_boxoffice_group"] = out["dup_boxoffice_group"].astype("string")
    out["dup_boxoffice_resolved"] = out["dup_boxoffice_resolved"].astype("string")
    p = b[b["avg_price_usd"].notna()]
    n_priced = p.groupby("artist_id").size()
    dup = p[p.duplicated(["venue_id", "show_date", "gross_usd"], keep=False)]
    for _, g in dup.groupby(["venue_id", "show_date", "gross_usd"]):
        heads = []
        for i, r in g.iterrows():
            acts = _norm(r["opening_acts_raw"]) + _norm(r["opening_acts_wikilinks"])
            if any(_norm(o) and _norm(o) in acts for o in g.drop(index=i)["artist_name"]):
                heads.append(i)
        if len(heads) == 1:
            keep, how = heads[0], "opener_named"
        else:
            keep = sorted(g.index, key=lambda i: (-n_priced[g.at[i, "artist_id"]], g.at[i, "artist_id"]))[0]
            how = "most_priced_shows"
        out.loc[g.index, "dup_boxoffice_group"] = g.at[keep, "show_id"]
        out.loc[g.index, "dup_boxoffice_resolved"] = how
        out.loc[g.index.drop(keep), "dup_boxoffice_drop"] = True
    return out


def join_features(df: pd.DataFrame, coverage: dict, origin: dict) -> pd.DataFrame:
    n0 = len(df)
    priced = df["avg_price_usd"].notna()
    for name, fname, key, prefix, drop, keep in TABLES:
        path = INTERIM / fname
        info = {"file": f"data/interim/{fname}", "key": key}
        if not path.exists():
            info.update(status="missing", rows=0)
            coverage[name] = info
            df[f"has_{name}"] = False
            origin[f"has_{name}"] = ("derived", f"has_{name}")
            continue
        t = pd.read_parquet(path)
        if t[key].duplicated().any():
            raise ValueError(f"{fname}: duplicate {key}")
        processed = PROCESSED[name](t) if name in PROCESSED else pd.Series(True, index=t.index)
        t = t.drop(columns=[c for c in drop if c in t.columns])
        if keep is not None:
            t = t[[key, *keep]]
        ren = {}
        for c in t.columns:
            if c == key:
                continue
            new = f"{prefix}_{c}" if c in df.columns else c
            ren[c] = new
            origin[new] = (name, c)
        t = t.rename(columns=ren)
        matched_keys = set(t[key])
        processed_keys = set(t.loc[processed.to_numpy(), key])
        df = df.merge(t, on=key, how="left", validate="many_to_one")
        if len(df) != n0:
            raise AssertionError(f"join with {fname} changed row count {n0} -> {len(df)}")
        df[f"has_{name}"] = df[key].isin(matched_keys)
        origin[f"has_{name}"] = ("derived", f"has_{name}")
        filled = df[key].isin(processed_keys)
        info.update(
            status="ok",
            rows=int(len(t)),
            modified=datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(timespec="minutes"),
            orphan_keys=int(len(matched_keys - set(df[key]))),
            pct_shows_matched=round(100 * df[f"has_{name}"].mean(), 1),
            pct_priced_matched=round(100 * df.loc[priced, f"has_{name}"].mean(), 1),
            pct_shows_filled=round(100 * filled.mean(), 1),
            pct_priced_filled=round(100 * filled[priced].mean(), 1),
            _filled=filled,
        )
        if info["pct_shows_matched"] < 99.5 or info["pct_shows_filled"] < 99.5:
            info["status"] = "partial"
        coverage[name] = info
    return df


def build() -> tuple[pd.DataFrame, dict, dict]:
    b = pd.read_parquet(INTERIM / "shows_base.parquet")
    if b["show_id"].duplicated().any():
        raise ValueError("shows_base has duplicate show_id")
    origin: dict[str, tuple[str, str]] = {c: ("shows_base", c) for c in b.columns}
    df = b.copy()

    def derived(col: str, values) -> None:
        df[col] = values
        origin[col] = ("derived", col)

    # --- aggregates --------------------------------------------------------
    gid = aggregate_groups(df)
    derived("agg_group_id", gid)
    grp = df[gid.notna()].groupby(gid[gid.notna()])
    agg_stats = pd.DataFrame({
        "agg_n_venues": grp["venue_id"].nunique(),
        "agg_span_days": (grp["show_date"].max() - grp["show_date"].min()).dt.days,
        "agg_last_date": grp["show_date"].max(),
    })
    for c in agg_stats.columns:
        derived(c, df["agg_group_id"].map(agg_stats[c]))
    derived("agg_n_venues", df["agg_n_venues"].astype("Int64"))
    derived("agg_span_days", df["agg_span_days"].astype("Int64"))
    derived("is_aggregate_unit", (df["aggregate_n_shows"] > 1) & df["aggregate_is_first"])
    k = df["aggregate_n_shows"].where(df["aggregate_is_first"]).astype(float)
    derived("tickets_sold_per_show", df["tickets_sold"] / k)
    derived("tickets_available_per_show", df["tickets_available"] / k)
    derived("gross_usd_per_show", df["gross_usd"] / k)

    # --- duplicates, cancellation, currency ---------------------------------
    for c, v in boxoffice_duplicates(df).items():
        derived(c, v)
    derived("is_cancelled_spine", df["status_note"].fillna("").str.contains("cancel"))
    derived("usd_assumed_non_us", df["gross_currency"].eq("USD") & df["country_iso2"].notna()
            & ~df["country_iso2"].isin(["US", "PR"]))

    # --- CPI ------------------------------------------------------------------
    cpi, imputed = load_cpi()
    real, idx = deflate(df["avg_price_usd"], df["show_date"], cpi, CPI_BASE_MONTH)
    derived("cpi_base_month", CPI_BASE_MONTH.strftime("%Y-%m"))
    derived("cpi_show_month", idx)
    months = df["show_date"].dt.to_period("M").dt.to_timestamp()
    derived("cpi_month_imputed", months.map(imputed).astype("boolean"))
    derived("avg_price_real", real)
    derived("gross_usd_real", deflate(df["gross_usd"], df["show_date"], cpi, CPI_BASE_MONTH)[0])
    derived("gross_usd_real_per_show", df["gross_usd_real"] / k)
    derived("log_avg_price_real", np.log(df["avg_price_real"].where(df["avg_price_real"] > 0)))
    derived("log_avg_price_nominal", np.log(df["avg_price_usd"].where(df["avg_price_usd"] > 0)))

    # --- feature tables -------------------------------------------------------
    coverage: dict = {}
    df = join_features(df, coverage, origin)

    # --- analysis sample ------------------------------------------------------
    cancelled = df["is_cancelled_spine"] | df.get("is_cancelled", pd.Series(False, index=df.index)).fillna(False).astype(bool)
    reasons = [
        ("unpriced", df["avg_price_usd"].isna()),
        ("non_usd", ~df["gross_currency"].eq("USD")),
        ("implausible", df["avg_price_flag"].eq("implausible")),
        ("tour_outlier", df["avg_price_flag"].eq("tour_outlier")),
        ("cancelled", cancelled),
        ("dup_boxoffice", df["dup_boxoffice_drop"]),
        ("aggregate_multi_venue", df["is_aggregate_unit"] & (df["agg_n_venues"].fillna(1) > 1)),
        ("no_cpi", ~np.isfinite(df["log_avg_price_real"])),
    ]
    reason = pd.Series(pd.NA, index=df.index, dtype="string")
    for name, m in reversed(reasons):
        reason = reason.mask(m.fillna(False).astype(bool), name)
    derived("analysis_exclusion_reason", reason)
    derived("analysis_sample", reason.isna())

    # --- targets and split ------------------------------------------------------
    s = df["analysis_sample"]
    split_key, artist_key = artist_keys(df)
    derived("split_key", split_key)
    derived("artist_key", artist_key)
    derived("artist_split", artist_split(df["split_key"]))
    med = df.loc[s].groupby("artist_key")["log_avg_price_real"].median()
    cnt = df.loc[s].groupby("artist_key").size()
    derived("artist_median_log_price_real", df["artist_key"].map(med).where(s))
    derived("artist_n_analysis", df["artist_key"].map(cnt).fillna(0).astype(int))
    derived("price_rel_artist_median", artist_relative_target(df, s).where(s))
    derived("unit_n_shows", df["aggregate_n_shows"].where(s).astype("Int64"))

    # per-column coverage of each feature table on the analysis sample
    for name, info in coverage.items():
        if "_filled" in info:
            f = info.pop("_filled")
            info["pct_analysis_filled"] = round(100 * f[s].mean(), 1)
        else:
            info["pct_analysis_filled"] = 0.0
    coverage["_summary"] = {
        "built": datetime.now(timezone.utc).isoformat(timespec="minutes"),
        "rows": int(len(df)),
        "priced": int(df["avg_price_usd"].notna().sum()),
        "analysis_sample": int(s.sum()),
        "analysis_artists": int(df.loc[s, "artist_id"].nunique()),
        "exclusions": {k: int(v) for k, v in reason.value_counts().items()},
        "split_artists": {k: int(v) for k, v in df.loc[s].groupby("artist_split")["artist_id"].nunique().items()},
        "split_keys": {k: int(v) for k, v in df.loc[s].groupby("artist_split")["split_key"].nunique().items()},
        "analysis_artist_keys": int(df.loc[s, "artist_key"].nunique()),
        "split_rows": {k: int(v) for k, v in df.loc[s, "artist_split"].value_counts().items()},
        "cpi_base_month": CPI_BASE_MONTH.strftime("%Y-%m"),
    }
    df.attrs = {}
    return df, coverage, origin


def main() -> None:
    df, coverage, origin = build()
    df.to_parquet(OUT, index=False)
    COVERAGE.write_text(json.dumps(coverage, indent=2, default=str))
    (ROOT / "data/shows_column_origin.json").write_text(json.dumps(origin, indent=1))
    from analysis.data_dictionary import write_dictionary
    write_dictionary(df, coverage, origin)
    sm = coverage["_summary"]
    print(f"wrote {OUT.relative_to(ROOT)}: {sm['rows']} rows, {df.shape[1]} cols, "
          f"priced {sm['priced']}, analysis_sample {sm['analysis_sample']} ({sm['analysis_artists']} artists)")
    for name, info in coverage.items():
        if name != "_summary":
            print(f"  {name:13s} {info['status']:8s} matched {info.get('pct_shows_matched', 0):5}% "
                  f"filled(priced) {info.get('pct_priced_filled', 0):5}% filled(sample) {info['pct_analysis_filled']:5}%")
    print("  exclusions:", sm["exclusions"])
    print("  split artists:", sm["split_artists"], "rows:", sm["split_rows"])


if __name__ == "__main__":
    main()
