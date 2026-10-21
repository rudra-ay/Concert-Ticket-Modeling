# Forward collector (Ticketmaster Discovery API v2)

`forward_collector.py` takes one snapshot a day of Ticketmaster's public event data (price ranges, sale dates, status, venue, artists, genre) for a watchlist of upcoming US concerts and stores it in SQLite. It is the forward-looking half of the PATH data: nothing is available retroactively, so **every day it isn't running is lost for good.**

Source: SOURCES.md A6 (ALLOWED). Decisions: DECISIONS.md items 4 and 5, plus option (b) of 2026-10-19 (below). Attribution: "Data from Ticketmaster Discovery API". Data dictionary: `data/interim/forward_tm_panel.md`.

> **What the prices are.** Ticketmaster `priceRanges` are **PRIMARY-market face-value ranges** (min and max of Ticketmaster's own price levels). Every range seen so far is type **`standard`, USD, without fees**. They are **not resale prices**. PATH from this panel therefore measures **primary / dynamic face-price movement** (tier releases, repricing, status changes). **Resale paths still depend on the Rebrowser grant (REBROWSER_REQUEST.md) or the marketplace permissions (PERMISSION_REQUESTS.md).** The panel is also deliberately **tilted toward genres where Ticketmaster publishes ranges** (Jazz, Alternative, Folk); see "Pilot result" and use the IPW weights.

## Status (2026-10-19)

- **Collecting since 2026-10-19.** The key is in `.env`. **The launchd job was installed on 2026-10-19 and bootstrapped without a kickstart.** The first scheduled `daily` is 2026-10-20 at 09:15 local time (§2).
- First `daily` (2026-10-19, UTC day): **2,960 snapshots** saved, with 0 errors and 0 404s (plus 40 from the pilot run, for 3,000 events snapshotted that day). Event status: 2,808 onsale, 174 offsale, 18 rescheduled. **API calls that UTC day: 3,218** (pilot 100, full discover 152, daily 2,966).
- Watchlist: **3,000 active** (2,061 ranges pool, 739 random without ranges, 200 pilot). 1,680 first observed ≥60 days out. 975 venues, 1,142 artists, 49 states.
- Days to show at the start: 1–6: 271 · 7–13: 189 · 14–29: 463 · 30–44: 215 · 45–59: 182 · 60–89: 998 · 90–120: 682.

## Pilot result and option (b) (2026-10-19)

The pilot found a **priceRanges fill rate below the 30% threshold**: 26.2% of search candidates and 15% of 40 detail responses. The full discover measured fill on the whole candidate pool of US music events. Regenerate this table with `.venv/bin/python forward_collector.py fill-report`.

Candidate pool on 2026-10-19: 24,095 US music events, 1–120 days out (Music segment; parking and add-ons excluded).

| days out | events | fill % |
|---|---|---|
| 1-6 | 2,744 | 25.9 |
| 7-13 | 2,561 | 26.0 |
| 14-29 | 6,042 | 28.0 |
| 30-44 | 4,048 | 28.0 |
| 45-59 | 3,780 | 25.2 |
| 60-89 | 2,641 | 27.8 |
| 90-120 | 2,279 | 19.0 |
| **>=45** | 8,700 | **24.3** |
| **>=60** | 4,920 | **23.7** |

| genre | events | fill % |
|---|---|---|
| Rock | 6,161 | 19.6 |
| Other | 3,668 | 15.5 |
| Country | 1,834 | 25.6 |
| Jazz | 1,747 | 82.7 |
| Pop | 1,573 | 19.6 |
| Dance/Electronic | 1,434 | 22.6 |
| Alternative | 1,238 | 60.6 |
| Hip-Hop/Rap | 1,107 | 19.4 |
| Undefined | 974 | 0.0 |
| R&B | 925 | 20.5 |
| Metal | 672 | 24.4 |
| Classical | 556 | 0.7 |
| Folk | 524 | 48.1 |
| Blues | 431 | 30.6 |
| Latin | 395 | 0.0 |
| **all** | 24,095 | **26.2** |

On the event detail endpoint (the first full `daily`, 2,960 snapshots), fill matched the selection: 100% for the 2,061 ranges-pool events, 0% for the 739 random no-ranges events, and 21% for the 200 pilot events. Every one of the 2,103 ranges was `standard`, USD, without fees. The detail and search endpoints agree.

Fill for shows ≥45 days out (24.3%) is close to the pilot's 26.2%. The 90–120 day band is lower (19.0%), so ranges are often published later. **Missingness depends heavily on genre**, so an unweighted panel would be thin, and a ranges-only panel would be biased.

**Decision (lead, 2026-10-19): option (b), a ranges-tilted stratified panel.**
- Strata are (band, state, genre), where band = `far` (show ≥60 days out on the selection day) or `near`. 60% of new slots went to the far band on 2026-10-19; 30% since 2026-10-22 (scenario C, below).
- In each band, **80% of slots go to events that publish priceRanges**, picked round-robin across strata with soft per-venue and per-artist caps. The remaining **20% are a simple random draw within each stratum** (proportional allocation) of events **without** ranges. This shows whether ranges appear or disappear later, and supports inverse-probability weighting.
- When a pool runs short, its slots overflow to the other pool. On 2026-10-19 the far band had only 1,165 priced events in total, and all of them were taken (p = 1). The far band is therefore 1,165 with ranges plus 515 random without (69/31).
- Every watchlist row records `selected_for_ranges`, `stratum`, `selection_prob` (selected / available in its stratum and pool) and `has_ranges_at_selection`. The 200 pilot events are marked `source='discover-pilot'` and carry no weights.
- **Promotions:** `daily` runs discover every day. Day-slices are re-searched once they are 7 or more days old, so every show is rescanned weekly and each new day-120 slice is picked up daily. A candidate first seen without ranges that later shows them can fill a free slot. It is logged (`promotion event=...`) and recorded in the `promotions` table with its `first_seen_on`, `ranges_seen_on` and `promoted_on` (= path start). **Never back-date a promoted event's path.**

### Watchlist raised to 4,000, far share 0.3 (scenario C, 2026-10-21)

Proposed by collector-prices for PATH readiness (`src/analysis/path_readiness.py`, `readiness_schedule_wide.csv`, which simulate `select_panel` day by day) and chosen by the lead. **Target 4,000 active events, and 30% of new slots go to the far band** (it was 60%). Ranges share (0.8), strata and `selection_prob` are unchanged. The simulation's estimates for C:
- priced N = 500 at the 7-day horizon on Nov 12 (status quo Nov 19), and at 14 days on Nov 16 (Nov 29);
- priced N = 1,000 at 7 days on Nov 22 (Dec 18);
- 60-day dates unchanged (Feb 19).

It was approved under the lead's rule that calls stay ≤ 4,500 per day including the weekly discover, which the rolling-24 h budget enforces (steady-state math under Limits).

**When:** the first top-up is the scheduled `daily` on **2026-10-22 at 09:15**. It happens at the discover step after the main snapshot pass. The catch-up pass then takes the new events' day-0 snapshots under the cap, and any that don't fit carry over to 10-23 (their paths start then).

**What the extra 1,000 slots contain.** All but 6 of the priced far-band events were already on the watchlist. A preview on 2026-10-22's pool:

| far share | far with ranges | far random without | near with ranges | near random without |
|---|---|---|---|---|
| 0.6 (old) | 6 | 594 | 320 | 80 |
| **0.3 (C)** | **6** | **294** | **560** | **140** |

C adds 566 priced events instead of 326. That is where the earlier short-horizon (7–30 day) readiness comes from. Far events without ranges add priced 60-day paths only if Ticketmaster publishes ranges for them later. From 2026-10-22 on, daily replacement adds also use 0.3.

**IPW across selection days.** `selection_prob` is the realized share **within that day's pool** (stratum × with/without ranges), and the pool excludes events already on the watchlist. The band mix also differs by cohort: 0.6 far on 2026-10-19, 0.3 from 2026-10-22. So treat the **selection day (the `added_at` date) as an extra stratum**: weight 1/`selection_prob` within each day's cohort, and combine the cohorts as strata, not as one sample. An event's overall inclusion probability across days, 1 − Π(1 − pₖ) over the days it was available, would need every day's pool, and `discover_candidates` keeps only the latest scan. So use cohort-stratified estimates. `discover-pilot` rows carry no weight.

**Drift risk (accepted, not time-shifted).** launchd runs at 09:15, or at wake if the Mac was asleep. The job does **not** shift itself to keep runs 24 h apart. If a run starts late by D hours, the next 09:15 run shares the rolling window with it. That run then follows the old calls as they age out, waiting at most 3 h in total. If D is more than about 3 h, it stops early (exit 0, `stopped='…rolling 24h…'`), losing roughly 2,000 snapshots per extra hour.
- Snapshot order is nearest-show-first, so **short-horizon paths (7- and 14-day) are protected** and far events lose that day. 60-day paths tolerate up to 6 missed days (the 10% rule).
- Manual catch-up runs late in the day cause the same overlap, so avoid them unless the scheduled run failed.

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
- `launchctl print gui/$(id -u)/com.ticketpriceresearch.forward-collector | grep -E "last exit|runs"` should show `last exit code = 0`. Code 3 means no key; code 5 means Ticketmaster rejected the key; **code 6 means the run stopped on HTTP 429 and must be reported before the next run** (see Limits).
- Logs: `data/forward/logs/forward_collector-YYYY-MM.log` (the script's own log) and `launchd.out.log` / `launchd.err.log`.
- A run that is rerun on the same UTC day only fetches what is missing, so running it by hand after a failure is always safe.

## 3. What a daily run does

`daily` does the following:
1. **Snapshot.** It calls `GET /discovery/v2/events/{id}.json` once per active watchlist event, nearest show first, so that if the budget runs out, the events closest to their show (where PATH moves most) are covered.
2. **Discover (every day; cheap), then a catch-up pass.** Only day-slices that are new or 7 or more days old are searched, so most days cost a few calls and one day a week costs about 150–250 (a full rescan). It searches `events.json?classificationName=music&countryCode=US` one UTC day at a time for 1–120 days out (200 per page, up to Ticketmaster's 1,000-item deep-paging cap per day) and tops the watchlist up to `--target` (**default 4,000 since 2026-10-21**; it was 3,000) active events using the option (b) selection above. A final catch-up pass (`daily-new` in `runs`) snapshots the new events the same day and retries events missed by network errors earlier in the run (2026-10-20/21: 30 and 37 read timeouts, DNS failures and "network unreachable" errors while the Mac slept).

Within the with-ranges pool, discover picks for diversity. It round-robins over (state × genre) strata, with soft caps per venue and per artist: 3 each to start, doubling only when slots would otherwise go unfilled. It excludes parking, upgrades, and add-ons. `--far-share` (default 0.3 since 2026-10-22; it was 0.6) sets the share of new slots for shows 60 or more days out, the only ones that can yield a full 60-day path. The Discovery API has no venue capacity, so venue size diversity comes from spreading across many venues. Capacity is joined later from Wikidata.

Watchlist management: `watchlist add <id>...`, `watchlist import ids.csv` (needs an `event_id` column), and `watchlist export out.csv`. Events drop off automatically once their date has passed, once they are cancelled, or after three 404s in a row.

### Stored per event per day (`data/forward/tm_forward.sqlite`)

| Table | Contents |
|---|---|
| `snapshots` (PK `event_id, snap_date`) | UTC snapshot timestamp, HTTP status, name, `event_status` (onsale / offsale / cancelled / postponed / rescheduled), local date and time, UTC start, timezone, **`days_until_show`** (venue-local calendar days) and `hours_until_show`, public sale start and end, presales (JSON), venue id / name / city / state / country / lat / lon, attraction ids and names, segment / genre / subgenre plus the full classifications JSON, `has_price_ranges`, min and max over the ranges, the ticket-limit note, the source URL (no key), and the **gzipped raw JSON** |
| `price_ranges` | one row per range: `type` (e.g. `standard`, `standard including fees`), `currency`, `min`, `max` |
| `missing_price_ranges` (view) | every 200-response snapshot without `priceRanges`. Each one is also logged as `missing_priceRanges event=...` and counted per run |
| `runs` | one row per run: calls, saved, missing ranges, 404s, errors, added, left undone, and the stop reason |
| `api_call_log` | timestamp of every API request, for the rolling-24 h budget (pruned after 48 h) |
| `api_calls` | calls per UTC day (reporting) |
| `watchlist`, `discover_candidates`, `discover_slices` | the panel, the search results, and the search cache |

### Limits and safety

- **Rate:** a token bucket at **3 req/s** or slower, with no bursts (`--rate` can only lower it). Ticketmaster allows 5. The first full run at 4 req/s (2026-10-19) drew six spike-arrest 429s, each cleared by one 2 s retry, so the default was lowered. A 3,000-event run takes about 17 minutes.
- **Rolling 24-hour budget (since 2026-10-21):** at most **4,500 calls in any rolling 24 hours** by default (`--budget` or `TM_DAILY_BUDGET`; the quota is 5,000/day). Ticketmaster's quota behaves like a **rolling 24-hour window, not a UTC day.** On 2026-10-20 the 09:15 run was cut at 1,563 calls when `Rate-Limit-Available` reached the 250 reserve, because the 3,218 calls made about 17 hours earlier still counted. Every attempt, including retries, is logged in `api_call_log`. When the window is full, the run **waits** for old calls to age out (at most `--max-wait-hours`, default 3 h, per run) and then stops cleanly (exit 0, `stopped='…rolling 24h…'`). On first use, the log was backfilled from the last 24 h of `runs`. The `Rate-Limit-Available` reserve stays as a hard stop. `api_calls` still holds per-UTC-day counts for reporting.
- **429 policy (lead, 2026-10-19):** a rare transient 429 (spike arrest: no `Retry-After`, no quota body) gets one exponential backoff (2 s, then 4 s, then 8 s for the same call). The run **stops for the day, exits 6, and must be reported** if a 429 carries `Retry-After` or a quota body, if more than **1%** of the run's calls draw 429s, or if a call is still 429 after 3 retries. A 401 or 403 stops at once and is never retried (exit 5). 5xx errors get 3 retries; an event that still fails is left unsaved, so a same-day rerun picks it up.
- **Idempotent:** one row per (event, UTC day), so a rerun the same day makes no calls for events already saved.
- **Key hygiene:** the key comes only from the environment or `.env`. Every log line passes through a redaction filter, raw JSON has `apikey=` (and the literal key) stripped before it is compressed, and saved URLs never contain it. The tests check all three.
- **Budget at steady state (target 4,000):** 4,000 snapshots × 1.03 (retries and network-error catch-ups; observed 429s are 0.2%, and catch-ups were 1.2% on 2026-10-21) = 4,120, plus the weekly full rescan (152 calls observed on 2026-10-19; budget 250), plus a few calls a day for the new day-120 slice. That's about **4,370 at most in any 24 h, under the 4,500 cap**, which is itself under Ticketmaster's 5,000 minus the 250 reserve. The cap enforces this in every 24-hour window, so a drifted start time (Mac asleep at 09:15) makes the next run wait or truncate instead of overrunning. Runs are latency-bound at about 0.6 req/s in practice (2026-10-21: 3,000 calls in 83 min), so a 4,000-event run takes about **2 h**, longer if it has to wait for the window. Storage is about 3 KB of gzipped raw JSON per snapshot, so about 12 MB a day.

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

**What each day of delay costs:** about 4,000 event-day snapshots, gone for good. The day's discovery cohort also slides out of the "60 or more days out" window: shows that are exactly 60 days out today will never have a complete 60-day path. Nothing can be backfilled from the API.

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

These cover parsing (including sparse events and the venue-timezone `days_until_show`), the missing-priceRanges case, same-day idempotency, 404 handling, cancelled and past events, key redaction (DB, raw JSON, logs, stdout), the no-key exit, the auth-error stop, the token bucket never exceeding 4 calls in any 1 s window and the 3 req/s cap, 429 handling with Retry-After, exponential backoff and the quota body, the persistent daily budget, the Rate-Limit-Available stop, discover paging and the deep-paging cap, the diversity caps and far-share, and the `daily` discover cadence. Fixtures are in `tests/fixtures/tm/`. They are hand-written in the documented Discovery v2 response shape, so the first real run should be checked against them (pilot step above).
