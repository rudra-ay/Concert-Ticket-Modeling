# SOURCES.md: data source evaluation

Scout evaluation, 2026-10-18. Research use only. **Nothing has been collected yet.** The collection specs below take effect only after the user approves this file.

Research questions:
- **LEVEL**: what explains a concert's price, measured as log(average ticket price) and as price relative to the artist's own median.
- **PATH**: how resale prices move from about 60 days out to the final hours, and what predicts the shape of that path.

Evidence cache: robots.txt files are in `data/raw/_scout/robots/`, terms pages in `data/raw/_scout/terms/`, shape samples in `data/raw/_scout/samples/`, HF dataset cards in `data/raw/_scout/hf/`, and paper PDFs and text in `data/raw/_scout/papers/`. Some terms pages were read with a web-fetch tool and not saved locally; those quotes link to the live page.

---

## Summary table

| # | Source | Access | Serves | Key needed | Verdict |
|---|---|---|---|---|---|
| A1 | Wikipedia tour articles | MediaWiki API (or dumps) | LEVEL (target) | No | **ALLOWED** |
| A2 | Wikidata | Entity JSON / SPARQL | features (venue capacity, type, coords; artist genre, career start) | No | **ALLOWED** |
| A3 | Wikimedia Pageviews API | REST API | features (hype), PATH covariate | No | **ALLOWED** |
| A4 | MusicBrainz | API (or CC0 dumps) | features (IDs, artist type, country, career start) | No | **ALLOWED** |
| A5 | ListenBrainz popularity | API | features (popularity, current snapshot only) | No | **ALLOWED** |
| A6 | Ticketmaster Discovery API v2 | Official API | LEVEL features (face price ranges, on-sale dates, genre); limited PATH (primary only, forward-looking) | **Yes** (`TICKETMASTER_API_KEY`) | **ALLOWED** (with storage caveat) |
| A7 | Open-Meteo Historical Weather | API | features (weather) | No | **ALLOWED** (non-commercial) |
| A8 | US Census ACS (bulk files) | Dataset download | features (metro income, population) | No | **ALLOWED** |
| A9 | BLS CPI-U | Flat-file download | deflator for LEVEL | No | **ALLOWED** |
| A10 | US federal holidays (OPM + `holidays` PyPI) | Pages / library | features | No | **ALLOWED** |
| A11 | Published papers and industry articles | Manual reading | priors, benchmarks | No | **ALLOWED** (manual citation only) |
| A12 | Federal Reserve G.5/H.10 foreign exchange rates | Bulk file + flat files | FX check of non-US grosses (units per USD, monthly) | No | **ALLOWED** (added 2026-10-19) |
| A13 | ECB euro foreign exchange reference rates | Bulk file | FX for currencies the Fed lacks (1999 on) | No | **ALLOWED** (added 2026-10-19; cite ECB, state modifications; collected, not required for the $=USD test) |
| N1 | StubHub | Web (no public API) | **PATH** (resale listings) | n/a | **NEEDS PERMISSION** |
| N2 | SeatGeek (API + web) | API / web | PATH, LEVEL | client_id | **NEEDS PERMISSION** (blocked us) |
| N3 | Vivid Seats | Web | PATH | n/a | **NEEDS PERMISSION** |
| N4 | Gametime | Web | PATH (last-minute) | n/a | **NEEDS PERMISSION** |
| N5 | TicketData.com | Web | **PATH** (historical get-in prices) | n/a | **NEEDS PERMISSION** (blocked us) |
| N6 | TickPick | Web | PATH | n/a | **NEEDS PERMISSION** (terms not verified) |
| N7 | Rebrowser datasets (StubHub / SeatGeek / Gametime on HF + Kaggle) | Dataset | **PATH** | Account | **NEEDS PERMISSION** (+ provenance decision) |
| N8 | Pollstar Data Cloud / Boxoffice | Subscription | **LEVEL** (per-show gross, attendance, price range) | Subscription | **NEEDS PERMISSION** |
| N9 | Billboard Boxscore (automated) | Articles | LEVEL | No | **NEEDS PERMISSION** |
| N10 | openICPSR 161484 (Bhave & Budish replication) | Dataset (login) | PATH (eBay 2007), LEVEL | openICPSR login | **NEEDS PERMISSION** (user action) |
| N11 | Last.fm API | API | features (listeners, playcount, tags) | Yes | **NEEDS PERMISSION** |
| N12 | setlist.fm API | API | features (tour length, show count, setlist length) | Yes | **NEEDS PERMISSION** |
| N13 | Google Trends (official API, alpha) | API | features (hype time series), PATH covariate | Alpha access | **NEEDS PERMISSION** |
| N14 | US Census Data API | API | features | Free key | **NEEDS PERMISSION** (host rejected our request) |
| N15 | Internet Archive Wayback (price-page snapshots) | CDX API | PATH (sparse) | No | **NEEDS PERMISSION** (terms not verified) |
| N16 | Songkick API | API | features (event calendars) | Yes | **NEEDS PERMISSION** (status unclear) |
| N17 | Deezer API | API | features (fan counts) | No | **NEEDS PERMISSION** |
| N18 | AXS / Live Nation web | Web | LEVEL / PATH | n/a | **NEEDS PERMISSION** (blocked us) |
| N19 | Kaggle community concert datasets | Dataset | LEVEL (redundant) | Kaggle token | **NEEDS PERMISSION** (licenses unverified; low value) |
| P1 | Spotify Web API | API | (would be features) | Yes | **PROHIBITED** |
| P2 | `pytrends` / unofficial Google Trends | Unofficial scraping | features | No | **PROHIBITED** |
| P3 | Bandsintown API | API | features | Artist app_id | **PROHIBITED** |
| P4 | Ticketmaster.com web pages (scraping) | Web | LEVEL / PATH | n/a | **PROHIBITED** (use A6 instead) |

**Counts:** 13 ALLOWED, 19 NEEDS PERMISSION, 4 PROHIBITED (A12 and A13 added 2026-10-19).

---

## Read this first: robots.txt on API hosts (a judgement call for the lead and user)

Several official API hosts serve a robots.txt that disallows everything, or disallows the API path, to generic crawlers. Each of these services also publishes API documentation that invites programmatic clients under its own terms:

