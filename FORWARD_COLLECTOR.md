# Forward collector (Ticketmaster Discovery API v2)

`forward_collector.py` takes one snapshot a day of Ticketmaster's public event data (price ranges, sale dates, status, venue, artists, genre) for a watchlist of upcoming US concerts and stores it in SQLite. It is the forward-looking half of the PATH data: nothing is available retroactively, so **every day it isn't running is lost for good.**

Source: SOURCES.md A6 (ALLOWED). Decisions: DECISIONS.md items 4 and 5, plus option (b) of 2026-10-19 (below). Attribution: "Data from Ticketmaster Discovery API". Data dictionary: `data/interim/forward_tm_panel.md`.

> **What the prices are.** Ticketmaster `priceRanges` are **PRIMARY-market face-value ranges** (min and max of Ticketmaster's own price levels). Every range seen so far is type **`standard`, USD, without fees**. They are **not resale prices**. PATH from this panel therefore measures **primary / dynamic face-price movement** (tier releases, repricing, status changes). **Resale paths still depend on the Rebrowser grant (REBROWSER_REQUEST.md) or the marketplace permissions (PERMISSION_REQUESTS.md).** The panel is also deliberately **tilted toward genres where Ticketmaster publishes ranges** (Jazz, Alternative, Folk); see "Pilot result" and use the IPW weights.

## Status (2026-10-19)

- **Collecting since 2026-10-19.** The key is in `.env`. The launchd job runs `daily` at 09:15 local time (§2).
- STATUS_PLACEHOLDER

## Pilot result and option (b) (2026-10-19)

The pilot found a **priceRanges fill rate below the 30% threshold**: 26.2% of search candidates and 15% of 40 detail responses. The full discover measured fill on the whole candidate pool of US music events. Regenerate this table with `.venv/bin/python forward_collector.py fill-report`.

FILL_PLACEHOLDER

Fill for shows ≥45 days out (24.3%) is close to the pilot's 26.2%. The 90–120 day band is lower (19.0%), so ranges are often published later. **Missingness depends heavily on genre**, so an unweighted panel would be thin, and a ranges-only panel would be biased.

**Decision (lead, 2026-10-19): option (b), a ranges-tilted stratified panel.**
- Strata are (band, state, genre), where band = `far` (show ≥60 days out on the selection day) or `near`. 60% of new slots go to the far band.
- In each band, **80% of slots go to events that publish priceRanges**, picked round-robin across strata with soft per-venue and per-artist caps. The remaining **20% are a simple random draw within each stratum** (proportional allocation) of events **without** ranges. This shows whether ranges appear or disappear later, and supports inverse-probability weighting.
- When a pool runs short, its slots overflow to the other pool. On 2026-10-19 the far band had only 1,165 priced events in total, and all of them were taken (p = 1). The far band is therefore 1,165 with ranges plus 515 random without (69/31).
- Every watchlist row records `selected_for_ranges`, `stratum`, `selection_prob` (selected / available in its stratum and pool) and `has_ranges_at_selection`. The 200 pilot events are marked `source='discover-pilot'` and carry no weights.
- **Promotions:** `daily` runs discover every day. Day-slices are re-searched once they are 7 or more days old, so every show is rescanned weekly and each new day-120 slice is picked up daily. A candidate first seen without ranges that later shows them can fill a free slot. It is logged (`promotion event=...`) and recorded in the `promotions` table with its `first_seen_on`, `ranges_seen_on` and `promoted_on` (= path start). **Never back-date a promoted event's path.**

## 1. Add the key (user action)

1. Register for free at https://developer.ticketmaster.com/ and create an app. Copy its **Consumer Key**.
2. Add one line to `.env` in the project root (gitignored; never commit it):
   ```
   TICKETMASTER_API_KEY=<your consumer key>
   ```
3. (Done 2026-10-19.) Run a small pilot by hand:
   ```
   .venv/bin/python forward_collector.py discover --target 200 --max-calls 60
   .venv/bin/python forward_collector.py run
   .venv/bin/python forward_collector.py status
   ```
   Check the **priceRanges fill rate** that `status` prints. If it comes back under about 30%, tell the lead: PATH-lite from Ticketmaster would be thin, and the Rebrowser data matters even more.
4. Then run the full discover (`.venv/bin/python forward_collector.py discover`, about 600–700 calls) and install the schedule.

## 2. Install the schedule (macOS launchd)

The template is `scripts/com.ticketpriceresearch.forward-collector.plist.template`. It runs `forward_collector.py daily` at 09:15 local time. If the Mac is asleep at that time, launchd runs the job at the next wake. If the Mac is off all day, that day is missed, and the next run carries on normally.

```
cd /Users/rudraayyagari/Ticket-price-corr-research
mkdir -p data/forward/logs
sed "s|__ROOT__|$PWD|g" scripts/com.ticketpriceresearch.forward-collector.plist.template \
  > ~/Library/LaunchAgents/com.ticketpriceresearch.forward-collector.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.ticketpriceresearch.forward-collector.plist
launchctl kickstart gui/$(id -u)/com.ticketpriceresearch.forward-collector   # optional: run once now
```

To uninstall: `launchctl bootout gui/$(id -u)/com.ticketpriceresearch.forward-collector`, then delete the plist.

### Check that it ran

- `.venv/bin/python forward_collector.py status` shows today's snapshot count, today's API calls, and the last 5 runs. A run marked `UNFINISHED` crashed partway. A non-empty `stopped` field explains an early stop (budget, 429, or a bad key).
- `launchctl print gui/$(id -u)/com.ticketpriceresearch.forward-collector | grep -E "last exit|runs"` should show `last exit code = 0`. Code 3 means no key; code 5 means Ticketmaster rejected the key.
- Logs: `data/forward/logs/forward_collector-YYYY-MM.log` (the script's own log) and `launchd.out.log` / `launchd.err.log`.
- A run that is rerun on the same UTC day only fetches what is missing, so running it by hand after a failure is always safe.

## 3. What a daily run does

`daily` does the following:
1. **Snapshot.** It calls `GET /discovery/v2/events/{id}.json` once per active watchlist event, nearest show first, so that if the budget runs out, the events closest to their show (where PATH moves most) are covered.
2. **Discover (every day; cheap).** Only day-slices that are new or 7 or more days old are searched, so most days cost a few calls and one day a week costs about 150–250 (a full rescan). It searches `events.json?classificationName=music&countryCode=US` one UTC day at a time for 1–120 days out (200 per page, up to Ticketmaster's 1,000-item deep-paging cap per day) and tops the watchlist up to `--target` (default 3,000) active events using the option (b) selection above. New events are snapshotted the same day.

Within the with-ranges pool, discover picks for diversity. It round-robins over (state × genre) strata, with soft caps per venue and per artist: 3 each to start, doubling only when slots would otherwise go unfilled. It excludes parking, upgrades, and add-ons. `--far-share 0.6` sends 60% of new slots to shows 60 or more days out, because only those can yield a full 60-day path. The Discovery API has no venue capacity, so venue size diversity comes from spreading across many venues. Capacity is joined later from Wikidata.

Watchlist management: `watchlist add <id>...`, `watchlist import ids.csv` (needs an `event_id` column), and `watchlist export out.csv`. Events drop off automatically once their date has passed, once they are cancelled, or after three 404s in a row.

### Stored per event per day (`data/forward/tm_forward.sqlite`)

| Table | Contents |
|---|---|
| `snapshots` (PK `event_id, snap_date`) | UTC snapshot timestamp, HTTP status, name, `event_status` (onsale / offsale / cancelled / postponed / rescheduled), local date and time, UTC start, timezone, **`days_until_show`** (venue-local calendar days) and `hours_until_show`, public sale start and end, presales (JSON), venue id / name / city / state / country / lat / lon, attraction ids and names, segment / genre / subgenre plus the full classifications JSON, `has_price_ranges`, min and max over the ranges, the ticket-limit note, the source URL (no key), and the **gzipped raw JSON** |
| `price_ranges` | one row per range: `type` (e.g. `standard`, `standard including fees`), `currency`, `min`, `max` |
| `missing_price_ranges` (view) | every 200-response snapshot without `priceRanges`. Each one is also logged as `missing_priceRanges event=...` and counted per run |
| `runs` | one row per run: calls, saved, missing ranges, 404s, errors, added, left undone, and the stop reason |
| `api_calls` | calls per UTC day, the persistent budget counter |
| `watchlist`, `discover_candidates`, `discover_slices` | the panel, the search results, and the search cache |

### Limits and safety

- **Rate:** a token bucket at 4 req/s or slower, with no bursts. Ticketmaster allows 5.
- **Daily budget:** 4,500 calls per UTC day by default (`--budget` or `TM_DAILY_BUDGET`; quota is 5,000). The budget counts every attempt, including retries, and persists across reruns. The run also stops early if Ticketmaster's `Rate-Limit-Available` header falls to 250.
- **429:** honors `Retry-After` (seconds or an HTTP date), or otherwise backs off 2 s, 4 s, then 8 s. After 3 retries, if the wait exceeds 120 s, or if the body says the quota is used up, the run **stops for the day**. A 401 or 403 stops at once and is never retried. 5xx errors get 3 retries; an event that still fails is left unsaved, so a same-day rerun picks it up.
- **Idempotent:** one row per (event, UTC day), so a rerun the same day makes no calls for events already saved.
- **Key hygiene:** the key comes only from the environment or `.env`. Every log line passes through a redaction filter, raw JSON has `apikey=` (and the literal key) stripped before it is compressed, and saved URLs never contain it. The tests check all three.
- **Budget at steady state:** about 3,000 snapshot calls a day, plus about 700 discover calls once a week, which is under 4,500. Storage is about 3 KB of gzipped raw JSON per snapshot, so about 9 MB a day, or roughly 1–1.5 GB over 4–5 months.

## 4. What PATH analysis needs from this, and how long it must run

**Unit:** one event's daily series `price_ranges.min` / `max` by `type`, plus `event_status` and the sale dates, indexed by `days_until_show` from 60 (or more) down to 0.

**Minimum for a usable PATH-lite panel:**
- **Coverage:** the event is first observed **60 or more days before the show** (`watchlist.first_days_out >= 60`) and still observed on show day or the day before.
- **Frequency:** one snapshot a day. Ticketmaster's primary prices change in steps (tier releases; LITERATURE H20), so daily resolution is enough. Intraday is out of budget and pointless for face prices.
- **Completeness:** no more than 10% of days missing in the 60-day window. Gaps from a sleeping laptop are fine if they're scattered.
- **Size:** at least **300 events with complete 60-day paths *and* non-missing priceRanges** to estimate an average path shape. About **1,000 or more** are needed to split by the moderators in H5 and H9 (sold-out status, genre, venue size, metro). **Actual (2026-10-19):** 1,680 far events entered on day 1. **1,165 of them already publish priceRanges**, which is the expected number of complete priced 60-day paths. Every far event with ranges in the US pool was taken. Add to that the far random-draw events that gain ranges later, plus later cohorts and promotions. That clears the 1,000 bar for the first cohort alone, with the genre tilt noted above.

**Timeline (collection started on day K = 2026-10-19):**
- **2026-12-18 (K + 60 days):** the first complete 60-day paths land, for shows that were 60 days out on 2026-10-19. They keep landing daily after that.
- **2027-02-16 (K + 120 days):** the last show of the first cohort (120 days out on 2026-10-19) has finished. This is the **minimum run length.**
- **About 2027-04-17 (K + 180 days, recommended):** weekly discovery keeps adding shows that are 60–120 days out, which brings in spring tours, more genres, and enough events for the moderator splits.

**What each day of delay costs:** about 3,000 event-day snapshots, gone for good. The day's discovery cohort also slides out of the "60 or more days out" window: shows that are exactly 60 days out today will never have a complete 60-day path. Nothing can be backfilled from the API.

## 5. Limitation: this is primary-market face data, not resale

Discovery's `priceRanges` is Ticketmaster's own **primary** price range for the event: min and max face value across price levels. The API can also return a fee-inclusive type (`standard including fees`), but **none appeared in the 2026-10-19 pilot or the first snapshots: every range was `standard`, without fees**. It is not the lowest available ticket, not a distribution, and not resale (Verified Resale listings are not included). Platinum or VIP pricing can inflate `max`. The field is often missing, and that is measured, not assumed (`missing_price_ranges`).

It **can** test: primary repricing and tier steps (H20), dynamic or platinum primary pricing (H9, primary side), status changes, and on-sale lead times. As LEVEL features it gives face value, genre, and venue.

It **cannot** test the core resale PATH hypotheses: H1 (late decline), H4/H5 (late rise for sold-out shows), H13 (peak at T-9/10), H14/H21 (minimum in the final hours). Those need resale data, which today means the Rebrowser StubHub/Gametime extract (see REBROWSER_REQUEST.md) or the marketplace permissions in PERMISSION_REQUESTS.md. Joining is possible through SeatGeek's `ticketmasterId` cross-IDs in the Rebrowser SeatGeek events table, or through artist + venue + date via `data/interim/SHOW_KEY.md`.

## 6. Storage terms caveat

Ticketmaster's terms allow storing Event Content only "for reasonable periods in order to provide the service you are providing". A panel kept for months for personal, non-commercial research is a gray area. Until Ticketmaster answers:
- Keep the database private. Don't redistribute raw or row-level data and don't publish a dataset; publish only aggregate findings, credited "Data from Ticketmaster Discovery API".
- Delete the data when the project ends: `.venv/bin/python forward_collector.py prune --keep-days N` deletes snapshots older than N days, or remove `data/forward/tm_forward.sqlite`.
- Send the clarification email drafted in **PERMISSION_REQUESTS.md, entry 0** (it asks about keeping snapshots for up to 12 months), and follow whatever Ticketmaster answers.

## Tests

```
.venv/bin/python -m pytest tests -q
```

These cover parsing (including sparse events and the venue-timezone `days_until_show`), the missing-priceRanges case, same-day idempotency, 404 handling, cancelled and past events, key redaction (DB, raw JSON, logs, stdout), the no-key exit, the auth-error stop, the token bucket never exceeding 4 calls in any 1 s window, 429 handling with Retry-After, exponential backoff and the quota body, the persistent daily budget, the Rate-Limit-Available stop, discover paging and the deep-paging cap, the diversity caps and far-share, and the `daily` discover cadence. Fixtures are in `tests/fixtures/tm/`. They are hand-written in the documented Discovery v2 response shape, so the first real run should be checked against them (pilot step above).
