# Skeptic review 4: task 9 (PATH), round 1

Input: reports/path_findings.md ([P1]–[P5]), reports/path_tables/*, data/forward/tm_forward.sqlite (read-only).
Mechanical: `src/review/autocheck.py --path` → 19 PASS, 0 FAIL, 0 WARN. Three notrace lines (design and pre-registration constants) were judged OK.
Judgment: `src/review/r4_path_checks.py`, an independent recompute of P1 from the raw DB.

## Checks run
- **P1 recompute:** 17 moves in 3,596 priced consecutive-day pairs = 0.47%, Wilson [0.30%, 0.76%]. The report says 3,602 pairs. The 6-pair gap comes from the show-start exclusion (I used hours_until_show ≤ 0), so reconcile the definition in the text. Each of the 17 moving events moved exactly once, so event clustering doesn't matter yet. The median days-to-show of a move is 17. 68% of priced pairs are ≥ 30 days out.
- **Contamination:** all 3,596 priced pairs seen so far predate the pre-registration (later snapshot ≤ 2026-10-21).
- **Literature:** the 7 new entries exist in LITERATURE.md §C with markers. Waisman appears twice (#9 UNVERIFIED and #31). Kemper & Breuer's findings are UNVERIFIED.

## Verdicts
P1 (primary face value rarely moves day to day in the first 3 days): PENDING edit E1
P2 (readiness schedule, simulated expected values; operational projection): APPROVED
P3 (watchlist 4,000 / far 30%, quota-safe; IPW ESS trade-off): PENDING edit E2
P4 (literature additions): PENDING edit E3
P5 (no path-shape clustering yet; prerequisites listed): APPROVED

## Required edits to findings
- **E1 (P1):** scope the headline:
  - "In the panel's first 3 snapshot days (2 day-to-day transitions; ranges-pool events, 68% of priced pairs ≥ 30 days out)".
  - Say that the Wilson CI treats pairs as independent, which is harmless here because each moving event moved once.
  - Reconcile 3,602 vs 3,596.
- **E2 (P3):** for the ranges pool, `selection_prob` is the realized share of a diversity-capped pick, not a sampling probability. IPW therefore can't support population statements for that pool. Say so next to the ESS table and in the registered IPW spec.
- **E3 (P4):** merge the duplicate Waisman entries (#9 and #31), and say that 2 of the 7 new sources (Waisman, Kemper & Breuer) have unverified findings.

## Required changes to the pre-registered family (before any test runs; re-pin afterwards)
- **F1 (H20b is a foregone test):**
  - The 5% "drift" threshold was set after a 0.47% rate (upper bound 0.75%) had been seen, so the rejection is effectively guaranteed. Inside BH it would also hand the other members a free rank.
  - Move H20b out of the family and report it as descriptive. The family becomes {H20a, H9p, H37}.
- **F2 (seen data):** the confirmatory sample excludes every day-pair whose later snapshot is ≤ 2026-10-21 (the data seen before registration). Every test runs on unseen pairs only.
- **F3 (H20a identification):**
  - Event FE + snapshot-date FE + days-to-show buckets is an age–period–cohort design: days_to_show = show_date − snapshot_date is exactly linear in the two FEs, so the bucket effects are identified only by the buckets' nonlinearity.
  - "Absorbs year" doesn't apply to a 2–3 month window.
  - Use event FE + days-to-show buckets + day-of-week dummies (no date FE). Optionally add calendar-week FE as a pre-declared sensitivity, with the identifying assumption written down.
- **F4 (power before the test date):**
  - At about 0.5% moves, N = 500 complete 30-day paths gives roughly 15,000 pairs and about 75 moves.
  - Pre-register a simulated MDE (artist-clustered) for H20a, H9p and H37. For H37, include the expected number of events with a sale-phase date inside their observed window, which is likely small given first snapshot ≥ 30 days out.
  - If an MDE is implausibly large, move that test date to N ≥ 1,000 now, before data. Never move it after looking.
- **F5 ("run once" enforced):** freeze `reports/path_tables/final_spec.json` now. It holds the sha256 of the test code (path_hypotheses.py), the parameters, the family and the sample rules. The test run appends a `kind: final` entry to `test_touch_log.jsonl` and refuses a second run or a hash mismatch, as in LEVEL. autocheck --path verifies both once they exist.
- **F6 (IPW spec):** the registered IPW sensitivity stratifies by selection day (the cohorts have different far shares), and its ranges-pool caveat follows E2.
