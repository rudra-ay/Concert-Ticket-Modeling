# Rebrowser research-access application (DRAFT; not submitted)

**For the user to submit.** It can't be sent on your behalf, because Rebrowser's process requires an account. Sign up or log in at https://rebrowser.net, then open https://rebrowser.net/free-datasets-for-research, pick a dataset in the checker, and submit the request. Decisions arrive by email and under **My Datasets → Research access**. Their contact email is shown on that page (it's hidden behind a script, so copy it from a normal browser) and there's an online chat, if a question comes up.

Context: DECISIONS.md item 3 (user accepted the provenance risk; use Rebrowser's own channels only; CC BY-NC 4.0; no redistribution), SOURCES.md N7, and PERMISSION_REQUESTS.md entry 5. **The report must disclose the provenance caveat:** Rebrowser collects this data with automated browsers from marketplaces whose terms restrict automated access.

## What their page says (fetched 2026-10-18, cached at `data/raw/rebrowser/_site/`)

- "Free access is limited to **historical CSV data**. Current data, API access, commercial use, and raw redistribution are not included."
- "**Premium fields require explicit team approval.**" Every price field is premium, so **the request must ask for the premium price fields by name and say why.** Without them the grant is useless for PATH (see the profile below).
- "Research access grants use of the existing Rebrowser dataset through our **standard preview, filtering, and export tools**. It does **not** include custom exports or data preparation." So we ask for filters their tool supports (dataset, entity, field filters, date range) and do the aggregation ourselves.
- One request covers "a specific, non-commercial academic or coursework project", as "a one-time historical CSV". Review takes "a few days".
- Their checker also lists **Vivid Seats**, **AXS** and **Ticketmaster** datasets. Vivid Seats would be a strong second resale source for PATH if StubHub is declined or too narrow. Its provenance caveat is the same.

## Submit one request per dataset, in this order

1. **StubHub** (priority: the deepest history, 2024-03-31 to the present, all-in `price`, section, quantity, and first/last seen).
2. **Gametime** (the final hours and days of the path, H14/H21; `priceTotal` including fees; since 2025-11-16).
3. **SeatGeek, events entity only** (event-level lowest/median/average price and listing counts, plus `ticketmasterId`/`stubhubId` cross-IDs to join with our Ticketmaster forward panel).

---

## Request text (paste into the form; adjust per dataset)

**Project title:** Concert ticket resale price dynamics before the show (personal, non-commercial research)

**Requester:** [Your name], independent researcher, rudraayyagari@gmail.com

**Project description:**
I'm running a personal, non-commercial research project on how concert ticket resale prices move in the roughly 60 days before a show, and what predicts the shape of that path. The academic literature disagrees. Sweeting (2012, JPE) finds steady declines toward the event in sports. Leslie & Sorensen (2014, REStud) find that concert resale prices rise slightly in the final two weeks for high-demand shows. Industry reports claim a peak about 9–10 days out followed by a fall. I want to test these competing predictions on recent US concert data and see whether the shape depends on sell-out status, genre, venue size and city. I'll also join resale paths to primary-market face-price ranges that I'm collecting myself from the official Ticketmaster Discovery API.

**Intended use:**
- Statistical analysis only: average price paths by days-to-show, event-level regressions, and comparisons between groups of events.
- Output: a private write-up with aggregate figures and charts. No row-level data will be published, shared or redistributed. No product, service, or commercial or client use.
- Attribution to Rebrowser in any write-up, and I'll follow the CC BY-NC 4.0 terms and your research-access terms.
- Data stored privately on my own computer and deleted when the project ends.

**Data requested (StubHub):**
- **Scope:** **concert events only** (music; exclude sports, theater, comedy, parking and multi-day passes), in the US. If your export tool can't filter by category, then the events and listings for the date range below, which I'll filter to concerts myself, ideally limited to events with `isParkingEvent = false`.
- **Time span:** all history for **events dated 2024-06-01 through the latest available date**, with listings from as early as they appear (ideally 90 or more days before each show) through show time. If that's too large, the most recent 12 months of event dates.
- **Entities:**
  - *Event listings*: `listingId`, `eventId`, `_firstSeenAt`, `_lastSeenAt`, `createdAt`, **`price`** 🔒 (all-in), **`faceValue`** 🔒, `section`, `row`, `quantity`, `availableQuantities`, `ticketClass`, `ticketClassName`, `listingTypeId`, `isSpeculativeRow`.
  - *Events*: `eventId`, `name`, `url`, `eventStartDatetime`, `eventState`, `eventAvailabilityState`, `venueId`, **`minPrice`** 🔒, **`ticketsRemaining`** 🔒, `medianPriceBucket`, `onSaleDateTime`, `rescheduledFromDate`, `isParkingEvent`, `isMultidayEvent`, with **one row per daily snapshot** (not only the latest state), so I can rebuild each event's daily lowest price.
  - *Venues*: all fields.
- **Premium fields, requested explicitly with justification:** `price`, `faceValue`, `minPrice` and `ticketsRemaining`. The research question is about how prices change over time, so the analysis can't be done without the price fields. `ticketsRemaining` measures remaining supply, which is the main moderator in the competing theories. I do **not** need `dealScore`, `starRating`, `discount` or `seatQualityScore`.
- **What I'll compute from it:** per event and day, the lowest and median all-in price (overall and by `ticketClassName` zone), the listing count, and the total quantity listed; per listing, the price changes between first and last seen.

**Data requested (Gametime)** (same project text):
- Scope: `category = music`, US, events dated 2025-11-16 through the latest available date.
- *Event listings*: `listingId`, `eventId`, `_firstSeenAt`, `_lastSeenAt`, **`priceTotal`** 🔒, **`pricePrefee`** 🔒, **`priceFaceValue`** 🔒, `availableLots`, `section`, `row`, `sectionGroup`, `deliveryType`, `inHandDate`, `eventDatetimeUtc`.
- *Events* (one row per daily snapshot): `eventId`, `name`, `category`, `datetimeUtc`, `salesCutOff`, **`minPriceTotal`** 🔒, **`maxPriceTotal`** 🔒, `venueId`, `performerIds`. *Performers* and *Venues*: all fields.
- Justification for the premium fields: Gametime focuses on last-minute sales, so its all-in prices in the final hours are the only way to test whether the minimum price falls on show day.

**Data requested (SeatGeek, events only)** (same project text):
- Scope: `taxonomyName = concerts`, US, all available history (2025-10-05 onward), one row per daily snapshot.
- Fields: `eventId`, `name`, `datetimeUtc`, `status`, `scheduleStatus`, `venueId`, `performerIds`, **`lowestPrice`** 🔒, **`medianPrice`** 🔒, **`averagePrice`** 🔒, **`highestPrice`** 🔒, **`listingCount`** 🔒, **`ticketCount`** 🔒, `ticketmasterId`, `stubhubId`, plus *Venues* (`capacity` in particular) and *Performers*.
- Justification: event-level daily price statistics give a second, independent resale path, and the cross-IDs let me match to Ticketmaster and StubHub.

**Format:** CSV (your standard export) is fine.

**Acknowledgement:** I understand the access is a one-time historical export for non-commercial research, with no redistribution, under CC BY-NC 4.0 and your research-access terms.

---

## What the public sample gives us (profiled 2026-10-18; see below)

See the "Profile of the public preview" section at the end of this file. In short, the public sample **cannot support PATH**. All price fields are `[PREMIUM]`-masked, and each daily file is a separate sample rather than a panel, so no event can be followed from 60 days out to the show. The research grant, **with premium fields approved**, is the only Rebrowser route that does.

## Profile of the public preview (downloaded 2026-10-18/19, no login)

Download: `src/rebrowser_download.py` (Hugging Face, ungated, no token; robots allows all; one UA; 5 s or more between requests; parquet only, because the CSVs duplicate it). It's 8.4 MB under `data/raw/rebrowser/`. The full profile is in `data/interim/rebrowser_profile.txt` (`src/rebrowser_profile.py`). The run stopped three times on connection resets or timeouts while the laptop slept. These were not 403s or challenges, and the run resumed from cache each time.

| Dataset / entity | Rows (sample) | Daily files | Locked (`[PREMIUM]`) | Panel? |
|---|---|---|---|---|
| StubHub listings | 30,000 (817 events) | 2026-09-05..10-04 | `price`, `faceValue`, `dealScore`, `starRating`, `discount`, `seatQualityScore` | Listings are tracked by first/last seen: median life 2 days, p90 12.5 days. 60 events appear on 7 or more daily files, max 8 |
| StubHub events | 1,606 | 2026-09-05..10-03 | `minPrice`, `ticketsRemaining`, `isFastSelling` | **No.** Each event appears in exactly one daily file. `medianPriceBucket` (0–3) is unlocked but never observed twice for the same event. `isUnderHundred` is False for 100% of rows (looks like a placeholder) |
| StubHub venues | 224 | single file | none | – |
| Gametime listings | 30,000 (826 events; 5,562 rows music) | 2026-09-06..10-05 | all 7 price fields | Median life 1.1 days. 81 events on 7 or more files, max 25 |
| Gametime events | 20,101 (8,111 music, show dates 2026-09-10..12-10) | 2026-09-06..10-05 | min/max price, deal prices, popularity | **No.** One row per event (the latest state) |
| Gametime performers / venues | 1,000 / 1,000 | single file | images only | – |
| SeatGeek listings | 30,000 (520 events) | 2026-09-05..10-04 | `price`, `priceWithFees`, `fee`, `dealScore` | Max 6 days per event |
| SeatGeek events | 2,926 | 2026-09-05..10-04 | all price stats, listing and ticket counts | **No**, and the sample is **100% sports** (MLB, NBA, NHL, NFL, stadium tours): zero concerts. `ticketmasterId` 37% filled, `stubhubId` 16% |
| SeatGeek performers / venues | 263 / 194 | single file | images only | – |

**Can the public sample support PATH? No.**
1. Every price field (listing and event level, on all three datasets) is masked as `[PREMIUM]`.
2. Even ignoring price, the samples aren't panels. Each daily file is a separate draw of about 1,000 rows. No event in any events table is observed on two days, and no listing-level event series reaches more than 25 days, so far short of 60 days to the show.
3. The SeatGeek sample contains no concerts at all.

**What it is useful for now:** schema and field semantics for writing the loaders ahead of the grant; venue directories (StubHub 224, Gametime 1,000 with lat/lon and timezone, SeatGeek 194 with **capacity**); Gametime performer genres; listing-level non-price structure (sections, ticket classes, split quantities, and listing lifetimes); and the `ticketmasterId` cross-ID mechanism.

**After the grant (with premium fields approved):** StubHub listings with `_firstSeenAt`/`_lastSeenAt` and all-in `price` from 2024-03-31 make it possible to rebuild per-event daily min and median paths from 60 or more days out. That is the full PATH test set (H1, H3, H4, H5, H13, H21). Gametime adds the final-hours tail (H14). Two caveats remain. The request must win premium-field approval. And whether past daily event snapshots (as opposed to only the latest state) are exportable is still unconfirmed, which is why the request asks for one row per daily snapshot explicitly.
