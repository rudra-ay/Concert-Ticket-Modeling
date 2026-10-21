# NEXT TASK (queued 2026-10-21): Concert Price Forecast ("Price Timeline")

Start only after the research tasks 6-10 (LEVEL review, PATH, final report) are done and pushed.
User's direction when queuing: "dont compromise on quality, but streamline process to make fast and utilize less tokens".
Spec below is verbatim from the user.

---

# Feature: Concert Price Forecast ("Price Timeline")

## Goal
The user enters ARTIST, CONCERT DATE, and CITY/VENUE. The app returns a forecast of resale ticket prices from today until the show. The forecast is a timeline with a median (p50) and a range (p10–p90) at each point. It also gives a best-time-to-buy window, a backtested accuracy statement for the matching segment, and a disclaimer.

## Working rules (apply throughout)
- **Checkpoints:** stop and wait for my OK at exactly three points: (1) after PLAN.md, (2) after the data feasibility report, (3) after the first backtest. Between checkpoints, keep working without asking.
- **Iterate on the sample, verify on full data.** Every command supports `SAMPLE=1` and finishes in under 30s that way. Use the sample for all development. Run on full data only at checkpoints and at the end.
- **Test proportionally.** After each change, run only the tests for the code you touched (`pytest tests/test_<area>.py -x -q`). Run the full `make test` before each commit and at each checkpoint.
- **Keep context lean.** Send long command output to `logs/<step>.log` and read only the tail or the errors. Don't print whole dataframes. Use `.head()`, `.describe()`, or shapes.
- **Never claim something works without running it.** Paste the command and the key result line as evidence.
- **Commit** after each working step with a clear message.
- **Default stack** unless the repo already uses something else: Python 3.11+, polars (pandas only where a library needs it), LightGBM, FastAPI, a single-page frontend with a lightweight chart library, pytest. Don't spend time evaluating alternatives.

## Step 0: Explore and plan (plan mode)
1. Survey the repo: structure, existing data, models, notebooks, dependencies. Summarize in 10 lines or fewer.
2. Write CLAUDE.md, kept under 60 lines: layout, `make` commands, data sources with their ToS notes, and these rules: no ToS-violating scraping, no hardcoded accuracy numbers, no simulated data presented as real, all features computed as-of snapshot_date.
3. Write PLAN.md covering data sources, schema, modeling, API, UI, and the test plan. **Checkpoint 1.**

## Step 1: Data feasibility gate (before building the pipeline)
Historical resale price snapshots are the riskiest dependency. Confirm they exist before investing in anything downstream.
- For each source (Ticketmaster Discovery API, SeatGeek API, setlist.fm, Spotify Web API, Google Trends, Kaggle or other public datasets), make one small test call or download and record:
  - which fields actually come back
  - whether it gives historical price snapshots or only current prices
  - rate limits, access requirements, and ToS constraints
- Verify current API availability rather than assuming it. Some Spotify fields have been restricted for newer apps, and pytrends is unofficial and can break. Propose a fallback for each one that fails (for example, Last.fm for artist popularity).
- Write `reports/data_feasibility.md` with a table of source × fields × history depth × usable (yes/no), plus the estimated count of events that have enough price snapshots to train on.
- If historical snapshots are thin, list exactly what's missing and propose options. One option is to start a daily snapshot collector now so history accumulates. Do not fabricate or simulate data and present it as real. **Checkpoint 2.**

## Step 2: Pipeline scripts (before feature code)
Build a `Makefile` with file-based targets so Make skips steps whose outputs are already up to date:
- `make data`: fetch into `data/raw/` as parquet. Cache on disk keyed by request, handle rate limits with backoff, and never re-download what's already cached. Put API keys in `.env` (gitignored) and add `.env.example`.
- `make collect`: append today's price snapshot for tracked events. It should be idempotent per day and safe to run on a schedule.
- `make features`: build `data/features.parquet`, vectorized with no row loops.
- `make train`: train with fixed seeds and save to `models/<version>/` with a metadata JSON (data hash, params, git SHA).
- `make backtest`: run a walk-forward backtest and write `reports/metrics.json` and `reports/backtest.md` with plots.
- `make test`, `make serve`, and `make all` (the full pipeline).
- Add a small, real data subset in `data/sample/` (a slice of fetched data, not synthetic) checked into the repo.

