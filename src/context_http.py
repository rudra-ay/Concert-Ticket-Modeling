"""Polite, cached HTTP fetcher shared by the context collectors (CPI, ACS, Gazetteer, Open-Meteo).

Rules enforced here (DECISIONS.md / lead brief):
- one honest User-Agent, no cookies, no retries around 403/429/challenges;
- >= 5 s between requests to the same domain;
- every response cached on disk; a cached path is never refetched.
"""
from __future__ import annotations

import time
from pathlib import Path
from urllib.parse import urlparse

import requests

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
INTERIM = ROOT / "data" / "interim"

USER_AGENT = "TicketPriceResearch/0.1 (personal research; contact: rudraayyagari@gmail.com)"
MIN_INTERVAL_S = 5.0

_last_request: dict[str, float] = {}


class BlockedError(RuntimeError):
    """The server pushed back (403/429/challenge). Stop and report; never retry."""


def _wait_for_domain(domain: str) -> None:
    last = _last_request.get(domain)
    if last is not None:
        gap = time.monotonic() - last
        if gap < MIN_INTERVAL_S:
            time.sleep(MIN_INTERVAL_S - gap)
    _last_request[domain] = time.monotonic()


def fetch_cached(url: str, cache_path: Path, params: dict | None = None, timeout: int = 120) -> Path:
    """Return cache_path, downloading url into it first if it isn't cached yet."""
    if cache_path.exists() and cache_path.stat().st_size > 0:
        return cache_path
    domain = urlparse(url).netloc
    _wait_for_domain(domain)
    with requests.Session() as s:  # fresh session: no cookie carry-over
        s.headers.update({"User-Agent": USER_AGENT})
        resp = s.get(url, params=params, timeout=timeout, stream=True, allow_redirects=True)
    if resp.status_code in (403, 429):
        raise BlockedError(f"{resp.status_code} from {domain} for {url}; stopping, not retrying")
    resp.raise_for_status()
    head = resp.content[:2000].lower()
    if b"captcha" in head or b"request rejected" in head or b"access denied" in head:
        raise BlockedError(f"challenge/block page from {domain} for {url}; stopping")
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = cache_path.with_suffix(cache_path.suffix + ".part")
    tmp.write_bytes(resp.content)
    tmp.rename(cache_path)
    return cache_path


# ---------------------------------------------------------------------------
# Spine loading (shared by features_calendar / tour_context / weather / metro)
# ---------------------------------------------------------------------------
import os  # noqa: E402
import re  # noqa: E402
import unicodedata  # noqa: E402

import pandas as pd  # noqa: E402

SPINE_PATH = INTERIM / "shows_base.parquet"


def venue_features_path() -> Path:
    """collector-features' venue table. CONTEXT_VENUE_FEATURES overrides it for dev runs."""
    return Path(os.environ.get("CONTEXT_VENUE_FEATURES") or INTERIM / "features_venue.parquet")


def out_dir() -> Path:
    """Where feature tables go. CONTEXT_OUT overrides (dev runs on the synthetic spine write elsewhere)."""
    d = Path(os.environ.get("CONTEXT_OUT") or INTERIM)
    d.mkdir(parents=True, exist_ok=True)
    return d

