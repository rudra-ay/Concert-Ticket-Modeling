"""Build data/interim/features_venue.parquet (one row per venue_id) from Wikidata (CC0).

venue wikilink (spine) -> enwiki title -> QID (dumps, features_wikilinks) -> EntityData.
Capacity: all P1083 statements with P518 configuration qualifiers; the concert
configuration (Q182832) is preferred. Type and indoor/outdoor come from P31 class
labels (one level of P279 superclasses when a direct class is unmapped).
"""
from __future__ import annotations

import re

import pandas as pd

import features_wikidata as W
from features_common import OUT
from features_spine import load_spine
from features_wikilinks import Resolver

CONCERT = "Q182832"
US = "Q30"
US_STATE = "Q35657"

# (regex on class label, venue_type, indoor_outdoor). First match wins.
TYPE_RULES = [
    (r"retractable", "stadium", "retractable"),
    (r"dome|domed|indoor stadium|covered stadium", "stadium", "indoor"),
    (r"stadium|ballpark|baseball park|cricket ground|football ground", "stadium", "outdoor"),
    (r"amphitheat|bandshell|band shell|music shed|outdoor (theat|venue)|pavilion", "amphitheatre", "outdoor"),
    (r"festival|fairground|racecourse|race ?track|speedway|park\b|polo field|showground|beach", "festival ground", "outdoor"),
    (r"arena|multi-purpose hall|multipurpose hall|indoor (sports )?venue|sports hall|events? cent(er|re)|"
     r"convention cent(er|re)|exhibition (cent(er|re)|hall)|coliseum|coliseo|palais|palacio|forum", "arena", "indoor"),
    (r"nightclub|night club|\bclub\b|ballroom|bar\b|music venue", "club", "indoor"),
    (r"theat|concert hall|opera house|auditorium|music hall|philharmonic|performing arts", "theatre", "indoor"),
]


def classify(class_labels: list[str]) -> tuple[str | None, str | None, str | None]:
    """Return (venue_type, indoor_outdoor, matched_label) from P31 class labels."""
    # Priority is by rule order, so a dome stadium beats a plain stadium label.
    for pat, vtype, io in TYPE_RULES:
        for lab in class_labels:
            if lab and re.search(pat, lab, re.I):
                return vtype, io, lab
    return None, None, None


def _class_labels(qids: list[str], walk_up: bool) -> list[str]:
    labs = [W.label(q) or "" for q in qids]
    if walk_up and classify(labs)[0] is None:
        for q in qids:
            labs += [W.label(s) or "" for s in W.values(W.entity(q), "P279")[:5]]
    return labs


def _us_state(qid: str | None, depth: int = 0) -> str | None:
    """Walk P131 to a U.S. state; return its ISO 3166-2 code (P300), e.g. US-NY."""
    if not qid or depth > 5:
        return None
    ent = W.entity(qid)
    if US_STATE in W.values(ent, "P31"):
        return W.first(ent, "P300")
    return _us_state(W.first(ent, "P131"), depth + 1)


def capacity(ent: dict) -> dict:
    configs = []
    for s in W.all_statements(ent, "P1083"):
        v = W._value(s["mainsnak"])
        if v is None:
            continue
        parts = W.qualifiers(s, "P518")
        when = [W.year_of(t) for t in W.qualifiers(s, "P585")]
        configs.append({"cap": int(v), "parts": parts, "year": next((y for y in when if y), None),
                        "rank": s.get("rank")})
    if not configs:
        return {"capacity": None, "capacity_config": None, "capacity_max": None,
                "capacity_n_configs": 0, "capacity_all": None}
    concert = [c for c in configs if CONCERT in c["parts"]]
    unqual = [c for c in configs if not c["parts"]]
    pref = [c for c in configs if c["rank"] == "preferred"]
    if concert:
        pick, how = max(concert, key=lambda c: (c["year"] or 0, c["cap"])), "concert"
    elif pref:
        pick, how = pref[0], "preferred_rank"
    elif unqual:
        pick, how = max(unqual, key=lambda c: (c["year"] or 0, c["cap"])), "unqualified"
    else:
        pick, how = max(configs, key=lambda c: c["cap"]), "max_of_configs"
    part_label = lambda c: "/".join(W.label(p) or p for p in c["parts"]) or "unspecified"
    return {
        "capacity": pick["cap"],
        "capacity_config": how,
        "capacity_max": max(c["cap"] for c in configs),
        "capacity_n_configs": len({c["cap"] for c in configs}),
        "capacity_all": "; ".join(f"{c['cap']} ({part_label(c)}{', ' + str(c['year']) if c['year'] else ''})"
                                  for c in configs),
    }


def venue_row(qid: str | None) -> dict:
    ent = W.entity(qid)
    row = {"venue_qid": qid if ent else None}
    if not ent:
        return row
    p31 = W.values(ent, "P31")
    labs = _class_labels(p31, walk_up=True)
    vtype, io, matched = classify(labs)
    coords = W.first(ent, "P625")
    country = W.first(ent, "P17") or W.country_of(W.first(ent, "P131"))
    opening = W.first(ent, "P1619") or W.first(ent, "P571")
    row.update({
        "venue_label": W.label(ent),
        "p31_classes": "; ".join(f"{q}:{W.label(q) or ''}" for q in p31),
        "venue_type": vtype,
        "indoor_outdoor": io,
        "type_matched_label": matched,
        "lat": coords[0] if coords else None,
        "lon": coords[1] if coords else None,
        "coord_source": "wikidata" if coords else None,
        "wd_city": W.label(W.first(ent, "P131")),
        "country_iso2": W.country_iso2(country),
        "us_state": _us_state(W.first(ent, "P131")) if country == US else None,
        "opening_year": W.year_of(opening),
        **capacity(ent),
    })
    return row


def build() -> pd.DataFrame:
    spine = load_spine()
    venues = (spine.dropna(subset=["venue_id"])
              .groupby("venue_id", as_index=False)
              .agg(venue_name=("venue_name", "first"), city=("city", "first"), country=("country", "first"),
                   venue_wikilink=("venue_wikilink", lambda s: s.dropna().mode().iat[0] if s.notna().any() else None),
                   n_shows=("show_id", "size")))
    res = Resolver()
    rows = []
    for i, v in enumerate(venues.itertuples(index=False)):
        title, qid = res.resolve(v.venue_wikilink)
        src = "spine_wikilink" if qid else None
        if not qid and v.venue_name:
            # Name fallback, accepted only if the item looks like a venue.
            t2, q2 = res.resolve(v.venue_name)
            e2 = W.entity(q2) if q2 else None
            if e2 and (classify(_class_labels(W.values(e2, "P31"), walk_up=False))[0]
                       or W.values(e2, "P1083")):
                title, qid, src = t2, q2, "name_match"
        r = venue_row(qid)  # features_common.Blocked propagates: stop, never retry
        rows.append({"venue_id": v.venue_id, "venue_enwiki_title": title, "venue_link_source": src, **r})
        if i % 50 == 0:
            print(f"venue {i}/{len(venues)}", flush=True)
    out = venues.merge(pd.DataFrame(rows), on="venue_id", how="left")
    out.to_parquet(OUT / "features_venue.parquet", index=False)
    return out


if __name__ == "__main__":
    df = build()
    print(df.notna().mean().round(3).to_string())
