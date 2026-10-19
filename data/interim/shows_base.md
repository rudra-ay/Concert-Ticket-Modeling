# shows_base.parquet

Per-show box office spine for the LEVEL question, parsed from English Wikipedia tour articles (source A1). One row per show date in a tour article's shows table. Written by collector-prices with `src/collect_wikipedia_boxoffice.py` (fetch) and `src/boxoffice_parse.py` (parse). It is rerunnable from cache with `.venv/bin/python src/collect_wikipedia_boxoffice.py parse`.

**Status: PARTIAL.** It grows as more dump streams are fetched. See `shows_base_coverage.md` for current counts.

**License:** CC BY-SA 4.0 (Wikipedia text). Attribute each row to `tour_title` at revision `tour_revid` of the enwiki 20261001 dump. Derived tables shared publicly must be CC BY-SA.

## Columns

| column | type | unit | meaning / null meaning |
|---|---|---|---|
| show_id | str | | `<artist_slug>__<YYYY-MM-DD>__<venue_slug>` per SHOW_KEY.md; `__2`, `__3` are appended for collisions |
| artist_id | str | | slug of `artist_name` |
| venue_id | str | | `<venue_slug>__<city_slug>` |
| show_date | datetime64 | date | show date. The year comes from the cell, else the date header, caption, leg row, section heading or infobox start year, with a rollover when the month goes backwards by more than 150 days |
| artist_name | str | | infobox `artist` text (co-headliners are kept as written, e.g. "Chris Brown & Usher"). If there's no infobox, it falls back to the article title |
| venue | str | | venue display text |
| city | str | | city display text |
| region | str | | US state, Canadian province or Australian state; null outside those countries unless the table has its own column |
| region_source | str | | `table` (own column), `country_slot` (the table put the state where the country goes), `city_wikilink` (from a `City, State` link target or a known bare city link), or `city_name_map` (the city name maps to exactly one region elsewhere in the data; not used when the city link names another place), or `venue_consensus` (a lone dissenting region at a venue, overridden by the venue's majority; this fixes article link errors like [[Edinburg, Ohio]] for Bert Ogden Arena); null = unknown |
| country | str | | country as written (states in the country slot are moved to region) |
| country_iso2 | str | | pycountry lookup plus aliases (England/Scotland/Wales → GB); null = unmapped |
| tickets_sold | float | tickets | the left side of "sold / available", or a lone number. Null when missing, "—", "sold out" without a count, or a non-first row of an aggregate |
| tickets_available | float | tickets | the right side of "sold / available"; null if not given |
| gross | float | currency units | the parsed revenue figure ("$1.2 million" → 1,200,000) |
| gross_currency | str | ISO 4217 | from the symbol in the cell or the header; a bare `$` is treated as USD (Boxscore convention, see known issues) |
| gross_usd | float | nominal USD | `gross` when the currency is USD, else null. No FX or CPI conversion |
| avg_price_usd | float | nominal USD/ticket | `gross_usd / tickets_sold`. **Target variable.** For aggregates it's the average across all the shows in the aggregate |
| avg_price_flag | str | | `implausible` when the average is < $5 or > $2,000; `tour_outlier` when it is > 4× or < 0.25× the tour median (tours with ≥ 5 priced shows), usually a multi-night or tour total in one row. Rows are kept; screen on this |
| sellout_ratio | float | ratio | sold / available |
| aggregate_n_shows | int | shows | >1 when the attendance/revenue cell spans several date rows (multi-night stand reported as one figure) |
| aggregate_is_first | bool | | True on the row that carries the aggregate figures. Other rows in the group have null figures. **Don't divide by 1 show**: the figures cover `aggregate_n_shows` shows |
| status_note | str | | comma-joined keywords found in the row: cancelled, postponed, rescheduled, festival, relocated, private, charity, benefit, co-headline, matinee, livestream, and "cancelled/postponed table" when the table sits under a cancelled-shows heading |
| tour_title | str | | article title (provenance) |
| leg | str | | the last in-table leg/separator row above the show (e.g. "North America"), else the nearest section heading (often generic, like "Tour dates") |
| section | str | | full heading path to the table (" / "-joined) |
| table_caption | str | | the table caption (`|+`) |
| table_index | int | | the table's ordinal in the article |
| tour_page_id, tour_revid, rev_timestamp | int, int, str | | enwiki page id, revision id and revision timestamp (20261001 dump) |
| date_raw | str | | the cleaned date cell |
| city_wikilink | str | | city link target(s), " \| "-joined. Carried to later rows of the same page for the same city text (Wikipedia links on first mention only) |
| venue_wikilink | str | | venue link target(s) as written (unresolved redirects). Only on a venue's first mention in a page |
| opening_acts_raw | str | | acts as " \| "-separated text (split on `<br>`, bullets, list templates, commas and semicolons; not on "and"). Placeholders like "—" or "TBA" are dropped |
| opening_acts_wikilinks | str | | link targets in the opening-act cell, " \| "-joined. Unlinked mentions have none (source-side) |
| attendance_raw, revenue_raw, notes_raw | str | | the cleaned cell text, for auditing |
| tour_start_date, tour_end_date | datetime64 | | infobox `start_date`/`end_date` |
| tour_announced_date | datetime64 | | infobox announcement field. **The concert infobox has no such field, so this is almost always null** |
| tour_infobox_* | str | | infobox gross, attendance, number_of_shows, number_of_legs, type, album, as text |
| capacity_bucket | category | | from `tickets_available`, else `tickets_sold`: <3k, 3k–8k, 8k–25k, 25k+ |
| source | str | | provenance and license string |

## Parsing rules
1. **Candidate pages:** titles in the multistream index that match tour patterns (`… Tour`, `(… tour)`, `Residency`, `List of … concerts/tour dates/live performances`), minus redirects and sports/cycling/golf etc. Any article in a fetched stream is kept if it has a wikitable with an Attendance/Revenue/Gross column **and** either the `{{Infobox concert}}` template (the old `Infobox concert tour` name redirects to it) or a tour-like title.
2. **Tables:** a table is a shows table if it has a header row with ≥ 3 header cells, a Date column, and an Attendance or Revenue/Gross column. Rowspan and colspan are expanded into a grid (as in HTML, a full-width leg row uses up one row of any pending rowspan beneath it). Refs are stripped from the whole table first, and lines are joined while a `{{template}}` or `[[link]]` is open, so multi-line citations don't create spurious cells. Rows without a parseable date (totals, sub-headers) are skipped. A single-cell row spanning the table is read as a leg/separator (which can also set the year).
3. **Cells:** refs, comments and footnote templates (`efn`, `refn`, `cn`…) are removed. `sort`, `dts`, `flag*`, `nowrap`, `US$` and date templates are expanded. Wikilink targets are kept.
4. **Attendance:** "9,998 / 10,000" → sold, available. A lone number ≥ 50 → sold. "—", "N/A" and "sold out" → null.
5. **Gross:** the first number, with "million"/"billion" multipliers. Values < 1,000 are discarded (stray footnote numbers).
6. **Aggregates:** if the attendance or revenue cell has rowspan > 1, the figures go on the first row only and `aggregate_n_shows` = the rowspan.
7. **Non-shows:** rows without a venue are dropped (tour-summary rows on "List of … live performances" pages, TBA venues). "Georgia" in the country slot counts as the US state only when the city link says ", Georgia"; otherwise it is the country (GE).
8. **Dedupe:** the same show appearing on both a tour article and a "List of … concerts" page is collapsed when the show_id and raw figures match.

## Known issues (for the analyst)
- **Coverage bias:** Wikipedia only has box office tables for tours big enough to report to Billboard Boxscore/Pollstar, mostly arena and stadium acts in pop, rock, K-pop and Latin, from ~2010 on. Club/theater tours and the later legs of big tours are often missing figures. Rows without figures are kept so this bias is measurable.
- **Currency:** a bare `$` is assumed to be USD. Some Australian/Canadian/Latin American rows may be local dollars written as `$`. Boxscore converts to USD, but editors sometimes don't. Check `country_iso2` vs. price outliers.
- **Gross definition** varies (fees, VIP packages, and taxes are included inconsistently). Figures are promoter-reported.
- **Upcoming shows** (2026–27) appear with null figures.
- **Malformed source tables** (overlapping rowspans, missing pipes) are handled best-effort. A missing attribute pipe (`| rowspan="11" {{TBA}}`) is repaired. Overlapping rowspans can shift a column; these show up as null figures, not wrong numbers, in the cases checked.
- Venue and opening-act wikilinks are unresolved redirect targets.
- No FX or CPI conversion is done here (that happens in the analyst's join).
