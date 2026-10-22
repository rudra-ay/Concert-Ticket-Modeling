# features_venue.parquet

One row per `venue_id` in `shows_base.parquet`. Built by `src/features_venue.py` (rerunnable from cache: `.venv/bin/python src/features_venue.py`).

**Route:** spine `venue_wikilink` (filled across all rows of the same `venue_id`) → enwiki 20261001 dumps (multistream index + `redirect.sql.gz` + `page_props.sql.gz`, see `src/features_wikilinks.py`) → Wikidata QID → `Special:EntityData/<QID>.json` (cached in `data/raw/wikidata/`). No SPARQL, no api.php. Venues with no wikilink anywhere in the spine use a guarded name match: the venue display name must be an exact enwiki title (after redirects) whose item classifies as a venue type or has a capacity claim (`venue_link_source = name_match`).

**Licenses:** Wikidata values are CC0 1.0. Title resolution uses Wikipedia dump metadata (CC BY-SA 4.0); attribute Wikipedia if titles are redistributed.

**Status (final, 2026-10-20):** every venue of a priced show (4,400 of 13,048) was fully processed with network access. For the 8,648 remaining venues the user chose to skip uncached fetches: the table was finished by `src/venue_lean.py --cache-only`, so a remainder venue has values only where its items were already cached (3,377 of 8,648 have a QID). Null on a remainder venue means "not fetched", not "no match".

