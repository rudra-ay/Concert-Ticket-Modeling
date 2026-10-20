"""Polite, cached HTTP fetcher shared by the context collectors (CPI, ACS, Gazetteer, Open-Meteo).

Rules enforced here (DECISIONS.md / lead brief):
- one honest User-Agent, no cookies, no retries around 403/429/challenges;
- >= 5 s between requests to the same domain;
- every response cached on disk; a cached path is never refetched.
"""
from __future__ import annotations

import fcntl
import json
import os
import time
from pathlib import Path
from urllib.parse import urlparse

import requests

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
INTERIM = ROOT / "data" / "interim"

USER_AGENT = "TicketPriceResearch/0.1 (personal research; contact: rudraayyagari@gmail.com)"
MIN_INTERVAL_S = 5.0

class BlockedError(RuntimeError):
    """The server pushed back (403/429/challenge/unrecognised page). Stop and report; never retry."""


class TransientError(RuntimeError):
    """5xx or an empty body: log, skip, back off. Not pushback."""


class NetworkDown(RuntimeError):
    """Several transient failures in a row: stop; a supervisor restarts once the host resolves again."""


LOCKS = RAW / "_locks"
REQUEST_LOG = RAW / "_requests"
BAD_RESPONSES = RAW / "_bad_responses"
_CHALLENGE_MARKERS = (b"captcha", b"request rejected", b"access denied", b"challenge", b"cloudflare",
                      b"too many requests", b"rate limit", b"attention required", b"just a moment")


def _save_bad_response(domain: str, resp: requests.Response | None, note: str, body: bytes = b"") -> Path:
    BAD_RESPONSES.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%dT%H%M%S", time.gmtime())
    status = resp.status_code if resp is not None else "none"
    path = BAD_RESPONSES / f"{domain}__{stamp}__{status}.txt"
    head = {"note": note, "status": status, "url": resp.url if resp is not None else None,
            "headers": dict(resp.headers) if resp is not None else {}}
    path.write_bytes(json.dumps(head, indent=1).encode() + b"\n----- body (first 64 KB) -----\n" + body[:65536])
    return path


def _log_request(domain: str, row: dict) -> None:
    REQUEST_LOG.mkdir(parents=True, exist_ok=True)
    path = REQUEST_LOG / f"{domain}.csv"
    new = not path.exists()
    with open(path, "a") as f:
        if new:
            f.write("start_utc,end_utc,start_to_start_s,end_to_start_s,status,bytes,content_type,note\n")
        f.write(",".join(str(row.get(k, "")) for k in
                         ["start_utc", "end_utc", "start_to_start_s", "end_to_start_s", "status", "bytes",
                          "content_type", "note"]) + "\n")


def polite_get(url: str, params: dict | None = None, timeout: int = 120, expect_json: bool = False,
               deadline: float | None = None) -> bytes:
    """One GET under the collection rules.

    - Cross-process lock per domain: one request in flight; the next starts >= MIN_INTERVAL_S after the previous
      one ENDED (end-to-start), using the end time persisted in the lock file. Every request is logged.
    - 403/429, or (expect_json) a non-empty non-JSON 2xx body, or a challenge page -> BlockedError (body saved).
    - 5xx or an empty body -> TransientError (body saved). Other 4xx -> requests.HTTPError.
    - deadline: cap on the whole download in seconds (`timeout` only bounds the gap between reads, so a
      server trickling bytes can otherwise hold the request open for many minutes) -> requests.Timeout.
    """
    domain = urlparse(url).netloc
    LOCKS.mkdir(parents=True, exist_ok=True)
    with open(LOCKS / f"{domain}.lock", "a+") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        try:
            lk.seek(0)
            prev = (lk.read().split() + ["0", "0"])[:2]
            last_start, last_end = float(prev[0] or 0), float(prev[1] or 0)
            wait = last_end + MIN_INTERVAL_S - time.time()
            if wait > 0:
                time.sleep(wait)
            t0 = time.time()
            row = {"start_utc": _iso(t0), "start_to_start_s": f"{t0 - last_start:.2f}" if last_start else "",
                   "end_to_start_s": f"{t0 - last_end:.2f}" if last_end else ""}
            resp, note, body = None, "", b""
            try:
                with requests.Session() as sess:  # fresh session: no cookie carry-over
                    sess.headers.update({"User-Agent": USER_AGENT})
                    resp = sess.get(url, params=params, allow_redirects=True, stream=True,
                                    timeout=(10, min(timeout, deadline)) if deadline else timeout)
                    chunks = []
                    for chunk in resp.iter_content(65536):
                        chunks.append(chunk)
                        if deadline and time.time() - t0 > deadline:
                            resp.close()
                            raise requests.Timeout(f"no complete response within {deadline:.0f} s")
                    body = resp._content = b"".join(chunks)
            except requests.RequestException as e:
                note, body = type(e).__name__, b""
                raise
            finally:
                t1 = time.time()
                lk.seek(0); lk.truncate(); lk.write(f"{t0} {t1}"); lk.flush()
                row.update(end_utc=_iso(t1), status=resp.status_code if resp is not None else "",
                           bytes=len(body),
                           content_type=(resp.headers.get("Content-Type", "") if resp is not None else "").replace(",", ";"),
                           note=note)
                _log_request(domain, row)
                # watchdog audit format (same as features_common): start epoch, end epoch, pid; tab-separated
                (RAW / "logs").mkdir(parents=True, exist_ok=True)
                with open(RAW / "logs" / f"requests_{domain}.log", "a") as wl:
                    wl.write(f"{t0:.3f}\t{t1:.3f}\t{os.getpid()}\n")
        finally:
            fcntl.flock(lk, fcntl.LOCK_UN)

    if resp.status_code in (403, 429):
        saved = _save_bad_response(domain, resp, "pushback", body)
        raise BlockedError(f"{resp.status_code} from {domain}; stopping, not retrying (saved {saved.name})")
    if resp.status_code >= 500:
        saved = _save_bad_response(domain, resp, "5xx", body)
        raise TransientError(f"{resp.status_code} from {domain} (saved {saved.name})")
    resp.raise_for_status()
    low = body[:4000].lower()
    if any(m in low for m in _CHALLENGE_MARKERS) and not low.lstrip().startswith((b"{", b"[")):
        saved = _save_bad_response(domain, resp, "challenge markers", body)
        raise BlockedError(f"challenge/block page from {domain}; stopping (saved {saved.name})")
    if not body.strip():
        saved = _save_bad_response(domain, resp, "empty body", body)
        raise TransientError(f"empty body ({resp.status_code}) from {domain} (saved {saved.name})")
    if expect_json:
        try:
            json.loads(body)
        except ValueError:
            # JSON that starts fine but breaks off is a cut-off stream (Open-Meteo appends
            # "Unexpected error while streaming data: timeoutReached"): a server hiccup, not pushback.
            if low.lstrip().startswith((b"{", b"[")) and "json" in resp.headers.get("Content-Type", ""):
                saved = _save_bad_response(domain, resp, "truncated JSON stream", body)
                raise TransientError(f"truncated JSON from {domain} (saved {saved.name})")
            # Non-empty, non-JSON page with a 2xx: possibly a challenge we don't recognise. Stop; a human looks.
            saved = _save_bad_response(domain, resp, "non-JSON 2xx", body)
            raise BlockedError(f"non-JSON {resp.status_code} body from {domain}; stopping (saved {saved.name})")
    return body


