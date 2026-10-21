# forward_tm_panel: Ticketmaster Discovery forward panel (data dictionary)

Source DB: `data/forward/tm_forward.sqlite` (gitignored; private, see the storage caveat in FORWARD_COLLECTOR.md §6), written daily by `forward_collector.py` since **2026-10-19**. Attribution: "Data from Ticketmaster Discovery API". Not part of `data/shows.parquet`; join by artist + venue + local date per `data/interim/SHOW_KEY.md`, or via SeatGeek `ticketmasterId` cross-IDs.

## READ FIRST: what the prices are

- `price_ranges` / `snapshots.price_min` / `price_max` are Ticketmaster **PRIMARY-market face-value ranges**: the min and max of Ticketmaster's own price levels for the event. They are **not resale prices**, not the lowest ticket available, and not a distribution.
- Every range observed so far has `type = 'standard'`, USD. **Fees are not included.** No `standard including fees` range appeared in the pilot.
- So **PATH from this panel measures primary / dynamic face-price movement** (tier releases, dynamic repricing, H20/H9 primary side) and status changes. **Resale paths (H1, H4/H5, H13, H14, H21) still depend on the Rebrowser grant (REBROWSER_REQUEST.md) or the marketplace permissions in PERMISSION_REQUESTS.md.**
- **Missing priceRanges is common:** about 26% of candidate events have them (pilot pool of 24,095 US music events; 24.3% for shows ≥45 days out). Missingness is far from random by genre: Jazz 83%, Alternative 61%, Folk 48%, Blues 31%, Country 26%; Rock, Pop, Hip-Hop and R&B 19–21%; Other 16%; Classical, Latin and Undefined about 0%.
- **Genre tilt by design (option b, 2026-10-19):** about 80% of new watchlist slots go to events that already publish ranges, so the panel over-represents Jazz, Alternative and Folk relative to the US concert population. Use `selection_prob` for inverse-probability weights when making population statements.

## Tables

### `watchlist` (one row per tracked event)
| column | type | meaning |
|---|---|---|
| event_id | text | Ticketmaster Discovery event id |
| added_at | text | UTC ISO time added. **The path starts here**; no earlier data exists |
| source | text | `discover` (stratified selection), `promotion` (gained ranges after an earlier scan without them; see `promotions`), `discover-pilot` (200 pilot events of 2026-10-19, picked before the weights existed: **no weights, exclude from IPW analyses**), `manual`, `csv` |
| event_date | text | venue-local show date, refreshed from each snapshot |
| active | int | 1 while being snapshotted |
| deactivated_why | text | `show date passed`, `cancelled`, `404 repeatedly` |
| first_days_out | int | days to show at the first snapshot. **≥60 = eligible for a full 60-day path** |
| selected_for_ranges | int | 1 = picked from the with-ranges pool (diversity round-robin; includes promotions); 0 = **simple random draw** within its stratum from events without ranges; NULL = pilot/manual |
| stratum | text | `far|near` + `|state|genre` at selection. far = show ≥60 days out on the selection day. `pilot` for pilot rows |
| selection_prob | real | realized probability = selected / available in (stratum, with-/without-ranges pool) on the selection day. IPW weight = 1 / selection_prob. For with-ranges picks it is a realized share of a diversity-capped (not random) pick. **Conditional on that day's pool** (which excludes events already on the watchlist). Treat the selection day (`added_at` date) as an extra stratum: weight within each day's cohort and combine cohorts as strata. Cohorts so far: 2026-10-19 main (far share 0.6), the 2026-10-22 raise from 3,000 to 4,000 under scenario C (far share 0.3: about 6 far with ranges, 294 far random without, 560 near with ranges, 140 near random without; the far priced pool was exhausted), and small daily replacement adds (far share 0.3 from 2026-10-22) |
| has_ranges_at_selection | int | whether the event had priceRanges in the discover scan that selected it |

### `snapshots` (one row per event per UTC day; PK `event_id, snap_date`)
| column | meaning |
|---|---|
| snap_date / snapshot_ts | UTC day of the run / UTC time of the response |
| http_status | 200, or 404 (event gone; no other fields) |
| event_status | `dates.status.code`: onsale, offsale, cancelled, postponed, rescheduled |
| local_date, local_time, start_utc, event_timezone | show date and time. Timezone falls back to the venue's (`dates.timezone` is absent on about 40% of events) |
| days_until_show | venue-local show date minus the snapshot's venue-local date (integer days; 0 = show day) |
| hours_until_show | start_utc minus snapshot_ts |
| public_sale_start/end, public_sale_start_tbd, presales_json | primary sale windows |
| venue_id, venue_name, city, state, country, venue_lat, venue_lon | venue |
| attraction_ids, attractions_json | performers (Ticketmaster attraction ids and names) |
| segment, genre, subgenre, classifications_json | Ticketmaster primary classification |
| has_price_ranges | 1 if the response had `priceRanges` (see the `missing_price_ranges` view) |
| price_min, price_max | min and max over all ranges (USD face value, no fees) |
| ticket_limit_info | Ticketmaster's ticket-limit note |
| source_url | request URL **without** the API key |
| raw_json_gz | gzipped full response (key stripped) |

### `price_ranges` (PK `event_id, snap_date, idx`)
`type` (so far always `standard`), `currency` (USD), `min`, `max`: primary face value, no fees.

### `promotions`
Events that a discover scan first saw **without** ranges and a later scan saw **with** ranges, then added to a free slot. `promoted_on` = the date the path starts, `first_seen_on`, `ranges_seen_on`, `days_out_at_promotion`. A promoted event has no data before `promoted_on`. Never back-date its path.

### Other tables
`runs` (per-run counts and stop reasons), `api_call_log` (timestamp of every request, for the rolling-24 h budget), `api_calls` (calls per UTC day), `discover_candidates` (the latest scan of every candidate, plus `first_seen_on` / `first_has_ranges` / `ranges_seen_on`), `discover_slices` (search cache), and the view `missing_price_ranges`.

## Recommended analysis filters
- Full 60-day path: `first_days_out >= 60` and the show has passed, with snapshots on at least 90% of the days in the window.
- Price path: also `has_price_ranges = 1` on most days. Ranges can appear or disappear mid-path; measure that rather than dropping such events.
- Population estimates: exclude `source = 'discover-pilot'` and weight by `1 / selection_prob`.
