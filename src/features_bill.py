"""Build features_bill.parquet (one row per show_id).

Bill size and openers come from the spine's opening_acts_raw / opening_acts_wikilinks
(enwiki tour tables, CC BY-SA 4.0). Opener popularity = Wikimedia pageviews (CC0)
of linked opener articles, windows ending the day before the show. Farewell/reunion
flags come from tour-title keywords and from the tour article's enwiki categories
(e.g. "Farewell concert tours"), keeping the matched keyword/category for audit.
"""
from __future__ import annotations

import os
import re

import numpy as np
import pandas as pd

import features_wikidata as W
from features_artist import _is_music_entity, split_links
from features_common import OUT
from features_pageviews import fetch_daily, hype_features, is_cached
from features_spine import load_spine
from features_tours import tour_memberships
from features_wikilinks import Resolver

# Staging flags (see features_bill.md): Wikidata steps can be deferred while the venue
# job has priority on the Wikidata lock; pageviews can be read from cache only.
USE_WIKIDATA = os.environ.get("FEATURES_BILL_WIKIDATA", "1") != "0"
FETCH_PV = os.environ.get("FEATURES_BILL_PV_FETCH", "1") != "0"

FAREWELL = re.compile(r"farewell|final tour|final world tour|the final|last tour|goodbye|end of the road|"
                      r"retirement|one last|last time around|so long", re.I)
REUNION = re.compile(r"reunion|reunited|back together|reunite", re.I)
FESTIVAL = re.compile(r"festival|\bfest\b|fest$", re.I)
NO_OPENER = {"—", "–", "-", "", "none", "n/a"}
JUNK = re.compile(r"rowspan|colspan|style=|^tba$|^tbc$|^tbd$", re.I)


def _raw_acts(raw) -> list[str] | None:
    """Split opening_acts_raw. None = unknown (null or markup junk); [] = explicit dash/none."""
    if raw is None or (isinstance(raw, float) and pd.isna(raw)) or raw is pd.NA:
        return None
    s = str(raw).strip()
    if JUNK.search(s):
        return None
    if s.lower() in NO_OPENER:
        return []
    # Not split on "and"/"&": band names contain them (spine already joins acts with " | ").
    parts = re.split(r"\s*(?:\||<br\s*/?>|,|;)\s*", s)
    return [p for p in parts if p and p.lower() not in NO_OPENER]


ALBUM_CLASSES = {"Q482994", "Q208569", "Q169930", "Q209939", "Q222910", "Q1242743"}  # album, studio, EP, live, compilation, mixtape


def resolve_album(res: Resolver, album: str, artist_titles: list[str], artist_qids: set[str]) -> str | None:
    """Enwiki title of the tour's album, verified on Wikidata: an album-type item
    whose performer (P175) is one of the headliners. Unverified guesses are dropped."""
    names = [a.strip() for a in re.split(r"\s*\|\s*", album or "") if a.strip()]
    for name in names:
        if name.lower() in {"various", "none", "n/a"}:
            continue
        cands = [f"{name} ({re.sub(r'_\(.*\)$', '', t).replace('_', ' ')} album)" for t in artist_titles]
        cands += [f"{name} (album)", name]
        for c in cands:
            title, q = res.resolve(c)
            if not q:
                continue
            ent = W.entity(q)
            if ALBUM_CLASSES.intersection(W.values(ent, "P31")) and artist_qids.intersection(W.values(ent, "P175")):
                return title
    return None