| Host / path | robots.txt says | API docs say |
|---|---|---|
| `en.wikipedia.org/w/` (incl. `api.php`) | `Disallow: /w/` for `*` (only `action=mobileview` is allowed) | MediaWiki API:Etiquette invites API clients: no hard read limit, serial requests, descriptive UA |
| `query.wikidata.org/sparql` | `Disallow: /sparql` | WDQS manual: 60 s of query time per 60 s per client, 5 parallel queries per IP |
| `musicbrainz.org/ws` | `Disallow: /ws` (`Crawl-delay: 2`) | API docs: 1 req/s per IP with an identifying UA |
| `archive-api.open-meteo.com` | `Disallow: /` | Free API with 600/min, 5,000/h, 10,000/day for non-commercial use |
| `api.bls.gov` | `Disallow: /` | Public data API |
| `api.seatgeek.com`, `api.spotify.com`, `api.deezer.com` | `Disallow: /` | API hosts |

**My interpretation:** robots.txt governs crawlers that discover and index pages. A documented API used as documented, within its terms, with an identifying UA and within its rate limits, is not crawling. On that basis I marked A1, A2, A4, and A7 ALLOWED. **If the user prefers a strict reading, robots-clean routes exist for every ALLOWED source:**
- Wikipedia: monthly XML or HTML dumps from `dumps.wikimedia.org` (no robots.txt; returns 404).
- Wikidata: `www.wikidata.org/wiki/Special:EntityData/<QID>.json` (explicitly `Allow`ed in robots.txt).
- MusicBrainz: CC0 database dumps from `data.metabrainz.org` (no robots.txt).
- BLS: flat files on `download.bls.gov` (no robots.txt).
- Open-Meteo: no robots-clean alternative is verified. NOAA GHCN-Daily is a candidate I did not check.

**Disclosure:** before I read these robots files, I made one sample request each to `en.wikipedia.org/w/api.php` (2 pages), `musicbrainz.org/ws/2` (1 search), and `archive-api.open-meteo.com` (1 call). The archive-api robots.txt fetch errored the first time and succeeded later. All of these are cached in `data/raw/_scout/samples/`.

---

## ALLOWED sources

### A1. Wikipedia tour articles (box office per show)
- **URL:** https://en.wikipedia.org/w/api.php (dumps: https://dumps.wikimedia.org/enwiki/)
- **Access:** MediaWiki Action API, `action=parse&prop=wikitext` or `action=query&prop=revisions&rvprop=content|ids`
- **Fields:** per show: date, city, country, venue, opening act, **attendance ("sold / available")**, and **revenue (gross, USD)**. Average price = gross ÷ tickets sold. Also tour-level totals and the article's citations (usually Billboard Boxscore or Pollstar). Confirmed in the sample `samples/wiki_parse_guts_world_tour.json`: the *Guts World Tour* table has `Attendance` like `9,998 / 9,998` and `Revenue` like `$1,733,194`.
- **Serves:** LEVEL target (log average price), sell-out rate (sold ÷ capacity), and the artist-relative price.
- **Auth:** none.
- **Rate limits:** API:Etiquette says "There is no hard speed limit on read requests", asks for serial requests, recommends `maxlag`, and requires a descriptive User-Agent (Wikimedia User-Agent Policy).
- **License:** text is CC BY-SA 4.0. Gross and attendance figures are facts, sourced to Billboard Boxscore and Pollstar. Any redistributed table derived from it needs attribution and share-alike.
- **robots.txt:** `Disallow: /w/` for `*`. See the API-host note above. Dumps are the strict fallback.
- **Caveats:** coverage is biased toward big tours that report to Boxscore, and later legs are often missing figures. Figures are promoter-reported and sometimes aggregated across multi-night stands, with one figure for 2–4 shows. Tables use `rowspan` (careful parsing needed). Currencies are mostly USD but not always. Gross can include fees and VIP packages inconsistently. Article titles move, so record `revid`.
- **Collection spec:**
  - Seed list: tours linked from `List of highest-grossing concert tours`, `List of highest-grossing concert tours by women`, and the year lists of highest-grossing tours (e.g. `List of highest-grossing concert tours of 2023`), plus each tour's `List of ... tour dates/shows` subpage when it exists. Scope: tours starting 2010–2026.
  - Calls: `action=query&prop=revisions&rvprop=content|ids&rvslots=main&titles=<up to 50 joined by |>&format=json&formatversion=2&maxlag=5`, batched 50 titles per call.
  - Fields to keep: title, revid, timestamp, raw wikitext. Parse later into `show_date, city, country, venue_wikilink, tickets_sold, tickets_available, gross_usd, currency_note, footnotes`.
  - Expected volume: about 400–800 articles (16 or fewer batched calls for content, plus link discovery), about 15–30k show rows, and under 200 MB raw.
  - Rate: 1 request at a time, at least 5 s apart, UA `TicketPriceResearch/0.1 (personal research; contact: rudraayyagari@gmail.com)`. Stop on any 429 or 403.
  - Cache: `data/raw/wikipedia/<title-slug>__<revid>.json`.
  - License to carry forward: **CC BY-SA 4.0. Attribute Wikipedia and the page revision. Derived tables shared publicly must be CC BY-SA.**
- **Route actually used (collector-prices, 2026-10-18; strict robots reading per DECISIONS.md):** enwiki dump `20261001` from dumps.wikimedia.org, not the Action API.
  - `dumps.wikimedia.org/robots.txt` returns 404 (no rules), cached at `data/raw/wikipedia_dumps/meta/robots.txt`. Usage note on the front page (cached at `meta/index.html`): the WMF User-Agent Policy is enforced for dumps, and "Downloads are also rate limited and capped at 3 connections per-IP". The team stays at 2 connections or fewer (lead instruction) and coordinates through a shared lock file in `src/wikidump_http.py` (at least 5 s between request starts, across processes).
  - Files: `enwiki-20261001-pages-articles-multistream-index.txt.bz2` (285 MB, sha1 verified against `dumpstatus.json`), plus serial HTTP Range requests for only the bz2 streams that hold candidate tour pages in `enwiki-20261001-pages-articles-multistream.xml.bz2` (26.9 GB; never downloaded whole, because the observed throughput of about 100 KB/s per connection would take about 3 days). The candidate titles come from title patterns in the index, minus redirects, which are identified from `enwiki-20261001-redirect.sql.gz` (downloaded by collector-features).
  - No 403s, 429s or challenges so far. Two dropped connections on the index download were resumed with a Range request.
  - Cache: `data/raw/wikipedia_dumps/streams/20261001/<start>-<end>.bz2` (raw stream bytes), `pages/20261001/<page_id>__<revid>.json` (extracted tour pages), and `fetch_log.jsonl`. Code: `src/collect_wikipedia_boxoffice.py` and `src/boxoffice_parse.py`.

