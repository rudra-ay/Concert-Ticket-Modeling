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