def _iso(t: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(t)) + f".{int((t % 1) * 1000):03d}Z"


def write_atomic(path: Path, data: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".part")
    tmp.write_bytes(data)
    tmp.rename(path)
    return path


def fetch_cached(url: str, cache_path: Path, params: dict | None = None, timeout: int = 120) -> Path:
    """Return cache_path, downloading url into it first if it isn't cached yet."""
    if cache_path.exists() and cache_path.stat().st_size > 0:
        return cache_path
    return write_atomic(cache_path, polite_get(url, params=params, timeout=timeout))


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


MAX_KM_TO_LOCALITY = 50.0  # venue P625 this far from its own locality's P625 = self-contradictory item


def load_venue_coords(spine: pd.DataFrame | None = None) -> pd.DataFrame | None:
    """collector-features' venue coordinates with every guard applied; None if the table is absent.

    Returns venue_id, lat, lon, venue_us_state, coord_dropped_reason. lat/lon (and us_state) are nulled when:
    - link_ambiguous: one QID linked from several spine cities (chain articles like "Hard Rock Live");
    - km_to_locality > 50: the item's coordinates contradict its own locality;
    - venue_link_source == name_match and the Wikidata locality doesn't match the tour table's city.
    """
    p = venue_features_path()
    if not p.exists():
        return None
    v = pd.read_parquet(p)
    lat = _first(v, ["lat", "latitude", "venue_lat"])
    lon = _first(v, ["lon", "lng", "longitude", "venue_lon"])
    if not (lat and lon and "venue_id" in v):
        return None
    v = v.rename(columns={lat: "lat", lon: "lon"}).drop_duplicates("venue_id").reset_index(drop=True)
    v["venue_us_state"] = (v["us_state"].astype("string").str.replace("US-", "", regex=False)
                           if "us_state" in v else pd.NA)
    reason = pd.Series(pd.NA, index=v.index, dtype="string")
    if "link_ambiguous" in v:
        reason = reason.mask(v.link_ambiguous.fillna(False).astype(bool) & reason.isna(), "link_ambiguous")
    if "km_to_locality" in v:
        reason = reason.mask((pd.to_numeric(v.km_to_locality, errors="coerce") > MAX_KM_TO_LOCALITY)
                             & reason.isna(), "far_from_own_locality")
    loc_col = _first(v, ["wd_locality", "wd_city"])
    if spine is not None and loc_col and "venue_link_source" in v:
        city = spine.groupby("venue_id").city.agg(lambda x: x.dropna().mode().iloc[0] if x.notna().any() else None)
        sc = v.venue_id.map(city)
        mismatch = [isinstance(a, str) and isinstance(b, str) and bool(slugify(a)) and bool(slugify(b))
                    and not (slugify(a) in slugify(b) or slugify(b) in slugify(a)) for a, b in zip(sc, v[loc_col])]
        reason = reason.mask((v.venue_link_source == "name_match") & pd.Series(mismatch, index=v.index)
                             & reason.isna(), "name_match_city_mismatch")
    drop = reason.notna()
    v.loc[drop, ["lat", "lon"]] = float("nan")
    v.loc[reason.eq("link_ambiguous").fillna(False), "venue_us_state"] = pd.NA
    v["coord_dropped_reason"] = reason
    return v[["venue_id", "lat", "lon", "venue_us_state", "coord_dropped_reason"]]
