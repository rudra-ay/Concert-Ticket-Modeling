# Shared show key (contract between collectors and analyst)

`data/interim/shows_base.parquet` is written by collector-prices and is the spine every feature table joins to.

- `show_id`: `<artist_slug>__<YYYY-MM-DD>__<venue_slug>`, with slugs lowercase ASCII, accents stripped, non-alphanumerics → `-`, collapsed. If two shows share an id (two shows at one venue on the same day), append `__2`.
- `artist_id`: artist slug. `venue_id`: `<venue_slug>__<city_slug>`.
- Feature tables are keyed by `show_id`, `artist_id` or `venue_id` and live in `data/interim/features_<name>.parquet`, each with a matching `features_<name>.md` dictionary (column, type, unit, source, null meaning).
- Money is nominal USD as reported, plus the original currency column. CPI deflation happens in the analyst's join, not in the collectors.
