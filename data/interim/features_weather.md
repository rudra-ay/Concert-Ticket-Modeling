# features_weather.parquet

One row per `show_id`. Built by `src/features_weather.py` from the **Open-Meteo Historical Weather API** (`archive-api.open-meteo.com/v1/archive`). This is the one robots.txt exception approved in DECISIONS.md, for weather only.

**License:** free tier, **non-commercial use only**. Data under CC BY 4.0: **"Weather data by Open-Meteo.com"**. Underlying reanalysis: ERA5 / ECMWF (Copernicus).

**Leakage:** show-day weather is a **context variable that is not known at purchase time** (`wx_known_at_purchase = False` on every row). Use it to explain LEVEL or walk-up behaviour, never as a predictor of advance prices.

## Method
- Coordinates: (1) venue coordinates from collector-features' `features_venue.parquet` (Wikidata), else (2) the Census Gazetteer internal point of the venue's US city (`venue_metro.parquet`). City centroids are usually within 5–15 km of the venue, which is well inside the reanalysis grid scale. Non-US venues without venue coordinates have no weather.
- One request per venue per cluster of show dates spanning ≤ 14 days, with `timezone=auto`, so hourly values are **venue-local time**. At least 5 s between requests and one honest UA. Each response is cached as `data/raw/open_meteo/<venue_id>__<lat>_<lon>__<start>__<end>.json` and never refetched. A 403 or 429 stops the run (no retries).
- Evening window: local hours **18:00–23:00 inclusive** (6 hourly values).
- Shows later than today − 6 days are not in the archive yet (`wx_status = not_yet_in_archive`).

| column | type | unit | null meaning |
|---|---|---|---|
| show_id | string | | never null |
| wx_status | string | `ok`, `no_coordinates`, `not_yet_in_archive`, `request_failed`, `date_missing_in_response`, `no_date` | never null |
| wx_coord_source | string | `venue_wikidata` or `census_place_centroid` | no coordinates |
| wx_query_lat / wx_query_lon | float | degrees, the point we asked for | no coordinates |
| wx_grid_lat / wx_grid_lon / wx_elevation_m | float | the grid cell Open-Meteo used | not `ok` |
| wx_timezone | string | IANA zone of the venue | not `ok` |
| wx_temp_max_c / wx_temp_min_c | float | °C, daily, at 2 m | not `ok` |
| wx_precip_mm / wx_rain_mm | float | mm, daily sum | not `ok` |
| wx_snowfall_cm | float | cm, daily sum | not `ok` |
| wx_precip_hours | float | hours with precipitation, daily | not `ok` |
| wx_wind_max_kmh | float | km/h, daily max at 10 m | not `ok` |
| wx_weather_code | float | WMO code, daily (most severe) | not `ok` |
| wx_eve_temp_mean_c | float | °C, mean over 18–23 h | not `ok` |
| wx_eve_apparent_temp_min_c | float | °C, min "feels like" over 18–23 h | not `ok` |
| wx_eve_precip_mm | float | mm, sum over 18–23 h | not `ok` |
| wx_eve_precip_hours | Int16 | evening hours with ≥ 0.1 mm | not `ok` |
| wx_eve_wind_max_kmh | float | km/h | not `ok` |
| wx_eve_weather_code_max | float | WMO code, max over the evening (0 clear, 1–3 cloud, 45/48 fog, 51–67 drizzle/rain, 71–77 snow, 80–86 showers, 95–99 thunderstorm) | not `ok` |
| wx_eve_thunderstorm | boolean | any evening code ≥ 95 | not `ok` |
| wx_eve_hours_covered | Int16 | should be 6 | not `ok` |
| wx_known_at_purchase | bool | always False | never null |

## Caveats
- Reanalysis is grid-based (about 9–25 km), not station data. Local storms can be missed or smeared.
- Weather matters mostly for **outdoor** venues (stadiums, amphitheatres). Join the indoor/outdoor flag from collector-features before interpreting it. Indoor arena weather mostly captures travel friction.
- The WMO "max code" is ordinal-ish, not a severity scale (e.g. 45 fog < 51 drizzle numerically, but not necessarily in impact). Prefer the precipitation and thunderstorm columns.