def build() -> pd.DataFrame:
    spine = load_spine()
    raw = pd.read_parquet(__import__("features_spine").spine_path())
    extra = raw[["show_id"] + [c for c in ("opening_acts_wikilinks", "tour_page_id", "table_caption", "tour_infobox_album")
                               if c in raw.columns]]
    spine = spine.merge(extra, on="show_id", how="left")
    res = Resolver()

    venue_type = {}
    vpath = OUT / "features_venue.parquet"
    if vpath.exists():
        v = pd.read_parquet(vpath)
        venue_type = dict(zip(v["venue_id"], v["venue_type"]))

    # Tour article categories mentioning farewell/reunion.
    mem = tour_memberships()
    mem = mem[mem["category"].str.contains("arewell|eunion", regex=True)]
    tour_cats = mem.groupby("page_id")["category"].apply(lambda s: "; ".join(sorted(s))).to_dict()

    series: dict[str, pd.Series | None] = {}
    album_cache: dict = {}
    rows = []
    for s in spine.itertuples(index=False):
        headliners = split_links(s.artist_wikilink) or [s.artist_name]
        links = split_links(getattr(s, "opening_acts_wikilinks", None))
        raw_acts = _raw_acts(s.opening_acts_raw)
        if raw_acts is None and not links:
            n_open, open_src = pd.NA, None
        else:
            # Raw text sometimes loses separators, so never count fewer acts than links.
            n_open = max(len(links), len(raw_acts or []))
            open_src = "links_and_raw" if links else "raw_text"
        n_head = len(headliners)

        # Opener popularity: linked openers, plus unlinked names whose exact enwiki
        # title resolves to a music-related Wikidata item (has MBID/genre/instrument).
        pvs, n_name_matched = [], 0
        linked_titles = {res.resolve(l)[0] for l in links}
        cands = [(l, "link") for l in links]
        if USE_WIKIDATA:
            cands += [(a, "name") for a in (raw_acts or []) if res.resolve(a)[0] not in linked_titles]
        pv_pending = False
        for l, how in cands:
            title, q = res.resolve(l)
            if not title:
                continue
            if how == "name":
                if not (q and _is_music_entity(W.entity(q))):
                    continue
                n_name_matched += 1
            if title not in series:
                if not FETCH_PV and not is_cached(title):
                    pv_pending = True
                    continue
                series[title] = fetch_daily(title)
            pvs.append(hype_features(series[title], s.show_date, prefix="o")["o_mean_90d"]
                       if s.show_date else np.nan)
        pvs_ok = [x for x in pvs if pd.notna(x)]

        # Set-list proxy: attention to the album being toured (setlist.fm needs permission).
        album_key = (getattr(s, "tour_infobox_album", None), s.artist_wikilink)
        if not USE_WIKIDATA:
            album_cache.setdefault(album_key, None)
        elif album_key not in album_cache:
            resolved_h = [res.resolve(h) for h in headliners]
            album_cache[album_key] = resolve_album(
                res, album_key[0] if isinstance(album_key[0], str) else "",
                [t for t, _ in resolved_h if t], {q for _, q in resolved_h if q})
        album_title = album_cache[album_key]
        if album_title and album_title not in series:
            if not FETCH_PV and not is_cached(album_title):
                album_title = None
            else:
                series[album_title] = fetch_daily(album_title)
        album_hype = hype_features(series.get(album_title), s.show_date, prefix="album") \
            if album_title and s.show_date else {}

        tour = str(s.tour_title or "")
        fw = FAREWELL.search(tour)
        ru = REUNION.search(tour)
        cats = tour_cats.get(getattr(s, "tour_page_id", None), "")
        fw_cat = "; ".join(c for c in cats.split("; ") if "arewell" in c) if cats else ""
        ru_cat = "; ".join(c for c in cats.split("; ") if "eunion" in c) if cats else ""

        vt = venue_type.get(s.venue_id)
        fest_reason = None
        if FESTIVAL.search(tour) or FESTIVAL.search(str(getattr(s, "table_caption", "") or "")):
            fest_reason = "title_keyword"
        elif FESTIVAL.search(str(s.venue_name or "")):
            fest_reason = "venue_name_keyword"
        elif vt == "festival ground":
            fest_reason = "venue_type"
        elif pd.notna(n_open) and n_head + n_open >= 5:
            fest_reason = "bill_size>=5"

        rows.append({
            "show_id": s.show_id,
            "n_headliners": n_head,
            "co_headliner_flag": n_head > 1,
            "n_openers": n_open,
            "openers_source": open_src,
            "n_acts_on_bill": (n_head + n_open) if pd.notna(n_open) else pd.NA,
            "multi_artist_flag": True if n_head > 1 else (pd.NA if pd.isna(n_open) else n_open > 0),
            "opener_names": " | ".join(links) if links else (" | ".join(raw_acts) if raw_acts else None),
            "n_openers_linked": len(links),
            "n_openers_name_matched": n_name_matched if USE_WIKIDATA else pd.NA,
            "n_openers_with_pv": len(pvs_ok),
            "opener_pv_mean_90d_max": max(pvs_ok) if pvs_ok else np.nan,
            "opener_pv_mean_90d_sum": sum(pvs_ok) if pvs_ok else np.nan,
            "tour_album_title": album_title,
            "album_pv_mean_90d": album_hype.get("album_mean_90d", np.nan),
            "album_pv_momentum": album_hype.get("album_momentum", np.nan),
            "opener_pv_status": "pending" if pv_pending else "done",
            "wikidata_status": "done" if USE_WIKIDATA else "pending",
            "festival_flag": fest_reason is not None,
            "festival_reason": fest_reason,
            "farewell_flag": bool(fw or fw_cat),
            "farewell_match": (fw.group(0) if fw else None) or (fw_cat or None),
            "reunion_flag": bool(ru or ru_cat),
            "reunion_match": (ru.group(0) if ru else None) or (ru_cat or None),
        })
    out = pd.DataFrame(rows)
    for c in ("n_openers", "n_acts_on_bill", "n_openers_name_matched"):
        out[c] = out[c].astype("Int32")
    out["multi_artist_flag"] = out["multi_artist_flag"].astype("boolean")
    out.to_parquet(OUT / "features_bill.parquet", index=False)
    return out


if __name__ == "__main__":
    df = build()
    print(df.notna().mean().round(3).to_string())
    print(df[["farewell_flag", "reunion_flag", "festival_flag", "multi_artist_flag"]].mean().to_string())
