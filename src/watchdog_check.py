"""One round of watchdog checks over the background collection jobs (stdlib only).

Appends one line per check to data/raw/logs/watchdog.log and prints `ALERT: ...` for
problems (and `OK: ...` / `INFO: ...` for the rest). Observe only: never starts, stops
or edits a job, never touches the network, never runs a git command that writes.

Acknowledged alerts can be silenced until a time via data/raw/logs/watchdog_ack.json:
{"<alert key>": "2026-10-19T14:00:00"} (local time). Keys are printed as [key].
"""
from __future__ import annotations

import datetime as dt
import glob
import json
import os
import re
import shutil
import statistics
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
LOGS = RAW / "logs"
INTERIM = ROOT / "data" / "interim"
WATCHLOG = LOGS / "watchdog.log"
ACK = LOGS / "watchdog_ack.json"
SCRATCH = "/private/tmp/claude-501/-Users-rudraayyagari-ticket-tracker/ae575fa5-fcb5-4ef7-9fda-ca57230da16e/scratchpad"

NOW = time.time()
MIN_FREE_GB = 50
PUSHBACK = re.compile(r"\bBLOCKED\b|\bBlocked\b|BlockedError|\b(403|429)\b|challenge", re.I)

results: list[tuple[str, str, str]] = []  # (level, key, message)


def add(level: str, key: str, msg: str) -> None:
    results.append((level, key, msg))


def age(path: Path | str) -> float | None:
    try:
        return NOW - os.stat(path).st_mtime
    except OSError:
        return None


def fmt_age(sec: float | None) -> str:
    if sec is None:
        return "missing"
    return f"{sec / 60:.0f}m ago" if sec >= 120 else f"{sec:.0f}s ago"


def pids(pattern: str) -> list[int]:
    out = subprocess.run(["pgrep", "-f", pattern], capture_output=True, text=True).stdout
    return [int(p) for p in out.split() if int(p) != os.getpid()]


def py_pids(script_args: str) -> list[int]:
    """Python processes whose command line starts with the interpreter and this script (not shells
    or supervisors that merely mention it)."""
    return pids(r"^[^ ]*python[^ ]* (-u )?([^ ]*/)?" + re.escape(script_args))


def proc_age(pid: int) -> float | None:
    """Wall-clock seconds since the process started."""
    out = subprocess.run(["ps", "-o", "lstart=", "-p", str(pid)], capture_output=True, text=True).stdout.strip()
    try:
        return NOW - time.mktime(time.strptime(out, "%a %b %d %H:%M:%S %Y"))
    except ValueError:
        return None


STARTUP_GRACE_S = 2400  # feature builds load large caches before their first log line


def tail(path: Path | str, n: int = 40) -> list[str]:
    try:
        with open(path, "rb") as fh:
            fh.seek(0, 2)
            fh.seek(max(0, fh.tell() - 64_000))
            lines = fh.read().decode("utf-8", "replace").splitlines()
        return [ln for ln in lines if ln.strip()][-n:]
    except OSError:
        return []


def last_match(lines: list[str], pat: str) -> str | None:
    for ln in reversed(lines):
        if re.search(pat, ln):
            return ln
    return None


def pushback_check(key: str, lines: list[str], alive: bool, progress_pat: str) -> None:
    """Pushback in the log is fine if the job stopped; continuing after it is a violation."""
    idx = [i for i, ln in enumerate(lines) if PUSHBACK.search(ln) and "net_error" not in ln]
    if not idx:
        return
    after = lines[idx[-1] + 1:]
    if alive and any(re.search(progress_pat, ln) for ln in after):
        add("ALERT", f"{key}.rules", f"{key}: pushback line then kept going: {lines[idx[-1]][:200]!r}")
    else:
        add("INFO", f"{key}.pushback", f"{key}: pushback seen and job stopped: {lines[idx[-1]][:200]!r}")


