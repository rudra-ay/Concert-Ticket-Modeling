"""Tour-article counts per artist from enwiki 20261001 categories (dumps; CC BY-SA 4.0).

An artist's tours are the articles in "Category:<Artist title> concert tours".
A tour's start year is the smallest year among its "Category:<YYYY> concert tours"
memberships, so "tours started before the show year" is computable without any
API call. Lists ("List of ...") and subcategories are excluded.
"""
from __future__ import annotations

import gzip
import re

import pandas as pd

from features_common import RAW, wiki_title_key

DUMP = RAW / "wikipedia_dumps" / "20261001"
CACHE = RAW / "wikipedia_dumps" / "derived"
_Q = r"'((?:[^'\\]|\\.)*)'"


def _unq(s: str) -> str:
    return s.replace("\\'", "'").replace('\\"', '"').replace("\\\\", "\\")


def _lines(path):
    with gzip.open(path, "rt", encoding="utf-8", errors="replace") as fh:
        yield from fh


def tour_categories() -> pd.DataFrame:
    """linktarget ids of ns-14 titles ending in 'concert_tours'."""
    out = CACHE / "lt_concert_tours.parquet"
    if out.exists():
        return pd.read_parquet(out)
    pat = re.compile(r"\((\d+),14," + _Q + r"\)")
    rows = []
    for line in _lines(DUMP / "enwiki-20261001-linktarget.sql.gz"):
        if "concert_tours" not in line:
            continue
        rows += [(int(i), _unq(t)) for i, t in pat.findall(line) if t.endswith("concert_tours")]
    df = pd.DataFrame(rows, columns=["lt_id", "category"])
    CACHE.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out, index=False)
    return df


def tour_memberships() -> pd.DataFrame:
    """(page_id, category) for pages (not subcats/files) in any *concert_tours category."""
    out = CACHE / "cl_concert_tours.parquet"
    if out.exists():
        return pd.read_parquet(out)
    cats = tour_categories()
    lt = dict(zip(cats["lt_id"], cats["category"]))
    # (cl_from, cl_sortkey, cl_timestamp, cl_sortkey_prefix, cl_type, cl_collation_id, cl_target_id)
    pat = re.compile(r"\((\d+)," + _Q + r",'[^']*'," + _Q + r",'(page|subcat|file)',(\d+),(\d+)\)")
    rows = []
    for line in _lines(DUMP / "enwiki-20261001-categorylinks.sql.gz"):
        for m in pat.finditer(line):
            tid = int(m.group(6))
            if tid in lt and m.group(4) == "page":
                rows.append((int(m.group(1)), lt[tid]))
    df = pd.DataFrame(rows, columns=["page_id", "category"])
    df.to_parquet(out, index=False)
    return df


class TourIndex:
    def __init__(self, id_to_title: dict[int, str]) -> None:
        m = tour_memberships()
        m = m.assign(title=m["page_id"].map(id_to_title))
        m = m[m["title"].notna() & ~m["title"].str.startswith("List_of")]
        years = m[m["category"].str.fullmatch(r"\d{4}_concert_tours")]
        self.start_year = years.assign(y=years["category"].str[:4].astype(int)).groupby("page_id")["y"].min().to_dict()
        artist_cats = m[~m["category"].str.fullmatch(r"\d{4}_concert_tours")]
        self.by_cat = artist_cats.groupby("category")["page_id"].apply(list).to_dict()

    def tours(self, artist_title: str | None) -> tuple[str | None, list[int]]:
        """(matched category, tour page_ids) for an artist article title."""
        if not artist_title:
            return None, []
        t = wiki_title_key(artist_title)
        for cand in (t, re.sub(r"_\([^)]*\)$", "", t)):  # "Queen_(band)" -> also "Queen"
            cat = f"{cand}_concert_tours"
            if cat in self.by_cat:
                return cat, self.by_cat[cat]
        return None, []
