"""Wikipedia tour box office -> data/interim/shows_base.parquet (source A1).

Route (DECISIONS.md, strict robots reading): enwiki 20261001 multistream dump
on dumps.wikimedia.org. We read the multistream index, pick candidate tour
pages by title, and fetch only the bz2 streams that hold them with serial HTTP
Range requests (wikidump_http enforces UA, >= 5 s spacing, stop on 403/429).
Every fetched stream is cached and never refetched, so reruns are offline.

Stages:
  select  build the candidate list (needs only the cached index + redirect.sql.gz)
  fetch   fetch missing streams in priority order, extract tour pages
  parse   parse cached pages into shows_base.parquet (+ coverage summary)

Usage: .venv/bin/python src/collect_wikipedia_boxoffice.py select|fetch [--max N]|parse|all
"""
from __future__ import annotations

import bz2
import gzip
import json
import re
import sys
import time
import xml.etree.ElementTree as ET

import requests
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from wikidump_http import CACHE, Blocked, get_range  # noqa: E402

DUMP = "20261001"
DDIR = CACHE / DUMP
INDEX = DDIR / f"enwiki-{DUMP}-pages-articles-multistream-index.txt.bz2"
REDIRECTS = DDIR / f"enwiki-{DUMP}-redirect.sql.gz"
DUMP_URL = f"https://dumps.wikimedia.org/enwiki/{DUMP}/enwiki-{DUMP}-pages-articles-multistream.xml.bz2"
DUMP_SIZE = 26917225724
STREAMS = CACHE / "streams" / DUMP      # raw bz2 bytes, <start>-<end>.bz2
PAGES = CACHE / "pages" / DUMP          # extracted tour pages, <page_id>__<revid>.json
CANDS = CACHE / "candidates.json"
FETCH_LOG = CACHE / "fetch_log.jsonl"
RECENT_PAGE_ID = 79_000_000

TITLE_POS = re.compile(
    r"(\bTour\b|\btour\)|Residency|\bresidency\)|concert tour|\bConcerts?\b|"
    r"List of .* (concerts|tour dates|concert tours|shows|live performances)\b)")
TITLE_NEG = re.compile(
    r"^(Talk|User|Wikipedia|File|Template|Category|Portal|Draft|Module|Help|MediaWiki|TimedText)"
    r"( talk)?:|Tour de |Tour of |PGA Tour|ATP |WTA |European Tour|Champions Tour|Golf|[Cc]ycling|"
    r"Grand Tour|Tour Finals|Tour Championship|Rugby|[Cc]ricket|Down Under|Korn Ferry|Challenge Tour|"
    r"Challenger|Asian Tour|Sunshine Tour|LPGA|Women's Tour|\brace\b|Rally|Tennis|NASCAR|PDC|PBA |"
    r"Athletics|Snooker|Darts|Surf|Bowling|\(film\)|\(album\)|\(video\)|\(song\)|\(book\)|Eiffel|"
    r"Tour Card|Tour \(Paris|Tour du |Tour d'|Tour, |\(DVD\)|\(EP\)|\(Live\)")
# Titles that look like an artist's tour article proper get fetched first.
TITLE_TIER1 = re.compile(
    r"(Tour|tour\)|Residency|residency\)|Tour \d{4}(–\d{2,4})?|Tour '\d\d)( \([^)]*\))?$|"
    r"List of .* (concerts|tour dates|live performances)")

NS = "{http://www.mediawiki.org/xml/export-0.11/}"
BOXOFFICE_SIGNAL = re.compile(r"(Attendance|Revenue|Gross|Box office)", re.I)
INFOBOX_CONCERT = re.compile(r"\{\{\s*Infobox[ _]concert", re.I)


# ---------------------------------------------------------------- select
def select() -> list[dict]:
    if CANDS.exists():
        return json.loads(CANDS.read_text())
    redirect_ids: set[int] = set()
    rx = re.compile(rb"\((\d+),(-?\d+),")
    with gzip.open(REDIRECTS, "rb") as fh:
        for line in fh:
            redirect_ids.update(int(a) for a, _ in rx.findall(line))
    offsets: list[int] = []
    cands = []
    with bz2.open(INDEX, "rt", encoding="utf-8") as fh:
        for line in fh:
            off, pid, title = line.rstrip("\n").split(":", 2)
            off_i = int(off)
            if not offsets or offsets[-1] != off_i:
                offsets.append(off_i)
            pid_i = int(pid)
            if pid_i in redirect_ids or TITLE_NEG.search(title) or not TITLE_POS.search(title):
                continue
            title = title.replace("&amp;", "&").replace("&quot;", '"').replace("&#039;", "'")
            cands.append({"start": off_i, "page_id": pid_i, "title": title,
                          "tier": 1 if TITLE_TIER1.search(title) else 2})
    nxt = {a: b for a, b in zip(offsets, offsets[1:] + [DUMP_SIZE])}
    for c in cands:
        c["end"] = nxt[c["start"]]
    CANDS.write_text(json.dumps(cands))
    return cands


