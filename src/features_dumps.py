"""Download (once) the bulk dumps the feature tables need.

- enwiki 20261001 SQL tables (CC BY-SA 4.0 / GFDL page metadata): page_props,
  redirect, categorylinks, linktarget (page_id <-> title comes from the multistream
  index that collector-prices downloads). Used for title -> page_id -> Wikidata QID,
  redirect resolution, and tour-article counts via categories.
- MusicBrainz fullexport 20261017-002244: mbdump.tar.bz2 (core, CC0) and
  mbdump-derived.tar.bz2 (tags/genres, CC BY-NC-SA 3.0).

Usage: .venv/bin/python src/features_dumps.py [enwiki|musicbrainz|all]
"""
from __future__ import annotations

import sys
import time

import requests

from features_common import RAW
from features_common import download_file as _download_once
import wikidump_http  # shared cross-process gap lock for dumps.wikimedia.org (collector-prices)


def download_file(url, dest, expected_size=None, attempts=6):
    """Resume after dropped connections only. Blocked (403/429) propagates immediately."""
    for i in range(attempts):
        try:
            return _download_once(url, dest, expected_size)
        except (requests.exceptions.ChunkedEncodingError, requests.exceptions.ConnectionError,
                requests.exceptions.ReadTimeout) as exc:
            print(f"connection dropped ({exc.__class__.__name__}); resume {i + 1}/{attempts}", flush=True)
            time.sleep(30)
    raise IOError(f"gave up on {url}")

ENWIKI_DATE = "20261001"
ENWIKI_TABLES = {  # table -> size in bytes from dumpstatus.json
    "page_props": 483959463,
    "redirect": 187638901,
    "linktarget": 1443058692,
    "categorylinks": 2549901446,
}
MB_DIR = "20261017-002244"
MB_FILES = ["mbdump-derived.tar.bz2", "mbdump.tar.bz2"]


def enwiki() -> None:
    for table, size in ENWIKI_TABLES.items():
        name = f"enwiki-{ENWIKI_DATE}-{table}.sql.gz"
        url = f"https://dumps.wikimedia.org/enwiki/{ENWIKI_DATE}/{name}"
        print("enwiki", name, flush=True)
        wikidump_http.download(url, RAW / "wikipedia_dumps" / ENWIKI_DATE / name, size)


def musicbrainz() -> None:
    for name in MB_FILES:
        url = f"https://data.metabrainz.org/pub/musicbrainz/data/fullexport/{MB_DIR}/{name}"
        print("musicbrainz", name, flush=True)
        download_file(url, RAW / "musicbrainz_dumps" / MB_DIR / name)


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    if which in ("enwiki", "all"):
        enwiki()
    if which in ("musicbrainz", "all"):
        musicbrainz()
    print("done", flush=True)