| column | type | unit / values | source | null meaning |
|---|---|---|---|---|
| venue_id | string | `<venue_slug>__<city_slug>` | spine | never null |
| venue_name, city, country | string | display text from the spine (first row) | spine | not in spine |
| venue_wikilink | string | link target as written in the tour table, most common across the venue's rows | spine | the venue is never linked in the spine |
| city_wikilink | string | the spine's city link target (most common for the venue) | spine | city never linked |
| city_qid | string | Wikidata item of the spine city (via dumps) | dumps | city unlinked/unresolved |
| n_priced_shows | int | rows with `avg_price_usd` | spine | never null |
| n_shows | int | rows in shows_base for this venue | spine | never null |
| n_priced_shows | int | rows with `avg_price_usd` | spine | never null |
| venue_enwiki_title | string | canonical enwiki title after redirects | dumps | unresolved |
| venue_link_source | string | `spine_wikilink` or `name_match` | | unresolved (or not yet processed in a partial file) |
| venue_qid | string | Wikidata item | dumps | no item / unresolved |
| venue_label | string | Wikidata English label | Wikidata | no item |
| p31_classes | string | `QID:label; …` of P31 (instance of), for audit | Wikidata | no item |
| venue_type | string | stadium, arena, amphitheatre, theatre, club, festival ground | P31 class labels (one level of P279 superclasses if the direct class is unmapped), first matching rule in `TYPE_RULES` | class not mappable (e.g. "building", "sports venue") |
| indoor_outdoor | string | `indoor`, `outdoor`, `retractable` | derived from the class: dome/indoor/covered stadium → indoor, retractable-roof stadium → retractable, other stadiums/amphitheatres/festival grounds → outdoor, arenas/theatres/clubs → indoor | venue_type null |
| venue_type_source | string | `wikidata_class` (P31 label rules), `name_keyword` (venue name contains arena/stadium/amphitheatre/theatre/club/… when the class is generic like "sports venue" or "event venue"), `capacity_rule` (generic class and no name keyword: ≥ 30,000 stadium, ≥ 5,000 arena, else theatre) | | venue_type null |
| type_matched_label | string | the class label that decided the type (audit) | | venue_type null |
| lat, lon | float | WGS84 decimal degrees | P625 | no coordinates on the item |
| coord_source | string | `wikidata` | | no coordinates |
| wd_city | string | label of the first P131 (located in) | Wikidata | no P131 |
| wd_locality_qid, wd_locality | string | first **populated place** walking P131 up from the venue (the P31 class's head noun is city / town / village / municipality / urban agglomeration, …; boroughs, counties, districts and states are skipped, so MSG → New York City and The O2 → Greater London). Compare this with the spine city, not `wd_city` (which is often a borough or county, e.g. MSG → Manhattan) | Wikidata | no populated place within 6 P131 levels |
| km_to_locality | float | km | great-circle distance from the venue's P625 to the locality's P625. Large values (> ~50 km) mean the item's coordinates and location disagree (e.g. Hard Rock Live: P131 Hollywood FL, P625 Orlando) | missing coords on either item |
| country_iso2 | string | ISO 3166-1 alpha-2 | P17 → P297, else walk P131 up to 4 levels | no country found |
| us_state | string | ISO 3166-2, e.g. `US-NY` | walk P131 (≤ 6 levels) to an item that is a U.S. state (Q35657), then its P300. **Filled independently of lat/lon.** | non-US venue, or the chain does not reach a state. Washington, D.C. (Q61) is mapped to `US-DC` explicitly |
| qid_n_spine_cities | Int64 | distinct spine cities (city QIDs, else normalized names) whose venues resolve to this QID (informational) | derived | venue unresolved |
| city_matches_wikidata | boolean | spine city (QID or name) appears on the venue item's P131 chain | derived, cache only | chain stops at county/state level, or city unknown |
| km_city_to_venue | float | km | venue P625 to the spine city item's P625 | no city QID or missing coordinates |
| link_ambiguous | boolean | **coordinates disagree with the place**: `km_city_to_venue > 50` or `km_to_locality > 50`. Catches chain/generic links (e.g. `[[Hard Rock Live]]` for Orlando shows) and self-contradictory items. **Don't trust lat/lon/us_state on these rows; use the spine city.** 53 priced shows | derived | venue unresolved |
| opening_year | Int64 | year | P1619 (date of official opening), else P571 (inception) | missing on item |
| capacity | Int64 | seats | P1083. Preference: the **concert** configuration (P518 = Q182832 concert, latest P585 year, then largest); else a preferred-rank value; else the latest unqualified value; else the max over configurations | no P1083 |
| capacity_config | string | which rule picked `capacity`: `concert`, `preferred_rank`, `unqualified`, `max_of_configs` | | no P1083 |
| capacity_max | Int64 | largest P1083 value over all configurations | | no P1083 |
| capacity_n_configs | Int64 | number of distinct capacity values | | 0 = no P1083 |
| capacity_all | string | every value with its P518 configuration and P585 year (audit) | | no P1083 |

## Quality notes
- **Wikidata items can contradict themselves.** Example: Q5655372 "Hard Rock Live" has P131 = Hollywood (FL) but P625 coordinates in Orlando. The tour table linked this chain-level article for a Hollywood, FL show; collector-context caught it. `link_ambiguous` flags the shared-QID case, but a self-contradictory item linked from a single city isn't detectable here. Cross-check coordinates against the spine city (collector-context's metro step does this).
- **Capacity is configuration-dependent and current.** Wikidata typically holds the sports configuration (e.g. Madison Square Garden: 18,006 ice hockey / 19,812 basketball / 20,000 concert / 20,789 boxing). Only some venues have a concert-qualified value; `capacity_config` says which rule applied. Values are today's capacity, not the capacity on the show date (renovations are not time-matched). Prefer the spine's `tickets_available` for per-show capacity when it exists.
- **Indoor/outdoor is inferred from the class**, not from a roof property: Wikidata has no consistently used roof property. Stadiums default to outdoor unless the class says dome/indoor/covered/retractable, so a domed stadium typed only as "stadium" is misclassified as outdoor. Check `type_matched_label` and `p31_classes`.
- Name-matched venues can be wrong when a display name equals another venue's title (e.g. a renamed arena whose old name now redirects to a successor). The guard requires a venue-like item, but not the right city; compare `wd_city` with `city`.

## Lean fill of the non-priced venues (2026-10-20)

Venues beyond the priced milestone (those with no priced show) were filled by `src/venue_lean.py --cache-only` from items already cached, with no new requests (user decision: the ~1,900 uncached venue items cover only unpriced shows, which the LEVEL analysis does not use). Class (P31/P279), locality and state (P131) items are also read from the cache only. Remainder venues whose item was never cached have `venue_qid` empty. Priced venues are unchanged. For a non-priced venue whose class, city or state item was never cached, `venue_type`, `indoor_outdoor`, `wd_locality*` or `us_state` can be empty, even though the full run would have filled them.
