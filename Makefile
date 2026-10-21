# One command per research stage. Run from the repo root. Long output goes to logs/<target>.log;
# the terminal shows only the tail.
PY := .venv/bin/python
LOG = mkdir -p logs && $(1) > logs/$@.log 2>&1; rc=$$?; tail -n 15 logs/$@.log; exit $$rc

.PHONY: status shows level level-final check-level check-path report test

status:        ## collection + forward collector status
	@$(PY) src/collect_all.py status; $(PY) forward_collector.py status | head -12

shows:         ## rebuild data/shows.parquet from the feature tables
	@$(call LOG,$(PY) -u src/analysis/build_shows.py)

level:         ## full LEVEL rerun on train/valid (never touches test)
	@$(call LOG,$(PY) -u src/analysis/level.py)

level-final:   ## the one logged test-split evaluation: make level-final NOTE="why"
	@test -n "$(NOTE)" || { echo 'NOTE="..." is required (it is written to the test touch log)'; exit 2; }
	@$(call LOG,$(PY) -u src/analysis/level.py --final --note "$(NOTE)")

check-level:   ## skeptic's mechanical checks (run before sending findings for review)
	@$(call LOG,$(PY) src/review/autocheck.py --level)

check-path:
	@$(call LOG,$(PY) src/review/autocheck.py --path)

report:        ## reports/findings.md -> reports/findings.html (refuses unapproved findings)
	@$(PY) src/report/build_report.py

test:
	@$(call LOG,$(PY) -m pytest -q tests)
