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
import unicodedata

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
    (r"baseball (venue|stadium)|cricket field|cricket ground|rugby (league |union )?(ground|stadium)|velodrome", "stadium", "outdoor"),
    (r"fair ?ground|^fair$|\bsquare\b|plaza|public park|piazza", "festival ground", "outdoor"),
    (r"ice rink|ice hockey arena|civic cent(er|re)|basketball arena|sports arena", "arena", "indoor"),
    (r"casino|showroom|cabaret|^hotel$|resort", "theatre", "indoor"),
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
                   city_wikilink=("city_wikilink", lambda s: s.dropna().mode().iat[0] if s.notna().any() else None),
                   n_shows=("show_id", "size"), n_priced_shows=("priced", "sum"))
              # Partial writes cover priced shows (the LEVEL sample) first, then the most shows.
              .sort_values(["n_priced_shows", "n_shows"], ascending=False, kind="stable"))
    n_priced_venues = int((venues["n_priced_shows"] > 0).sum())
    res = Resolver()
    venues["city_qid"] = venues["city_wikilink"].map(lambda t: res.resolve(t)[1])
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


# Fallbacks when P31 classes are generic ("sports venue", "event venue", "building", …).
NAME_RULES = [
    (r"amphithea|amfitea|bowl\b|pavilion|music cent(er|re) at|outdoor", "amphitheatre", "outdoor"),
    (r"stadium|stadion|estadio|est[aá]dio|stade|stadio|field\b|park\b|ballpark|dome\b", "stadium", None),
    (r"arena|forum|coliseum|coliseo|palais|palacio|palasport|halle\b|hall\b.*(sport|event)|"
     r"(event|entertainment|sports|civic|convention|exhibition) cent(er|re)", "arena", "indoor"),
    (r"theat|teatro|th[eé][aâ]tre|auditorium|opera|music hall|concert hall|philharmon|symphony|playhouse", "theatre", "indoor"),
    (r"club|ballroom|lounge|bar\b|tavern|social|room\b|house of blues|fillmore|9:30", "club", "indoor"),
    (r"festival|fairground|showground|racecourse|speedway|common\b|meadow", "festival ground", "outdoor"),
]


def _norm(t) -> str:
    return re.sub(r"[^a-z0-9 ]", " ", unicodedata.normalize("NFKD", str(t or "")).encode("ascii", "ignore")
                  .decode().lower()).strip()


def _place_chain(qid: str | None) -> tuple[set[str], list[str]]:
    """QIDs and labels/aliases along P131 (≤ 6 levels), read from cache only."""
    qids, labs, q = set(), [], qid
    for _ in range(6):
        ent = W.entity(q, cache_only=True) if q else None
        if not ent:
            break
        qids.add(q)
        labs.append(W.label(ent) or "")
        labs += [a["value"] for a in ent.get("aliases", {}).get("en", [])]
        q = W.first(ent, "P131")
    return qids, [x for x in labs if x]


def postprocess(out: pd.DataFrame) -> pd.DataFrame:
    """Offline (cache-only) derived columns: type fallbacks, city-vs-Wikidata checks."""
    if "venue_qid" not in out:
        return out
    labs = out["p31_classes"].fillna("").map(lambda s: [x.split(":", 1)[-1] for x in s.split("; ") if x])
    vt, io, src = [], [], []
    for lab, name, cap, qid in zip(labs, out["venue_name"], out["capacity"], out["venue_qid"]):
        t, i, _ = classify(lab)
        how = "wikidata_class" if t else None
        if not t and isinstance(name, str):
            for pat, nt, ni in NAME_RULES:
                if re.search(pat, name, re.I):
                    t, i, how = nt, ni, "name_keyword"
                    break
        if t == "stadium" and i is None:
            i = "outdoor"
        if not t and pd.notna(qid) and pd.notna(cap):
            t, i, how = (("stadium", "outdoor") if cap >= 30000 else ("arena", "indoor") if cap >= 5000
                         else ("theatre", "indoor")), None, "capacity_rule"
            t, i = t
        vt.append(t); io.append(i); src.append(how)
    out["venue_type"], out["indoor_outdoor"], out["venue_type_source"] = vt, io, src

    chains = {q: _place_chain(W.first(W.entity(q, cache_only=True), "P131"))
              for q in out["venue_qid"].dropna().unique()}
    city_qid = out["city_qid"] if "city_qid" in out else pd.Series(pd.NA, index=out.index)

    def matches(city, cq, qid):
        if pd.isna(qid) or qid not in chains:
            return pd.NA
        cqids, labs = chains[qid]
        if isinstance(cq, str) and cq in cqids:
            return True
        c = _norm(city)
        if c and any(c == x or (len(c) > 4 and (c in x or x in c)) for x in map(_norm, labs) if x):
            return True
        # A chain that stops at county/state level can't contradict the spine city.
        return pd.NA if not isinstance(cq, str) or len(cqids) <= 2 else False
    out["city_matches_wikidata"] = pd.array(
        [matches(c, cq, q) for c, cq, q in zip(out["city"], city_qid, out["venue_qid"])], dtype="boolean")
    # Distinct spine cities per venue QID (informational).
    key = city_qid.where(city_qid.notna(), "name:" + out["city"].map(_norm))
    ncity = key[out["venue_qid"].notna()].groupby(out["venue_qid"]).nunique()
    out["qid_n_spine_cities"] = out["venue_qid"].map(ncity).astype("Int64")
    # Geographic check: venue P625 vs the spine city's P625 (city item from city_wikilink).
    def km_city(cq, lat, lon):
        if not isinstance(cq, str) or pd.isna(lat):
            return None
        cc = W.first(W.entity(cq, cache_only=True), "P625")
        return round(_km((lat, lon), cc), 1) if cc else None
    out["km_city_to_venue"] = pd.to_numeric(pd.Series(
        [km_city(cq, la, lo) for cq, la, lo in zip(city_qid, out["lat"], out["lon"])], index=out.index))
    far = (out["km_city_to_venue"] > 50) | (out["km_to_locality"] > 50)
    out["link_ambiguous"] = far.astype("boolean").where(out["venue_qid"].notna())
    return out


def _write(venues: pd.DataFrame, rows: list[dict]) -> pd.DataFrame:
    """Write the table (partial runs leave unprocessed venues with null features)."""
    out = venues.merge(pd.DataFrame(rows), on="venue_id", how="left")
    out = postprocess(out)
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
