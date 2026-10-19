"""Lead-specified ordering of the Wikidata lock (2026-10-19):
1. venue job up to PRICED_MILESTONE (already running under features_supervise.py),
2. then bill's Wikidata steps (full bill build),
3. then the venues beyond the milestone (full venue build, resumes from cache).

Usage: .venv/bin/python src/features_chain.py
Waits for PRICED_MILESTONE in the venue log, stops the running venue supervisor and
job between requests (cache writes are atomic), then runs steps 2 and 3, each under
the supervisor. Exits non-zero if any step stops for a non-network reason.
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOGS = ROOT / "data" / "raw" / "logs"
PY = str(ROOT / ".venv" / "bin" / "python")


def pids(pattern: str) -> list[int]:
    out = subprocess.run(["pgrep", "-f", pattern], capture_output=True, text=True).stdout.split()
    return [int(p) for p in out if int(p) != os.getpid()]


def supervise(script: str, log: str, env: dict | None = None) -> int:
    e = {**os.environ, **(env or {})}
    return subprocess.call([PY, str(ROOT / "src" / "features_supervise.py"), script, str(LOGS / log), "30"],
                           cwd=ROOT, env=e)


def main() -> int:
    venue_log = LOGS / "features_venue.log"
    print(f"{time.strftime('%H:%M:%S')} waiting for PRICED_MILESTONE", flush=True)
    while "PRICED_MILESTONE" not in venue_log.read_text(errors="replace"):
        if not pids("features_supervise.py features_venue.py"):
            print("venue supervisor exited before the milestone; stopping chain", flush=True)
            return 1
        time.sleep(30)
    print(f"{time.strftime('%H:%M:%S')} milestone reached; pausing venue job", flush=True)
    for pattern in ("features_supervise.py features_venue.py", "src/features_venue.py"):
        for pid in pids(pattern):
            os.kill(pid, signal.SIGTERM)
    time.sleep(5)

    while pids("src/features_bill.py"):  # let a running partial bill build (pageview fill) finish first
        time.sleep(30)
    print(f"{time.strftime('%H:%M:%S')} bill: full build (Wikidata + pageviews)", flush=True)
    rc = supervise("features_bill.py", "features_bill.log")
    print(f"{time.strftime('%H:%M:%S')} bill finished rc={rc}", flush=True)
    if rc != 0:
        return rc

    print(f"{time.strftime('%H:%M:%S')} venue: remainder beyond the milestone", flush=True)
    os.replace(venue_log, LOGS / "features_venue.to_milestone.log")
    rc = supervise("features_venue.py", "features_venue.log")
    print(f"{time.strftime('%H:%M:%S')} venue finished rc={rc}", flush=True)
    return rc


if __name__ == "__main__":
    sys.exit(main())
