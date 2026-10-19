"""MusicBrainz lookups from the 20261017-002244 fullexport (no /ws/2; see DECISIONS.md).

Core tables (artist, artist_type, area, iso_3166_1, genre) are CC0.
artist_tag and tag come from mbdump-derived and are CC BY-NC-SA 3.0; anything
derived from them is kept in mb_genre_* columns only.
Derived lookups are cached as parquet under data/raw/musicbrainz_dumps/derived/.
"""
from __future__ import annotations

import csv

import pandas as pd

from features_common import RAW

MB = RAW / "musicbrainz_dumps" / "20261017-002244"
CORE = MB / "extracted_core" / "mbdump"
DER = MB / "extracted_derived" / "mbdump"
CACHE = RAW / "musicbrainz_dumps" / "derived"

ARTIST_COLS = ["id", "gid", "name", "sort_name", "begin_year", "begin_month", "begin_day",
               "end_year", "end_month", "end_day", "type", "area", "gender", "comment",
               "edits_pending", "last_updated", "ended", "begin_area", "end_area"]


def _read(path, names, usecols=None):
    return pd.read_csv(path, sep="\t", header=None, names=names, usecols=usecols, na_values=["\\N"],
                       keep_default_na=False, quoting=csv.QUOTE_NONE, dtype=str)


def artists() -> pd.DataFrame:
    """mbid, mb_name, mb_type (Person/Group/...), begin/end year, ended, country_iso2 (area chain depth 1)."""
    out = CACHE / "artist.parquet"
    if out.exists():
        return pd.read_parquet(out)
    a = _read(CORE / "artist", ARTIST_COLS,
              ["id", "gid", "name", "begin_year", "end_year", "type", "area", "ended", "comment"])
    types = _read(CORE / "artist_type", ["id", "name", "parent", "child_order", "description", "gid"],
                  ["id", "name"]).set_index("id")["name"]
    iso = _read(CORE / "iso_3166_1", ["area", "code"]).set_index("area")["code"]
    a = a.assign(mb_type=a["type"].map(types), country_iso2=a["area"].map(iso),
                 begin_year=pd.to_numeric(a["begin_year"], errors="coerce").astype("Int32"),
                 end_year=pd.to_numeric(a["end_year"], errors="coerce").astype("Int32"))
    a = a.rename(columns={"id": "mb_artist_id", "gid": "mbid", "name": "mb_name", "comment": "mb_comment"})
    a = a[["mb_artist_id", "mbid", "mb_name", "mb_comment", "mb_type", "begin_year", "end_year",
           "ended", "country_iso2"]]
    CACHE.mkdir(parents=True, exist_ok=True)
    a.to_parquet(out, index=False)
    return a


def genre_tags() -> pd.DataFrame:
    """mb_artist_id -> genre tags (tags whose name is an official MB genre), with vote counts.

    License: CC BY-NC-SA 3.0 (derived dump)."""
    out = CACHE / "artist_genre_tags.parquet"
    if out.exists():
        return pd.read_parquet(out)
    genres = set(_read(CORE / "genre", ["id", "gid", "name", "comment", "edits_pending", "last_updated"],
                       ["name"])["name"].str.lower())
    tag = _read(DER / "tag", ["id", "name", "ref_count"], ["id", "name"])
    tag = tag[tag["name"].str.lower().isin(genres)]
    at = _read(DER / "artist_tag", ["artist", "tag", "count", "last_updated"], ["artist", "tag", "count"])
    at = at.merge(tag, left_on="tag", right_on="id")
    at["count"] = pd.to_numeric(at["count"], errors="coerce")
    at = at[at["count"] > 0].rename(columns={"artist": "mb_artist_id", "name": "genre"})
    at = at[["mb_artist_id", "genre", "count"]].sort_values(["mb_artist_id", "count"], ascending=[True, False])
    at.to_parquet(out, index=False)
    return at
