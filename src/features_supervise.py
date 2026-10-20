"""Supervise a features_* job: restart it after NetworkDown once DNS resolves again.

Usage: .venv/bin/python src/features_supervise.py <script.py> <log> [max_restarts]

- exit 0                    -> done, stop.
- log ends in Blocked       -> stop for good (403/429/challenge: never retry around pushback).
- log ends in NetworkDown   -> poll DNS for www.wikidata.org every 60 s, then restart
                               (work resumes from the cache; spacing is enforced by the job).
- any other failure         -> stop (a bug; restarting would just loop).
"""
from __future__ import annotations

import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROBE_HOST = "www.wikidata.org"


def log_tail(path: Path, start: int, n: int = 4000) -> str:
    """Last n chars written to path since byte offset start (this attempt only: the log is shared across
    runs, so an older run's EXIT line must not decide how this one ended)."""
    try:
        with open(path, "rb") as fh:
            fh.seek(start)
            return fh.read().decode(errors="replace")[-n:]
    except FileNotFoundError:
        return ""


def wait_for_dns() -> None:
    while True:
        try:
            socket.getaddrinfo(PROBE_HOST, 443)
            return
        except OSError:
            print(f"{time.strftime('%H:%M:%S')} DNS for {PROBE_HOST} still failing; retry in 60 s", flush=True)
            time.sleep(60)


def main() -> int:
    script, log = sys.argv[1], Path(sys.argv[2])
    max_restarts = int(sys.argv[3]) if len(sys.argv) > 3 else 30
    for attempt in range(max_restarts + 1):
        print(f"{time.strftime('%H:%M:%S')} start {script} (attempt {attempt + 1})", flush=True)
        start = log.stat().st_size if log.exists() else 0
        with open(log, "a") as fh:
            rc = subprocess.call([str(ROOT / ".venv/bin/python"), str(ROOT / "src" / script)],
                                 cwd=ROOT, stdout=fh, stderr=subprocess.STDOUT)
        tail = log_tail(log, start)
        if rc == 0:
            print(f"{time.strftime('%H:%M:%S')} {script} finished OK", flush=True)
            return 0
        if "features_common.Blocked" in tail:
            print(f"{time.strftime('%H:%M:%S')} BLOCKED: stopping for good", flush=True)
            return 2
        if "features_common.NetworkDown" not in tail:
            print(f"{time.strftime('%H:%M:%S')} crashed (rc={rc}) for a non-network reason: stopping", flush=True)
            return 3
        print(f"{time.strftime('%H:%M:%S')} NetworkDown: waiting for DNS, then restarting", flush=True)
        wait_for_dns()
        time.sleep(30)
    print("max restarts reached: stopping", flush=True)
    return 4


if __name__ == "__main__":
    sys.exit(main())
