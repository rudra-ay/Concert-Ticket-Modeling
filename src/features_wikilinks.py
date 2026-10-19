"""Title -> page_id -> Wikidata QID resolution from enwiki 20261001 dumps (no api.php).

Sources (all under data/raw/wikipedia_dumps/20261001/):
- page_props.sql.gz: pp_page -> wikibase_item (QID)
- redirect.sql.gz: rd_from (page_id) -> target title (ns 0 only)
- pages-articles-multistream-index.txt.bz2 (collector-prices): offset:page_id:title

Derived lookups are cached as parquet under data/raw/wikipedia_dumps/derived/.
"""
from __future__ import annotations

import bz2
import gzip
import re

import pandas as pd

from features_common import RAW, wiki_title_key

DUMP = RAW / "wikipedia_dumps" / "20261001"
DERIVED = RAW / "wikipedia_dumps" / "derived"


def _inserts(path):
    with gzip.open(path, "rt", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if line.startswith("(") or line.startswith("INSERT INTO"):
                yield line


def page_qid() -> pd.DataFrame:
    out = DERIVED / "page_qid.parquet"
    if out.exists():
        return pd.read_parquet(out)
    pat = re.compile(r"\((\d+),'wikibase_item','(Q\d+)',")
    rows = [(int(a), b) for line in _inserts(DUMP / "enwiki-20261001-page_props.sql.gz")
            for a, b in pat.findall(line)]
    df = pd.DataFrame(rows, columns=["page_id", "qid"])
    DERIVED.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out, index=False)
    return df


def redirects() -> pd.DataFrame:
    """rd_from page_id -> target title (namespace 0)."""
    out = DERIVED / "redirect_ns0.parquet"
    if out.exists():
        return pd.read_parquet(out)
    # (rd_from, rd_namespace, 'rd_title', 'rd_interwiki', 'rd_fragment')
    pat = re.compile(r"\((\d+),0,'((?:[^'\\]|\\.)*)',")
    rows = [(int(a), b.replace("\\'", "'").replace('\\"', '"').replace("\\\\", "\\"))
            for line in _inserts(DUMP / "enwiki-20261001-redirect.sql.gz") for a, b in pat.findall(line)]
    df = pd.DataFrame(rows, columns=["page_id", "target_title"])
    df.to_parquet(out, index=False)
    return df


def titles() -> pd.DataFrame:
    """ns0 page_id <-> title from the multistream index (titles with a namespace prefix dropped)."""
    out = DERIVED / "title_ns0.parquet"
    if out.exists():
        return pd.read_parquet(out)
    path = DUMP / "enwiki-20261001-pages-articles-multistream-index.txt.bz2"
    ns_prefix = re.compile(r"^(Talk|User|Wikipedia|File|MediaWiki|Template|Help|Category|Portal|Draft|"
                           r"TimedText|Module|Event|[A-Za-z ]+ talk):")
    ids, ts = [], []
    with bz2.open(path, "rt", encoding="utf-8") as fh:
        for line in fh:
            _, pid, title = line.rstrip("\n").split(":", 2)
            if ns_prefix.match(title):
                continue
            ids.append(int(pid))
            ts.append(title.replace(" ", "_"))
    df = pd.DataFrame({"page_id": ids, "title": ts})
    df.to_parquet(out, index=False)
    return df


class Resolver:
    """Resolve wikilink targets to canonical title + QID, following one redirect hop."""

    def __init__(self) -> None:
        t = titles()
        self.title_to_id = dict(zip(t["title"], t["page_id"]))
        self.id_to_title = dict(zip(t["page_id"], t["title"]))
        r = redirects()
        self.redirect = dict(zip(r["page_id"], r["target_title"]))
        q = page_qid()
        self.qid = dict(zip(q["page_id"], q["qid"]))

    def resolve(self, title: str | None) -> tuple[str | None, str | None]:
        """Return (canonical_title, qid). Fragment (#section) is dropped."""
        if not isinstance(title, str) or not title.strip():  # None / NaN / NA
            return None, None
        key = wiki_title_key(title.split("#")[0])
        pid = self.title_to_id.get(key)
        if pid is None:
            return None, None
        for _ in range(2):  # double redirects are rare; stop after 2 hops
            if pid in self.redirect:
                tgt = wiki_title_key(self.redirect[pid])
                nxt = self.title_to_id.get(tgt)
                if nxt is None:
                    return tgt, None
                pid = nxt
        return self.id_to_title.get(pid), self.qid.get(pid)
