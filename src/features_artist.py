"""Build features_artist.parquet (by artist_id) and features_artist_show.parquet (by show_id).

Sources: enwiki dumps (title -> QID, tour categories), Wikidata EntityData (CC0),
MusicBrainz dumps (core CC0; genre tags CC BY-NC-SA 3.0, kept in mb_genre_* columns),
ListenBrainz popularity (CC0, current snapshot), Wikimedia pageviews (CC0).

Co-headlined shows: artist_wikilink holds several links separated by " | ".
Static artist fields describe the first-listed (primary) artist; pageview hype
uses the sum of all headliners' daily views.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import date

import pandas as pd

import features_wikidata as W
from features_common import OUT, RAW, get_json_cached
from features_musicbrainz import artists as mb_artists
from features_musicbrainz import genre_tags as mb_genre_tags
from features_pageviews import fetch_daily, hype_features
from features_spine import load_spine
from features_tours import TourIndex
from features_wikilinks import Resolver

LB_URL = "https://api.listenbrainz.org/1/popularity/artist"
LB_CACHE = RAW / "listenbrainz"
LB_SNAPSHOT = "2026-10-18"

HUMAN = "Q5"
# Coarse genre rules, checked in this order against each genre label (first match wins).
COARSE_RULES = [
    ("K-pop", r"k-pop|kpop|korean"),
    ("Latin", r"latin|reggaet|salsa|bachata|merengue|cumbia|banda|corrido|ranchera|mariachi|norte[nñ]o|"
              r"regional mexican|tejano|urbano|dembow|vallenato|bossa|samba|sertanejo|flamenco"),
    ("hip-hop/rap", r"hip.?hop|\brap\b|rapper|trap|drill|grime|gangsta"),
    ("country", r"country|americana|bluegrass|honky|outlaw"),
    ("metal", r"metal|metalcore|deathcore|thrash|grindcore"),
    ("EDM/electronic", r"electronic|electro|\bedm\b|house|techno|trance|dubstep|drum and bass|"
                       r"big room|future bass|dance music|eurodance|hardstyle|synthwave"),
    ("R&B", r"r&b|r'n'b|rhythm and blues|soul|funk|new jack|quiet storm"),
    ("indie/alt", r"indie|alternative|grunge|emo|shoegaze|post-punk|post-rock|lo-fi|bedroom|britpop"),
    ("rock", r"rock|punk|blues"),
    ("pop", r"pop|teen|boy band|girl group|adult contemporary"),
]


def coarse_genre(label: str | None) -> str | None:
    if not label:
        return None
    for name, pat in COARSE_RULES:
        if re.search(pat, label, re.I):
            return name
    return "other"


def pick_coarse(labels: list[str]) -> str | None:
    """Weighted vote: earlier-listed genres count more (Wikidata/MB order ~ salience)."""
    votes: dict[str, float] = {}
    for i, lab in enumerate(labels):
        c = coarse_genre(lab)
        if c:
            votes[c] = votes.get(c, 0) + 1.0 / (1 + i)
    if not votes:
        return None
    order = [n for n, _ in COARSE_RULES] + ["other"]
    return max(votes, key=lambda c: (votes[c], -order.index(c)))


def split_links(v) -> list[str]:
    if v is None or (isinstance(v, float) and pd.isna(v)) or v is pd.NA:
        return []
    return [p.strip() for p in str(v).split("|") if p.strip()]


def listenbrainz(mbids: list[str]) -> dict[str, dict]:
    """Per-MBID popularity; only MBIDs not yet cached are POSTed (batches of 100, >= 5 s apart)."""
    per = LB_CACHE / "mbid"
    todo = [m for m in dict.fromkeys(mbids) if m and not (per / f"{m}.json").exists()]
    for i in range(0, len(todo), 100):
        batch = sorted(todo[i:i + 100])
        key = hashlib.sha1("".join(batch).encode()).hexdigest()[:16]
        data = get_json_cached(LB_URL, LB_CACHE / f"popularity_{key}.json", method="POST",
                               body={"artist_mbids": batch}) or []
        got = {d.get("artist_mbid"): d for d in data}
        per.mkdir(parents=True, exist_ok=True)
        for m in batch:  # store misses too, so they are not re-requested
            (per / f"{m}.json").write_text(json.dumps(got.get(m, {"artist_mbid": m})))
    return {m: json.loads((per / f"{m}.json").read_text()) for m in mbids if m and (per / f"{m}.json").exists()}


def _is_music_entity(ent) -> bool:
    return bool(W.values(ent, "P434") or W.values(ent, "P136") or W.values(ent, "P1303"))


def artist_static(title: str | None, qid: str | None, mb: pd.DataFrame, mb_by_name: dict, tours: TourIndex,
                  fallback_name: str | None) -> dict:
    ent = W.entity(qid) if qid else None
    mbid = W.first(ent, "P434")
    mbid_source = "wikidata_P434" if mbid else None
    mbrow = mb.loc[mbid] if mbid and mbid in mb.index else None
    if mbrow is None and fallback_name:
        cands = mb_by_name.get(fallback_name.casefold(), [])
        if len(cands) == 1:  # unique exact name only; ambiguous names stay unlinked
            mbid, mbid_source = cands[0], "mb_unique_name"
            mbrow = mb.loc[mbid]
    p31 = W.values(ent, "P31")
    if ent:
        a_type = "solo" if HUMAN in p31 else "group"
        type_source = "wikidata_P31"
    elif mbrow is not None and pd.notna(mbrow["mb_type"]):
        a_type = {"Person": "solo", "Character": "solo"}.get(mbrow["mb_type"], "group")
        type_source = "musicbrainz_type"
    else:
        a_type, type_source = None, None
    # Career start: work period start (P2031), else inception for groups (P571),
    # else MB begin year for non-persons (MB person begin = birth, not career).
    start = W.year_of(W.first(ent, "P2031"))
    start_src = "wikidata_P2031" if start else None
    if start is None and a_type == "group":
        start = W.year_of(W.first(ent, "P571"))
        start_src = "wikidata_P571" if start else None
    if start is None and mbrow is not None and mbrow["mb_type"] not in ("Person", None) and pd.notna(mbrow["begin_year"]):
        start, start_src = int(mbrow["begin_year"]), "musicbrainz_begin"
    country_q = (W.values(ent, "P495") or W.values(ent, "P27") or [None])[0]
    country = W.country_iso2(country_q)
    country_src = "wikidata" if country else None
    if not country and mbrow is not None and pd.notna(mbrow["country_iso2"]):
        country, country_src = mbrow["country_iso2"], "musicbrainz_area"
    genre_q = W.values(ent, "P136")
    genres = [W.label(g) for g in genre_q]
    genres = [g for g in genres if g]
    cat, tour_pages = tours.tours(title)
    return {
        "artist_enwiki_title": title,
        "artist_qid": qid if ent else None,
        "mbid": mbid,
        "mbid_source": mbid_source,
        "artist_type": a_type,
        "artist_type_source": type_source,
        "country_iso2": country,
        "country_source": country_src,
        "genres_wikidata": "; ".join(genres) or None,
        "genre_coarse": pick_coarse(genres),
        "career_start_year": start,
        "career_start_source": start_src,
        "tour_category": cat,
        "n_tour_articles": len(tour_pages) if title else None,
        "_tour_years": [tours.start_year.get(p) for p in tour_pages],
        "_mb_artist_id": None if mbrow is None else mbrow["mb_artist_id"],
    }


def build() -> tuple[pd.DataFrame, pd.DataFrame]:
    spine = load_spine()
    res = Resolver()
    tours = TourIndex(res.id_to_title)
    mb = mb_artists().set_index("mbid", drop=False)
    mb_by_name = mb.groupby(mb["mb_name"].str.casefold())["mbid"].apply(list).to_dict()
    tags = mb_genre_tags()

    arts = (spine.groupby("artist_id", as_index=False)
            .agg(artist_name=("artist_name", "first"),
                 artist_wikilink=("artist_wikilink", lambda s: s.dropna().mode().iat[0] if s.notna().any() else None),
                 n_shows=("show_id", "size")))
    rows, headliner_titles = [], {}
    for i, a in enumerate(arts.itertuples(index=False)):
        links = split_links(a.artist_wikilink)
        resolved = [res.resolve(l) for l in links]
        link_src = "spine_wikilink"
        if not links:  # name fallback, accepted only if the item is music-related
            t, q = res.resolve(a.artist_name)
            resolved = [(t, q)] if q and _is_music_entity(W.entity(q)) else []
            link_src = "name_match" if resolved else None
        headliner_titles[a.artist_id] = [t for t, _ in resolved if t]
        title, qid = resolved[0] if resolved else (None, None)
        row = {"artist_id": a.artist_id, "artist_name": a.artist_name, "n_shows_in_spine": a.n_shows,
               "n_headliners": max(len(links), 1), "artist_link_source": link_src,
               **artist_static(title, qid, mb, mb_by_name, tours,
                               a.artist_name if len(links) <= 1 else None)}
        rows.append(row)
        if i % 25 == 0:
            print(f"artist {i}/{len(arts)}", flush=True)
    art = pd.DataFrame(rows)

    # MusicBrainz genre tags (CC BY-NC-SA 3.0): kept separate from the CC0 columns.
    top = tags[tags["mb_artist_id"].isin(art["_mb_artist_id"].dropna())].groupby("mb_artist_id")["genre"] \
        .apply(lambda s: list(s)[:5])
    art["mb_genre_tags"] = art["_mb_artist_id"].map(lambda x: "; ".join(top.get(x, [])) or None)
    art["mb_genre_coarse"] = art["_mb_artist_id"].map(lambda x: pick_coarse(top.get(x, [])))
    art["genre_coarse_final"] = art["genre_coarse"].fillna(art["mb_genre_coarse"])
    art["genre_coarse_source"] = art["genre_coarse"].notna().map({True: "wikidata"}).where(
        art["genre_coarse"].notna(), art["mb_genre_coarse"].notna().map({True: "musicbrainz_tags", False: None}))

    lb = listenbrainz(art["mbid"].dropna().tolist())
    art["lb_total_listen_count"] = art["mbid"].map(lambda m: lb.get(m, {}).get("total_listen_count"))
    art["lb_total_user_count"] = art["mbid"].map(lambda m: lb.get(m, {}).get("total_user_count"))
    art["lb_snapshot_date"] = LB_SNAPSHOT

    # Time-varying part, keyed by show_id.
    tour_years = dict(zip(art["artist_id"], art["_tour_years"]))
    start_year = dict(zip(art["artist_id"], art["career_start_year"]))
    has_title = dict(zip(art["artist_id"], art["artist_enwiki_title"].notna()))
    series = {}
    show_rows = []
    for s in spine.dropna(subset=["show_date"]).itertuples(index=False):
        d: date = s.show_date
        sy = start_year.get(s.artist_id)
        yrs = [y for y in tour_years.get(s.artist_id) or [] if y]
        titles = headliner_titles.get(s.artist_id, [])
        for t in titles:
            if t not in series:
                series[t] = fetch_daily(t)
        parts = [series[t] for t in titles if series.get(t) is not None]
        summed = pd.concat(parts, axis=1).sum(axis=1, min_count=len(parts)) if parts else None
        if summed is not None and len(parts) < len(titles):
            summed = None  # a headliner without pageview data: don't report a partial sum
        show_rows.append({
            "show_id": s.show_id, "artist_id": s.artist_id,
            "years_active_at_show": (d.year - int(sy)) if pd.notna(sy) else None,
            "n_tours_started_before_show_year": sum(y < d.year for y in yrs) if has_title.get(s.artist_id) else None,
            "n_tours_started_by_show_year": sum(y <= d.year for y in yrs) if has_title.get(s.artist_id) else None,
            **hype_features(summed, d, prefix="pv"),
        })
    shows = pd.DataFrame(show_rows)
    for c in ("years_active_at_show", "n_tours_started_before_show_year", "n_tours_started_by_show_year"):
        shows[c] = shows[c].astype("Int32")
    shows["pv_spike_flag"] = shows["pv_spike_flag"].astype("boolean")

    art = art.drop(columns=["_tour_years", "_mb_artist_id"])
    for c in ("career_start_year", "n_tour_articles", "lb_total_listen_count", "lb_total_user_count"):
        art[c] = pd.to_numeric(art[c], errors="coerce").astype("Int64")
    art.to_parquet(OUT / "features_artist.parquet", index=False)
    shows.to_parquet(OUT / "features_artist_show.parquet", index=False)
    return art, shows


if __name__ == "__main__":
    a, s = build()
    print(a.notna().mean().round(3).to_string())
    print(s.notna().mean().round(3).to_string())
