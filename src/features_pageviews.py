"""Wikipedia pageview hype features (A3, Wikimedia REST pageviews API, CC0).

One cached call per enwiki article covering 2015-07-01 .. DATA_END, agent=user.
Per show, every window ends the day BEFORE the show date (no same-day or later
data -> no leakage). A window that starts before 2015-07-01 is missing, never
imputed.

Library use: fetch_daily(title) -> pd.Series; hype_features(series, show_date) -> dict.
"""
from __future__ import annotations

import math
from datetime import date, timedelta
from urllib.parse import quote

import numpy as np
import pandas as pd

from features_common import RAW, get_json_cached, wiki_title_key

PV_START = date(2015, 7, 1)
DATA_END = date(2026, 10, 17)  # last complete day when collected (2026-10-18)
API = ("https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/en.wikipedia/"
       "all-access/user/{title}/daily/{start}/{end}")
CACHE = RAW / "wikimedia_pageviews"
SPIKE_RATIO = 5.0  # max day in [-30,-1] vs median of [-365,-31]


def _cache_name(title: str) -> str:
    return quote(wiki_title_key(title), safe="")[:200] + ".json"


def is_cached(title: str) -> bool:
    return (CACHE / _cache_name(wiki_title_key(title))).exists()


def fetch_daily(title: str) -> pd.Series | None:
    """Daily user views for one article, indexed by date. None if the article has no data."""
    key = wiki_title_key(title)
    url = API.format(title=quote(key, safe=""), start=PV_START.strftime("%Y%m%d"),
                     end=DATA_END.strftime("%Y%m%d"))
    data = get_json_cached(url, CACHE / _cache_name(key))
    if not data or not data.get("items"):
        return None
    s = pd.Series({pd.Timestamp(it["timestamp"][:8]): it["views"] for it in data["items"]},
                  dtype="float64").sort_index()
    # The API omits zero-view days; fill them with 0 from the article's first
    # recorded day on. Days before that (article not yet created) stay NaN so a
    # missing article is not read as "no hype".
    full = pd.date_range(pd.Timestamp(PV_START), pd.Timestamp(DATA_END), freq="D")
    s = s.reindex(full)
    first = s.first_valid_index()
    s.loc[first:] = s.loc[first:].fillna(0.0)
    return s


def _window(s: pd.Series, show: date, first: int, last: int) -> pd.Series | None:
    """Views on days show-first .. show-last (first > last >= 1). None if outside coverage."""
    start, end = show - timedelta(days=first), show - timedelta(days=last)
    if start < PV_START or end > DATA_END:
        return None
    w = s.loc[pd.Timestamp(start):pd.Timestamp(end)]
    return None if w.isna().any() else w


def hype_features(s: pd.Series | None, show: date, prefix: str = "pv") -> dict:
    out = {f"{prefix}_mean_90d": np.nan, f"{prefix}_mean_365d": np.nan,
           f"{prefix}_momentum": np.nan, f"{prefix}_spike_ratio": np.nan,
           f"{prefix}_spike_flag": pd.NA}
    if s is None:
        return out
    w90 = _window(s, show, 90, 1)
    w1_30 = _window(s, show, 30, 1)
    w61_90 = _window(s, show, 90, 61)
    w365 = _window(s, show, 365, 1)
    base = _window(s, show, 365, 31)
    if w90 is not None:
        out[f"{prefix}_mean_90d"] = float(w90.mean())
    if w1_30 is not None and w61_90 is not None:
        out[f"{prefix}_momentum"] = math.log((w1_30.mean() + 1) / (w61_90.mean() + 1))
    if w365 is not None:
        out[f"{prefix}_mean_365d"] = float(w365.mean())
    if w1_30 is not None and base is not None:
        ratio = float(w1_30.max() / max(base.median(), 1.0))
        out[f"{prefix}_spike_ratio"] = ratio
        out[f"{prefix}_spike_flag"] = bool(ratio >= SPIKE_RATIO)
    return out
