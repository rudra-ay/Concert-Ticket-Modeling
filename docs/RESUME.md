# Resume point (updated 2026-10-26)

## State
Research tasks 1-10 are DONE. The final report is reports/findings.md + reports/findings.html (`make report`).
Everything in it is approved: L1-L23 and P1-P5 (reviews/approved.json).

## App
The Price Timeline app lives in ~/price-timeline (its PLAN.md has the status). Resale data requests
(TicketData, Rebrowser) are user actions: ~/price-timeline/docs/DATA_REQUESTS.md.

## Collector (2026-10-26, DECISIONS.md item 6)
`sweep` (every US music show to +365 days, ~450 calls/day), `feed` (Discovery Feed, 1 call), `near` (final-week
intraday pass), `daily --mode auto` (switches to sweep mode after 2 days pass `sweep-compare`; day 1 passed).
**User action pending:** install the new schedule from scripts/launchd/ (FORWARD_COLLECTOR.md, "Sweep + feed").

## Scheduled
- The PATH confirmatory tests {H20a, H9p} run ONCE at >=1,000 complete priced 30-day paths (~2027-01-02):
  `.venv/bin/python src/analysis/path_hypotheses.py --final` (it refuses earlier or twice).
- launchd `com.ticketpriceresearch.forward-collector`: daily 09:15 (`daily --mode auto` once the new plist is
  installed), rolling 24 h budget; `com.ticketpriceresearch.feed`: every 4 h, scripts/intraday.sh (feed + near).
  The Mac must be awake. Stop it with: `launchctl bootout gui/$(id -u)/com.ticketpriceresearch.forward-collector`

## Commands (repo root)
`make status` · `make test` · `make check-level` · `make check-path` · `make report`

## Rules
Research only; keys only in .env; never commit data/raw/ or data/forward/; commit with the noreply email
342760955+rudra-ay@users.noreply.github.com and push at each milestone. Agents don't survive a restart:
respawn fresh ones with tight briefs. Subagents can't write report files; the lead saves them.