### A2. Wikidata (venues and artists)
- **URL:** https://www.wikidata.org/wiki/Special:EntityData/ ; https://query.wikidata.org/sparql
- **Fields:** venue: `P1083` maximum capacity (**multiple values, with `P518` "applies to part" or configuration qualifiers**; Madison Square Garden returns 18,006 / 18,500 / 19,812 / 20,000 / 20,789 in `samples/wikidata_sparql_msg.json`), `P31` instance of (indoor arena, stadium, amphitheatre, which gives indoor/outdoor), `P625` coordinates, `P131` location, `P571` inception. Artist: `P136` genre, `P434` MusicBrainz ID, `P2031` work period start, `P571` formation, `P27`/`P495` country.
- **Serves:** LEVEL features (capacity, venue type, career age, genre) and the join keys (QID ↔ MBID).
- **Auth:** none.
- **Rate limits:** WDQS allows "60 seconds of processing time each 60 seconds" per client, 30 error queries per minute, 5 parallel queries per IP, and a 60 s timeout. Respect 429 with `Retry-After`.
- **License:** structured data is CC0 1.0.
- **robots.txt:** `query.wikidata.org` has `Disallow: /sparql`. `www.wikidata.org` explicitly `Allow: /wiki/Special:EntityData/*.`
- **Caveats:** capacity varies by configuration (concert vs. sports) and changes over time. Indoor/outdoor must be inferred from `P31`. Some venues have no item, and venue renames need alias matching.
- **Collection spec:**
  - Prefer EntityData: `GET https://www.wikidata.org/wiki/Special:EntityData/<QID>.json` for each venue and artist QID resolved from Wikipedia wikilinks via `action=query&prop=pageprops&ppprop=wikibase_item` (batched 50).
  - Optional SPARQL: `VALUES ?v { ... }` in batches of 200 or fewer, selecting capacity with qualifiers `P518` and `P585`, plus `P31` and `P625`.
  - Volume: about 2–5k venues and about 1–3k artists, about 5–8k requests, about 300 MB.
  - Rate: 1 request at a time, at least 5 s apart. Cache: `data/raw/wikidata/<QID>.json`.
  - License: **CC0. No restrictions; cite Wikidata.**

### A3. Wikimedia Pageviews API (hype)
- **URL:** `https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/en.wikipedia/all-access/user/<Article>/daily/<YYYYMMDD>/<YYYYMMDD>`
- **Fields:** daily views per article, from 2015-07-01 onward. Confirmed in `samples/pageviews_sample.json` (e.g. `Olivia_Rodrigo` 2025-01-01: 8,480 views).
- **Serves:** LEVEL (artist hype before on-sale) and PATH covariates (daily attention near the show).
- **Auth:** none.
- **Rate limits:** the access policy requires a User-Agent: "wait for each request to finish before sending another", and "Your client may be blocked if you endanger the stability of the service."
- **License:** "Data provided by the API is available under the CC0 1.0 license."
- **robots.txt:** `wikimedia.org/robots.txt` returns 404, so there are no restrictions.
- **Caveats:** this measures English Wikipedia only. Bot filtering is imperfect (use `agent=user`). Page renames split history, so follow redirects. Spikes come from news, deaths, and scandals, not only tours.
- **Collection spec:** one call per artist (and optionally per tour article) for `20150701` → `20261017`, about 1–3k calls returning about 4k daily rows each. Rate: at least 5 s apart. Cache: `data/raw/wikimedia_pageviews/<article>.json`. License: **CC0**.

