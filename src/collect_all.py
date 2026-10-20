"""One orchestrator for the remaining collection, run by launchd every 15 min. No agents in the loop.

Usage:
  .venv/bin/python src/collect_all.py tick     # idempotent: (re)start whatever should be running, then write status
  .venv/bin/python src/collect_all.py status   # print the one-screen status

Jobs (each runs detached under its existing supervisor, which already handles NetworkDown restarts,
stops for good on 403/429/challenge pages, and enforces the per-domain spacing):
  weather  weather_fast.py --until-done       (Open-Meteo, priced shows, 95% quota; waits for resets)
  venue    venue_lean.py                      (Wikidata, 1 request per venue, >= 5 s end-to-start)
Then, once both are done: build_context.py metro -> analysis/build_shows.py, and status says ALL DONE.

A job whose supervisor stopped for good (BLOCKED or a crash) is never restarted by a tick; status shows
NEEDS A HUMAN with the log tail. Delete data/raw/logs/collect_state.json entries to reset a job.
"""
from __future__ import annotations

import fcntl
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = str(ROOT / ".venv" / "bin" / "python")
LOGS = ROOT / "data" / "raw" / "logs"
STATE = LOGS / "collect_state.json"
STATUS = LOGS / "collect_status.txt"

JOBS = {
    "weather": {
        "match": "src/weather_fast.py",
        "sup_match": "context_supervise.py",
        "log": LOGS / "weather.log",
        "sup_log": LOGS / "weather_supervisor.log",
        "cmd": lambda j: [PY, "-u", str(ROOT / "src/context_supervise.py"), str(j["log"]),
                          "archive-api.open-meteo.com", "weather_fast.py", "--until-done"],
    },
    "venue": {
        "match": "src/venue_lean.py",
        "sup_match": "features_supervise.py venue_lean.py",
        "log": LOGS / "features_venue.log",
        "sup_log": LOGS / "venue_supervisor.log",
        "cmd": lambda j: [PY, "-u", str(ROOT / "src/features_supervise.py"), "venue_lean.py", str(j["log"]), "30"],
    },
}
# Supervisor exit lines (both supervisors print these).
DONE_MARK = "finished OK"
STOP_MARKS = ("BLOCKED", "crashed", "max restarts")


def now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def pids(pattern: str) -> list[int]:
    out = subprocess.run(["pgrep", "-f", pattern], capture_output=True, text=True).stdout.split()
    return [int(p) for p in out if int(p) != os.getpid()]


def tail(path: Path, n: int = 3) -> list[str]:
    try:
        return path.read_text(errors="replace").strip().splitlines()[-n:]
    except FileNotFoundError:
        return []


def load_state() -> dict:
    try:
        return json.loads(STATE.read_text())
    except (FileNotFoundError, ValueError):
        return {}


def save_state(state: dict) -> None:
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=1))
    tmp.replace(STATE)


def job_state(name: str, job: dict, state: dict) -> str:
    """running | done | stopped | idle (should be started)."""
    if pids(job["sup_match"]) or pids(job["match"]):
        return "running"
    st = state.get(name, {}).get("status")
    if st in ("done", "stopped"):
        return st
    last = "\n".join(tail(job["sup_log"], 2))
    if DONE_MARK in last:
        return "done"
    if any(m in last for m in STOP_MARKS):
        return "stopped"
    return "idle"


def start(name: str, job: dict) -> None:
    with open(job["sup_log"], "a") as fh:
        subprocess.Popen(job["cmd"](job), cwd=ROOT, stdout=fh, stderr=subprocess.STDOUT,
                         stdin=subprocess.DEVNULL, start_new_session=True)
    log(f"started {name}")


def log(msg: str) -> None:
    with open(LOGS / "collect_all.log", "a") as fh:
        fh.write(f"{now()} {msg}\n")


def run_step(state: dict, key: str, cmd: list[str]) -> None:
    if state.get(key, {}).get("status") == "done":
        return
    log(f"running {key}")
    with open(LOGS / f"{key}.log", "a") as fh:
        rc = subprocess.call(cmd, cwd=ROOT, stdout=fh, stderr=subprocess.STDOUT)
    state[key] = {"status": "done" if rc == 0 else "stopped", "rc": rc, "at": now()}
    log(f"{key} rc={rc}")


def tick() -> None:
    lock = open(LOGS / "collect_all.lock", "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return  # previous tick still running (a post-processing step)
    state = load_state()
    states = {}
    for name, job in JOBS.items():
        s = job_state(name, job, state)
        if s in ("done", "stopped") and state.get(name, {}).get("status") != s:
            state[name] = {"status": s, "at": now()}
            log(f"{name} {s}")
        if s == "idle":
            start(name, job)
            s = "running"
        states[name] = s
    if all(s == "done" for s in states.values()):
        run_step(state, "metro", [PY, "-u", str(ROOT / "src/build_context.py"), "metro"])
        if state["metro"]["status"] == "done":
            run_step(state, "build_shows", [PY, "-u", str(ROOT / "src/analysis/build_shows.py")])
    save_state(state)
    STATUS.write_text(render(state, states))


def quota_line() -> str:
    try:
        q = json.loads((ROOT / "data/raw/open_meteo/_quota.json").read_text())
        day = max(q)
        return f"Open-Meteo calls used {day} (UTC): {q[day]} / 9500"
    except (FileNotFoundError, ValueError):
        return "Open-Meteo quota: unknown"


def min_gap(path: Path, last_n: int = 200) -> str:
    """Smallest end-to-next-start gap in a requests log (start<TAB>end<TAB>pid)."""
    rows = []
    for line in tail(path, last_n):
        parts = line.split("\t")
        try:
            rows.append((float(parts[0]), float(parts[1])))
        except (ValueError, IndexError):
            continue
    gaps = [b[0] - a[1] for a, b in zip(rows, rows[1:])]
    return f"min end-to-start {min(gaps):.2f}s over {len(gaps)} gaps" if gaps else "no recent requests"


def render(state: dict, states: dict) -> str:
    lines = [f"collect_all status at {now()}", ""]
    for name, job in JOBS.items():
        s = states[name]
        label = {"stopped": "STOPPED - NEEDS A HUMAN"}.get(s, s.upper())
        lines.append(f"[{name}] {label}")
        lines += [f"    {t[:160]}" for t in tail(job["log"], 2)]
        if s == "stopped":
            lines += [f"    supervisor: {t[:160]}" for t in tail(job["sup_log"], 3)]
    lines += ["", quota_line(),
              f"Open-Meteo spacing: {min_gap(LOGS / 'requests_archive-api.open-meteo.com.log')}",
              f"Wikidata spacing:   {min_gap(LOGS / 'requests_www.wikidata.org.log')}"]
    for key in ("metro", "build_shows"):
        if key in state:
            lines.append(f"{key}: {state[key]['status']} (rc={state[key].get('rc')}, {state[key]['at']})")
    if state.get("build_shows", {}).get("status") == "done":
        lines += ["", "ALL DONE: data/shows.parquet rebuilt with final venue, metro and weather tables."]
    return "\n".join(lines) + "\n"


def main() -> int:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "tick"
    if cmd == "tick":
        tick()
    elif cmd != "status":
        print(__doc__)
        return 2
    print(STATUS.read_text() if STATUS.exists() else "no status yet; run tick")
    return 0


if __name__ == "__main__":
    sys.exit(main())
