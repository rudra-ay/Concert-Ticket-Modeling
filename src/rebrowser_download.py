"""Download the public (ungated, no-login) Rebrowser preview datasets from Hugging Face.

Source: SOURCES.md N7. Decision: DECISIONS.md item 3 (use Rebrowser's own channels only).
License: CC BY-NC 4.0, non-commercial, no redistribution. Attribute "Data from Rebrowser (rebrowser.net)".

Rules followed here:
- No login, no token, no cookies. If a file needs auth (401/403), we stop and report it.
- One honest User-Agent, >= 5 s between requests to the same host, robots.txt checked.
- Everything cached under data/raw/rebrowser/; cached files are never refetched.

Usage:
    .venv/bin/python src/rebrowser_download.py            # all three datasets
    .venv/bin/python src/rebrowser_download.py stubhub-dataset
"""
from __future__ import annotations

import json
import sys
import time
import urllib.robotparser
from pathlib import Path
from urllib.parse import quote, urlparse

import requests

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "raw" / "rebrowser"
UA = "TicketPriceResearch/0.1 (personal research; contact: rudraayyagari@gmail.com)"
MIN_GAP_S = 5.0
DATASETS = ["stubhub-dataset", "seatgeek-dataset", "gametime-dataset"]
HF = "https://huggingface.co"

_session = requests.Session()
_session.headers["User-Agent"] = UA
_session.headers["Connection"] = "close"  # CDN drops idle keep-alives during our 5 s gaps
_last_hit: dict[str, float] = {}
_robots: dict[str, urllib.robotparser.RobotFileParser] = {}


class Blocked(RuntimeError):
    pass


def _wait(host: str) -> None:
    gap = time.monotonic() - _last_hit.get(host, -1e9)
    if gap < MIN_GAP_S:
        time.sleep(MIN_GAP_S - gap)
    _last_hit[host] = time.monotonic()


def _allowed(url: str) -> bool:
    host = urlparse(url).netloc
    if host not in _robots:
        rp = urllib.robotparser.RobotFileParser()
        _wait(host)
        r = _session.get(f"https://{host}/robots.txt", timeout=30)
        rp.parse(r.text.splitlines() if r.status_code == 200 else [])
        (OUT / "_robots").mkdir(parents=True, exist_ok=True)
        (OUT / "_robots" / f"{host}.txt").write_text(r.text if r.status_code == 200 else f"HTTP {r.status_code}\n")
        _robots[host] = rp
    return _robots[host].can_fetch(UA, url)


def fetch(url: str, dest: Path) -> Path:
    """Fetch url into dest once. Never refetch a cached file; never retry a 401/403/429."""
    if dest.exists():
        return dest
    if not _allowed(url):
        raise Blocked(f"robots.txt disallows {url}")
    _wait(urlparse(url).netloc)
    # Redirects go to HF's own CDN for LFS/Xet files; requests drops nothing we send (no auth).
    try:
        r = _session.get(url, timeout=120, stream=True)
    except requests.RequestException as exc:
        # Don't hammer: a reset/timeout ends this run. Rerunning resumes from the cache.
        raise Blocked(f"network error on {url}: {exc.__class__.__name__}; rerun later to resume") from None
    is_html = r.headers.get("content-type", "").startswith("text/html")
    if r.status_code in (401, 403, 429) or (is_html and "captcha" in r.text[:5000].lower()):
        raise Blocked(f"HTTP {r.status_code} for {url} (needs login/token or we were throttled); stopping")
    r.raise_for_status()
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    with tmp.open("wb") as f:
        for chunk in r.iter_content(1 << 20):
            f.write(chunk)
    tmp.rename(dest)
    return dest


def download(dataset: str) -> None:
    base = OUT / dataset
    listing = fetch(f"{HF}/api/datasets/rebrowser/{dataset}/tree/main?recursive=true", base / "_tree.json")
    files = [e for e in json.loads(listing.read_text()) if e.get("type") == "file"]
    meta = fetch(f"{HF}/api/datasets/rebrowser/{dataset}", base / "_meta.json")
    info = json.loads(meta.read_text())
    if info.get("gated") or info.get("private"):
        raise Blocked(f"{dataset} is gated/private on HF (gated={info.get('gated')}); user action needed")
    total = sum(e.get("size", 0) for e in files)
    print(f"{dataset}: {len(files)} files, {total/1e6:.1f} MB")
    paths = {e["path"] for e in files}
    for e in files:
        path = e["path"]
        if path.endswith(".svg"):
            continue  # charts, not data
        if path.endswith(".csv") and path[:-4] + ".parquet" in paths:
            continue  # same rows as the parquet next to it
        fetch(f"{HF}/datasets/rebrowser/{dataset}/resolve/main/{quote(path)}", base / path)
    print(f"{dataset}: done")


def main(argv: list[str]) -> int:
    for ds in argv or DATASETS:
        try:
            download(ds)
        except Blocked as exc:
            print(f"STOPPED: {exc}", file=sys.stderr)
            return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
