# features_bill.parquet

One row per `show_id`. Built by `src/features_bill.py` (rerunnable from cache: `.venv/bin/python src/features_bill.py`; run after `features_venue.py`, whose `venue_type` it reads).

**Build stages (2026-10-19):** the Wikidata lock goes to venues first (they gate LEVEL), so this table is published in stages; rows say which via `wikidata_status` / `opener_pv_status`. (1) No Wikidata, pageviews from cache only. (2) Linked-opener pageviews fetched (wikimedia.org). (3) Full build with opener name matching and album verification, after the venue priced milestone (`src/features_chain.py`). Bill size, co-headliner, festival, farewell and reunion columns are final from stage 1 on.

**Sources:** the spine's `opening_acts_raw` / `opening_acts_wikilinks` / `artist_wikilink` / `tour_title` / `tour_page_id` / `tour_infobox_album` (enwiki tour tables, CC BY-SA 4.0); enwiki 20261001 category membership of the tour article (dumps, CC BY-SA 4.0); Wikidata EntityData (CC0) to verify opener and album items; Wikimedia pageviews REST API (CC0) for opener and album attention. Every pageview window ends the **day before** the show.

| column | type | unit / values | definition | null meaning |
|---|---|---|---|---|
| show_id | string | | spine key | never null |
| n_headliners | int | count | links in `artist_wikilink` (split on " \| "), else 1 | never null |
| co_headliner_flag | bool | | n_headliners > 1 | never null |
| n_openers | Int32 | count | max(#opener wikilinks, #names in `opening_acts_raw`) | opener cell empty, missing or unparseable (unknown, **not** zero). An explicit "—" in the source becomes 0 only if collector-prices keeps it; currently it drops "—"/"TBA", so these appear as unknown |
| openers_source | string | `links_and_raw` or `raw_text` | | n_openers null |
| n_acts_on_bill | Int32 | count | n_headliners + n_openers | n_openers null |
| multi_artist_flag | boolean | | True if co-headlined or n_openers > 0 | single headliner and openers unknown |
| opener_names | string | " \| "-joined link targets (or raw names if none linked) | | no openers |
| n_openers_linked | int | count | openers with a wikilink | never null |
| n_openers_name_matched | int | count | unlinked opener names whose exact enwiki title resolves to a music-related Wikidata item (has MBID, genre or instrument) | never null |
| n_openers_with_pv | int | count | openers with a usable 90-day pageview window | never null |
| opener_pv_mean_90d_max | float | views/day | max over openers of mean daily views, days −90…−1 | no opener with pageview data in the window |
| opener_pv_mean_90d_sum | float | views/day | sum over openers of the same | as above |
| tour_album_title | string | enwiki title | the tour's album (`tour_infobox_album`), accepted only if the Wikidata item is an album type **and** its performer (P175) is a headliner. Tries `<Album> (<Artist> album)`, `<Album> (album)`, `<Album>` | no album in the infobox, "Various", or not verifiable |
| album_pv_mean_90d | float | views/day | mean daily views of the album article, days −90…−1 | no verified album, or window outside 2015-07-01…2026-10-17 / before the article existed |
| album_pv_momentum | float | log ratio | log((days −30…−1 mean + 1)/(days −90…−61 mean + 1)) for the album article | as above |
| opener_pv_status | string | `done` / `pending` | `pending` = at least one linked opener's pageviews weren't fetched yet in this build, so `opener_pv_*` and `n_openers_with_pv` are incomplete (a lower bound) | never null |
| wikidata_status | string | `done` / `pending` | `pending` = the Wikidata-dependent fields weren't computed in this build: `n_openers_name_matched` (null), `tour_album_title`, `album_pv_mean_90d`, `album_pv_momentum` (all null), and opener pageviews cover **linked** openers only | never null |
| festival_flag | bool | | any of the `festival_reason` rules | never null |
| festival_reason | string | `title_keyword` (tour title or table caption contains "festival"/"fest"), `venue_name_keyword`, `venue_type` (venue is a festival ground), `bill_size>=5` | first rule that fired | not a festival |
| farewell_flag | bool | | tour title matches `FAREWELL` (farewell, final tour, the final, last tour, goodbye, end of the road, retirement, one last, …) **or** the tour article is in `Category:Farewell concert tours` | never null |
| farewell_match | string | the matched keyword, else the category name (audit) | | not farewell |
| reunion_flag | bool | | tour title matches reunion/reunited/back together **or** the tour article is in `Category:Reunion concert tours` | never null |
| reunion_match | string | matched keyword or category (audit) | | not reunion |

## Gaps, substitutes and caveats
- **Set-list popularity: gap.** setlist.fm is NEEDS PERMISSION (its terms forbid retaining data), so per-show set lists and song popularity aren't collected. **Proxy used:** `album_pv_*`, attention to the album being toured (from `tour_infobox_album`, verified on Wikidata). Another allowed proxy, not built: ListenBrainz per-artist top recordings (CC0), but only as a current snapshot, not point-in-time.
- **Opener counts depend on table formatting.** Some tour tables list openers only once per leg or leave the cell blank, so `n_openers` null is common and means unknown. Openers are counted only from the opening-act column; guest appearances in notes aren't counted.
- **Farewell/reunion are tour-level labels.** Category membership reflects today's article, and a tour can be categorized "farewell" in hindsight. Titles without keywords (e.g. "Oasis Live '25 Tour") rely entirely on the category. `Co-headlining_concert_tours` and `All-stadium_concert_tours` categories exist too and could become flags later.
- **Festival flag is heuristic.** The spine comes from tour articles, so festival appearances show up as single dates on a tour, usually with the festival named in the venue or notes. The `bill_size>=5` rule can fire for package tours.
