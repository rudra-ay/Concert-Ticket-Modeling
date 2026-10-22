# Resume point (updated 2026-10-22)

## State
Research tasks 1-10 are DONE. The final report is reports/findings.md + reports/findings.html (`make report`).
Everything in it is approved: L1-L23 and P1-P5 (reviews/approved.json).

## Next (only when the user says so)
The queued app in docs/NEXT_price_forecast_spec.md. Start with Step 0 (CLAUDE.md + PLAN.md), which ends at checkpoint 1.
Key fact for checkpoint 2: TM primary face value moves on ~0.47% of priced event-days, so a useful
forecast needs resale data. The Rebrowser StubHub request (REBROWSER_REQUEST.md) is a user action.

## Scheduled
- The PATH confirmatory tests {H20a, H9p} run ONCE at >=1,000 complete priced 30-day paths (~2027-01-02):
  `.venv/bin/python src/analysis/path_hypotheses.py --final` (it refuses earlier or twice).
- launchd `com.ticketpriceresearch.forward-collector`: daily 09:15, 4,000 events, rolling 24 h budget.
  The Mac must be awake. Stop it with: `launchctl bootout gui/$(id -u)/com.ticketpriceresearch.forward-collector`

## Commands (repo root)
`make status` · `make test` · `make check-level` · `make check-path` · `make report`

## Rules
Research only; keys only in .env; never commit data/raw/ or data/forward/; commit with the noreply email
342760955+rudra-ay@users.noreply.github.com and push at each milestone. Agents don't survive a restart:
respawn fresh ones with tight briefs. Subagents can't write report files; the lead saves them.
