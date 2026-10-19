# features_weather.parquet

One row per `show_id`. Built by `src/features_weather.py` from the **Open-Meteo Historical Weather API** (`archive-api.open-meteo.com/v1/archive`). This is the one robots.txt exception approved in DECISIONS.md, for weather only.

**License:** free tier, **non-commercial use only**. Data under CC BY 4.0: **"Weather data by Open-Meteo.com"**. Underlying reanalysis: ERA5 / ECMWF (Copernicus).

**Leakage:** show-day weather is a **context variable that is not known at purchase time** (`wx_known_at_purchase = False` on every row). Use it to explain LEVEL or walk-up behaviour, never as a predictor of advance prices.

## Method
- **Coordinates:** (1) venue coordinates from collector-features' `features_venue.parquet` (Wikidata P625), except venues flagged `coord_conflict_km` in features_metro, else (2) the Census Gazetteer internal point of the venue's matched US place (`venue_metro.parquet`). San Francisco's internal point lies in the Farallon Islands, so it is overridden with City Hall (37.7793, −122.4193). City centroids are usually within 5–15 km of the venue, well inside the reanalysis grid scale. **Non-US venues without venue coordinates have no weather** (`no_coordinates`).
- **Requests:** time is cut into fixed 14-day windows. Each request covers one window for up to 20 venues (40 timed out about 5% of the time) with a show in it (Open-Meteo accepts coordinate lists), with `timezone=auto`, so hourly values are **venue-local time**. Ten variables over ≤ 14 days means each location counts as exactly 1 API call.
- **Politeness:** one honest UA, ≥ 5 s between requests, and quota pacing at 80% of the free tier (≤ 480 location-calls a minute, ≤ 4,000 an hour, ≤ 8,000 per UTC day, the daily count persisted in `data/raw/open_meteo/_quota.json`). A 403, 429 or challenge page, or 3 consecutive timeouts or connection errors, stops the run with no retry.
- **Cache:** one file per venue and window, `data/raw/open_meteo/<venue_id>__<lat>_<lon>__<start>__<end>.json`, never refetched. The coordinates in the key mean a later switch to venue coordinates fetches fresh data instead of reusing a different point. A stopped run still writes the table (`pending` rows), and rerunning resumes from cache. `features_weather.py --until-done` waits for 00:05 UTC after a daily-budget stop and continues. Each pass rereads the current spine and rewrites the table.
- **Order:** venue-windows containing a priced show (`avg_price_usd` not null) are fetched first. The table is written as soon as that slice is complete (a checkpoint, with the rest `pending`), then again after the unpriced remainder.
- **Coordinate guards:** collector-features coordinates are ignored (`load_venue_coords` in `src/context_http.py`) when `link_ambiguous` is true (one Wikidata item linked from several spine cities, e.g. the chain article Hard Rock Live), when `km_to_locality` > 50 (the item's coordinates contradict its own locality), or when a `name_match` venue's `wd_locality` disagrees with the tour table's city. Backstop: coordinates more than 40 km from a same-state city named in the tour table lose to the tour city (`coord_conflict_km`). Guarded venues fall back to the Census city centroid (US) or get no weather.
- **Evening window:** local hours **18:00–23:00 inclusive** (6 hourly values).
- Shows later than today − 6 days are not in the archive yet (`not_yet_in_archive`).

| column | type | unit | null meaning |
|---|---|---|---|
| show_id | string | | never null |
| wx_priced_show | boolean | the show has `avg_price_usd` in shows_base; these are fetched first | never null |
| wx_status | string | `ok`, `no_coordinates`, `not_yet_in_archive`, `pending` (the run stopped on quota or pushback; rerun to fill), `request_failed`, `date_missing_in_response`, `no_date` | never null |
| wx_coord_source | string | `venue_wikidata` or `census_place_centroid` | no coordinates |
| wx_query_lat / wx_query_lon | float | degrees, the point we asked for | no coordinates |
| wx_grid_lat / wx_grid_lon / wx_elevation_m | float | the grid cell Open-Meteo used | not `ok` |
| wx_timezone | string | IANA zone of the venue | not `ok` |
| wx_temp_max_c / wx_temp_min_c | float | °C, daily, at 2 m | not `ok` |
| wx_precip_mm | float | mm, daily sum (rain + snow water equivalent) | not `ok` |
| wx_precip_hours | float | hours with precipitation, daily | not `ok` |
| wx_wind_max_kmh | float | km/h, daily max at 10 m | not `ok` |
| wx_weather_code | float | WMO code, daily (most severe) | not `ok` |
| wx_snow_day | boolean | daily WMO code is a snow code (71, 73, 75, 77, 85, 86) | not `ok` |
| wx_eve_temp_mean_c | float | °C, mean over 18–23 h | not `ok` |
| wx_eve_precip_mm | float | mm, sum over 18–23 h | not `ok` |
| wx_eve_precip_hours | Int16 | evening hours with ≥ 0.1 mm | not `ok` |
| wx_eve_wind_max_kmh | float | km/h | not `ok` |
| wx_eve_weather_code_max | float | WMO code, max over the evening (0 clear, 1–3 cloud, 45/48 fog, 51–67 drizzle/rain, 71–77 snow, 80–86 showers, 95–99 thunderstorm) | not `ok` |
| wx_eve_thunderstorm | boolean | any evening code ≥ 95 | not `ok` |
| wx_eve_hours_covered | Int16 | should be 6 | not `ok` |
| wx_known_at_purchase | bool | always False | never null |

## Caveats
- Reanalysis is grid-based (about 9–25 km), not station data. Local storms can be missed or smeared. ERA5 runs from 1940, so 1970s shows have data, but it is coarser and less certain.
- Weather matters mostly for **outdoor** venues (stadiums, amphitheatres). Join `indoor_outdoor` from collector-features' `features_venue` before interpreting it. Indoor arena weather mostly captures travel friction.
- The WMO "max code" is ordinal-ish, not a severity scale (e.g. 45 fog < 51 drizzle numerically, but not necessarily in impact). Prefer the precipitation, snow and thunderstorm columns.
- No separate rain, snowfall or apparent-temperature columns: requests are trimmed to 10 variables to stay at 1 call per location.
