"""Polite HTTP access to dumps.wikimedia.org.

Rules (DECISIONS.md / lead instructions):
- one honest UA, no cookies, no retries after 403/429/challenge;
- >= 5 s between request *starts* to the same domain, coordinated across
  processes through a lock file (so a parallel range fetcher and the big
  streamed download never violate spacing; at most 2 connections open);
- everything cached under data/raw/wikipedia_dumps/, never refetched.
"""
from __future__ import annotations

import fcntl
import os
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "data" / "raw" / "wikipedia_dumps"
UA = "TicketPriceResearch/0.1 (personal research; contact: rudraayyagari@gmail.com)"
MIN_GAP_S = 5.0
_LOCK = CACHE / ".domain_gap.lock"


class Blocked(RuntimeError):
    """Server pushed back (403/429/challenge). Stop; never retry."""


def _session() -> requests.Session:
    s = requests.Session()
    s.headers["User-Agent"] = UA
    s.cookies.set_policy(_NoCookies())
    return s


class _NoCookies:  # http.cookiejar policy that refuses every cookie
    netscape = True
    rfc2965 = hide_cookie2 = False

    def set_ok(self, cookie, request):
        return False

    def return_ok(self, cookie, request):
        return False

    def domain_return_ok(self, domain, request):
        return False

    def path_return_ok(self, path, request):
        return False


_S = _session()


def _wait_turn() -> None:
    """Block until >= MIN_GAP_S since the last request start (any process)."""
    CACHE.mkdir(parents=True, exist_ok=True)
    with open(_LOCK, "a+") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        fh.seek(0)
        raw = fh.read().strip()
        last = float(raw) if raw else 0.0
        delay = last + MIN_GAP_S - time.time()
        if delay > 0:
            time.sleep(delay)
        fh.seek(0)
        fh.truncate()
        fh.write(repr(time.time()))
        fh.flush()
        fcntl.flock(fh, fcntl.LOCK_UN)


def _check(resp: requests.Response) -> None:
    if resp.status_code in (403, 429) or resp.status_code >= 500:
        raise Blocked(f"{resp.status_code} for {resp.url}; stopping (no retry)")
    ctype = resp.headers.get("Content-Type", "")
    if "text/html" in ctype and "challenge" in resp.text[:2000].lower():
        raise Blocked(f"challenge page for {resp.url}; stopping")


def get_small(url: str, dest: Path) -> bytes:
    """GET a small file once and cache it."""
    if dest.exists():
        return dest.read_bytes()
    _wait_turn()
    r = _S.get(url, timeout=60)
    if r.status_code != 404:
        _check(r)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(r.content if r.ok else f"HTTP {r.status_code}\n".encode() + r.content)
    return dest.read_bytes()


def download(url: str, dest: Path, expected_size: int | None = None,
             attempts: int = 8) -> Path:
    """Download with resume after *dropped connections only* (not pushback)."""
    for i in range(attempts):
        try:
            return _download_once(url, dest, expected_size)
        except (requests.exceptions.ConnectionError, requests.exceptions.ChunkedEncodingError,
                requests.exceptions.Timeout) as exc:
            print(f"dropped ({exc.__class__.__name__}); resume {i + 1}/{attempts}", flush=True)
            time.sleep(30)
    raise IOError(f"gave up on {url}")


def _download_once(url: str, dest: Path, expected_size: int | None = None,
                   chunk: int = 1 << 20) -> Path:
    """Single long streamed GET of a big file (counts as one request).

    Writes to dest.part; if a .part exists, resumes with one Range request
    (still a single connection, never parallel)."""
    if dest.exists():
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_suffix(dest.suffix + ".part")
    have = part.stat().st_size if part.exists() else 0
    headers = {"Range": f"bytes={have}-"} if have else {}
    _wait_turn()
    with _S.get(url, headers=headers, stream=True, timeout=(30, 300)) as r:
        _check(r)
        if have and r.status_code != 206:
            raise RuntimeError(f"server ignored resume Range ({r.status_code})")
        r.raise_for_status()
        with open(part, "ab") as fh:
            for block in r.iter_content(chunk):
                fh.write(block)
    if expected_size is not None and part.stat().st_size != expected_size:
        raise requests.exceptions.ChunkedEncodingError(
            f"short read {part.stat().st_size} != {expected_size}")
    part.rename(dest)
    return dest


def get_range(url: str, start: int, end: int) -> bytes:
    """One Range request for bytes [start, end) (no caching here; callers cache)."""
    _wait_turn()
    r = _S.get(url, headers={"Range": f"bytes={start}-{end - 1}"}, timeout=120)
    _check(r)
    if r.status_code != 206:
        raise RuntimeError(f"expected 206, got {r.status_code} for {url}")
    return r.content
