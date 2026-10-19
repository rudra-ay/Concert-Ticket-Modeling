"""Shared helpers for the features_* collectors.

Polite HTTP: one fixed honest User-Agent, >= 5 s between requests per domain,
serial requests, file cache under data/raw/<source>/, never refetch cached
items, and stop (raise Blocked) on 403/429 or a challenge page. No retries
after a block.
"""
from __future__ import annotations

import contextlib
import fcntl
import json
import os
import re
import time
import unicodedata
from pathlib import Path
from urllib.parse import urlparse

import requests

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
INTERIM = ROOT / "data" / "interim"
# Feature tables go here; dev runs set FEATURES_OUT to a scratch dir.
OUT = Path(os.environ.get("FEATURES_OUT", INTERIM))
UA = "TicketPriceResearch/0.1 (personal research; contact: rudraayyagari@gmail.com)"
MIN_GAP_S = 5.0

_session = requests.Session()
_session.headers.update({"User-Agent": UA, "Accept-Encoding": "gzip"})


class Blocked(RuntimeError):
    """Raised on 403/429/challenge. Callers must stop, not retry."""


class NetworkDown(RuntimeError):
    """Raised after MAX_CONSECUTIVE_NET_ERRORS transient failures in a row. Stop the run."""


TRANSIENT = (requests.exceptions.ConnectionError, requests.exceptions.Timeout,
             requests.exceptions.ChunkedEncodingError)
MAX_CONSECUTIVE_NET_ERRORS = 3
_net = {"consecutive": 0, "skipped": 0}


def transient_skips() -> int:
    """Items skipped this run because of transient network errors (left uncached; a rerun fills them)."""
    return _net["skipped"]


@contextlib.contextmanager
def _domain_slot(domain: str):
    """Hold the per-domain cross-process lock for the whole request.

    The next request to the domain (any features_* process) can start only
    >= MIN_GAP_S after this one FINISHED, so both start-to-start and
    finish-to-finish spacing are >= MIN_GAP_S. Start/end times are appended to
    data/raw/logs/requests_<domain>.log for audit."""
    lock = RAW / ".locks" / f"{domain}.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    with open(lock, "a+") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            fh.seek(0)
            raw = fh.read().strip()
            delay = (float(raw) if raw else 0.0) + MIN_GAP_S - time.time()
            if delay > 0:
                time.sleep(delay)
            t0 = time.time()
            try:
                yield
            finally:
                t1 = time.time()
                fh.seek(0)
                fh.truncate()
                fh.write(repr(t1))
                fh.flush()
                with open(RAW / "logs" / f"requests_{domain}.log", "a") as log:
                    log.write(f"{t0:.3f}\t{t1:.3f}\t{os.getpid()}\n")
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def _check(resp: requests.Response) -> None:
    if resp.status_code in (403, 429):
        raise Blocked(f"{resp.status_code} from {resp.url}")
    ctype = resp.headers.get("Content-Type", "")
    if "html" in ctype and re.search(r"captcha|challenge|are you a robot", resp.text[:5000], re.I):
        raise Blocked(f"challenge page from {resp.url}")


def get_json_cached(url: str, cache_path: Path, *, method: str = "GET", body: dict | None = None,
                    ok_404: bool = True) -> dict | list | None:
    """Fetch JSON once and cache it. A cached 404 is stored as {"_status": 404}."""
    if cache_path.exists():
        data = json.loads(cache_path.read_text())
        return None if isinstance(data, dict) and data.get("_status") == 404 else data
    try:
        for _hop in range(3):  # redirects are followed manually, each as its own throttled request
            with _domain_slot(urlparse(url).netloc):
                if method == "POST":
                    resp = _session.post(url, json=body, timeout=60, allow_redirects=False)
                else:
                    resp = _session.get(url, timeout=60, allow_redirects=False)
            if resp.status_code in (301, 302, 303, 307, 308) and resp.headers.get("Location"):
                url = requests.compat.urljoin(url, resp.headers["Location"])
                continue
            break
    except TRANSIENT as exc:
        # Transient network error (not server pushback): log, skip, leave uncached.
        _net["consecutive"] += 1
        _net["skipped"] += 1
        print(f"net_error skip {url} ({exc.__class__.__name__}); "
              f"{_net['consecutive']}/{MAX_CONSECUTIVE_NET_ERRORS} consecutive", flush=True)
        if _net["consecutive"] >= MAX_CONSECUTIVE_NET_ERRORS:
            raise NetworkDown(f"{_net['consecutive']} consecutive network errors; last: {exc!r}") from exc
        time.sleep(30)
        return None
    _net["consecutive"] = 0
    _check(resp)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    if resp.status_code == 404 and ok_404:
        cache_path.write_text(json.dumps({"_status": 404, "url": url}))
        return None
    resp.raise_for_status()
    data = resp.json()
    tmp = cache_path.with_suffix(cache_path.suffix + ".tmp")
    tmp.write_text(json.dumps(data))
    tmp.rename(cache_path)
    return data


def download_file(url: str, dest: Path, expected_size: int | None = None) -> Path:
    """Stream a large file to dest once, resuming a partial .part file with Range."""
    if dest.exists() and (expected_size is None or dest.stat().st_size == expected_size):
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_suffix(dest.suffix + ".part")
    have = part.stat().st_size if part.exists() else 0
    headers = {"Range": f"bytes={have}-"} if have else {}
    with _domain_slot(urlparse(url).netloc), \
            _session.get(url, headers=headers, stream=True, timeout=120) as resp:
        _check(resp)
        if have and resp.status_code != 206:
            have = 0  # server ignored Range; start over
        resp.raise_for_status()
        with open(part, "ab" if have else "wb") as fh:
            for chunk in resp.iter_content(chunk_size=1 << 20):
                fh.write(chunk)
    if expected_size is not None and part.stat().st_size != expected_size:
        raise IOError(f"size mismatch for {dest.name}: {part.stat().st_size} != {expected_size}")
    part.rename(dest)
    return dest


def slugify(text: str) -> str:
    """Slug rule from data/interim/SHOW_KEY.md."""
    s = unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-z0-9]+", "-", s.lower())
    return re.sub(r"-+", "-", s).strip("-")


def wiki_title_key(title: str) -> str:
    """Normalize an enwiki title the way the dumps store it: spaces -> _, first letter upper."""
    t = title.strip().replace(" ", "_")
    t = re.sub(r"_+", "_", t)
    return t[:1].upper() + t[1:] if t else t