# ---------------------------------------------------------------- fetch
def _stream_path(start: int, end: int) -> Path:
    return STREAMS / f"{start}-{end}.bz2"


def _extract_pages(raw: bytes) -> list[dict]:
    xml = bz2.decompress(raw).decode("utf-8")
    root = ET.fromstring(f"<root xmlns='{NS[1:-1]}'>{xml}</root>")
    out = []
    for page in root.iter(f"{NS}page"):
        if page.findtext(f"{NS}ns") != "0" or page.find(f"{NS}redirect") is not None:
            continue
        rev = page.find(f"{NS}revision")
        text = rev.findtext(f"{NS}text") or ""
        out.append({"title": page.findtext(f"{NS}title"), "page_id": int(page.findtext(f"{NS}id")),
                    "revid": int(rev.findtext(f"{NS}id")), "timestamp": rev.findtext(f"{NS}timestamp"),
                    "text": text})
    return out


def _is_tour_page(p: dict) -> bool:
    t = p["text"]
    has_table = "{|" in t and BOXOFFICE_SIGNAL.search(t) is not None
    return has_table and (INFOBOX_CONCERT.search(t) is not None or TITLE_POS.search(p["title"]) is not None)


def _save_pages(raw: bytes) -> int:
    n = 0
    for p in _extract_pages(raw):
        if _is_tour_page(p):
            dest = PAGES / f"{p['page_id']}__{p['revid']}.json"
            if not dest.exists():
                dest.write_text(json.dumps(p, ensure_ascii=False))
            n += 1
    return n


def fetch(max_requests: int | None = None) -> None:
    STREAMS.mkdir(parents=True, exist_ok=True)
    PAGES.mkdir(parents=True, exist_ok=True)
    cands = select()
    streams: dict[tuple[int, int], tuple[int, int]] = {}
    for c in cands:
        # priority: tier-1 titles first; within a tier, pages created before ~2025
        # (page_id < 79M) newest-first, since the newest articles are mostly
        # upcoming tours that have no box office figures yet
        key = (c["start"], c["end"])
        pri = (c["tier"], c["page_id"] >= RECENT_PAGE_ID, -c["page_id"])
        streams[key] = min(streams.get(key, pri), pri)
    order = sorted(streams, key=lambda k: streams[k])
    todo = [k for k in order if not _stream_path(*k).exists()]
    print(f"{len(order)} candidate streams, {len(todo)} to fetch", flush=True)
    done = fails = 0
    for start, end in todo:
        if max_requests is not None and done >= max_requests:
            break
        t0 = time.time()
        try:
            raw = get_range(DUMP_URL, start, end)
        except Blocked as exc:
            print(f"BLOCKED: {exc}; stopping", flush=True)
            return
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as exc:
            # a stalled connection is not pushback: skip this stream (picked up on the next run)
            fails += 1
            print(f"network error on {start}-{end} ({exc.__class__.__name__}); {fails} in a row", flush=True)
            if fails >= 5:
                print("5 consecutive network errors; stopping", flush=True)
                return
            time.sleep(30)
            continue
        fails = 0
        if len(raw) != end - start:
            print(f"short range {start}-{end}: {len(raw)}; skipping", flush=True)
            continue
        tmp = _stream_path(start, end).with_suffix(".part")
        tmp.write_bytes(raw)
        tmp.rename(_stream_path(start, end))
        kept = _save_pages(raw)
        done += 1
        with open(FETCH_LOG, "a") as fh:
            fh.write(json.dumps({"start": start, "end": end, "bytes": len(raw), "secs": round(time.time() - t0, 1),
                                 "tour_pages": kept, "at": time.strftime("%Y-%m-%dT%H:%M:%S")}) + "\n")
        if done % 25 == 0:
            print(f"fetched {done}/{len(todo)} streams; pages on disk {len(list(PAGES.glob('*.json')))}", flush=True)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "all"
    mx = int(sys.argv[sys.argv.index("--max") + 1]) if "--max" in sys.argv else None
    if cmd in ("select", "all"):
        cs = select()
        print(len(cs), "candidates;", len({(c["start"], c["end"]) for c in cs}), "streams;",
              sum(c["tier"] == 1 for c in cs), "tier-1")
    if cmd in ("fetch", "all"):
        fetch(mx)
    if cmd in ("parse", "all"):
        from boxoffice_parse import build
        build()