_COUNTRY_ALIASES = {
    "united states": "US", "united states of america": "US", "usa": "US", "u.s.": "US", "us": "US",
    "canada": "CA", "mexico": "MX", "united kingdom": "GB", "uk": "GB", "england": "GB", "scotland": "GB",
    "wales": "GB", "northern ireland": "GB", "great britain": "GB", "ireland": "IE", "republic of ireland": "IE",
    "france": "FR", "germany": "DE", "netherlands": "NL", "the netherlands": "NL", "belgium": "BE",
    "luxembourg": "LU", "switzerland": "CH", "austria": "AT", "italy": "IT", "spain": "ES", "portugal": "PT",
    "denmark": "DK", "sweden": "SE", "norway": "NO", "finland": "FI", "iceland": "IS", "poland": "PL",
    "czech republic": "CZ", "czechia": "CZ", "hungary": "HU", "slovakia": "SK", "slovenia": "SI",
    "croatia": "HR", "serbia": "RS", "romania": "RO", "bulgaria": "BG", "greece": "GR", "turkey": "TR",
    "türkiye": "TR", "russia": "RU", "ukraine": "UA", "estonia": "EE", "latvia": "LV", "lithuania": "LT",
    "israel": "IL", "united arab emirates": "AE", "uae": "AE", "saudi arabia": "SA", "qatar": "QA",
    "bahrain": "BH", "kuwait": "KW", "egypt": "EG", "south africa": "ZA", "morocco": "MA", "nigeria": "NG",
    "kenya": "KE", "india": "IN", "japan": "JP", "south korea": "KR", "korea": "KR", "china": "CN",
    "hong kong": "HK", "taiwan": "TW", "singapore": "SG", "malaysia": "MY", "thailand": "TH",
    "indonesia": "ID", "philippines": "PH", "vietnam": "VN", "australia": "AU", "new zealand": "NZ",
    "brazil": "BR", "argentina": "AR", "chile": "CL", "colombia": "CO", "peru": "PE", "uruguay": "UY",
    "paraguay": "PY", "ecuador": "EC", "venezuela": "VE", "costa rica": "CR", "panama": "PA",
    "guatemala": "GT", "puerto rico": "PR", "dominican republic": "DO",
}


def slugify(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().lower()
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", s)).strip("-")


def to_iso2(country) -> str | None:
    if country is None or (isinstance(country, float) and pd.isna(country)):
        return None
    c = str(country).strip()
    if len(c) == 2 and c.isalpha():
        return c.upper()
    return _COUNTRY_ALIASES.get(c.lower())


def _first(df: pd.DataFrame, names: list[str]) -> str | None:
    return next((n for n in names if n in df.columns), None)


def load_spine(path: str | os.PathLike | None = None) -> pd.DataFrame:
    """Load shows_base and normalise the columns the context features rely on.

    Override the path with CONTEXT_SPINE=... (used for the synthetic dev spine).
    Output always has: show_id, artist_id, venue_id, date (datetime64, naive), city, country_iso2,
    and, when available in the source, state, tour, leg, tour_announced_date, venue.
    """
    p = path or os.environ.get("CONTEXT_SPINE") or SPINE_PATH
    df = pd.read_parquet(p).copy()
    date_col = _first(df, ["date", "show_date", "event_date"])
    if date_col is None:
        raise KeyError(f"no show date column in {p}: {list(df.columns)}")
    df["date"] = pd.to_datetime(df[date_col], errors="coerce").dt.tz_localize(None).dt.normalize()
    iso = pd.Series(None, index=df.index, dtype="object")
    for c in ["country_iso2", "country_code", "country"]:  # first usable value wins, row by row
        if c in df:
            iso = iso.fillna(df[c].map(to_iso2))
    if "city" in df:  # "Seoul, South Korea" with no country column value
        tail = df["city"].astype("string").str.extract(r",\s*([^,]+)$")[0]
        iso = iso.fillna(tail.map(lambda t: to_iso2(t) if isinstance(t, str) and len(t) > 2 else None))
    df["country_iso2"] = iso
    for want, cands in {
        "city": ["city", "venue_city"],
        "state": ["state", "region", "state_code", "subdivision"],
        "tour": ["tour", "tour_title", "tour_name", "tour_slug", "tour_article", "tour_id"],
        "leg": ["leg", "tour_leg", "section", "leg_name"],
        "tour_announced_date": ["tour_announced_date", "announced_date", "announcement_date", "tour_announced"],
        "venue": ["venue", "venue_name"],
        "status_note": ["status_note", "status"],
    }.items():
        src = _first(df, cands)
        if src and src != want:
            df[want] = df[src]
        elif not src:
            df[want] = pd.NA
    if df["tour_announced_date"].notna().any():
        df["tour_announced_date"] = pd.to_datetime(df["tour_announced_date"], errors="coerce").dt.tz_localize(None)
    return df