MIN_GAP_S = 5.0
WIKIDATA_REQ_LOG = LOGS / "requests_www.wikidata.org.log"  # start<TAB>end<TAB>pid, epoch seconds


def start_gap_check(key: str, domain: str, starts: list[float], source: str,
                    ends: list[float] | None = None) -> None:
    """Exact request-start spacing over the last 30 min; any start-to-start gap < 5.0 s is an ALERT."""
    pairs = sorted((st, en) for st, en in zip(starts, ends or [None] * len(starts)) if NOW - st < 1800)
    gaps = [b[0] - a[0] for a, b in zip(pairs, pairs[1:])]
    if not gaps:
        add("OK", f"{key}.gap", f"{domain}: <2 requests in the last 30 min ({source})")
        return
    short = [round(g, 2) for g in gaps if g < MIN_GAP_S]
    extra = ""
    if ends:
        idle = [b[0] - a[1] for a, b in zip(pairs, pairs[1:]) if a[1] is not None]
        if idle:
            extra = f"; end-to-next-start min {min(idle):.2f}s"
    if short:
        add("ALERT", f"{key}.gap", f"{domain}: request STARTS closer than {MIN_GAP_S}s: {short[:10]} "
            f"({len(short)}/{len(gaps)} gaps, {source})")
    else:
        add("OK", f"{key}.gap", f"{domain}: start-to-start min {min(gaps):.2f}s over {len(gaps)} gaps{extra} ({source})")


def completion_gaps(key: str, times: list[float], domain: str, alert: bool) -> None:
    """Gaps between completion times (write times after the response). These include response-time
    jitter, so a short one is only a hint unless no start-time source exists (alert=True)."""
    times = sorted(t for t in times if NOW - t < 1800)
    gaps = [b - a for a, b in zip(times, times[1:])]
    if not gaps:
        return
    short = [round(g, 1) for g in gaps if g < MIN_GAP_S]
    msg = (f"{domain}: COMPLETION-time gaps (not request starts; include latency jitter): min {min(gaps):.1f}s, "
           f"median {statistics.median(gaps):.1f}s, {len(short)}/{len(gaps)} < {MIN_GAP_S}s")
    add("ALERT" if alert and short else "INFO", f"{key}.cgap", msg)


def newest_mtimes(directory: Path, n: int, pattern: str = "*") -> list[float]:
    try:
        with os.scandir(directory) as it:
            ms = [e.stat().st_mtime for e in it if e.is_file() and Path(e.name).match(pattern)
                  and not e.name.startswith(".")]
    except OSError:
        return []
    return sorted(ms)[-n:]


