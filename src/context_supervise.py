"""Supervise a collector-context job (e.g. features_weather.py --until-done); modelled on features_supervise.py.

Usage: .venv/bin/python src/context_supervise.py <log> <probe_host> <script.py> [script args...]

- exit 0                                  -> done, stop.
- log ends with "EXIT context_http.BlockedError" -> stop for good (403/429/challenge/non-JSON page: never
                                             retry around pushback; a human reads data/raw/_bad_responses/).
- log ends with "EXIT context_http.NetworkDown"  -> poll DNS for <probe_host> every 60 s, wait 5 min, restart
                                             (work resumes from the cache; spacing is enforced in polite_get).
- anything else (a crash)                 -> stop (a bug; restarting would just loop). Max 20 restarts.
"""
from __future__ import annotations

import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAX_RESTARTS = 20


def log_tail(path: Path, start: int, n: int = 4000) -> str:
    """Last n chars written to path since byte offset start (this attempt only: the log is shared across
    runs, so an older run's EXIT line must not decide how this one ended)."""
    try:
        with open(path, "rb") as fh:
            fh.seek(start)
            return fh.read().decode(errors="replace")[-n:]
    except FileNotFoundError:
        return ""


def resolves(host: str, timeout: float = 10) -> bool:
    """getaddrinfo with a time limit: campus DNS sometimes hangs for minutes instead of failing.
    The lookup runs in a daemon thread, so a hung one is abandoned rather than waited for."""
    ok: list[bool] = []

    def lookup() -> None:
        try:
            socket.getaddrinfo(host, 443)
            ok.append(True)
        except OSError:
            pass

    t = threading.Thread(target=lookup, daemon=True)
    t.start()
    t.join(timeout)
    return bool(ok)


def wait_for_dns(host: str) -> None:
    while not resolves(host):
        print(f"{time.strftime('%H:%M:%S')} DNS for {host} failing; retry in 60 s", flush=True)
        time.sleep(60)
    print(f"{time.strftime('%H:%M:%S')} DNS for {host} OK", flush=True)


def main() -> int:
    log, host, script, args = Path(sys.argv[1]), sys.argv[2], sys.argv[3], sys.argv[4:]
    for attempt in range(MAX_RESTARTS + 1):
        print(f"{time.strftime('%H:%M:%S')} start {script} {' '.join(args)} (attempt {attempt + 1})", flush=True)
        start = log.stat().st_size if log.exists() else 0
        with open(log, "a") as fh:
            rc = subprocess.call([str(ROOT / ".venv/bin/python"), "-u", str(ROOT / "src" / script), *args],
                                 cwd=ROOT, stdout=fh, stderr=subprocess.STDOUT)
        tail = log_tail(log, start)
        if rc == 0:
            print(f"{time.strftime('%H:%M:%S')} {script} finished OK", flush=True)
            return 0
        if "EXIT context_http.BlockedError" in tail:
            print(f"{time.strftime('%H:%M:%S')} BLOCKED: stopping for good", flush=True)
            return 2
        if "EXIT context_http.NetworkDown" not in tail:
            print(f"{time.strftime('%H:%M:%S')} crashed (rc={rc}), not a network stop: stopping", flush=True)
            return 3
        print(f"{time.strftime('%H:%M:%S')} NetworkDown: waiting for DNS, then 5 min, then restarting", flush=True)
        wait_for_dns(host)
        time.sleep(300)
    print("max restarts reached: stopping", flush=True)
    return 4


if __name__ == "__main__":
    sys.exit(main())
