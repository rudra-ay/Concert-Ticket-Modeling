"""Build data/interim/features_venue.parquet (one row per venue_id) from Wikidata (CC0).

venue wikilink (spine) -> enwiki title -> QID (dumps, features_wikilinks) -> EntityData.
Capacity: all P1083 statements with P518 configuration qualifiers; the concert
configuration (Q182832) is preferred. Type and indoor/outdoor come from P31 class
labels (one level of P279 superclasses when a direct class is unmapped).
"""
from __future__ import annotations

import math
import os
import re

import pandas as pd

import features_wikidata as W
from features_common import OUT, Blocked, NetworkDown, transient_skips
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
    if qid == "Q61":  # Washington, D.C. is a federal district, not a Q35657 state
        return "US-DC"
    ent = W.entity(qid)
    if US_STATE in W.values(ent, "P31"):
        return W.first(ent, "P300")
    return _us_state(W.first(ent, "P131"), depth + 1)


# Populated-place classes (checked by QID first, then by class label).
LOCALITY_QIDS = {"Q515", "Q486972", "Q1093829", "Q3957", "Q15127012", "Q532", "Q1549591", "Q200250",
                 "Q5119", "Q15284", "Q1637706", "Q484170", "Q747074", "Q2039348", "Q21518270", "Q262166"}
# The head noun must be a settlement word ("city in the United States", "big city", "town"),
# so "borough of New York City" or "district of X" do not count.
LOCALITY_LABEL = re.compile(r"^([\w-]+ )?(city|town|village|municipality|commune|comune|metropolis|"
                            r"capital city|human settlement|urban agglomeration|frazione|hamlet)\b", re.I)
NOT_LOCALITY = re.compile(r"county|district|region|province|state|prefecture|department|country", re.I)


def _is_locality(ent: dict) -> bool:
    p31 = W.values(ent, "P31")
    if LOCALITY_QIDS.intersection(p31):
        return True
    labs = [W.label(q) or "" for q in p31]
    return any(LOCALITY_LABEL.search(l) and not NOT_LOCALITY.search(l) for l in labs)


def locality(qid: str | None, depth: int = 0) -> tuple[str | None, str | None, tuple | None]:
    """First populated place walking P131 up from qid: (qid, label, coords)."""
    if not qid or depth > 5:
        return None, None, None
    ent = W.entity(qid)
    if ent and _is_locality(ent):
        return qid, W.label(ent), W.first(ent, "P625")
    return locality(W.first(ent, "P131"), depth + 1)


def _km(a: tuple, b: tuple) -> float:
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(h))


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
        **_locality_fields(W.first(ent, "P131"), coords),
        "country_iso2": W.country_iso2(country),
        "us_state": _us_state(W.first(ent, "P131")) if country == US else None,
        "opening_year": W.year_of(opening),
        **capacity(ent),
    })
    return row


def _locality_fields(p131: str | None, coords) -> dict:
    lq, lab, lc = locality(p131)
    return {"wd_locality_qid": lq, "wd_locality": lab,
            "km_to_locality": round(_km(coords, lc), 1) if coords and lc else None}


def build() -> pd.DataFrame:
    spine = load_spine()
    raw = pd.read_parquet(__import__("features_spine").spine_path(), columns=["show_id", "avg_price_usd"])
    spine = spine.merge(raw.assign(priced=raw["avg_price_usd"].notna())[["show_id", "priced"]],
                        on="show_id", how="left")
    venues = (spine.dropna(subset=["venue_id"])
              .groupby("venue_id", as_index=False)
              .agg(venue_name=("venue_name", "first"), city=("city", "first"), country=("country", "first"),
                   venue_wikilink=("venue_wikilink", lambda s: s.dropna().mode().iat[0] if s.notna().any() else None),
                   n_shows=("show_id", "size"), n_priced_shows=("priced", "sum"))
              # Partial writes cover priced shows (the LEVEL sample) first, then the most shows.
              .sort_values(["n_priced_shows", "n_shows"], ascending=False, kind="stable"))
    n_priced_venues = int((venues["n_priced_shows"] > 0).sum())
    res = Resolver()
    rows = []
    for i, v in enumerate(venues.itertuples(index=False)):
        title, qid = res.resolve(v.venue_wikilink)
        src = "spine_wikilink" if qid else None
        if not qid and isinstance(v.venue_name, str):
            # Name fallback, accepted only if the item looks like a venue.
            t2, q2 = res.resolve(v.venue_name)
            e2 = W.entity(q2) if q2 else None
            if e2 and (classify(_class_labels(W.values(e2, "P31"), walk_up=False))[0]
                       or W.values(e2, "P1083")):
                title, qid, src = t2, q2, "name_match"
        try:
            r = venue_row(qid)
        except (Blocked, NetworkDown):  # pushback or network down: stop the run, never retry
            _write(venues, rows)
            raise
        except Exception as exc:  # one bad item must not stop the build
            print(f"venue {v.venue_id} error: {exc!r}", flush=True)
            r = {"venue_qid": None}
        rows.append({"venue_id": v.venue_id, "venue_enwiki_title": title, "venue_link_source": src, **r})
        if i % 50 == 0:
            print(f"venue {i}/{len(venues)}", flush=True)
        if i % 200 == 199:
            _write(venues, rows)
        if i == n_priced_venues - 1:  # every venue of a priced show is done
            _write(venues, rows)
            print(f"PRICED_MILESTONE {n_priced_venues} venues", flush=True)
            if os.environ.get("FEATURES_VENUE_STOP_AT_MILESTONE") == "1":
                return _write(venues, rows)  # remainder runs later, after bill's Wikidata steps
    print(f"done; transient network skips this run: {transient_skips()} (rerun from cache to fill)", flush=True)
    return _write(venues, rows)


def _write(venues: pd.DataFrame, rows: list[dict]) -> pd.DataFrame:
    """Write the table (partial runs leave unprocessed venues with null features)."""
    out = venues.merge(pd.DataFrame(rows), on="venue_id", how="left")
    # A QID shared by venues in different spine cities usually means the tour table
    # linked a chain or generic article (e.g. [[Hard Rock Live]] for Hollywood FL and
    # Orlando). Flag it; consumers should trust the spine city over these coordinates.
    if "venue_qid" in out:
        n_cities = out.dropna(subset=["venue_qid"]).groupby("venue_qid")["city"].nunique()
        out["qid_n_spine_cities"] = out["venue_qid"].map(n_cities).astype("Int64")
        out["link_ambiguous"] = (out["qid_n_spine_cities"] > 1).astype("boolean")
    for c in ("opening_year", "capacity", "capacity_max", "capacity_n_configs"):
        if c in out:
            out[c] = pd.to_numeric(out[c], errors="coerce").astype("Int64")
    tmp = OUT / "features_venue.parquet.tmp"
    out.to_parquet(tmp, index=False)
    tmp.rename(OUT / "features_venue.parquet")
    return out


if __name__ == "__main__":
    df = build()
    print(df.notna().mean().round(3).to_string())
