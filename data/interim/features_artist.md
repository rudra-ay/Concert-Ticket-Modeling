# features_artist.parquet and features_artist_show.parquet

Built by `src/features_artist.py` (rerunnable from cache: `.venv/bin/python src/features_artist.py`). Two tables:
- `features_artist.parquet`: one row per `artist_id` (static or current-snapshot attributes).
- `features_artist_show.parquet`: one row per `show_id` (time-varying: years active, prior tours, pageview hype).

**Route:** spine `artist_wikilink` → enwiki 20261001 dumps (title → redirects → QID) → Wikidata `Special:EntityData/<QID>.json`. MBID from Wikidata P434 → MusicBrainz fullexport 20261017 dump. Tour counts from enwiki category membership (`categorylinks` + `linktarget` dumps). ListenBrainz popularity via `POST api.listenbrainz.org/1/popularity/artist`. Pageviews via the Wikimedia REST per-article endpoint (`agent=user`). No SPARQL, no api.php, no MusicBrainz /ws/2.

**Co-headlined shows** (e.g. `Chris Brown | Usher (musician)`): the artist_id is the joint act. Static fields describe the **first-listed** artist; `n_headliners` counts the links; pageview hype is the **sum** of all headliners' daily views.

**Licenses:** Wikidata, MusicBrainz core, ListenBrainz and Wikimedia pageviews are CC0. `mb_genre_tags` and `mb_genre_coarse` derive from MusicBrainz **tags** (mbdump-derived), which are **CC BY-NC-SA 3.0**: non-commercial, share-alike, attribute MusicBrainz. Keep them out of any CC0-only release. Category and title data come from Wikipedia (CC BY-SA 4.0).

## features_artist.parquet (by artist_id)

| column | type | unit / values | source | null meaning |
|---|---|---|---|---|
| artist_id | string | artist slug (SHOW_KEY.md) | spine | never null |
| artist_name | string | display name | spine | never null |
| n_shows_in_spine | int | rows in shows_base | spine | never null |
| n_headliners | int | number of linked headliners (≥ 1) | spine `artist_wikilink` | never null |
| artist_link_source | string | `spine_wikilink`, or `name_match` (exact enwiki title of `artist_name`, accepted only if the item has an MBID, genre or instrument) | | no wikilink and no accepted name match (a `spine_wikilink` row can still have a null `artist_qid` when the link target is not in the dump, e.g. a red link) |
| artist_enwiki_title | string | canonical enwiki title (first headliner) | dumps | unresolved |
| artist_qid | string | Wikidata item | dumps | unresolved / no item |
| mbid | string | MusicBrainz artist MBID | Wikidata P434, else a **unique** exact-name match in the MB dump (single-headliner acts only) | none found or ambiguous name |
| mbid_source | string | `wikidata_P434` or `mb_unique_name` | | no MBID |
| artist_type | string | `solo` / `group` | Wikidata P31 (Q5 human → solo, anything else → group), else MB type (Person → solo) | unresolved |
| artist_type_source | string | `wikidata_P31` or `musicbrainz_type` | | unresolved |
| country_iso2 | string | ISO 3166-1 alpha-2 | Wikidata P495 (country of origin), else P27 (citizenship) → P297; else MB area | not found |
| country_source | string | `wikidata` or `musicbrainz_area` | | not found |
| genres_wikidata | string | `; `-joined P136 labels in Wikidata order | Wikidata (CC0) | no P136 |
| genre_coarse | string | pop, rock, hip-hop/rap, country, EDM/electronic, R&B, Latin, K-pop, metal, indie/alt, other | `pick_coarse(genres_wikidata)`: each label maps by the first matching rule in `COARSE_RULES`; labels vote with weight 1/(1+position) | no Wikidata genre |
| mb_genre_tags | string | top 5 MB genre tags by vote count | MB tags (**CC BY-NC-SA 3.0**) | no MBID or no genre tags |
| mb_genre_coarse | string | coarse genre from `mb_genre_tags` | MB tags (**CC BY-NC-SA 3.0**) | as above |
| genre_coarse_final | string | `genre_coarse`, else `mb_genre_coarse` | | neither available |
| genre_coarse_source | string | `wikidata` or `musicbrainz_tags` | | neither available |
| career_start_year | Int64 | year | Wikidata P2031 (work period start); for groups, else P571 (inception); else the MB begin year for non-Person artists. **Never a birth year.** | not found (solo artists without P2031 stay null) |
| career_start_source | string | `wikidata_P2031`, `wikidata_P571`, `musicbrainz_begin` | | not found |
| tour_category | string | matched enwiki category, e.g. `Taylor_Swift_concert_tours` | categorylinks dump | artist has no tour category |
| n_tour_articles | Int64 | tour articles in that category (excluding "List of …" pages and subcategories) | categorylinks dump | artist unresolved (0 = resolved but no category) |
| lb_total_listen_count | Int64 | all-time listens | ListenBrainz | no MBID / not in ListenBrainz |
| lb_total_user_count | Int64 | all-time distinct listeners | ListenBrainz | as above |
| lb_snapshot_date | string | `2026-10-18` | | never null |

## features_artist_show.parquet (by show_id)

| column | type | unit | definition | null meaning |
|---|---|---|---|---|
| show_id | string | | spine key | never null |
| artist_id | string | | spine key | never null |
| years_active_at_show | Int32 | years | show year − career_start_year | no career start |
| n_tours_started_before_show_year | Int32 | count | artist tour articles whose earliest "YYYY concert tours" category year is < the show's year | artist unresolved |
| n_tours_started_by_show_year | Int32 | count | same, ≤ show year (includes the current tour if it started that year) | artist unresolved |
| pv_mean_90d | float | views/day | mean daily enwiki user views of the headliner article(s), days −90…−1 | window before 2015-07-01, before the article existed, after 2026-10-17, or no article |
| pv_mean_365d | float | views/day | days −365…−1 | as above (also null for shows before 2016-07-01) |
| pv_momentum | float | log ratio | log((mean views days −30…−1 + 1) / (mean views days −90…−61 + 1)) | as above |
| pv_spike_ratio | float | ratio | max single day in −30…−1 ÷ max(1, median of days −365…−31) | as above |
| pv_spike_flag | boolean | | pv_spike_ratio ≥ 5 | as above |

## Substitutes and caveats
- **"Follower growth over the prior 90 days" is unavailable** (Spotify prohibited, Last.fm needs permission). `pv_momentum` is the substitute. It measures English-Wikipedia attention, not fandom, and news events (deaths, scandals, awards, album drops) also move it.
- **Leakage:** every pageview window ends the day **before** the show. Note that the on-sale date is usually months earlier, so for purchase-time prediction, windows anchored on the show date still include post-on-sale attention. The analyst should re-anchor if the on-sale date becomes available.
- **ListenBrainz is a current, all-time snapshot**, not point-in-time. It postdates most shows and reflects a small, tech-skewed user base. Use it only as a cross-sectional popularity level.
- **Tour counts are from today's categories.** `n_tour_articles` counts all tours, including those after the show; use `n_tours_started_before_show_year` for point-in-time models. Tours without their own article (common for smaller acts) are not counted, and residencies are excluded.
- **Genres are current labels** (Wikidata and MB are edited over time) and reflect the whole career, not the era of the show.
- Pageview series follow the **current** article title only. Views of a page under an earlier title (before a rename) are not added, so momentum may jump at a rename.
