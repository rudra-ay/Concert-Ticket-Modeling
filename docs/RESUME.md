# Resume point (paused 2026-10-21 by the user: "stop all activity until further notice")

## State
- Tasks 1-8 are done. Task 7 (LEVEL review) is fully approved: L1-L23 in reviews/approved.json.
- Task 9 (PATH review), round 1 (reviews/review4_task9.md): P2 and P5 are approved. Still to do:
  - Text edits to P1 (scope "first 3 snapshot days"; reconcile 3,602 vs 3,596), P3 (IPW caveat for the
    ranges pool) and P4 (duplicate Waisman entry; flag 2 unverified sources).
  - Pre-registration fixes:
    - H20b becomes descriptive.
    - Exclude pairs seen up to 2026-10-21.
    - H20a: event FE + days-out buckets + day-of-week, no date FE.
    - Pre-registered MDEs.
    - Frozen spec hash + a touch log that refuses a second run.
    - IPW sensitivity stratified by selection day.
  - Then the skeptic re-pins and verifies only those items.
- Task 10 (final report) is not started. Write reports/findings.md with the brief's 7 sections, citing [L#]/[P#]
  tags. Limitations must include L21 (2026 snapshot features; not an on-sale forecast), the 53 link_ambiguous
  shows, and the MusicBrainz CC BY-NC-SA genre. Then run `make report`.
- After that comes the queued app: docs/NEXT_price_forecast_spec.md, starting with Step 0, which ends at checkpoint 1.
  Key fact for checkpoint 2: TM face value moves on only 0.47% of priced event-days, so a useful resale
  forecast needs the Rebrowser StubHub data (REBROWSER_REQUEST.md; user action).

## Still running on its own
- launchd `com.ticketpriceresearch.forward-collector`: daily 09:15, 4,000 events, rolling 24 h budget. It needs the
  Mac awake and logged in around 09:15-11:30. Stop it with:
  `launchctl bootout gui/$(id -u)/com.ticketpriceresearch.forward-collector`
- The collection orchestrator is finished and disabled (plist parked in scripts/disabled/).

## Commands (repo root)
`make status` · `make test` · `make check-level` · `make check-path` · `make report` ·
`.venv/bin/python src/analysis/path_report.py --all` (PATH rebuild)

## Team (respawn as needed; all agents were told to stop)
analyst (LEVEL, report) · skeptic (reviews, src/review/autocheck.py, reviews/approved.json) ·
collector-prices (PATH findings) · collector-path (forward collector). Their other roles are done.
Rules: research only; keys only in .env; never commit data/raw/ or data/forward/; commit with the noreply email
342760955+rudra-ay@users.noreply.github.com and push at each milestone.
