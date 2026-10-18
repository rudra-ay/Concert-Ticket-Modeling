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

## Engineering conventions

- Python: the project virtualenv `.venv/` (gitignored). Run scripts with `.venv/bin/python`. Install extra packages with `.venv/bin/pip install` and list them in `requirements.txt`.
- Raw caches: `data/raw/<source>/` (gitignored). Intermediate tables: `data/interim/`. Final tables: `data/` (e.g. `data/shows.parquet`).
- Code lives in `src/` (collectors, features, analysis). One script per source.
- Keys only in `.env`. Load them with python-dotenv, never print or log them, and never write them into cached files or URLs that get saved.
- Only the lead commits to git.
