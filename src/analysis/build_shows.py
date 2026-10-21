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
    artist_era_target,
    artist_keys,
    artist_relative_target,
    artist_split,
    deflate,
    load_cpi,
    tour_relative_target,
    wikidata_group_edges,
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


DEDUPE_CSV = ROOT / "data/manual/boxoffice_dedupe.csv"
RELATIONS_CSV = ROOT / "data/manual/artist_relations.csv"
NON_PERFORMERS_CSV = ROOT / "data/manual/non_performers.csv"


TOUR_GAP_DAYS = 90
TOUR_MAX_SPAN_DAYS = 730


def tour_units(df: pd.DataFrame) -> pd.Series:
    """Split tour_key into tour units (review 1, amendment A1).

    Some tour_keys are list articles or residencies spanning many years (Phish concert tours,
    List of Yes tours, Billy Joel at MSG), and some real tours have long pauses (No Filter's
    COVID break). Rule: only tour_keys spanning more than 2 years are split. Within such a key,
    start a new unit after a gap of more than 90 days between consecutive played shows; a unit
    that still spans more than 2 years (a residency with regular dates) is split by calendar
    year. Tours of up to 2 years are left whole, so between-leg breaks stay within the tour. Units are named `<tour_key>#<k>` when a
    key is split, else the tour_key itself.
    """
    out = pd.Series(pd.NA, index=df.index, dtype="string")
    d = df[df["tour_key"].notna()].sort_values(["tour_key", "show_date"])
    for key, g in d.groupby("tour_key", sort=False):
        if (g["show_date"].max() - g["show_date"].min()).days <= TOUR_MAX_SPAN_DAYS:
            out.loc[g.index] = key  # an ordinary tour, breaks between legs included
            continue
        gap = g["show_date"].diff().dt.days.fillna(0)
        seg = (gap > TOUR_GAP_DAYS).cumsum()
        labels = seg.astype(str)
        for sid, sg in g.groupby(seg):
            if (sg["show_date"].max() - sg["show_date"].min()).days > TOUR_MAX_SPAN_DAYS:
                labels.loc[sg.index] = f"{sid}y" + sg["show_date"].dt.year.astype(str)
        if labels.nunique() == 1:
            out.loc[g.index] = key
        else:
            codes = pd.Series(pd.factorize(labels)[0] + 1, index=g.index)
            out.loc[g.index] = key + "#" + codes.astype(str)
    return out