Target schema: one row per (event_id, snapshot_date) with price stats (min, median, and by section tier where available), days_to_event, artist, venue, city, capacity, event_date, and onsale_date.

## Step 3: Model
- **Target:** price at days_to_event as a ratio to the initial or face price, so curves are comparable across artists.
- **Features:** days_to_event, day of week, weekend flag, month, artist popularity and trend momentum, number of tour dates and number in the same city, venue capacity, city market size, days since on-sale, sell-out signals, and holiday or competing-event flags. Every feature must be computable as-of snapshot_date.
- **Order of work:**
  1. Baselines: the average curve by days-out, and the artist-tier average curve.
  2. LightGBM quantile models for p10, p50, and p90, with a small fixed tuning budget (at most 20 configs, early stopping).
  3. Sort the three predictions so quantiles never cross.
  4. If p10–p90 coverage misses 80% by more than 5 points, add conformal calibration on a held-out time slice.
  5. Keep the model only if it beats both baselines in backtest. Otherwise ship the better baseline and say so.
- **Validation:** strict time-based walk-forward splits, grouped by event so no event appears in both train and test. Add an automated test that fails if any feature uses information from after the snapshot date.
- **Best-time-to-buy definition:** the recommended window is the 7-day span with the lowest forecast p50. It counts as correct if the realized minimum price falls in that window, or if the price inside the window is within 5% of the realized minimum.
- **Report:** MAPE of p50, p10–p90 coverage, and best-buy accuracy, overall and broken down by artist popularity tier and days-out bucket, each with sample counts. **Checkpoint 3.**

## Step 4: Accuracy statement and legal safety
- NEVER hardcode an accuracy number. The UI reads only from `reports/metrics.json` for the matching segment, for example: "On N past concerts like this one, the actual price fell within our range X% of the time. Typical error: ±Y%."
- Confidence label (High, Medium, or Low) from segment sample size and segment backtest performance, with thresholds defined in config. Show "Low confidence: limited data" when it applies.
- Disclaimer on every forecast: estimates only, not financial advice, not affiliated with any ticket seller, prices can change unpredictably, use at your own risk. Add a short Terms page.

## Step 5: API and UI
- **Endpoint:** `POST /forecast` with {artist, date, location}. It returns the matched event, the timeline array (date, p10, p50, p90), the best-buy window, the confidence, the backtested accuracy for the segment, and the disclaimer.
- **Input handling:** artist autocomplete, and fuzzy matching of artist and city to a real event via the API. Cache event lookups. If there's no confident match, return "Did you mean…?" options instead of guessing.
- **UI:** timeline chart with the p50 line, a shaded p10–p90 band, a "today" marker, and the best-buy window highlighted. Mobile-friendly.
- **Tests:** API contract tests, plus one golden-sample forecast snapshot test.

## Parallelism
Use subagents only after the schema and `features.parquet` format are frozen, and only for these independent pieces:
- (a) the source clients for `make data` and `make collect`
- (b) the frontend, built against a mocked `/forecast` response
- (c) the API contract tests

Give each subagent its exact file scope and the interface it must match. Keep the modeling and backtest work in the main session.

## Extras (after the core is done and committed, each behind a flag)
Build these in order, and stop after #3 to show me:
1. Buy-now vs. wait: the probability the price will be lower in 7 or 14 days.
2. "Why this forecast": the top 3 drivers in plain English (SHAP).
3. Budget mode: the user enters a max price and gets the probability and likely dates the price reaches it.
4. Cheaper alternatives: other dates or nearby cities on the same tour.
5. Section-tier curves, only where the data supports them.
6. Fee-inclusive estimate toggle.
7. Calendar export (.ics) for the best-buy window.
8. Shareable forecast link.

## Final report
What was built, the backtest results table (model vs. baselines, by segment, with N), known limitations, and the data that would most improve accuracy.