### A4. MusicBrainz (artist identity and metadata)
- **URL:** https://musicbrainz.org/ws/2/ ; dumps: https://data.metabrainz.org/pub/musicbrainz/data/fullexport/
- **Fields:** MBID, type (person or group), country, begin date (career age), gender, area, aliases, URL relations (Wikidata, Wikipedia, Spotify IDs), and tags and genres. Confirmed in `samples/mb_artist_search.json`.
- **Serves:** the cross-source join key (MBID) and LEVEL features.
- **Auth:** none.
- **Rate limits:** "1 request per second" per IP on average. Every request "needs to include a User-Agent header" that identifies the app and a contact.
- **License:** "The core data of the database is licensed under the CC0." **Supplementary data (tags, ratings) and the Live Data Feed are CC BY-NC-SA 3.0** (https://musicbrainz.org/doc/About/Data_License).
- **robots.txt:** `Disallow: /ws`, `Crawl-delay: 2`. See the API-host note. Dumps are robots-clean.
- **Caveats:** name matching is ambiguous, so use the Wikidata `P434` link first and the search score second. Genres and tags are crowd-sourced and sparse.
- **Collection spec:** resolve MBIDs from Wikidata `P434`. For the remainder, `GET /ws/2/artist/?query=artist:"<name>"&limit=3&fmt=json`, then `GET /ws/2/artist/<mbid>?inc=tags+genres+url-rels&fmt=json`. About 1–3k artists, 2–6k calls, at least 5 s apart (stricter than the 1 req/s limit). Cache: `data/raw/musicbrainz/<mbid>.json`. License: **core CC0; tags and genres are CC BY-NC-SA 3.0 (non-commercial, share-alike), so keep them in a separate column set.**

### A5. ListenBrainz popularity
- **URL:** `https://api.listenbrainz.org/1/popularity/artist` (POST `{"artist_mbids": [...]}`)
- **Fields:** `total_listen_count` and `total_user_count` per artist (all-time, current snapshot).
- **Serves:** LEVEL popularity feature, as a partial replacement for Spotify popularity.
- **Auth:** not stated for popularity endpoints. Docs: clients "never make more than ONE call per second", User-Agent with contact required.
- **License:** CC0 per MetaBrainz/ListenBrainz (from the dumps docs and secondary sources; I did not read a license page directly).
- **robots.txt:** `api.listenbrainz.org/robots.txt` returns **410 Gone** (no file).
- **Caveats:** small, tech-skewed user base. This is all-time totals, not a time series, so it can't be time-matched to show dates.
- **Collection spec:** batched POSTs of 100 MBIDs or fewer, about 10–30 calls, at least 5 s apart. Cache: `data/raw/listenbrainz/popularity_<batch>.json`. License: **CC0**.

### A6. Ticketmaster Discovery API v2
- **URL:** https://app.ticketmaster.com/discovery/v2/events.json and `/events/{id}.json`. Docs: https://developer.ticketmaster.com/products-and-docs/apis/discovery-api/v2/. Terms: https://developer.ticketmaster.com/support/terms-of-use/ (Last Updated June 27, 2023).
- **Fields:** event id, name, `dates.start.localDate/dateTime`, `dates.status.code` (onsale, offsale, cancelled, rescheduled), `sales.public.startDateTime/endDateTime`, presales, **`priceRanges[] {type, currency, min, max}`**, `classifications` (segment, genre, subGenre), `_embedded.venues` (id, name, city, state, location, timezone), and `_embedded.attractions` (artist ids).
- **Serves:** LEVEL features: primary face-value range, genre, on-sale lead time, day of week, and venue. **PATH (weak):** daily forward snapshots of `priceRanges` show *primary* repricing (dynamic or tiered pricing) and status changes. They do **not** show resale prices, and nothing is available retroactively.
- **Auth:** **API key required.** No `TICKETMASTER_API_KEY` exists yet. The user must register at developer.ticketmaster.com and put `TICKETMASTER_API_KEY=...` in `.env` at the project root (never commit it).
- **Rate limits:** "default quota of 5000 API calls per day and rate limitation of 5 requests per second". Deep paging: "we only support retrieving the 1000th item. i.e. ( size * page < 1000)".
- **Terms (paraphrased and quoted):** non-exclusive, non-transferable license. Don't "Cache or store any Event Content other than for reasonable periods in order to provide the service you are providing". Don't sell, lease, or sublicense, or replicate Ticketmaster.com's user experience. TM "may rate limit or block applications that make a large number of calls". The terms say nothing about research, ML, or scraping.
- **robots.txt:** `app.ticketmaster.com/robots.txt` returns 404 (no rules). `developer.ticketmaster.com` allows all.
- **Caveats:** `priceRanges` is often missing. That's a widely reported problem I did not verify; the pilot should measure the fill rate. Ranges are min/max face (sometimes excluding fees), not a distribution. Platinum and VIP pricing can distort `max`. The storage clause makes multi-month panels a gray area, so I filed a clarification request (PERMISSION_REQUESTS.md, entry 0). Coverage is TM-ticketed events only.
- **Collection spec:**
  - (a) Weekly event census: `GET /discovery/v2/events.json?apikey=$KEY&classificationName=music&countryCode=US&startDateTime=<d>T00:00:00Z&endDateTime=<d+1>T00:00:00Z&size=200&page=<n>`, sliced by day (and by `stateCode` when a day has more than 1,000 results). About 120 days ahead × 1–5 pages, so about 300–600 calls per week.
  - (b) Daily panel for PATH-lite: `GET /discovery/v2/events/{id}.json` for up to about 3,500 tracked events, from 60 days out to the show date.
  - Budget: stay at 4,500 calls/day or fewer (90% of quota), at 1 req/s or slower.
  - Fields to keep: id, name, attraction ids and names, venue id/name/city/state/lat/lon, `dates.*`, `sales.*`, `priceRanges`, `classifications`, plus the poll timestamp.
  - Volume: about 4.5k calls/day, about 25–50 MB/day gzipped.
  - Cache: `data/raw/ticketmaster/<YYYY-MM-DD>/<id or slice>.json.gz`.
  - License notes: **no redistribution of raw data, no public dataset release, keep raw files only for the project's duration (pending TM's clarification), and attribute "Data from Ticketmaster Discovery API".**

### A7. Open-Meteo Historical Weather API
- **URL:** https://archive-api.open-meteo.com/v1/archive. Terms: https://open-meteo.com/en/terms
- **Fields:** daily `temperature_2m_max/min`, `precipitation_sum`, `rain_sum`, `snowfall_sum`, `wind_speed_10m_max`, and hourly values if needed. Confirmed in `samples/openmeteo_sample.json`.
- **Serves:** features (show-day weather, which matters most for outdoor venues and walk-up resale).
- **Auth:** none.
- **Rate limits:** "Less than 10'000 API calls per day, 5'000 per hour and 600 per minute", and 300k per month.
- **License/terms:** "You may only use the free API services for non-commercial purposes." Data is "provided under the terms of the CC-BY 4.0 licence". Their examples list "Public research conducted at public institutions" as non-commercial and "Undisclosed research at commercial entities" as commercial. Personal non-commercial research fits the free tier.
- **robots.txt:** `archive-api.open-meteo.com`: `Disallow: /` (API host; see the note above). `open-meteo.com`: allows all.
- **Caveats:** this is reanalysis (ERA5-based) at grid resolution, not a station reading. Snap coordinates to the venue.
- **Collection spec:** one call per venue covering all show dates in that venue's range (`start_date`/`end_date`), about 2–5k calls at least 5 s apart. Cache: `data/raw/open_meteo/<venue_qid>.json`. License: **CC BY 4.0, attribute "Weather data by Open-Meteo.com"; non-commercial only.**
- **Incident log (collector-context):** 2026-10-19 ~17:38 PDT, after 808 calls that UTC day: one 2xx response whose body wasn't JSON ("Expecting value: line 1 column 1": empty, or starting with "<"). **Its status and body were not captured**, so it can't be classified after the fact: it was either a transient empty body or an unrecognised page. There was no 403/429 and no other pushback. Earlier that evening there were ~9 read timeouts (120 s) on 20-venue × 14-day requests. Response: requests now hold a cross-process lock with end-to-start ≥ 5 s spacing and are logged in `data/raw/_requests/archive-api.open-meteo.com.csv`. Any 403/429, challenge page or non-JSON 2xx stops the run and is saved to `data/raw/_bad_responses/`. 5xx, empty bodies and timeouts back off (60 s, 120 s) and stop as NetworkDown after 3 in a row. The job runs under `src/context_supervise.py`.

