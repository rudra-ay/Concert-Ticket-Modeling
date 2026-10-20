"""Lean run of features_venue.py for the venues beyond the priced milestone: one Wikidata request per venue.

Usage:
  .venv/bin/python src/venue_lean.py --plan   # count the requests left; no network
  .venv/bin/python src/venue_lean.py          # build features_venue.parquet (all venues)
  .venv/bin/python src/venue_lean.py --cache-only   # no network at all: uncached venues get empty rows

features_venue.py fetches the venue item and then walks class (P31/P279), locality and state (P131) items,
about 2.4 requests per venue at >= 5 s each. Here only the venue items themselves (and name-match
candidates) may touch the network; every other item is read from the cache, which already holds the
classes, cities and states reached from the 4,400 priced venues. Priced venues are fully cached, so their
rows come out unchanged. A remainder venue whose city or class was never cached gets those fields empty
(features_venue.md notes this). Spacing, Blocked/NetworkDown handling and the cache are features_common's.
"""
from __future__ import annotations

import sys

import features_venue as FV
import features_wikidata as W
from features_wikilinks import Resolver

_fetch_entity = W.entity
ALLOW: set[str] = set()


def _lean_entity(qid: str, cache_only: bool = False):
    return _fetch_entity(qid, cache_only=cache_only or qid not in ALLOW)


def venue_qids() -> set[str]:
    """QIDs build() fetches directly: a venue's wikilink target, or its name-match candidate only when the
    venue has no wikilink QID (build() never tries the name otherwise). Mirrors build()'s per-venue choice."""
    spine = FV.load_spine().dropna(subset=["venue_id"])
    v = spine.groupby("venue_id").agg(
        wl=("venue_wikilink", lambda s: s.dropna().mode().iat[0] if s.notna().any() else None),
        name=("venue_name", "first"))
    res, out = Resolver(), set()
    for wl, name in zip(v.wl, v.name):
        q = res.resolve(wl)[1] or (res.resolve(name)[1] if isinstance(name, str) else None)
        if q:
            out.add(q)
    return out


def main() -> None:
    if "--cache-only" not in sys.argv:
        ALLOW.update(venue_qids())
    uncached = sorted(q for q in ALLOW if not (W.CACHE / f"{q}.json").exists())
    print(f"{len(ALLOW)} venue QIDs; {len(uncached)} not cached -> about {len(uncached)} requests "
          f"(~{len(uncached) * 5.2 / 3600:.1f} h at >= 5 s spacing)", flush=True)
    if "--plan" in sys.argv:
        return
    W.entity = _lean_entity  # FV calls W.entity / W.label through the module, so this covers every lookup
    FV.build()


if __name__ == "__main__":
    main()