# --- 1. collector-prices: Wikipedia dump fetch --------------------------------------------
def check_prices() -> None:
    key = "prices"
    log = LOGS / "prices_fetch.log"
    flog = RAW / "wikipedia_dumps" / "fetch_log.jsonl"
    lines = tail(log, 60)
    fetcher = py_pids("src/collect_wikipedia_boxoffice.py fetch")
    supervisor = pids("LOG=data/raw/logs/prices_fetch.log")
    prog = last_match(lines, r"fetched \d+/\d+ streams")
    pushback_check(key, lines, bool(fetcher), r"fetched \d+/")
    if fetcher:
        a = age(flog)
        if a is None or a > 600:
            add("ALERT", f"{key}.stall", f"prices: fetcher alive (pid {fetcher}) but fetch_log.jsonl last write "
                f"{fmt_age(a)}; log tail: {lines[-3:]}")
        else:
            add("OK", f"{key}.alive", f"prices: fetcher pid {fetcher}, fetch_log {fmt_age(a)}; {prog}")
        if not supervisor:
            add("INFO", f"{key}.nosup", "prices: supervisor loop not running (fetcher still alive)")
        starts, done_at = [], []
        for ln in tail(flog, 400):
            try:
                rec = json.loads(ln)
                done_at.append(dt.datetime.fromisoformat(rec["at"]).timestamp())
                if "req_start" in rec:
                    starts.append(float(rec["req_start"]))
            except (ValueError, KeyError):
                pass
        if starts:
            start_gap_check(key, "dumps.wikimedia.org", starts, "fetch_log req_start")
        else:  # older log lines carry only completion times
            completion_gaps(key, done_at, "dumps.wikimedia.org", alert=True)
        return
    complete = any(" 0 to fetch" in ln for ln in lines[-5:])
    if complete:
        sb = age(INTERIM / "shows_base.parquet")
        la = age(log)
        if supervisor:
            add("OK", f"{key}.done", "prices: all streams fetched; supervisor running final parse")
        elif sb is not None and la is not None and sb <= la + 60:
            add("OK", f"{key}.done", f"prices: fetch complete; shows_base.parquet rebuilt {fmt_age(sb)}")
        else:
            add("ALERT", f"{key}.parse", f"prices: fetch complete but shows_base.parquet ({fmt_age(sb)}) "
                f"not rebuilt after log ({fmt_age(la)}) and no supervisor")
        return
    if supervisor and (age(log) or 1e9) < 180:
        add("OK", f"{key}.restarting", "prices: fetcher between runs; supervisor restarting it")
        return
    add("ALERT", f"{key}.dead", f"prices: fetcher not running, not complete (supervisor "
        f"{'alive' if supervisor else 'gone'}); log {fmt_age(age(log))}; tail: {lines[-3:]}")


# --- 2. collector-features: venue + artist builds -----------------------------------------
def check_feature(name: str, script: str, progress_pat: str, done_pat: str, outputs: list[str],
                  window: int) -> None:
    key = name
    log = LOGS / f"{name}.log"
    lines = tail(log, 80)
    alive = py_pids(f"src/{script}")
    pushback_check(key, lines, bool(alive), progress_pat)
    prog = last_match(lines, progress_pat)
    la = age(log)
    if alive:
        pa = proc_age(alive[0])
        if not lines and pa is not None and pa < STARTUP_GRACE_S:
            add("OK", f"{key}.starting", f"{name}: pid {alive} started {fmt_age(pa)}, still loading (no log yet)")
        elif (la is None or la > window) and NOW - last_request_by_pid().get(alive[0], 0) < window:
            req = NOW - last_request_by_pid()[alive[0]]
            add("OK", f"{key}.alive", f"{name}: pid {alive}, log quiet {fmt_age(la)} but last request "
                f"{fmt_age(req)} (quiet phase); {prog}")
        elif la is None or la > window:
            add("ALERT", f"{key}.stall", f"{name}: alive (pid {alive}) but log last write {fmt_age(la)}; "
                f"tail: {lines[-3:]}")
        else:
            add("OK", f"{key}.alive", f"{name}: pid {alive}, log {fmt_age(la)}; {prog}")
        return
    if last_match(lines, done_pat):
        missing = [o for o in outputs if age(INTERIM / o) is None or age(INTERIM / o) > (la or 0) + 900]
        if missing:
            add("ALERT", f"{key}.outputs", f"{name}: finished but outputs missing/stale: {missing}")
        else:
            add("OK", f"{key}.done", f"{name}: complete; outputs {outputs} present")
        return
    add("ALERT", f"{key}.dead", f"{name}: process gone without completion line; log {fmt_age(la)}; "
        f"last progress {prog!r}; tail: {lines[-4:]}")


def read_req_log(path: Path) -> list[tuple[float, float, int]]:
    rows = []
    for ln in tail(path, 600):
        parts = ln.split("\t")
        try:
            rows.append((float(parts[0]), float(parts[1]), int(parts[2])))
        except (ValueError, IndexError):
            pass
    return rows


def last_request_by_pid() -> dict[int, float]:
    """Latest request end per pid across all per-domain request logs (progress for quiet phases)."""
    last: dict[int, float] = {}
    for path in LOGS.glob("requests_*.log"):
        for _, en, pid in read_req_log(path):
            last[pid] = max(last.get(pid, 0.0), en)
    return last


