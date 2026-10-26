# Decisions

## Task 2: user approval of SOURCES.md (2026-10-18)

1. **All sources approved** as evaluated in SOURCES.md. The 11 ALLOWED sources may be collected under their collection specs. NEEDS PERMISSION and PROHIBITED sources stay off limits until permission arrives, except for the Rebrowser decision below.
2. **robots.txt on API hosts: strict reading, plus one exception.** Use the bulk downloads and robots-clean routes instead of the robots-disallowed API paths:
   - Wikipedia: database dumps from dumps.wikimedia.org (multistream index + byte ranges for the pages we need), not `en.wikipedia.org/w/api.php`.
   - Wikidata: `Special:EntityData/<QID>.json` (robots allows it) or the dumps, not `query.wikidata.org/sparql`.
   - MusicBrainz: CC0 database dumps, not `/ws/2`.
   - BLS CPI: flat files, not `api.bls.gov`.
   - **Exception:** Open-Meteo's historical weather API is used directly (lenient reading), for weather data only.
   - Wikimedia pageviews (REST API on wikimedia.org, or the pageview dumps) as specified in SOURCES.md.
3. **Rebrowser datasets (N7): use them.** The user accepts the provenance risk because the StubHub data is valuable for PATH. This means obtaining Rebrowser's datasets through their own channels (public samples and the free research-data program) and following their license (CC BY-NC 4.0, non-commercial, no redistribution). It does **not** permit scraping StubHub, SeatGeek, Gametime or any other marketplace ourselves; those remain NEEDS PERMISSION. The report must disclose the provenance caveat.
4. **Forward collector: build it now and start collecting** as soon as a Ticketmaster key exists. This is personal, non-commercial research. The Ticketmaster storage clarification email in PERMISSION_REQUESTS.md is sent in parallel.
5. **Keys are pending from the user.** `TICKETMASTER_API_KEY` will arrive later. Teammates do everything that doesn't need it and report exactly where it becomes mandatory. The openICPSR download is also pending.
6. **Collector efficiency: search sweep + Discovery Feed (user approved 2026-10-26: "do it", "no need to check with me").** The per-event pass spent one call per show (~4,000/day) and ran ~12 h against the rolling budget, so the 12:30 app refresh always missed the day. The search endpoint returns 200 events per call with event objects identical to `/events/{id}.json` (all top-level fields equal on 28/28 overlapping events), so `sweep` snapshots every upcoming US music event (~25-30k) in ~200-300 calls. The Discovery Feed returns every US event (~110k) in one call, without prices but with status, hotEvent, transactable and sale windows; `feed` logs each field change. Same official API and key. `daily --mode auto` runs sweep and per-event side by side until 2 days pass the `sweep-compare` gate (>=90% of per-event events found; >=99% identical price and status on pairs snapped within 6 h), then switches to sweep mode for good (per-event calls only for watchlist events the sweep missed). The `snapshots` table keeps its meaning (watchlist events, one row per day); rows copied from the sweep carry `source_url = ".../events.json (sweep)"`.

## Engineering conventions

- Python: the project virtualenv `.venv/` (gitignored). Run scripts with `.venv/bin/python`. Install extra packages with `.venv/bin/pip install` and list them in `requirements.txt`.
- Raw caches: `data/raw/<source>/` (gitignored). Intermediate tables: `data/interim/`. Final tables: `data/` (e.g. `data/shows.parquet`).
- Code lives in `src/` (collectors, features, analysis). One script per source.
- Keys only in `.env`. Load them with python-dotenv, never print or log them, and never write them into cached files or URLs that get saved.
- Only the lead commits to git.
