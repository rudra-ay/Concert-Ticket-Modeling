# features_tour_context.parquet

One row per `show_id` with a valid date. Built by `src/features_tour_context.py` from `shows_base.parquet` only, with no network. The metro grouping uses `venue_metro.parquet` (from `src/features_metro.py`) when present, so **run features_metro first**.

**Leakage note:** tour length, show counts and "last show" flags describe the tour *as it was finally played*. Most dates are known at announcement, but added and cancelled dates are only known later. Treat `tour_n_shows`, `leg_n_shows`, `metro_n_dates_tour`, `venue_n_dates_tour`, `venue_run_length`, `is_last_show_of_*`, `tour_progress` and `days_to_next_show_artist` as **ex-post schedule** features. They are fine for explaining LEVEL, but not for purchase-time prediction.

| column | type | unit / values | null meaning |
|---|---|---|---|
| show_id | string | | never null |
| is_cancelled | boolean | `status_note` contains "cancel". Cancelled rows are kept but excluded from every count and position; all their other columns are null | never null |
| tour_key | string | `<artist_id>::<tour_title>`, or `<artist_id>::inferred-<n>` | cancelled |
| tour_inferred | bool | True when shows_base had no tour name: shows are split into tours at gaps > 180 days | never null |
| leg_number | int | 1-based leg index in date order | never null |
| leg_inferred | boolean | True when the source `leg` (nearest section heading) is unusable for the tour: missing for any show, only one distinct value, or a generic heading ("Tour dates", "Shows", "Box office", "Cancelled shows", …). Inferred legs split at gaps > 21 days or a continent change | cancelled |
| continent | string | north_america, latin_america, europe, mea, asia, oceania | country unmapped |
| tour_n_shows | int | shows on the tour in shows_base | never null |
| tour_show_number | int | 1-based position in the tour | never null |
| tour_span_days | int | days, first to last show | never null |
| tour_n_legs | int | | never null |
| tour_n_countries | int | | never null |
| days_since_tour_start | int | days | never null |
| tour_progress | float | 0 = first show … 1 = last | single-show tour |
| is_first_show_of_tour / is_last_show_of_tour | bool | | never null |
| leg_n_shows / leg_show_number / leg_span_days | int | | never null |
| is_first_show_of_leg / is_last_show_of_leg | bool | | never null |
| days_since_prev_show_artist | Int32 | days since the artist's previous show (any tour) | first show of the artist in the data |
| days_to_next_show_artist | Int32 | days | last show of the artist in the data |
| metro_key | string | `cbsa:<code>` for matched US venues, otherwise `<iso2>:<city slug>` | never null |
| metro_key_source | string | `cbsa` or `city` | never null |
| metro_n_dates_tour | int | dates in the same metro on the same tour | never null |
| metro_date_rank | int | 1 = first date in that metro on the tour, 2 = second, … | never null |
| venue_n_dates_tour / venue_date_rank | int | the same, at the same venue | never null |
| venue_run_length / venue_run_position | int | a "run" = consecutive dates at one venue, each ≤ 7 days after the previous | never null |
| is_multi_night_run | bool | the run has ≥ 2 dates | never null |
| is_added_date_proxy | bool | **proxy**: the 2nd+ date of a run | never null |
| days_announce_to_show | Int32 | days from tour announcement to show | no announcement date in shows_base (or announced after the show). **Expect mostly null**: collector-prices fills `tour_announced_date` only when the infobox has the field, which is rare |

## Heuristics and risks
- **Added-date proxy.** Wikipedia tables don't say which dates were added because of demand. A second+ consecutive date at the same venue (within 7 days) is the usual footprint of an added show, but **residencies and multi-night stands announced up front look identical** (e.g. stadium tours that announced 2–3 nights per city at once). The flag overstates true additions. Use it as "multi-night demand", not a causal "added" indicator.
- **Metro.** Newark and NYC, or Inglewood and LA, collapse to one CBSA only for US venues that features_metro could match. Non-US metros are city strings, so suburbs (e.g. Arnhem vs. Amsterdam) don't merge.
- **Inferred tours and legs** depend on gap thresholds (180 / 21 days). Only shows present in shows_base are counted. Wikipedia tables can omit or merge legs, and missing shows understate the counts.
- Dropped rows: spine rows whose date failed to parse (count printed at build time).
- Integer columns are nullable `Int32` and flags are nullable `boolean`, because cancelled rows carry nulls. Outside cancelled rows, the null-meaning column applies.
- Rescheduled shows: only "cancel" in `status_note` excludes a row. Rescheduled, postponed and festival rows count as played on the date in shows_base.