def check_spacing() -> None:
    for path in sorted(LOGS.glob("requests_*.log")):
        domain = path.stem.removeprefix("requests_")
        rows = read_req_log(path)
        if rows:
            start_gap_check(domain.split(".")[-2], domain, [r[0] for r in rows], "requests log",
                            [r[1] for r in rows])
    if not (LOGS / "requests_www.wikidata.org.log").exists():
        completion_gaps("wikidata", newest_mtimes(RAW / "wikidata", 60, "*.json"), "www.wikidata.org", alert=True)


def check_venue_outputs() -> None:
    vp = age(INTERIM / "features_venue.parquet")
    add("OK", "venue.parquet", f"features_venue.parquet written {fmt_age(vp)}")
    if last_match(tail(LOGS / "features_venue.log", 400), r"PRICED_MILESTONE"):
        add("INFO", "venue.milestone", "features_venue: PRICED_MILESTONE reached")


# --- 3. collector-context: weather ---------------------------------------------------------
def weather_log(pid: int | None) -> str | None:
    if pid:
        out = subprocess.run(["lsof", "-a", "-p", str(pid), "-d", "1"], capture_output=True, text=True).stdout
        m = re.search(r"(/\S+\.log)\s*$", out, re.M)
        if m:
            return m.group(1)
    cands = sorted(glob.glob(f"{SCRATCH}/collector_context_weather*.log"), key=os.path.getmtime)
    return cands[-1] if cands else None


def check_weather() -> None:
    key = "weather"
    alive = py_pids("src/features_weather.py")
    path = weather_log(alive[0] if alive else None)
    lines = tail(path, 60) if path else []
    la = age(path) if path else None
    try:
        quota = json.loads((RAW / "open_meteo" / "_quota.json").read_text())
    except (OSError, ValueError):
        quota = {}
    utc = dt.datetime.now(dt.timezone.utc)
    used = quota.get(utc.date().isoformat(), 0)
    pushback_check(key, lines, bool(alive), r"windows done|wrote ")
    if not alive:
        if last_match(lines[-15:], r"pass complete"):
            add("OK", f"{key}.done", f"weather: pass complete ({path})")
        else:
            add("ALERT", f"{key}.dead", f"weather: process gone, no 'pass complete'; quota today {used}; "
                f"log {path} {fmt_age(la)}; tail: {lines[-3:]}")
        return
    waiting = lines[-1] if lines and lines[-1].startswith("waiting until") else None
    if waiting:
        m = re.search(r"waiting until (\S+ \S+) UTC", waiting)
        resume = dt.datetime.strptime(m.group(1), "%Y-%m-%d %H:%M").replace(tzinfo=dt.timezone.utc) if m else None
        if resume and utc > resume + dt.timedelta(minutes=15):
            add("ALERT", f"{key}.noresume", f"weather: still '{waiting}' at {utc:%H:%M} UTC (should have resumed); "
                f"quota today {used}")
        else:
            add("OK", f"{key}.paused", f"weather: paused at daily cap as designed ({waiting}); quota today {used}")
        return
    om = newest_mtimes(RAW / "open_meteo", 80, "*.json")
    last_file = (NOW - om[-1]) if om else None
    fresh = min(x for x in (la, last_file, 1e9) if x is not None)
    if fresh > 900:
        add("ALERT", f"{key}.stall", f"weather: alive (pid {alive}), not paused, quota {used}/8000, but log "
            f"{fmt_age(la)} and newest cache file {fmt_age(last_file)}; tail: {lines[-3:]}")
    else:
        prog = last_match(lines, r"windows done")
        add("OK", f"{key}.alive", f"weather: active pid {alive}, quota {used}/8000, log {fmt_age(la)}; {prog}")
        # one request can cover several venue-windows: cluster writes within 1 s as one request
        clusters: list[float] = []
        for t in om:
            if not clusters or t - clusters[-1] > 1.0:
                clusters.append(t)
        # no cross-process start-time lock for Open-Meteo (spacing is in-process), so completion gaps
        # are the best measure available: flag any under 5 s for a look
        completion_gaps(key, clusters, "archive-api.open-meteo.com", alert=True)
    wp = age(INTERIM / "features_weather.parquet")
    add("OK", "weather.parquet", f"features_weather.parquet written {fmt_age(wp)}")


