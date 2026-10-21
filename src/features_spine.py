"""Load the show spine (data/interim/shows_base.parquet) with a normalized column set.

Collector-prices owns the spine; column names may differ, so map known aliases.
A dev spine can be passed with FEATURES_SPINE=<path> for testing.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

import pandas as pd

from features_common import INTERIM

# normalized name -> accepted source names (first present wins)
ALIASES = {
    "show_id": ["show_id"],
    "artist_id": ["artist_id"],
    "venue_id": ["venue_id"],
    "show_date": ["show_date", "date"],
    "artist_name": ["artist_name", "artist"],
    "artist_wikilink": ["artist_wikilink", "artist_title", "artist_page", "artist_wiki_title"],
    "venue_name": ["venue_name", "venue"],
    "venue_wikilink": ["venue_wikilink", "venue_title", "venue_page", "venue_wiki_title"],
    "city": ["city"],
    "country": ["country"],
    "city_wikilink": ["city_wikilink"],
    "tour_title": ["tour_title", "tour", "tour_name", "source_title", "page_title", "title"],
    "opening_acts_raw": ["opening_acts_raw", "opening_act_raw", "opening_acts", "opening_act", "openers"],
}


def spine_path() -> Path:
    return Path(os.environ.get("FEATURES_SPINE", INTERIM / "shows_base.parquet"))


def load_spine() -> pd.DataFrame:
    raw = pd.read_parquet(spine_path())
    out = pd.DataFrame(index=raw.index)
    for norm, names in ALIASES.items():
        src = next((n for n in names if n in raw.columns), None)
        out[norm] = raw[src] if src else pd.NA
    out["show_date"] = pd.to_datetime(out["show_date"], errors="coerce").dt.date
    for col in ("artist_wikilink", "venue_wikilink", "city_wikilink"):
        out[col] = out[col].map(_clean_link)
    return out


def _clean_link(v):
    """Accept '[[Title|text]]', 'Title', or NA; return a bare title or None."""
    if v is None or (isinstance(v, float) and pd.isna(v)) or v is pd.NA:
        return None
    m = re.search(r"\[\[([^\]|#]+)", str(v))
    t = (m.group(1) if m else str(v)).strip()
    return t or None