def country_final(df: pd.DataFrame) -> pd.Series:
    """Spine country_iso2, else the venue's Wikidata P17 country, else the spine country text.

    The spine text is sometimes doubled ("Germany Germany"); repeated halves are collapsed
    before the pycountry lookup.
    """
    import pycountry

    alias = {"England": "GB", "Scotland": "GB", "Wales": "GB", "Northern Ireland": "GB", "UK": "GB",
             "USA": "US", "U.S.": "US", "United States": "US", "South Korea": "KR", "Russia": "RU"}

    def from_text(x: object) -> object:
        if not isinstance(x, str) or not x.strip():
            return pd.NA
        w = x.split()
        if len(w) % 2 == 0 and w[: len(w) // 2] == w[len(w) // 2:]:
            x = " ".join(w[: len(w) // 2])
        x = alias.get(x.strip(), x.strip())
        if len(x) == 2 and x.isupper():
            return x
        try:
            return pycountry.countries.lookup(x).alpha_2
        except LookupError:
            return pd.NA

    venue = df["venue_country_iso2"] if "venue_country_iso2" in df else pd.Series(pd.NA, index=df.index)
    city_suffix = df["city"].str.rsplit(",", n=1).str[1].where(df["city"].str.contains(",", na=False))
    us_metro = df["metro_scope"].isin(["metropolitan", "micropolitan", "us_outside_cbsa", "us_unmatched"]) \
        if "metro_scope" in df else pd.Series(False, index=df.index)
    return (df["country_iso2"].astype("string").fillna(venue.astype("string"))
            .fillna(df["country"].map(from_text).astype("string"))
            .fillna(city_suffix.map(from_text).astype("string"))
            .fillna(pd.Series("US", index=df.index, dtype="string").where(us_metro)))


def detect_duplicate_groups(b: pd.DataFrame) -> pd.Series:
    """Group id for priced rows that report the same show twice; NA otherwise.

    Two priced rows on the same date are the same box office line when the gross is
    exactly equal, or tickets_sold is equal (> 1,000) and the gross is within 5%.
    Venue names are not compared (variants like "Superdome" / "Louisiana Superdome"
    defeat venue_id). Groups are connected components of such pairs, named
    "<date>|<first show_id>".
    """
    p = b[b["avg_price_usd"].notna() & b["gross_usd"].gt(10_000)]
    parent: dict[int, int] = {}

    def find(x: int) -> int:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for _, g in p.groupby("show_date"):
        if len(g) < 2:
            continue
        idx = g.index.to_numpy()
        gross = g["gross_usd"].to_numpy()
        tix = g["tickets_sold"].to_numpy()
        for i in range(len(idx)):
            for j in range(i + 1, len(idx)):
                same_gross = gross[i] == gross[j]
                same_tix = tix[i] == tix[j] and tix[i] > 1000 and abs(gross[i] - gross[j]) <= 0.05 * max(gross[i], gross[j])
                if same_gross or same_tix:
                    parent[find(idx[i])] = find(idx[j])
    comp = pd.Series({i: find(i) for i in parent})
    sizes = comp.value_counts()
    comp = comp[comp.map(sizes) > 1]
    names = {root: f"{b.at[root, 'show_date']:%Y-%m-%d}|{min(b.loc[comp.index[comp == root], 'show_id'])}"
             for root in comp.unique()}
    return comp.map(names).reindex(b.index).astype("string")


def boxoffice_duplicates(b: pd.DataFrame) -> pd.DataFrame:
    """Resolve duplicate box office lines with the hand-checked decisions in data/manual/boxoffice_dedupe.csv.

    Groups the CSV doesn't cover fall back to: keep the row whose opening-act cell
    names every other artist in the group, else drop all rows; they are flagged
    dup_unreviewed (a test requires zero).
    """
    gid = detect_duplicate_groups(b)
    out = pd.DataFrame(index=b.index, data={"dup_boxoffice_group": gid, "dup_boxoffice_drop": False,
                                             "dup_boxoffice_resolved": pd.Series(pd.NA, index=b.index, dtype="string"),
                                             "dup_unreviewed": False})
    manual = pd.read_csv(DEDUPE_CSV).set_index("show_id") if DEDUPE_CSV.exists() else pd.DataFrame(columns=["action", "reason"])
    for _, g in b[gid.notna()].groupby(gid[gid.notna()]):
        if g["show_id"].isin(manual.index).all():
            for i, sid in g["show_id"].items():
                out.at[i, "dup_boxoffice_drop"] = manual.at[sid, "action"] == "drop"
                out.at[i, "dup_boxoffice_resolved"] = manual.at[sid, "reason"]
            continue
        heads = [i for i, r in g.iterrows()
                 if all(_norm(o) and _norm(o) in _norm(r["opening_acts_raw"]) + _norm(r["opening_acts_wikilinks"])
                        for o in g.drop(index=i)["artist_name"])]
        keep = heads[0] if len(heads) == 1 and g["artist_id"].nunique() == len(g) else None
        for i in g.index:
            out.at[i, "dup_boxoffice_drop"] = i != keep
            out.at[i, "dup_boxoffice_resolved"] = "unreviewed fallback"
            out.at[i, "dup_unreviewed"] = True
    return out


def figure_copies(b: pd.DataFrame, dup_group: pd.Series) -> pd.Series:
    """Same artist, identical gross AND tickets on different dates: a figure copied between rows.

    Which date the figure belongs to can't be told, so every row of such a set is flagged.
    """
    p = b[b["avg_price_usd"].notna() & dup_group.isna()]
    m = p.duplicated(["artist_key", "gross_usd", "tickets_sold"], keep=False) & \
        ~p.duplicated(["artist_key", "show_date", "gross_usd"], keep=False)
    return pd.Series(False, index=b.index).mask(b.index.isin(p.index[m]), True)


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

    derived("is_cancelled_spine", df["status_note"].fillna("").str.contains("cancel"))

    # --- feature tables -------------------------------------------------------
    coverage: dict = {}
    df = join_features(df, coverage, origin)

    # --- country: spine ISO2, else the venue's Wikidata country, else the spine text ---
    cf = country_final(df)
    derived("country_final", cf)
    venue_c = df["venue_country_iso2"] if "venue_country_iso2" in df else pd.Series(pd.NA, index=df.index)
    derived("country_final_source", pd.Series(np.select(
        [df["country_iso2"].notna(), venue_c.notna(), cf.notna()], ["spine", "venue_wikidata", "spine_text_city_or_metro"],
        default="unknown"), index=df.index).astype("string"))
    derived("usd_assumed_non_us", df["gross_currency"].eq("USD") & cf.notna() & ~cf.isin(["US", "PR"]).fillna(False))

    # --- artist identity (needed by dedupe and the split) -----------------------
    relations = pd.read_csv(RELATIONS_CSV) if RELATIONS_CSV.exists() else \
        pd.DataFrame(columns=["artist_id_a", "artist_id_b", "relation"])
    split_key, artist_key = artist_keys(df, wikidata_group_edges(df["artist_qid"]), relations)
    derived("split_key", split_key)
    derived("artist_key", artist_key)
    derived("artist_split", artist_split(df["split_key"]))
    nonperf = pd.read_csv(NON_PERFORMERS_CSV) if NON_PERFORMERS_CSV.exists() else pd.DataFrame(columns=["artist_id"])
    derived("non_performer", df["artist_id"].isin(nonperf["artist_id"]))

    # --- duplicates -------------------------------------------------------------
    for c, v in boxoffice_duplicates(df).items():
        derived(c, v)
    derived("dup_figure_copy", figure_copies(df, df["dup_boxoffice_group"]))

    # --- CPI: aggregates are deflated at the midpoint of their date span ----------
    cpi, imputed = load_cpi()
    mid = df["show_date"] + (df["agg_last_date"] - df["show_date"]) / 2
    deflate_date = mid.where(df["is_aggregate_unit"] & df["agg_last_date"].notna(), df["show_date"])
    derived("cpi_deflate_date", deflate_date)
    real, idx = deflate(df["avg_price_usd"], deflate_date, cpi, CPI_BASE_MONTH)
    derived("cpi_base_month", CPI_BASE_MONTH.strftime("%Y-%m"))
    derived("cpi_show_month", idx)
    months = deflate_date.dt.to_period("M").dt.to_timestamp()
    derived("cpi_month_imputed", months.map(imputed).astype("boolean"))
    derived("avg_price_real", real)
    derived("gross_usd_real", deflate(df["gross_usd"], deflate_date, cpi, CPI_BASE_MONTH)[0])
    derived("gross_usd_real_per_show", df["gross_usd_real"] / k)
    derived("log_avg_price_real", np.log(df["avg_price_real"].where(df["avg_price_real"] > 0)))
    derived("log_avg_price_nominal", np.log(df["avg_price_usd"].where(df["avg_price_usd"] > 0)))

    # --- analysis sample ------------------------------------------------------
    cancelled = df["is_cancelled_spine"] | df.get("is_cancelled", pd.Series(False, index=df.index)).fillna(False).astype(bool)
    reasons = [
        ("unpriced", df["avg_price_usd"].isna()),
        ("non_usd", ~df["gross_currency"].eq("USD")),
        ("implausible", df["avg_price_flag"].eq("implausible")),
        ("tour_outlier", df["avg_price_flag"].eq("tour_outlier")),
        ("cancelled", cancelled),
        ("dup_boxoffice", df["dup_boxoffice_drop"]),
        ("dup_figure_copy", df["dup_figure_copy"]),
        ("aggregate_multi_venue", df["is_aggregate_unit"] & (df["agg_n_venues"].fillna(1) > 1)),
        ("non_performer", df["non_performer"]),
        ("no_cpi", ~np.isfinite(df["log_avg_price_real"])),
    ]
    reason = pd.Series(pd.NA, index=df.index, dtype="string")
    for name, m in reversed(reasons):
        reason = reason.mask(m.fillna(False).astype(bool), name)
    derived("analysis_exclusion_reason", reason)
    derived("analysis_sample", reason.isna())

    # --- targets ------------------------------------------------------------------
    s = df["analysis_sample"]
    med = df.loc[s].groupby("artist_key")["log_avg_price_real"].median()
    cnt = df.loc[s].groupby("artist_key").size()
    derived("artist_median_log_price_real", df["artist_key"].map(med).where(s))
    derived("artist_n_analysis", df["artist_key"].map(cnt).fillna(0).astype(int))
    derived("price_rel_artist_median", artist_relative_target(df, s).where(s))  # DEPRECATED: career-time confounded
    derived("tour_unit", tour_units(df))
    unit_start = df.groupby("tour_unit")["show_date"].transform("min")
    derived("tour_unit_start_year", unit_start.dt.year.astype("Int64"))
    derived("tour_unit_span_days", (df.groupby("tour_unit")["show_date"].transform("max") - unit_start).dt.days.astype("Int64"))
    derived("tour_n_analysis", df["tour_unit"].map(df.loc[s].groupby("tour_unit").size()).fillna(0).astype(int))
    derived("price_rel_tour", tour_relative_target(df, s).where(s))
    derived("year_bucket_5", (df["tour_unit_start_year"] // 5) * 5)
    derived("price_rel_artist_era", artist_era_target(df, s).where(s))
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