### A8. US Census ACS (bulk downloads)
- **URL:** https://www2.census.gov/programs-surveys/acs/ (ACS 5-year tables, e.g. B19013 median household income and B01003 population, by CBSA)
- **Serves:** LEVEL features (metro income, metro size).
- **Auth:** none for file downloads.
- **Terms:** Census data are US-government works. The Data API ToS asks services to display "This product uses the Census Bureau Data API but is not endorsed or certified by the Census Bureau" (for the API route) and prohibits re-identification.
- **robots.txt:** `www2.census.gov` has an empty `User-agent: *` group (allows all), with crawl-delays only for named bots.
- **Caveats:** ACS 5-year values are period averages. Map venue city → CBSA via the Census CBSA delineation file.
- **Collection spec:** download ACS 5-year table files for B19013 and B01003 at the CBSA level for vintages 2015–2024 (about 10 files or table extracts, under 500 MB), plus the CBSA delineation file. At least 5 s between files. Cache: `data/raw/census_acs/<vintage>/`. License: **public domain (US Gov). Cite the Census Bureau and don't imply endorsement.**

### A9. BLS CPI-U (deflator)
- **URL:** https://download.bls.gov/pub/time.series/cu/ (`cu.series`, `cu.data.1.AllItems`, and the regional series)
- **Serves:** deflating gross and price to constant dollars for LEVEL across 2010–2026.
- **Auth:** none.
- **Terms:** BLS prohibits "excessive robot activity" and "reserves the right to block robots that do not contain information that can be used to contact the owner" (https://www.bls.gov/bls/pss.htm). Our UA includes contact info. I assumed BLS data is public domain as US-government work; I did not read its copyright page.
- **robots.txt:** `download.bls.gov` returns 404 (none). `api.bls.gov` has `Disallow: /`, so use the flat files, not the API.
- **Collection spec:** 3–5 files, one fetch each, at least 5 s apart. Cache: `data/raw/bls_cpi/`. License: **public domain (assumed); cite BLS.**

### A10. US federal holidays and calendar features
- **URL:** https://www.opm.gov/policy-data-oversight/pay-leave/federal-holidays/ and the `holidays` PyPI package (MIT license, offline)
- **Serves:** features (holiday weekend, day of week, summer).
- **robots.txt:** `www.opm.gov` disallows only `/Search`, login, and print paths, so the holiday pages are allowed.
- **Collection spec:** prefer the offline `holidays` package, which needs no network. Optionally fetch OPM pages for 2010–2026 to cross-check (17 pages or fewer, at least 5 s apart). Cache: `data/raw/holidays/`. License: **public domain (OPM); MIT (library).**
- **Gap:** no national school-calendar source exists. See Coverage gaps.

### A11. Published papers and industry articles (manual)
- See LITERATURE.md. Use them to read benchmarks (e.g. Pollstar year-end average ticket prices: $135.92 in 2024 and $132.62 in 2025 for the Top 100 tours) and to set priors. **Manual reading and citation only.** No automated collection from Billboard (see N9) or Pollstar (N8).


### A12. Federal Reserve G.5/H.10 foreign exchange rates (added 2026-10-19 by collector-context)
- **URLs:** G.5/H.10 Data Download Program bulk file, `https://www.federalreserve.gov/datadownload/Output.aspx?rel=H10&filetype=zip` (one SDMX/ZIP, 2.1 MB zipped, all history, all series). Plus H.10 historical daily plain-text files for the euro-legacy currencies dropped from G.5: `https://www.federalreserve.gov/releases/h10/hist/dat89_<cc>.txt` (1971–1989) and `dat96_<cc>.txt` (1990–1998), and `dat00_gr.txt` for Greece (to 2000).
- **Serves:** a check of whether "$" grosses at non-US shows are really USD, and conversion of local-currency figures. Monthly, units per USD, 1971 on.
- **Auth:** none.
- **robots.txt:** `www.federalreserve.gov/robots.txt` returns **404** (no robots file, so no crawl restrictions). Evidence: `data/raw/fx/_robots_www.federalreserve.gov.txt`.
- **Terms:** Board website policies (https://www.federalreserve.gov/disclaimer.htm, cached in `data/raw/fx/_terms_disclaimer.html`): "Unless otherwise indicated, information on Board's website is in the public domain and may be copied and distributed without permission. Please cite to the Board as the source of the information."
- **Caveats:** (1) The DDP application is being retired; its header says the "Build Your Package" feature goes the week of November 9 (2026), and points to the release pages. The all-data ZIP is cached, so rebuilds don't need it. (2) The `.htm` versions of the historical pages carry a Cloudflare script tag; only the `.txt` files are used, and no challenge was served. (3) G.5 has no ARS, CLP, COP, PEN, PLN, CZK, HUF, RON, TRY, ILS, AED, RUB, PHP, IDR or MOP; MXN starts 1993-11, BRL 1995-01, CNY/HKD/SGD/THB 1981, KRW 1981-04, TWD 1983-10.
- **Collection spec (done):** 1 ZIP + 25 daily text files (11 legacy currencies × 2 periods, Greece 1999–2000, and 2 JPY files for validation), plus index, terms and 2 probe pages, at least 5 s apart, honest UA. Cache: `data/raw/fx/`. Built by `src/build_fx.py` into `data/interim/fx_monthly.parquet`. License: **public domain (US Government / Federal Reserve Board); cite "Board of Governors of the Federal Reserve System, G.5/H.10 Foreign Exchange Rates."**
- **Not used:** FRED. The Fed's own files serve the same G.5 series, so FRED's robots and terms weren't needed.


### A13. ECB euro foreign exchange reference rates (added 2026-10-19 by collector-context)
- **Status:** collected; not required for the $=USD test per skeptic review (2026-10-19). Kept in fx_monthly as flagged `is_cross_rate` rows at the lead's decision.
- **URL:** `https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist.zip`: one CSV with every daily reference rate since 1999-01-04, 41 currencies against EUR. Linked from the ECB's euro reference rates page.
- **Serves:** FX for currencies the Fed doesn't publish (A12 gaps): CZK, HUF, PLN, RON/ROL, TRY/TRL, RUB, BGN, HRK, ISK, ILS, PHP, IDR, and the pre-euro currencies of the 2007–2015 joiners. Crossed to units per USD via the same day's USD/EUR rate.
- **Auth:** none.
- **robots.txt:** `www.ecb.europa.eu` allows `/stats/` for `*`. It disallows only translated `_content.*.html` pages, some media folders and `/euro/changeover/shared/data/`, and sets **`Crawl-delay: 5`**, which our ≥ 5 s spacing meets. Evidence: `data/raw/fx_ecb/_robots_www.ecb.europa.eu.txt`.
- **Terms:** ECB "Disclaimer & copyright" (cached `data/raw/fx_ecb/_terms_disclaimer.html`): "users of this website may make free use of the information obtained directly from it subject to the following conditions: When such information is distributed or reproduced, it must appear accurately and the ECB must be cited as the source. [...] If the information is modified by the user (e.g. by seasonal adjustment of statistical data or calculation of growth rates) this must be stated explicitly." (The exception covers authored documents such as Working Papers, not statistics.) The rates page adds: "published for information purposes only. Using the rates for transaction purposes is strongly discouraged." Research use is fine.
- **Caveats:** ECB rates are fixed around 14:15 CET, not at New York noon. ECB-crossed vs Fed G.5 monthly averages differ by a median 0.05–0.07% (8 overlapping currencies). Some series are suspended or discontinued (ISK 2008–2018, RUB after 2022-03). No ARS, CLP, COP, PEN or other Latin American currencies except BRL and MXN, which the Fed already covers.
- **Collection spec (done):** 1 ZIP plus robots, terms and rates page, ≥ 5 s apart, honest UA. Cache: `data/raw/fx_ecb/`. Used by `src/build_fx.py` only for currencies absent from A12. License: **free use; cite "European Central Bank, euro foreign exchange reference rates", and state that the data were modified (crossed via USD/EUR and averaged by month)**, as fx_monthly.md does.

---

## NEEDS PERMISSION sources (detail; outreach drafts are in PERMISSION_REQUESTS.md)

### N1. StubHub (incl. viagogo)
- **URL:** https://www.stubhub.com. Terms: https://www.stubhub.com/legal?section=ua (cached: `terms/stubhub_legal_ua.html`)
- **Would give:** per-listing resale prices (all-in and face), section, row, quantity, and listing timestamps. This is the core of **PATH**.
- **Terms:** "use any robot, spider, scraper or other automated means to access our Site or Services for any purpose without our express written permission" is prohibited.
- **robots.txt:** allows event pages except `/secure/`, `/AjaxService/`, `/landingpage/`, and similar. That's irrelevant given the terms.
- **API:** no public API. Partner and affiliate access only.
- **Verdict:** NEEDS PERMISSION. **Do not scrape.**

### N2. SeatGeek (public API and website)
- **URL:** https://api.seatgeek.com/2 ; developer portal https://developer.seatgeek.com (a JS SPA that showed only "Loading" to our fetcher); API terms https://seatgeek.ca/api-terms
- **Would give:** event-level `stats` (lowest, average, highest, median price, listing count). Partner access would add listings. Daily `stats` snapshots would be a strong PATH proxy.
- **What happened:** `seatgeek.com/robots.txt` returned **403 with a DataDome CAPTCHA page**, and `seatgeek.ca/api-terms` returned **403**. Per the rules I stopped. `api.seatgeek.com/robots.txt` is `Disallow: /`. I couldn't confirm whether new developers can still get a `client_id` or what the current API terms say. A third-party claim of 1,000 requests/hour is unverified.
- **Verdict:** NEEDS PERMISSION.

### N3. Vivid Seats
- **Terms:** https://www.vividseats.com/terms (Global Terms, Effective July 22, 2026; cached `terms/vividseats_terms.html`). §17.3.3: you may not "crawl, scrape, or otherwise harvest data or information from any part of the Vivid Seats Marketplace (including the Website) other than as permitted under these Terms of Use".
- **robots.txt:** event pages are allowed. Search, cart, and `/account*` are disallowed.
- **Verdict:** NEEDS PERMISSION. Affiliate access reportedly runs via the Impact network (unverified).

### N4. Gametime
- **Terms:** https://gametime.co/terms-of-service (cached). §1.D prohibits "copying, distributing, or disclosing any part of the Service in any medium, including without limitation by any automated or non-automated 'scraping'" and robots that send more requests than a human with a browser could.
- **robots.txt:** `Disallow: /*listings`.
- **Would give:** last-minute (final hours) prices, which are uniquely valuable for the tail of PATH.
- **Verdict:** NEEDS PERMISSION.

### N5. TicketData.com
- **What happened:** `ticketdata.com/terms` returned **403** to our fetcher, so I stopped. Its robots.txt is the Cloudflare-managed file (`Content-Signal: search=yes,ai-train=no`; blocks AI crawlers).
- **Would give:** per Digital Music News (2025-10-21), "over a decade" of historical resale "Get-In Price" series per event (lowest price incl. fees, outliers removed). That would be **the single best ready-made PATH dataset** if they'll share it.
- **Verdict:** NEEDS PERMISSION.

### N6. TickPick
- **robots.txt:** event pages allowed. `/ajax/`, `/bid-*`, `/buy-*-tickets/`, and `/myaccount/*` are disallowed.
- **Terms:** my fetch of `/terms-of-service/` returned 404. The terms are **not verified**.
- **Verdict:** NEEDS PERMISSION (until terms are read). Low priority.

### N7. Rebrowser datasets (StubHub, SeatGeek, Gametime) on Hugging Face and Kaggle
- **URLs:** https://huggingface.co/datasets/rebrowser/stubhub-dataset , `.../seatgeek-dataset`, `.../gametime-dataset` (cards cached in `data/raw/_scout/hf/`). Research program: https://rebrowser.net/free-datasets-for-research
- **Contents:** StubHub event listings: **142,329,866 records, 2024-03-31 → 2026-10-11**, daily snapshots with `price` (all-in), `faceValue`, section, row, quantity, `availableQuantities`, `_firstSeenAt`/`_lastSeenAt`. Gametime: 36.8M listings since 2025-11-16 with `priceTotal`, `pricePrefee`, `salesTax`. SeatGeek: events with price stats and cross-IDs (`ticketmasterId`, `stubhubId`).
- **License:** cards say CC BY-NC-4.0, but the public samples are capped at 30,000 rows and **price fields are locked (🔒)**. The free research grant is "a specific, non-commercial academic or coursework project", "one-time historical CSV", with no redistribution.
- **Provenance problem:** Rebrowser sells "undetectable cloud browsers" and scraping services. The underlying data was almost certainly collected from sites whose terms prohibit automated access (N1, N2, N4). Using it would indirectly rely on bot-detection evasion, which this project's rules forbid us from doing ourselves. Rebrowser's CC BY-NC label can't grant rights it may not hold.
- **Verdict:** NEEDS PERMISSION, **and needs an explicit lead or user decision on provenance first.** My recommendation is not to use it as a primary source unless the marketplace (StubHub) also consents or the user accepts the risk in writing.

### N8. Pollstar (Data Cloud / Boxoffice)
- **Would give:** per-show gross, tickets sold, capacity, and **ticket price range (low/high)** for about 319k artists since 1999. That's the standard academic LEVEL source (used by Krueger, Courty & Pagliero, and Bennett et al.).
- **Access:** paid subscription ("Ultimate" tier includes Data Cloud). Demo or sales form: https://pages.pollstar.com/request-a-free-demo
- **robots.txt:** `Disallow: /data-cloud/*?`. The terms page URL I tried returned a 404 page, so the terms are **not verified**.
- **Verdict:** NEEDS PERMISSION (paid license or an academic arrangement).

### N9. Billboard Boxscore (automated collection)
- **Terms:** PMC Terms of Use (served at billboard.com/terms-of-use; Last updated August 21, 2026; cached). They forbid using "artificial intelligence systems, machine learning models or tools, software robots, spider, crawlers, or other data gathering, analysis or extraction tools, whether automated or manual, to access, acquire, copy, monitor, scrape or aggregate the Services". Use is "only for your personal, non-commercial use".
- **robots.txt:** `*` may crawl articles. Named AI agents (`anthropic-ai`, `ClaudeBot`, `GPTBot`, and others) are `Disallow: /`.
- **Note:** most Wikipedia per-show figures (A1) already come from Boxscore, so A1 covers most of this need.
- **Verdict:** NEEDS PERMISSION for any systematic extraction.

### N10. openICPSR 161484: Bhave & Budish replication package
- **URL:** https://www.openicpsr.org/openicpsr/project/161484/view (DOI 10.3886/E161484V1)
- **Contents:** an anonymized Ticketmaster 2007 primary-market auction dataset plus all associated eBay resale activity (Jan 2007–Apr 2008), with HTML files and code, per the search summary.
- **What happened:** the landing page returned **403** to our fetcher, so the license and terms are not verified. openICPSR downloads require a free login and accepting terms, which I can't do.
- **Verdict:** NEEDS PERMISSION as a **user action**: the user logs in, reads the license, and downloads manually into `data/raw/openicpsr_161484/`.

### N11. Last.fm API
- **Terms:** https://www.last.fm/api/tos §3.1: "You are permitted to use the Last.fm Data solely for non-commercial purposes". Usage cap: "a maximum of 100 MB". Attribution ("powered by AudioScrobbler") is required. **https://www.last.fm/api: for "commercial or research/academic purposes", "contact us prior to use via email at partners@last.fm."**
- **robots.txt:** `ws.audioscrobbler.com` returns 404.
- **Would give:** artist listeners, playcount, and tags.
- **Verdict:** NEEDS PERMISSION (research use requires prior contact). API key also needed.

### N12. setlist.fm API
- **Terms:** https://www.setlist.fm/help/terms. "You are permitted to use the API solely for non-commercial purposes". Developers may not "retain any copies of the Setlist.fm data" except cached "for short periods". Attribution is required. Scraping the site is prohibited.
- **Docs:** https://api.setlist.fm/docs/1.0/index.html. The key comes from setlist.fm/settings/api after login, sent as an `x-api-key` header. Commonly cited limits of 2 req/s and 1,440/day are **unverified**.
- **Would give:** shows per tour, setlist length, and the tour name per date (useful for linking shows to tours and for features like show count).
- **Verdict:** NEEDS PERMISSION, because the no-retention clause conflicts with building a research dataset.

### N13. Google Trends (official API, alpha)
- **Announced** 2025-07-24 (https://developers.google.com/search/blog/2025/07/trends-api). It's alpha and application-only, with about 1,800 days of history and daily, weekly, or monthly aggregation (per secondary reports).
- **robots.txt (trends.google.com):** `Disallow: /explore?` and `/trends/explore?`.
- **Verdict:** NEEDS PERMISSION (apply for alpha access). Manual CSV export from the UI for a handful of artists is fine for spot checks but won't scale.

### N14. US Census Data API
- `https://api.census.gov/robots.txt` returned a firewall page ("Request Rejected"), so I stopped. The API needs a free key (signup at api.census.gov/data/key_signup.html). The ToS has the disclaimer and no-re-identification clauses (https://www.census.gov/data/developers/about/terms-of-service.html).
- **Verdict:** NEEDS PERMISSION or user action (get a key, then verify access). **Not needed**, because A8 covers the same data.

### N15. Internet Archive Wayback Machine (snapshots of resale price pages)
- `web.archive.org/robots.txt` returns 404. The archive.org terms page is JS-rendered and returned no text to our fetcher. My recollection is that access is "for scholarship and research purposes only", but that's **unverified**. A 2026 blog reports new 429 throttling. Resale pages are client-rendered, so snapshots rarely contain prices.
- **Verdict:** NEEDS PERMISSION (verify terms). Expected yield is low.

### N16. Songkick API
- Key requests are "handled manually". A secondary source reports that Warner sold Songkick to Suno in November 2025 (unverified). `songkick.com` robots.txt blocks many AI bots. I couldn't confirm the current API status or terms.
- **Verdict:** NEEDS PERMISSION. Low value, because MusicBrainz, setlist.fm, and Ticketmaster cover event calendars.

### N17. Deezer API
- **Terms** (https://developers.deezer.com/termsofuse §IV): use is "strictly limited for a non-commercial purpose", for "strictly private use within a family scope". Other uses "shall be beforehand reviewed and approved by DEEZER". `api.deezer.com/robots.txt` is `Disallow: /*`.
- **Would give:** artist `nb_fan` (fan count), a Spotify-follower substitute.
- **Verdict:** NEEDS PERMISSION.

### N18. AXS and Live Nation (web)
- Both `axs.com/about-terms-of-use` and `livenation.com/terms` returned **403** to our fetcher, so I stopped. Live Nation is Ticketmaster's parent, so prefer A6.
- **Verdict:** NEEDS PERMISSION. Low priority.

### N19. Kaggle community concert datasets
- Searches found Wikipedia-derived tour tables (e.g. `gayu14/taylor-concert-tours-impact-on-attendance-and`, `amruthayenikonda/dirty-dataset-to-practice-data-cleaning`, `tymonbot/taylor-swift-eras-toure`), Kaggle mirrors of the Rebrowser datasets (N7), and the FiveThirtyEight NFL ticket prices dataset (2014, not concerts). Licenses were **not verified** (Kaggle pages are JS-rendered), and the Kaggle API needs the user's token. `kaggle.com/robots.txt` returned an HTML page (404).
- **Verdict:** NEEDS PERMISSION (license check per dataset). **Low value**, because A1 is the original source of the tour tables.

---

## PROHIBITED sources

### P1. Spotify Web API
- **Developer Policy** (https://developer.spotify.com/policy) III.13: "Do not analyze the Spotify Content or the Spotify Service for any purpose", including "creating new or derived listenership metrics, benchmarking". III.14: "Do not use ... any Spotify Content to train a machine learning or AI model".
- **Developer Terms** v10 (effective 15 May 2025) IV.3.a.1: "you may not store, aggregate or create compilations or databases of Spotify Content".
- **API changes:** Nov 27 2024 blocked new apps from Related Artists, Recommendations, and Audio Features (https://developer.spotify.com/blog/2024-11-27-changes-to-the-web-api). The **February 2026 changelog removed artist `followers` and `popularity` and track `popularity`** from Development Mode responses, and Dev Mode now needs the owner to have Premium (https://developer.spotify.com/documentation/web-api/references/changes/february-2026).
- **Verdict:** PROHIBITED. The fields we wanted are gone, and analysis is barred anyway.

### P2. `pytrends` and other unofficial Google Trends clients
- An unofficial client of undocumented endpoints, archived 2025-04-17, with frequent 429s reported. Google's terms bar automated access that doesn't follow its machine-readable instructions.
- **Verdict:** PROHIBITED. Use N13 instead.

### P3. Bandsintown API
- Data Applications Terms (https://corp.bandsintown.com/data-applications-terms, last updated 2019-02-25): meant "solely by artists, or people working in connection with or on behalf of artists". They prohibit aggregating Bandsintown content with third-party content and using "any automated means" to collect. `bandsintown.com` and `rest.bandsintown.com` returned **403 (Cloudflare block)** on our robots.txt request.
- **Verdict:** PROHIBITED for this project.

### P4. Ticketmaster.com web pages (scraping)
- The consumer Terms of Use (https://legal.ticketmaster.com/terms-of-use/, effective Aug 12 2025) are JS-rendered, so I couldn't read the body. A court filing that quotes them (thetmca.com, 17-cv-07232) describes a ban on bots or spiders that "retrieve, index, 'scrape,' 'data mine'". robots.txt disallows `/api/ismds/event`, `/event-queue`, checkout, and other paths.
- **Verdict:** PROHIBITED. Use the Discovery API (A6).

---

## Coverage gaps

1. **Resale price time series for PATH (the biggest gap).** No ALLOWED source provides resale prices over time. All resale marketplaces (N1–N6) prohibit automated access or blocked us. The only ready-made series are TicketData (N5), Rebrowser (N7, with a provenance problem), and old academic data (N10: eBay 2007). Ticketmaster Discovery (A6) gives only *primary* face-price ranges, only forward from the day we start, and often has no `priceRanges` at all. **Unless N1, N2, N5, or N7 is granted, PATH will rest on (a) the literature's stylized facts and (b) primary-market repricing from A6.**
2. **Per-show price distributions.** A1 and Boxscore give only average realized price (gross ÷ sold) for tours big enough to report. There are no face-price tiers, fee breakdowns, or VIP and platinum shares. Pollstar (N8) has price low/high per show. Ticketmaster (A6) has min/max for upcoming shows only.
3. **Selection bias in LEVEL.** Wikipedia and Boxscore coverage skews to large, successful tours and sell-outs. Small club shows and under-reported legs are largely missing, so models must treat this as a truncated sample.
4. **Historical popularity.** Spotify is gone (P1). Last.fm needs permission (N11). ListenBrainz is all-time totals only (A5). Google Trends is gated (N13). **Wikipedia pageviews (A3) is the only open, daily, historical hype measure.**
5. **Sell-through and inventory over time.** No source tells us how many tickets remain unsold at T-60 … T-0.
6. **School calendars.** No national source. Approximate with month, summer, and holiday dummies, or hand-collect for the top metros.
7. **Fees.** Gross figures mix fee treatments. Resale all-in vs. pre-fee prices can't be separated without marketplace data.
8. **Non-US shows.** Census, BLS, and holiday features are US-only. Restrict LEVEL to US shows or add country-level controls.
9. **Unverified items to resolve before collection:** the SeatGeek API's current availability and terms; TickPick, Pollstar, Internet Archive, and openICPSR terms; the ListenBrainz license page; the current `priceRanges` fill rate in Discovery; the setlist.fm rate limits.