# --- 4. collector-path: rebrowser ----------------------------------------------------------
def check_rebrowser() -> None:
    key = "rebrowser"
    log = RAW / "rebrowser_download.log"
    lines = tail(log, 30)
    alive = py_pids("src/rebrowser_download.py")
    pushback_check(key, lines, bool(alive), r"files,|: done")
    if alive:
        newest = newest_mtimes(RAW / "rebrowser", 1)
        sub = max((os.path.getmtime(p) for p in glob.glob(str(RAW / "rebrowser" / "*" / "*"))), default=0)
        fresh = min(x for x in (age(log), NOW - sub if sub else None, NOW - newest[-1] if newest else None, 1e9)
                    if x is not None)
        if fresh > 900:
            add("ALERT", f"{key}.stall", f"rebrowser: alive (pid {alive}) but nothing written for {fmt_age(fresh)}")
        else:
            add("OK", f"{key}.alive", f"rebrowser: running pid {alive}, last write {fmt_age(fresh)}")
    elif lines and lines[-1].rstrip().endswith(": done"):
        add("OK", f"{key}.done", f"rebrowser: not running; log complete ({lines[-1].strip()})")
    elif lines:
        add("ALERT", f"{key}.dead", f"rebrowser: not running and log not complete; tail: {lines[-3:]}")


# --- analyst (task 5) -----------------------------------------------------------------------
ANALYST_START = dt.datetime(2026, 10, 19, 16, 20).timestamp()  # lead: analyst started task 5
ANALYST_STALE_S = 45 * 60
ANALYST_PATHS = [ROOT / "src" / "analysis", ROOT / "data" / "shows.parquet",
                 ROOT / "data" / "DATA_DICTIONARY.md", ROOT / "reports" / "data_quality.md"]


def check_analyst() -> None:
    newest, newest_path, present = 0.0, None, []
    for p in ANALYST_PATHS:
        files = [p] if p.is_file() else [f for f in p.rglob("*") if f.is_file() and "__pycache__" not in f.parts] \
            if p.is_dir() else []
        if files:
            present.append(p.relative_to(ROOT).as_posix())
        for f in files:
            m = f.stat().st_mtime
            if m > newest:
                newest, newest_path = m, f.relative_to(ROOT).as_posix()
    ref = max(newest, ANALYST_START)
    if NOW - ref > ANALYST_STALE_S:
        what = f"newest change {newest_path} {fmt_age(NOW - newest)}" if newest_path else \
            f"none of its outputs exist {fmt_age(NOW - ANALYST_START)} after start"
        add("ALERT", "analyst.stale", f"analyst: no output change for 45+ min ({what}); "
            f"ask lead whether the analyst has reported")
    else:
        add("OK", "analyst.active", f"analyst: present {present or 'none yet'}; newest "
            f"{newest_path or '-'} {fmt_age(NOW - newest) if newest else ''}")


# --- caffeinate (keeps the Mac awake until the lead creates PROJECT_DONE) --------------------
PROJECT_DONE = LOGS / "PROJECT_DONE"


