"""Wikidata entity access via Special:EntityData/<QID>.json (robots-allowed route; CC0).

Never SPARQL (query.wikidata.org/sparql is robots-disallowed; see DECISIONS.md).
One cached JSON per QID under data/raw/wikidata/.
"""
from __future__ import annotations

import re

from features_common import RAW, get_json_cached

CACHE = RAW / "wikidata"
URL = "https://www.wikidata.org/wiki/Special:EntityData/{qid}.json"


def entity(qid: str) -> dict | None:
    if not qid or not re.fullmatch(r"Q\d+", qid):
        return None
    data = get_json_cached(URL.format(qid=qid), CACHE / f"{qid}.json")
    if not data:
        return None
    ents = data.get("entities", {})
    # A merged item redirects: the payload is keyed by the target QID.
    return ents.get(qid) or (next(iter(ents.values())) if ents else None)


def statements(ent: dict | None, prop: str) -> list[dict]:
    """Best-rank statements: preferred if any exist, else normal. Deprecated dropped."""
    if not ent:
        return []
    sts = [s for s in ent.get("claims", {}).get(prop, []) if s.get("rank") != "deprecated"]
    pref = [s for s in sts if s.get("rank") == "preferred"]
    return pref or sts


def all_statements(ent: dict | None, prop: str) -> list[dict]:
    """All non-deprecated statements (used where every configuration matters, e.g. capacity)."""
    if not ent:
        return []
    return [s for s in ent.get("claims", {}).get(prop, []) if s.get("rank") != "deprecated"]


def _value(snak: dict):
    if snak.get("snaktype") != "value":
        return None
    dv = snak["datavalue"]
    t, v = dv["type"], dv["value"]
    if t == "wikibase-entityid":
        return v.get("id") or f"Q{v['numeric-id']}"
    if t == "time":
        m = re.match(r"([+-]\d+)-(\d\d)-(\d\d)", v["time"])
        return {"year": int(m.group(1)), "month": int(m.group(2)), "day": int(m.group(3)),
                "precision": v["precision"]} if m else None
    if t == "quantity":
        return float(v["amount"])
    if t == "globecoordinate":
        return (v["latitude"], v["longitude"])
    return v  # string / monolingualtext


def values(ent: dict | None, prop: str) -> list:
    return [x for x in (_value(s["mainsnak"]) for s in statements(ent, prop)) if x is not None]


def first(ent: dict | None, prop: str):
    vals = values(ent, prop)
    return vals[0] if vals else None


def qualifiers(statement: dict, prop: str) -> list:
    return [x for x in (_value(q) for q in statement.get("qualifiers", {}).get(prop, [])) if x is not None]


def label(ent_or_qid, lang: str = "en") -> str | None:
    ent = entity(ent_or_qid) if isinstance(ent_or_qid, str) else ent_or_qid
    if not ent:
        return None
    lab = ent.get("labels", {}).get(lang) or ent.get("labels", {}).get("mul")
    return lab["value"] if lab else None


def enwiki_title(ent: dict | None) -> str | None:
    sl = (ent or {}).get("sitelinks", {}).get("enwiki")
    return sl["title"] if sl else None


def year_of(t: dict | None) -> int | None:
    """Year from a Wikidata time value, if precision is year or finer (>= 9)."""
    if not t or t.get("precision", 0) < 9:
        return None
    return t["year"]


def country_iso2(qid: str | None) -> str | None:
    """ISO 3166-1 alpha-2 (P297) of a country item."""
    return first(entity(qid), "P297") if qid else None


def country_of(qid: str | None, depth: int = 0) -> str | None:
    """Country QID for a place: its own P17, else walk P131 (located in) up to 4 levels."""
    if not qid or depth > 4:
        return None
    ent = entity(qid)
    if values(ent, "P297"):  # it is itself a country
        return qid
    c = first(ent, "P17")
    if c:
        return c
    return country_of(first(ent, "P131"), depth + 1)