def check_caffeinate() -> None:
    caf = pids(r"^caffeinate -dims")
    stopper = pids(r"caffeinate_stopper\.sh")
    if PROJECT_DONE.exists():
        add("OK", "caffeinate.done", f"caffeinate: PROJECT_DONE exists; caffeinate {'still running ' + str(caf) if caf else 'stopped'}")
        return
    if not caf:
        add("ALERT", "caffeinate.dead", "caffeinate -dims is not running and PROJECT_DONE does not exist: the Mac can sleep")
    else:
        add("OK", "caffeinate.alive", f"caffeinate pid {caf}")
    if not stopper:
        add("INFO", "caffeinate.stopper", "caffeinate_stopper.sh not running (caffeinate won't be stopped at PROJECT_DONE)")
    power = subprocess.run(["pmset", "-g", "batt"], capture_output=True, text=True).stdout
    if "Battery Power" in power:
        m = re.search(r"(\d+)%", power)
        pct = int(m.group(1)) if m else None
        lvl = "ALERT" if pct is not None and pct < 25 else "INFO"
        add(lvl, "power.battery", f"on battery ({pct}%): caffeinate -s has no effect, closing the lid still sleeps "
            f"the Mac, and an empty battery stops every job")


# --- git staging, disk ---------------------------------------------------------------------
KEYLIKE = re.compile(r"(?i)(api[_-]?key|secret|token|passw(or)?d|auth)\s*[:=]\s*['\"]?[A-Za-z0-9_\-./+]{12,}"
                     r"|AKIA[0-9A-Z]{16}|sk-[A-Za-z0-9_\-]{20,}|gh[pousr]_[A-Za-z0-9]{30,}|xox[abp]-[A-Za-z0-9-]{10,}")


def check_git() -> None:
    names = subprocess.run(["git", "-C", str(ROOT), "diff", "--cached", "--name-only"],
                           capture_output=True, text=True).stdout.split()
    bad = [n for n in names if re.search(r"(^|/)\.env(\.|$)|\.pem$|id_rsa|credentials", n)]
    diff = subprocess.run(["git", "-C", str(ROOT), "diff", "--cached", "--no-ext-diff", "-U0"],
                          capture_output=True, text=True).stdout
    hits = [ln[:120] for ln in diff.splitlines() if ln.startswith("+") and KEYLIKE.search(ln)]
    if bad or hits:
        add("ALERT", "git.secrets", f"git: staged secret-looking content: files {bad}, lines {hits[:3]}")
    else:
        add("OK", "git.secrets", f"git: {len(names)} staged files, no .env/key-looking content")


def check_disk() -> None:
    free = shutil.disk_usage(Path.home()).free / 1e9
    add("ALERT" if free < MIN_FREE_GB else "OK", "disk", f"disk: {free:.0f} GB free on home volume")


def main() -> None:
    for fn in (check_prices,
               lambda: check_feature("features_venue", "features_venue.py", r"venue \d+/\d+",
                                     r"^done; transient", ["features_venue.parquet"], 900),
               lambda: check_feature("features_artist", "features_artist.py", r"artist \d+/\d+",
                                     r"^transient network skips", ["features_artist.parquet"], 1200),
               lambda: check_feature("features_bill", "features_bill.py", r"^\S+\s+\d\.\d+$",
                                     r"farewell_flag", ["features_bill.parquet"], 1200),
               check_spacing, check_venue_outputs, check_weather, check_rebrowser, check_analyst, check_caffeinate, check_git, check_disk):
        try:
            fn()
        except Exception as exc:  # a broken check must not hide the others
            add("ALERT", "watchdog.error", f"watchdog check crashed: {exc!r}")
    try:
        acks = {k: dt.datetime.fromisoformat(v).timestamp() for k, v in json.loads(ACK.read_text()).items()}
    except (OSError, ValueError):
        acks = {}
    stamp = time.strftime("%Y-%m-%dT%H:%M:%S")
    with open(WATCHLOG, "a") as fh:
        for level, key, msg in results:
            if level == "ALERT" and acks.get(key, 0) > NOW:
                level = "ACKED"
            fh.write(f"{stamp} {level} [{key}] {msg}\n")
            print(f"{level}: [{key}] {msg}")


if __name__ == "__main__":
    main()
