#!/usr/bin/env python
"""Daily forward collector: Ticketmaster Discovery API v2 snapshots for PATH research.

Source: SOURCES.md A6 (ALLOWED). Decisions: DECISIONS.md items 4-5. Docs: FORWARD_COLLECTOR.md.
Attribution: "Data from Ticketmaster Discovery API". Personal, non-commercial research; no redistribution.

What it does, once per day:
  1. `run`      : GET /discovery/v2/events/{id}.json for every active watchlist event and store a
                  snapshot (parsed fields + gzipped raw JSON) in SQLite. One snapshot per event per
                  UTC day, so reruns on the same day never duplicate and never re-spend calls.
  2. `discover` : search upcoming US music events 1-120 days out and add a diverse sample to the
                  watchlist (spread over states, genres, venues, artists and days-out).
  `daily` = `run`, then `discover` with whatever budget is left if the last discover is >= 7 days old.
  3. `sweep`    : snapshot EVERY upcoming US music event via search pages (200 events per call, ~200-300
                  calls/day) into sweep_* tables. Same Discovery event objects as /events/{id}.json (all
                  top-level fields identical on 28/28 overlapping events, 2026-10-26). Raw JSON is stored
                  only when an event changed. `daily --mode sweep` sweeps first, copies watchlist events into
                  `snapshots`, and per-event calls only the watchlist events the sweep missed.
  5. `near`     : intraday re-sweep of shows in their final NEAR_DAYS days (where face moves concentrate), a few
                  calls per pass; compact rows in near_snapshots (price and status at each pass).
  4. `feed`     : the Discovery Feed (one call = every US event, ~110k, refreshed by TM several times a day).
                  No prices, but status, hotEvent, transactable, sale/presale windows. Keeps the latest
                  state of every music event and a timestamped log of each field change (sell-outs etc.).

Limits (official API, documented: 5 req/s, 5,000 calls/day): token bucket at <= 4 req/s, a persistent
per-UTC-day call budget (default 4,500), and on 429 we honor Retry-After for at most 3 retries, then
stop for the day. A 401/403 (bad key) stops immediately. The API key is never written to the DB, logs
or saved URLs.

Usage:
  .venv/bin/python forward_collector.py daily
  .venv/bin/python forward_collector.py run [--limit N]
  .venv/bin/python forward_collector.py discover [--target 3000] [--max-calls 700]
  .venv/bin/python forward_collector.py watchlist add <event_id>... | import <csv> | export <csv>
  .venv/bin/python forward_collector.py sweep [--days-max 180]
  .venv/bin/python forward_collector.py sweep-compare [--date YYYY-MM-DD]
  .venv/bin/python forward_collector.py feed
  .venv/bin/python forward_collector.py near
  .venv/bin/python forward_collector.py status
  .venv/bin/python forward_collector.py prune --keep-days 365
"""
from __future__ import annotations

import argparse
import csv
import email.utils
import gzip
import hashlib
import json
import logging
import os
import random
import re
import sqlite3
import sys
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Protocol
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

ROOT = Path(__file__).resolve().parent
DEFAULT_DB = ROOT / "data" / "forward" / "tm_forward.sqlite"
LOG_DIR = ROOT / "data" / "forward" / "logs"
API_BASE = "https://app.ticketmaster.com/discovery/v2"
USER_AGENT = "TicketPriceResearch/0.1 (personal research; contact: rudraayyagari@gmail.com)"

DAILY_QUOTA = 5000
DEFAULT_BUDGET = 4500          # max calls in any rolling 24 h (90% of the quota); the rest is safety margin
DEFAULT_MAX_WAIT_S = 3 * 3600  # how long a run may wait for the rolling window to free up
DEFAULT_TARGET = 4000          # active watchlist size (raised from 3,000 on 2026-10-21; see FORWARD_COLLECTOR.md)
DEFAULT_FAR_SHARE = 0.3        # share of NEW slots for shows >= 60 days out (scenario C, 2026-10-21; was 0.6)
DEFAULT_RATE = 3.0             # req/s; 4 req/s drew occasional spike-arrest 429s on 2026-10-19 (TM allows 5)
MAX_RETRIES = 3
RESERVE_AVAILABLE = 250        # stop if TM's Rate-Limit-Available header drops to this
DEEP_PAGING_CAP = 1000         # TM: size * page < 1000
DISCOVER_EVERY_DAYS = 7
SWEEP_DAYS_MAX = 365           # event dates swept: today .. today + 365 days (tours go on sale ~6-12 months out)
# The sweep may use the quota up to 5,000 minus the Price Timeline app's 200/day lookup cap minus a margin.
# TM's Rate-Limit-Available reserve (RESERVE_AVAILABLE) still stops every client first if TM disagrees.
SWEEP_BUDGET = 4750
SWEEP_SOURCE_URL = f"{API_BASE}/events.json (sweep)"
# `daily --mode auto` switches to sweep mode for good once GATE_DAYS parallel days each pass these checks.
GATE_DAYS, GATE_MIN_OVERLAP, GATE_MIN_IDENTICAL = 2, 0.90, 0.99
GATE_MAX_HOURS_APART = 6  # identity is judged only on pairs snapped this close (prices really change over a day)
NEAR_DAYS = 7                  # `near` re-sweeps event dates today .. today + 7 days
FEED_URL = "https://app.ticketmaster.com/discovery-feed/v2/events.json"
FEED_TRACKED = ("event_status", "hot_event", "transactable", "official_seller", "onsale_start", "onsale_end",
                "local_date", "start_utc", "presales_n", "in_feed")
DEACTIVATE_AFTER_404S = 3

EXIT_OK, EXIT_NO_KEY, EXIT_AUTH, EXIT_RATE_LIMITED = 0, 3, 5, 6
MAX_429_SHARE = 0.01           # more than 1% of a run's calls drawing 429 = stop and report

log = logging.getLogger("forward_collector")

# --------------------------------------------------------------------------- secrets

_APIKEY_RE = re.compile(r"(apikey=)[^&\s\"'<>]+", re.IGNORECASE)


def strip_apikey(text: str, key: str | None = None) -> str:
    """Remove any apikey query param (and the literal key, if known) from text."""
    text = _APIKEY_RE.sub(r"\1REDACTED", text)
    if key:
        text = text.replace(key, "REDACTED")
    return text


class RedactFilter(logging.Filter):
    def __init__(self, key: str | None = None) -> None:
        super().__init__()
        self.key = key

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = strip_apikey(record.getMessage(), self.key)
        record.args = ()
        return True


def load_api_key(env_file: Path) -> str | None:
    try:
        from dotenv import dotenv_values
    except ImportError:  # pragma: no cover
        dotenv_values = None
    key = os.environ.get("TICKETMASTER_API_KEY")
    if not key and dotenv_values and env_file.exists():
        key = dotenv_values(env_file).get("TICKETMASTER_API_KEY")
    return key.strip() if key and key.strip() else None


NO_KEY_MESSAGE = (
    "TICKETMASTER_API_KEY is not set.\n"
    "Register at https://developer.ticketmaster.com/ (free), copy the Consumer Key, and add\n"
    "    TICKETMASTER_API_KEY=<your key>\n"
    f"to {ROOT / '.env'} (never commit it). Nothing was fetched."
)

# --------------------------------------------------------------------------- clock + rate limit


class Clock(Protocol):
    def now(self) -> datetime: ...
    def monotonic(self) -> float: ...
    def sleep(self, seconds: float) -> None: ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(timezone.utc)

    def monotonic(self) -> float:
        return time.monotonic()

    def sleep(self, seconds: float) -> None:
        if seconds > 0:
            time.sleep(seconds)


class TokenBucket:
    """Capacity 1 means no bursts: consecutive calls are >= 1/rate seconds apart."""

    def __init__(self, rate: float, clock: Clock, capacity: float = 1.0) -> None:
        self.rate, self.capacity, self.clock = rate, capacity, clock
        self.tokens = capacity
        self.last = clock.monotonic()

    def _refill(self) -> None:
        now = self.clock.monotonic()
        self.tokens = min(self.capacity, self.tokens + (now - self.last) * self.rate)
        self.last = now

    def acquire(self) -> None:
        self._refill()
        if self.tokens < 1:
            self.clock.sleep((1 - self.tokens) / self.rate)
            self._refill()
            self.tokens = max(self.tokens, 1.0)  # guard float rounding
        self.tokens -= 1


# --------------------------------------------------------------------------- HTTP


@dataclass
class Response:
    status: int
    headers: dict[str, str] = field(default_factory=dict)
    body: bytes = b""

    def json(self) -> Any:
        return json.loads(self.body.decode("utf-8"))

    def header(self, name: str) -> str | None:
        for k, v in self.headers.items():
            if k.lower() == name.lower():
                return v
        return None


class Transport(Protocol):
    def get(self, url: str, params: dict[str, Any]) -> Response: ...


class TransportError(RuntimeError):
    pass


class RequestsTransport:
    def __init__(self, timeout: float = 30.0) -> None:
        import requests

        self._requests = requests
        self.session = requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT
        self.session.headers["Accept"] = "application/json"
        self.timeout = timeout

    def get(self, url: str, params: dict[str, Any]) -> Response:
        try:
            r = self.session.get(url, params=params, timeout=self.timeout)
        except self._requests.RequestException as exc:
            # requests puts the full URL (with apikey) in messages; never let it escape.
            raise TransportError(strip_apikey(str(exc), params.get("apikey"))) from None
        return Response(r.status_code, dict(r.headers), r.content)


class StopForToday(RuntimeError):
    """Budget spent, rate limited past our retries, or TM says the daily quota is gone."""


class AuthError(StopForToday):
    pass


class RateLimitStop(StopForToday):
    """A 429 we must not ride out: Retry-After or quota body, > 1% of calls, or retries exhausted."""


def parse_retry_after(value: str | None, now: datetime) -> float | None:
    if not value:
        return None
    value = value.strip()
    if value.isdigit():
        return float(value)
    try:
        when = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return max(0.0, (when - now).total_seconds())


class CallBudget:
    """Rolling-24h call budget persisted in SQLite (every attempt, incl. retries, counts).

    Ticketmaster's 5,000/day quota behaves like a rolling 24-hour window, not a UTC day: on
    2026-10-20 its Rate-Limit-Available hit the reserve after 1,563 calls because 3,218 calls made
    ~17 h earlier still counted. So no 24-hour window may hold more than `limit` calls. When the
    window is full the run waits for old calls to age out (up to `max_wait_s` in total), then stops.
    The per-UTC-day `api_calls` counter is kept for reporting.
    """

    WINDOW_S = 24 * 3600

    def __init__(self, conn: sqlite3.Connection, clock: Clock, limit: int,
                 max_wait_s: float = DEFAULT_MAX_WAIT_S) -> None:
        self.conn, self.clock, self.limit, self.max_wait_s = conn, clock, limit, max_wait_s
        self.spent = 0          # calls spent through this budget object (this process)
        self.waited = 0.0
        self.hard_stop: str | None = None
        self._backfill_from_runs()

    def _now(self) -> float:
        return self.clock.now().timestamp()

    def _backfill_from_runs(self) -> None:
        """First use on an older DB: spread recent runs' calls evenly over their start..finish."""
        if self.conn.execute("SELECT 1 FROM api_call_log LIMIT 1").fetchone():
            return
        since = self._now() - self.WINDOW_S
        rows = []
        for started, finished, calls in self.conn.execute(
                "SELECT started_at, finished_at, calls_used FROM runs WHERE calls_used > 0 AND finished_at IS NOT NULL"):
            a, b = _parse_iso(started), _parse_iso(finished)
            if not a or not b or b.timestamp() < since:
                continue
            span = max(0.0, b.timestamp() - a.timestamp())
            rows += [(a.timestamp() + span * (i + 0.5) / calls,) for i in range(calls)]
        if rows:
            self.conn.executemany("INSERT INTO api_call_log(ts) VALUES (?)", rows)
            self.conn.commit()
            log.info("budget: backfilled %d call timestamps from recent runs", len(rows))

    def day(self) -> str:
        return self.clock.now().date().isoformat()

    def used(self) -> int:
        """Calls in the current UTC day (reporting only)."""
        row = self.conn.execute("SELECT calls FROM api_calls WHERE day = ?", (self.day(),)).fetchone()
        return row[0] if row else 0

    def in_window(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM api_call_log WHERE ts > ?",
                                 (self._now() - self.WINDOW_S,)).fetchone()[0]

    def remaining(self) -> int:
        return 0 if self.hard_stop else max(0, self.limit - self.in_window())

    def stop_now(self, reason: str) -> None:
        self.hard_stop = reason

    def spend(self) -> None:
        while True:
            if self.hard_stop:
                raise StopForToday(f"call budget closed: {self.hard_stop}")
            now = self._now()
            n = self.in_window()
            if n < self.limit:
                break
            # Wait until enough old calls leave the window to make room for one more.
            row = self.conn.execute("SELECT ts FROM api_call_log WHERE ts > ? ORDER BY ts LIMIT 1 OFFSET ?",
                                    (now - self.WINDOW_S, n - self.limit)).fetchone()
            wait = row[0] + self.WINDOW_S - now + 1.0
            if self.waited + wait > self.max_wait_s:
                raise StopForToday(f"rolling 24h call budget of {self.limit} reached "
                                   f"(next slot in {wait / 60:.0f} min, over the {self.max_wait_s / 3600:.1f} h wait cap)")
            log.info("budget: %d calls in the last 24h (limit %d); waiting %.0f s for old calls to age out",
                     n, self.limit, wait)
            self.clock.sleep(wait)
            self.waited += wait
        now = self._now()
        self.conn.execute("INSERT INTO api_call_log(ts) VALUES (?)", (now,))
        self.conn.execute(
            "INSERT INTO api_calls(day, calls) VALUES (?, 1) "
            "ON CONFLICT(day) DO UPDATE SET calls = calls + 1",
            (self.day(),),
        )
        self.spent += 1
        if self.spent % 500 == 0:
            self.conn.execute("DELETE FROM api_call_log WHERE ts < ?", (now - 2 * self.WINDOW_S,))
        self.conn.commit()


class TMClient:
    def __init__(
        self,
        api_key: str,
        transport: Transport,
        clock: Clock,
        budget: CallBudget,
        rate: float = DEFAULT_RATE,
        max_retries: int = MAX_RETRIES,
    ) -> None:
        self.key, self.transport, self.clock, self.budget = api_key, transport, clock, budget
        self.bucket = TokenBucket(rate, clock)
        self.max_retries = max_retries
        self.last_available: int | None = None
        self.calls = 0          # HTTP requests sent by this client (this process)
        self.n429 = 0
        self.planned = 0        # calls the current job expects to make; sets the 1% 429 threshold
        self.rate_limited = False

    def _get(self, path: str, params: dict[str, Any], base: str = API_BASE) -> Response:
        url = base + path
        for attempt in range(self.max_retries + 1):
            self.budget.spend()
            self.bucket.acquire()
            resp = self.transport.get(url, {**params, "apikey": self.key})
            self.calls += 1
            avail = resp.header("Rate-Limit-Available")
            if avail and avail.strip().lstrip("-").isdigit():
                self.last_available = int(avail)
                if self.last_available <= RESERVE_AVAILABLE and resp.status != 429:
                    log.warning("Rate-Limit-Available=%s <= reserve %s; stopping after this call",
                                avail, RESERVE_AVAILABLE)
                    self.budget.stop_now(f"Rate-Limit-Available={avail} <= reserve {RESERVE_AVAILABLE}")
            if resp.status in (401, 403):
                raise AuthError(f"Ticketmaster returned HTTP {resp.status}: the API key was rejected "
                                "or access is forbidden. Check TICKETMASTER_API_KEY; not retrying.")
            if resp.status == 429:
                self.n429 += 1
                body = resp.body[:2000].decode("utf-8", "replace").lower()
                retry_after = resp.header("Retry-After")
                reason = None
                if "quota" in body:
                    reason = "Ticketmaster reports the daily quota is used up (429 quota body)"
                elif retry_after:
                    reason = f"HTTP 429 with Retry-After={retry_after}"
                elif self.n429 > MAX_429_SHARE * max(self.calls, self.planned):
                    reason = f"HTTP 429 on {self.n429} of {self.calls} calls (> {MAX_429_SHARE:.0%} of the run)"
                elif attempt == self.max_retries:
                    reason = f"HTTP 429 persisted after {attempt + 1} attempts on {path}"
                if reason:
                    self.rate_limited = True
                    raise RateLimitStop(f"{reason}; stopping for the day; report it")
                # Transient spike arrest (no Retry-After, no quota body, rare): one exponential backoff.
                wait = float(2 ** (attempt + 1))
                log.warning("429 on %s; waiting %.1fs (retry %d/%d; %d/%d calls so far)", path, wait,
                            attempt + 1, self.max_retries, self.n429, self.calls)
                self.clock.sleep(wait)
                continue
            if resp.status >= 500 and attempt < self.max_retries:
                wait = float(2 ** (attempt + 1))
                log.warning("HTTP %d on %s; waiting %.0fs (retry %d/%d)", resp.status, path, wait,
                            attempt + 1, self.max_retries)
                self.clock.sleep(wait)
                continue
            return resp
        raise AssertionError("unreachable")  # pragma: no cover

    def get_event(self, event_id: str) -> Response:
        return self._get(f"/events/{event_id}.json", {})

    def search_events(self, params: dict[str, Any]) -> Response:
        return self._get("/events.json", params)

    def get_feed(self, country: str = "US") -> Response:
        return self._get("", {"countryCode": country}, base=FEED_URL)


# --------------------------------------------------------------------------- storage

SCHEMA = """
CREATE TABLE IF NOT EXISTS watchlist (
    event_id        TEXT PRIMARY KEY,
    added_at        TEXT NOT NULL,           -- UTC ISO
    source          TEXT NOT NULL,           -- manual | csv | discover
    event_date      TEXT,                    -- venue-local YYYY-MM-DD, refreshed by each snapshot
    active          INTEGER NOT NULL DEFAULT 1,
    deactivated_why TEXT,
    not_found_streak INTEGER NOT NULL DEFAULT 0,
    first_days_out  INTEGER                  -- days to show when first snapshotted
);
CREATE TABLE IF NOT EXISTS snapshots (
    event_id            TEXT NOT NULL,
    snap_date           TEXT NOT NULL,       -- UTC date of the run (idempotency key)
    snapshot_ts         TEXT NOT NULL,       -- UTC ISO timestamp of the response
    http_status         INTEGER NOT NULL,
    name                TEXT,
    event_status        TEXT,                -- dates.status.code: onsale offsale cancelled postponed rescheduled
    local_date          TEXT,
    local_time          TEXT,
    start_utc           TEXT,                -- dates.start.dateTime
    date_tbd            INTEGER,
    time_tba            INTEGER,
    event_timezone      TEXT,
    days_until_show     INTEGER,             -- local_date minus snapshot date in venue tz
    hours_until_show    REAL,                -- start_utc minus snapshot_ts
    public_sale_start   TEXT,
    public_sale_end     TEXT,
    public_sale_start_tbd INTEGER,
    presales_json       TEXT,                -- [{name, startDateTime, endDateTime}]
    venue_id            TEXT,
    venue_name          TEXT,
    city                TEXT,
    state               TEXT,
    country             TEXT,
    venue_lat           REAL,
    venue_lon           REAL,
    attraction_ids      TEXT,                -- comma-separated
    attractions_json    TEXT,                -- [{id, name}]
    segment             TEXT,
    genre               TEXT,
    subgenre            TEXT,
    classifications_json TEXT,
    has_price_ranges    INTEGER NOT NULL DEFAULT 0,
    price_min           REAL,                -- min over all ranges, for convenience
    price_max           REAL,
    ticket_limit_info   TEXT,
    source_url          TEXT NOT NULL,       -- request URL without apikey
    raw_json_gz         BLOB,                -- gzipped response body, apikey stripped
    PRIMARY KEY (event_id, snap_date)
);
CREATE INDEX IF NOT EXISTS snapshots_by_date ON snapshots(snap_date);
CREATE TABLE IF NOT EXISTS price_ranges (
    event_id  TEXT NOT NULL,
    snap_date TEXT NOT NULL,
    idx       INTEGER NOT NULL,
    type      TEXT,                          -- e.g. standard, "standard including fees"
    currency  TEXT,
    min       REAL,
    max       REAL,
    PRIMARY KEY (event_id, snap_date, idx)
);
CREATE TABLE IF NOT EXISTS runs (
    run_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    command         TEXT NOT NULL,
    snap_date       TEXT NOT NULL,
    started_at      TEXT NOT NULL,
    finished_at     TEXT,
    calls_used      INTEGER DEFAULT 0,
    snapshots_saved INTEGER DEFAULT 0,
    missing_price_ranges INTEGER DEFAULT 0,
    not_found       INTEGER DEFAULT 0,
    errors          INTEGER DEFAULT 0,
    added_to_watchlist INTEGER DEFAULT 0,
    remaining_todo  INTEGER DEFAULT 0,
    stopped_reason  TEXT
);
CREATE TABLE IF NOT EXISTS api_call_log (
    ts REAL NOT NULL                         -- UTC epoch seconds of each request (rolling-24h budget)
);
CREATE INDEX IF NOT EXISTS api_call_log_ts ON api_call_log(ts);
CREATE TABLE IF NOT EXISTS api_calls (
    day   TEXT PRIMARY KEY,                  -- UTC date
    calls INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS discover_slices (
    slice_key  TEXT PRIMARY KEY,             -- e.g. 2026-12-01
    fetched_on TEXT NOT NULL,
    pages      INTEGER NOT NULL,
    total_elements INTEGER
);
CREATE TABLE IF NOT EXISTS discover_candidates (
    event_id   TEXT PRIMARY KEY,
    seen_on    TEXT NOT NULL,
    name       TEXT,
    local_date TEXT,
    event_status TEXT,
    segment    TEXT,
    genre      TEXT,
    subgenre   TEXT,
    venue_id   TEXT,
    venue_name TEXT,
    city       TEXT,
    state      TEXT,
    attraction_ids TEXT,
    has_price_ranges INTEGER
);
CREATE TABLE IF NOT EXISTS promotions (
    event_id        TEXT PRIMARY KEY,
    promoted_on     TEXT NOT NULL,           -- UTC date added to the watchlist (= path start)
    first_seen_on   TEXT,                    -- first discover scan that saw it (without ranges)
    ranges_seen_on  TEXT,                    -- first scan that saw priceRanges
    days_out_at_promotion INTEGER
);
CREATE VIEW IF NOT EXISTS missing_price_ranges AS
    SELECT event_id, snap_date, name, event_status, days_until_show
    FROM snapshots WHERE http_status = 200 AND has_price_ranges = 0;
"""


# Columns added after the first deployment; connect() adds them to older databases.
MIGRATIONS = {
    "watchlist": {
        "selected_for_ranges": "INTEGER",    # 1 = ranges pool (incl. promotions), 0 = random no-ranges draw, NULL = manual/pilot
        "stratum": "TEXT",                   # far|near + '|' + state + '|' + genre at selection
        "selection_prob": "REAL",            # selected / available in (stratum, ranges pool) that day
        "has_ranges_at_selection": "INTEGER",
    },
    "discover_candidates": {
        "first_seen_on": "TEXT",
        "first_has_ranges": "INTEGER",
        "ranges_seen_on": "TEXT",            # first scan date with priceRanges
    },
}


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    for table, cols in MIGRATIONS.items():
        have = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        for col, typ in cols.items():
            if col not in have:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typ}")
    _sweep_schema(conn)
    conn.commit()
    return conn


def _sweep_schema(conn: sqlite3.Connection) -> None:
    """sweep_snapshots mirrors snapshots' columns (plus raw_hash), so promotion is a plain column copy."""
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='sweep_snapshots'").fetchone():
        cols = [f"{r[1]} {r[2]}" for r in conn.execute("PRAGMA table_info(snapshots)")]
        conn.execute(f"CREATE TABLE sweep_snapshots ({', '.join(cols)}, raw_hash TEXT, "
                     "PRIMARY KEY (event_id, snap_date))")
    conn.executescript("""
CREATE INDEX IF NOT EXISTS sweep_snapshots_by_date ON sweep_snapshots(snap_date);
CREATE TABLE IF NOT EXISTS sweep_price_ranges (
    event_id TEXT NOT NULL, snap_date TEXT NOT NULL, idx INTEGER NOT NULL,
    type TEXT, currency TEXT, min REAL, max REAL,
    PRIMARY KEY (event_id, snap_date, idx)
);
CREATE TABLE IF NOT EXISTS sweep_slices (    -- a finished search window; reruns the same day skip it
    snap_date TEXT NOT NULL, start_utc TEXT NOT NULL, end_utc TEXT NOT NULL,
    pages INTEGER NOT NULL, total_elements INTEGER, events INTEGER,
    PRIMARY KEY (snap_date, start_utc, end_utc)
);
CREATE TABLE IF NOT EXISTS sweep_last (      -- hash of each event's last stored raw JSON
    event_id TEXT PRIMARY KEY, raw_hash TEXT NOT NULL, snap_date TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS collector_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL, set_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS near_snapshots (   -- final-week shows, every `near` pass
    event_id TEXT NOT NULL, snapshot_ts TEXT NOT NULL, local_date TEXT, event_status TEXT,
    price_min REAL, price_max REAL, has_price_ranges INTEGER,
    PRIMARY KEY (event_id, snapshot_ts)
);
CREATE TABLE IF NOT EXISTS feed_runs (
    run_ts TEXT PRIMARY KEY, last_modified TEXT, events INTEGER, music INTEGER,
    new_events INTEGER, changes INTEGER, skipped INTEGER
);
CREATE TABLE IF NOT EXISTS feed_state (       -- latest feed state per music event
    event_id TEXT PRIMARY KEY, first_seen_ts TEXT NOT NULL, last_seen_ts TEXT NOT NULL,
    name TEXT, local_date TEXT, start_utc TEXT, venue_id TEXT, venue_name TEXT, city TEXT, state TEXT,
    attraction_ids TEXT, genre TEXT, subgenre TEXT, event_status TEXT, hot_event INTEGER, transactable INTEGER,
    official_seller INTEGER, source TEXT, onsale_start TEXT, onsale_end TEXT, presales_n INTEGER, url TEXT,
    in_feed INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS feed_changes (     -- one row per tracked field change, at feed-pull time
    event_id TEXT NOT NULL, ts TEXT NOT NULL, field TEXT NOT NULL, old TEXT, new TEXT
);
CREATE INDEX IF NOT EXISTS feed_changes_by_event ON feed_changes(event_id, ts);
""")


# --------------------------------------------------------------------------- parsing


def _tz(name: str | None) -> ZoneInfo:
    try:
        return ZoneInfo(name) if name else ZoneInfo("UTC")
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def _parse_iso(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def _num(x: Any) -> float | None:
    try:
        return float(x) if x is not None else None
    except (TypeError, ValueError):
        return None


def _primary_classification(ev: dict) -> dict:
    cls = ev.get("classifications") or []
    for c in cls:
        if c.get("primary"):
            return c
    return cls[0] if cls else {}


def parse_event(ev: dict, snapshot_ts: datetime) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Map one Discovery event object to a snapshot row and its price-range rows."""
    dates = ev.get("dates") or {}
    start = dates.get("start") or {}
    venues = (ev.get("_embedded") or {}).get("venues") or [{}]
    venue = venues[0]
    attractions = [{"id": a.get("id"), "name": a.get("name")}
                   for a in (ev.get("_embedded") or {}).get("attractions") or []]
    cls = _primary_classification(ev)
    public = (ev.get("sales") or {}).get("public") or {}
    presales = [{"name": p.get("name"), "startDateTime": p.get("startDateTime"),
                 "endDateTime": p.get("endDateTime")}
                for p in (ev.get("sales") or {}).get("presales") or []]

    event_tz = dates.get("timezone") or venue.get("timezone")
    local_date = start.get("localDate")
    days_until = None
    if local_date:
        snap_local = snapshot_ts.astimezone(_tz(event_tz)).date()
        days_until = (date.fromisoformat(local_date) - snap_local).days
    start_utc = _parse_iso(start.get("dateTime"))
    hours_until = round((start_utc - snapshot_ts).total_seconds() / 3600, 2) if start_utc else None

    ranges = []
    for i, pr in enumerate(ev.get("priceRanges") or []):
        ranges.append({"idx": i, "type": pr.get("type"), "currency": pr.get("currency"),
                       "min": _num(pr.get("min")), "max": _num(pr.get("max"))})
    mins = [r["min"] for r in ranges if r["min"] is not None]
    maxs = [r["max"] for r in ranges if r["max"] is not None]
    loc = venue.get("location") or {}

    row = {
        "name": ev.get("name"),
        "event_status": (dates.get("status") or {}).get("code"),
        "local_date": local_date,
        "local_time": start.get("localTime"),
        "start_utc": start.get("dateTime"),
        "date_tbd": int(bool(start.get("dateTBD") or start.get("dateTBA"))),
        "time_tba": int(bool(start.get("timeTBA") or start.get("noSpecificTime"))),
        "event_timezone": event_tz,
        "days_until_show": days_until,
        "hours_until_show": hours_until,
        "public_sale_start": public.get("startDateTime"),
        "public_sale_end": public.get("endDateTime"),
        "public_sale_start_tbd": int(bool(public.get("startTBD") or public.get("startTBA"))),
        "presales_json": json.dumps(presales) if presales else None,
        "venue_id": venue.get("id"),
        "venue_name": venue.get("name"),
        "city": (venue.get("city") or {}).get("name"),
        "state": (venue.get("state") or {}).get("stateCode"),
        "country": (venue.get("country") or {}).get("countryCode"),
        "venue_lat": _num(loc.get("latitude")),
        "venue_lon": _num(loc.get("longitude")),
        "attraction_ids": ",".join(a["id"] for a in attractions if a["id"]) or None,
        "attractions_json": json.dumps(attractions) if attractions else None,
        "segment": (cls.get("segment") or {}).get("name"),
        "genre": (cls.get("genre") or {}).get("name"),
        "subgenre": (cls.get("subGenre") or {}).get("name"),
        "classifications_json": json.dumps(ev.get("classifications")) if ev.get("classifications") else None,
        "has_price_ranges": int(bool(ranges)),
        "price_min": min(mins) if mins else None,
        "price_max": max(maxs) if maxs else None,
        "ticket_limit_info": (ev.get("ticketLimit") or {}).get("info"),
    }
    return row, ranges


# --------------------------------------------------------------------------- run (daily snapshots)


@dataclass
class RunStats:
    calls_used: int = 0
    snapshots_saved: int = 0
    missing_price_ranges: int = 0
    not_found: int = 0
    errors: int = 0
    added_to_watchlist: int = 0
    remaining_todo: int = 0
    stopped_reason: str | None = None


def _start_run(conn: sqlite3.Connection, command: str, clock: Clock) -> int:
    now = clock.now()
    cur = conn.execute("INSERT INTO runs(command, snap_date, started_at) VALUES (?,?,?)",
                       (command, now.date().isoformat(), now.isoformat()))
    conn.commit()
    return int(cur.lastrowid)


def _finish_run(conn: sqlite3.Connection, run_id: int, stats: RunStats, clock: Clock) -> None:
    conn.execute(
        "UPDATE runs SET finished_at=?, calls_used=?, snapshots_saved=?, missing_price_ranges=?, "
        "not_found=?, errors=?, added_to_watchlist=?, remaining_todo=?, stopped_reason=? WHERE run_id=?",
        (clock.now().isoformat(), stats.calls_used, stats.snapshots_saved, stats.missing_price_ranges,
         stats.not_found, stats.errors, stats.added_to_watchlist, stats.remaining_todo,
         stats.stopped_reason, run_id),
    )
    conn.commit()


def _expire_past_events(conn: sqlite3.Connection, today_utc: date) -> int:
    # Venue-local dates can lag UTC by up to a day, so only expire events before yesterday-UTC.
    cutoff = (today_utc - timedelta(days=1)).isoformat()
    cur = conn.execute(
        "UPDATE watchlist SET active=0, deactivated_why='show date passed' "
        "WHERE active=1 AND event_date IS NOT NULL AND event_date < ?", (cutoff,))
    conn.commit()
    return cur.rowcount


def run_snapshots(conn: sqlite3.Connection, client: TMClient, clock: Clock,
                  limit: int | None = None, command: str = "run") -> RunStats:
    stats = RunStats()
    run_id = _start_run(conn, command, clock)
    snap_date = clock.now().date().isoformat()
    _expire_past_events(conn, clock.now().date())
    todo = [r[0] for r in conn.execute(
        "SELECT event_id FROM watchlist WHERE active=1 AND event_id NOT IN "
        "(SELECT event_id FROM snapshots WHERE snap_date=?) "
        "ORDER BY event_date IS NULL, event_date, event_id", (snap_date,))]
    if limit is not None:
        todo = todo[:limit]
    log.info("run %s: %d events to snapshot, budget remaining %d", snap_date, len(todo),
             client.budget.remaining())
    client.planned = max(client.planned, client.calls + len(todo))
    calls_before = client.budget.spent
    done = 0
    try:
        for event_id in todo:
            _snapshot_one(conn, client, clock, event_id, snap_date, stats)
            done += 1
    except StopForToday as exc:
        stats.stopped_reason = str(exc)
        log.warning("stopped for today: %s", exc)
        if isinstance(exc, AuthError):
            stats.remaining_todo = len(todo) - done
            stats.calls_used = client.budget.spent - calls_before
            _finish_run(conn, run_id, stats, clock)
            raise
    stats.remaining_todo = len(todo) - done
    stats.calls_used = client.budget.spent - calls_before
    _finish_run(conn, run_id, stats, clock)
    log.info("run %s done: saved=%d missing_priceRanges=%d not_found=%d errors=%d calls=%d left=%d%s",
             snap_date, stats.snapshots_saved, stats.missing_price_ranges, stats.not_found,
             stats.errors, stats.calls_used, stats.remaining_todo,
             f" stopped={stats.stopped_reason}" if stats.stopped_reason else "")
    return stats


def _snapshot_one(conn: sqlite3.Connection, client: TMClient, clock: Clock, event_id: str,
                  snap_date: str, stats: RunStats) -> None:
    source_url = f"{API_BASE}/events/{event_id}.json"
    try:
        resp = client.get_event(event_id)
    except TransportError as exc:
        stats.errors += 1
        log.error("network error for %s: %s", event_id, exc)
        return
    ts = clock.now()
    if resp.status == 404:
        stats.not_found += 1
        conn.execute("INSERT OR IGNORE INTO snapshots(event_id, snap_date, snapshot_ts, http_status, "
                     "source_url) VALUES (?,?,?,?,?)", (event_id, snap_date, ts.isoformat(), 404, source_url))
        conn.execute("UPDATE watchlist SET not_found_streak = not_found_streak + 1 WHERE event_id=?",
                     (event_id,))
        conn.execute("UPDATE watchlist SET active=0, deactivated_why='404 repeatedly' "
                     "WHERE event_id=? AND not_found_streak >= ?", (event_id, DEACTIVATE_AFTER_404S))
        conn.commit()
        log.info("not_found event=%s (404)", event_id)
        return
    if resp.status != 200:
        stats.errors += 1
        log.error("HTTP %d for %s; no snapshot saved (a rerun today will retry)", resp.status, event_id)
        return
    try:
        ev = resp.json()
    except (ValueError, UnicodeDecodeError):
        stats.errors += 1
        log.error("unparseable JSON for %s", event_id)
        return
    row, ranges = parse_event(ev, ts)
    raw = strip_apikey(resp.body.decode("utf-8", "replace"), client.key).encode("utf-8")
    cols = {"event_id": event_id, "snap_date": snap_date, "snapshot_ts": ts.isoformat(),
            "http_status": 200, **row, "source_url": source_url, "raw_json_gz": gzip.compress(raw)}
    cur = conn.execute(f"INSERT OR IGNORE INTO snapshots({','.join(cols)}) VALUES "
                       f"({','.join('?' * len(cols))})", list(cols.values()))
    if cur.rowcount:
        conn.executemany("INSERT OR IGNORE INTO price_ranges(event_id, snap_date, idx, type, currency, min, max) "
                         "VALUES (?,?,?,?,?,?,?)",
                         [(event_id, snap_date, r["idx"], r["type"], r["currency"], r["min"], r["max"])
                          for r in ranges])
        stats.snapshots_saved += 1
        if not ranges:
            stats.missing_price_ranges += 1
            log.info("missing_priceRanges event=%s status=%s days_until=%s",
                     event_id, row["event_status"], row["days_until_show"])
    _watchlist_after_snapshot(conn, event_id, row)
    conn.commit()


def _watchlist_after_snapshot(conn: sqlite3.Connection, event_id: str, row: dict[str, Any]) -> None:
    conn.execute("UPDATE watchlist SET event_date=COALESCE(?, event_date), not_found_streak=0, "
                 "first_days_out=COALESCE(first_days_out, ?) WHERE event_id=?",
                 (row["local_date"], row["days_until_show"], event_id))
    if row["event_status"] == "cancelled":
        conn.execute("UPDATE watchlist SET active=0, deactivated_why='cancelled' WHERE event_id=?", (event_id,))
    elif row["days_until_show"] is not None and row["days_until_show"] < 0:
        conn.execute("UPDATE watchlist SET active=0, deactivated_why='show date passed' WHERE event_id=?",
                     (event_id,))


# --------------------------------------------------------------------------- discover

EXCLUDE_NAME_RE = re.compile(
    r"\b(parking|upgrade|shuttle|voucher|gift card|add[- ]on|lot pass|locker|camping|merch(andise)? bundle)\b",
    re.IGNORECASE)


def _candidate_from_search(ev: dict, today: date) -> dict[str, Any]:
    row, ranges = parse_event(ev, datetime.combine(today, datetime.min.time(), timezone.utc))
    return {"event_id": ev.get("id"), "seen_on": today.isoformat(), "name": row["name"],
            "local_date": row["local_date"], "event_status": row["event_status"], "segment": row["segment"],
            "genre": row["genre"], "subgenre": row["subgenre"], "venue_id": row["venue_id"],
            "venue_name": row["venue_name"], "city": row["city"], "state": row["state"],
            "attraction_ids": row["attraction_ids"], "has_price_ranges": int(bool(ranges))}


def _upsert_candidate(conn: sqlite3.Connection, c: dict[str, Any]) -> None:
    """Latest scan wins for every field except the first-seen ones, which make promotions auditable."""
    c = {**c, "first_seen_on": c["seen_on"], "first_has_ranges": c["has_price_ranges"],
         "ranges_seen_on": c["seen_on"] if c["has_price_ranges"] else None}
    keep = {"event_id", "first_seen_on", "first_has_ranges", "ranges_seen_on"}
    updates = ", ".join(f"{k}=excluded.{k}" for k in c if k not in keep)
    conn.execute(
        f"INSERT INTO discover_candidates({','.join(c)}) VALUES ({','.join('?' * len(c))}) "
        f"ON CONFLICT(event_id) DO UPDATE SET {updates}, "
        "ranges_seen_on = COALESCE(discover_candidates.ranges_seen_on, excluded.ranges_seen_on)",
        list(c.values()))


def sweep_done(conn: sqlite3.Connection, day: date) -> bool:
    return bool(conn.execute("SELECT 1 FROM runs WHERE command='sweep' AND snap_date=? AND finished_at IS NOT NULL "
                             "AND remaining_todo=0", (day.isoformat(),)).fetchone())


def candidates_from_sweep(conn: sqlite3.Connection, day: date) -> int:
    """The sweep already saw every upcoming music event today: refresh discover_candidates from it."""
    cols = ["event_id", "name", "local_date", "event_status", "segment", "genre", "subgenre", "venue_id",
            "venue_name", "city", "state", "attraction_ids", "has_price_ranges"]
    rows = conn.execute(f"SELECT {','.join(cols)} FROM sweep_snapshots WHERE snap_date=?", (day.isoformat(),)).fetchall()
    for r in rows:
        _upsert_candidate(conn, {**dict(zip(cols, r)), "seen_on": day.isoformat()})
    conn.commit()
    return len(rows)


def fetch_candidates(conn: sqlite3.Connection, client: TMClient, clock: Clock, days_min: int, days_max: int,
                     max_calls: int, max_pages_per_day: int = 5, page_size: int = 200,
                     country: str = "US") -> int:
    """Search one UTC day at a time (fresh slices are reused for DISCOVER_EVERY_DAYS days)."""
    today = clock.now().date()
    calls = 0
    for d in range(days_min, days_max + 1):
        day = today + timedelta(days=d)
        key = day.isoformat()
        row = conn.execute("SELECT fetched_on FROM discover_slices WHERE slice_key=?", (key,)).fetchone()
        if row and (today - date.fromisoformat(row[0])).days < DISCOVER_EVERY_DAYS:
            continue
        pages, total = 0, None
        page = 0
        while page < max_pages_per_day and (page + 1) * page_size <= DEEP_PAGING_CAP:
            if calls >= max_calls:
                return calls
            params = {"classificationName": "music", "countryCode": country,
                      "startDateTime": f"{key}T00:00:00Z",
                      "endDateTime": f"{(day + timedelta(days=1)).isoformat()}T00:00:00Z",
                      "size": page_size, "page": page, "sort": "id,asc"}
            resp = client.search_events(params)
            calls += 1
            if resp.status != 200:
                log.error("discover: HTTP %d for day %s page %d", resp.status, key, page)
                break
            data = resp.json()
            events = (data.get("_embedded") or {}).get("events") or []
            info = data.get("page") or {}
            total = info.get("totalElements", total)
            for ev in events:
                if not ev.get("id"):
                    continue
                _upsert_candidate(conn, _candidate_from_search(ev, today))
            pages += 1
            page += 1
            if not events or page >= int(info.get("totalPages") or 0):
                break
        conn.execute("INSERT OR REPLACE INTO discover_slices(slice_key, fetched_on, pages, total_elements) "
                     "VALUES (?,?,?,?)", (key, today.isoformat(), pages, total))
        conn.commit()
        if total and total > DEEP_PAGING_CAP:
            log.info("discover: %s has %d events; only the first %d are reachable (TM deep-paging cap)",
                     key, total, min(DEEP_PAGING_CAP, max_pages_per_day * page_size))
    return calls


def select_diverse(cands: list[dict[str, Any]], slots: int, today: date, far_share: float,
                   per_venue: int = 3, per_attraction: int = 3, seed: str = "",
                   existing: Iterable[tuple[str | None, str | None]] = ()) -> list[str]:
    """Round-robin over (state, genre) strata, with soft caps per venue and per artist.

    Caps start at per_venue/per_attraction (counting `existing` active watchlist events) and double
    only when slots would otherwise go unfilled. `far_share` of the slots go to shows >= 60 days
    out, the only ones that can yield full 60-day paths.
    """
    rng = random.Random(f"discover-{seed}")
    venue_n: dict[str, int] = {}
    attr_n: dict[str, int] = {}

    def attrs_of(c: dict) -> list[str]:
        return [a for a in (c.get("attraction_ids") or "").split(",") if a]

    for v, a in existing:
        if v:
            venue_n[v] = venue_n.get(v, 0) + 1
        for x in (a or "").split(","):
            if x:
                attr_n[x] = attr_n.get(x, 0) + 1

    def days_out(c: dict) -> int:
        return (date.fromisoformat(c["local_date"]) - today).days

    def pick(pool: list[dict], n: int) -> list[str]:
        out: list[str] = []
        left = list(pool)
        mult = 1
        while len(out) < n and left:
            strata: dict[tuple, list[dict]] = {}
            for c in left:
                strata.setdefault((c.get("state") or "?", c.get("genre") or "?"), []).append(c)
            keys = sorted(strata)
            rng.shuffle(keys)
            for k in keys:
                rng.shuffle(strata[k])
            capped: list[dict] = []
            while len(out) < n and any(strata[k] for k in keys):
                for k in keys:
                    while strata[k]:
                        c = strata[k].pop()
                        v = c.get("venue_id") or c["event_id"]
                        attrs = attrs_of(c)
                        if venue_n.get(v, 0) >= per_venue * mult or \
                                any(attr_n.get(a, 0) >= per_attraction * mult for a in attrs):
                            capped.append(c)
                            continue
                        venue_n[v] = venue_n.get(v, 0) + 1
                        for a in attrs:
                            attr_n[a] = attr_n.get(a, 0) + 1
                        out.append(c["event_id"])
                        break
                    if len(out) >= n:
                        break
            left = capped
            mult *= 2
        return out

    far = [c for c in cands if days_out(c) >= 60]
    near = [c for c in cands if days_out(c) < 60]
    n_far = min(len(far), round(slots * far_share))
    chosen = pick(far, n_far)
    chosen += pick(near, slots - len(chosen))
    if len(chosen) < slots:  # near pool ran dry; give the rest to far
        taken = set(chosen)
        chosen += pick([c for c in far if c["event_id"] not in taken], slots - len(chosen))
    return chosen


RANGES_SHARE = 0.8


def _stratum(c: dict[str, Any], today: date) -> str:
    band = "far" if (date.fromisoformat(c["local_date"]) - today).days >= 60 else "near"
    return f"{band}|{c.get('state') or '?'}|{c.get('genre') or '?'}"


def _proportional_random(pool: list[dict[str, Any]], n: int, today: date, rng: random.Random) -> list[str]:
    """Simple random draw of n within each stratum, n allocated proportionally (largest remainder)."""
    strata: dict[str, list[dict]] = {}
    for c in pool:
        strata.setdefault(_stratum(c, today), []).append(c)
    n = min(n, len(pool))
    if n <= 0:
        return []
    quotas = {k: n * len(v) / len(pool) for k, v in sorted(strata.items())}
    alloc = {k: int(q) for k, q in quotas.items()}
    for k in sorted(quotas, key=lambda k: (alloc[k] - quotas[k], k))[: n - sum(alloc.values())]:
        alloc[k] += 1
    out: list[str] = []
    for k in sorted(strata):
        members = sorted(strata[k], key=lambda c: c["event_id"])
        out += [c["event_id"] for c in rng.sample(members, alloc[k])]
    return out


def select_panel(cands: list[dict[str, Any]], slots: int, today: date, far_share: float,
                 ranges_share: float = RANGES_SHARE, seed: str = "",
                 existing: Iterable[tuple[str | None, str | None]] = ()) -> list[dict[str, Any]]:
    """Option (b) from the 2026-10-19 pilot: tilt the panel toward events that publish priceRanges.

    In each band (far = show >= 60 days out, near) `ranges_share` of the slots go to events with
    priceRanges, picked for diversity by select_diverse; the rest are a simple random draw, within
    (band, state, genre) strata, of events without ranges. Each pick carries its stratum and the
    realized selection probability (selected / available in its stratum and pool) for IPW.
    """
    rng = random.Random(f"panel-{seed}")
    existing = list(existing)
    far = [c for c in cands if _stratum(c, today).startswith("far|")]
    near = [c for c in cands if not _stratum(c, today).startswith("far|")]
    far_slots = min(len(far), round(slots * far_share))
    near_slots = min(len(near), slots - far_slots)
    far_slots = min(len(far), slots - near_slots)  # near pool short: give the rest to far

    chosen: list[tuple[str, int]] = []
    for pool, n in ((far, far_slots), (near, near_slots)):
        with_r = [c for c in pool if c.get("has_price_ranges")]
        without = [c for c in pool if not c.get("has_price_ranges")]
        n_r = min(len(with_r), round(n * ranges_share))
        n_0 = min(len(without), n - n_r)
        n_r = min(len(with_r), n - n_0)  # without-pool short: give the rest to the ranges pool
        picked_r = select_diverse(with_r, n_r, today, 1.0, seed=f"{seed}-{len(chosen)}", existing=existing)
        by_id = {c["event_id"]: c for c in with_r}
        existing += [(by_id[e].get("venue_id"), by_id[e].get("attraction_ids")) for e in picked_r]
        chosen += [(e, 1) for e in picked_r] + [(e, 0) for e in _proportional_random(without, n_0, today, rng)]

    avail: dict[tuple[str, int], int] = {}
    for c in cands:
        k = (_stratum(c, today), int(bool(c.get("has_price_ranges"))))
        avail[k] = avail.get(k, 0) + 1
    by_id = {c["event_id"]: c for c in cands}
    keys = {e: (_stratum(by_id[e], today), flag) for e, flag in chosen}
    sel: dict[tuple[str, int], int] = {}
    for k in keys.values():
        sel[k] = sel.get(k, 0) + 1
    return [{"event_id": e, "selected_for_ranges": flag, "stratum": keys[e][0],
             "selection_prob": round(sel[keys[e]] / avail[keys[e]], 6),
             "has_ranges_at_selection": int(bool(by_id[e].get("has_price_ranges")))}
            for e, flag in chosen]


def discover(conn: sqlite3.Connection, client: TMClient, clock: Clock, target: int = DEFAULT_TARGET,
             days_min: int = 1, days_max: int = 120, max_calls: int = 700, far_share: float = DEFAULT_FAR_SHARE,
             max_pages_per_day: int = 5) -> RunStats:
    stats = RunStats()
    run_id = _start_run(conn, "discover", clock)
    today = clock.now().date()
    calls_before = client.budget.spent
    client.planned = max(client.planned, client.calls + max_calls)
    if sweep_done(conn, today):
        n = candidates_from_sweep(conn, today)
        log.info("discover: %d candidates from today's sweep (no search calls)", n)
    else:
        try:
            fetch_candidates(conn, client, clock, days_min, days_max, max_calls, max_pages_per_day)
        except StopForToday as exc:
            stats.stopped_reason = str(exc)
            log.warning("discover stopped: %s", exc)
    stats.calls_used = client.budget.spent - calls_before

    active = conn.execute("SELECT COUNT(*) FROM watchlist WHERE active=1").fetchone()[0]
    slots = max(0, target - active)
    lo, hi = (today + timedelta(days=days_min)).isoformat(), (today + timedelta(days=days_max)).isoformat()
    cols = ["event_id", "name", "local_date", "event_status", "segment", "genre", "venue_id", "state",
            "attraction_ids", "has_price_ranges", "first_seen_on", "first_has_ranges", "ranges_seen_on"]
    cands = [dict(zip(cols, r)) for r in conn.execute(
        f"SELECT {','.join(cols)} FROM discover_candidates WHERE local_date BETWEEN ? AND ? "
        "AND event_id NOT IN (SELECT event_id FROM watchlist) "
        "AND COALESCE(event_status,'') NOT IN ('cancelled') AND COALESCE(segment,'Music') = 'Music'",
        (lo, hi))]
    cands = [c for c in cands if not EXCLUDE_NAME_RE.search(c.get("name") or "")]
    # Don't let one venue/artist dominate, counting what is already on the watchlist.
    existing = conn.execute(
        "SELECT c.venue_id, c.attraction_ids FROM watchlist w JOIN discover_candidates c USING(event_id) "
        "WHERE w.active=1").fetchall()
    chosen = select_panel(cands, slots, today, far_share, seed=today.isoformat(),
                          existing=existing) if slots else []
    now = clock.now().isoformat()
    by_id = {c["event_id"]: c for c in cands}
    promos = []
    for p in chosen:
        c = by_id[p["event_id"]]
        promoted = p["selected_for_ranges"] and c.get("first_has_ranges") == 0
        conn.execute("INSERT OR IGNORE INTO watchlist(event_id, added_at, source, event_date, selected_for_ranges, "
                     "stratum, selection_prob, has_ranges_at_selection) VALUES (?,?,?,?,?,?,?,?)",
                     (p["event_id"], now, "promotion" if promoted else "discover", c["local_date"],
                      p["selected_for_ranges"], p["stratum"], p["selection_prob"], p["has_ranges_at_selection"]))
        if promoted:
            days_out = (date.fromisoformat(c["local_date"]) - today).days
            promos.append(p["event_id"])
            conn.execute("INSERT OR IGNORE INTO promotions(event_id, promoted_on, first_seen_on, ranges_seen_on, "
                         "days_out_at_promotion) VALUES (?,?,?,?,?)",
                         (p["event_id"], today.isoformat(), c.get("first_seen_on"), c.get("ranges_seen_on"),
                          days_out))
            log.info("promotion event=%s first_seen=%s ranges_seen=%s days_out=%d (path starts today)",
                     p["event_id"], c.get("first_seen_on"), c.get("ranges_seen_on"), days_out)
    conn.commit()
    stats.added_to_watchlist = len(chosen)
    if promos:
        log.info("discover: %d promotion(s) of events that gained priceRanges", len(promos))
    _finish_run(conn, run_id, stats, clock)
    log.info("discover: %d candidates in window, %d active, added %d (target %d), calls=%d%s",
             len(cands), active, len(chosen), target, stats.calls_used,
             f" stopped={stats.stopped_reason}" if stats.stopped_reason else "")
    return stats


# --------------------------------------------------------------------------- watchlist + misc commands


def watchlist_add(conn: sqlite3.Connection, ids: Iterable[str], source: str, clock: Clock) -> int:
    now = clock.now().isoformat()
    n = 0
    for raw in ids:
        eid = raw.strip()
        if not eid or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", eid):
            if eid:
                log.warning("skipping malformed event id %r", eid)
            continue
        cur = conn.execute("INSERT OR IGNORE INTO watchlist(event_id, added_at, source) VALUES (?,?,?)",
                           (eid, now, source))
        if not cur.rowcount:  # re-adding a deactivated id reactivates it
            cur = conn.execute("UPDATE watchlist SET active=1, deactivated_why=NULL, not_found_streak=0 "
                               "WHERE event_id=? AND active=0", (eid,))
        n += cur.rowcount
    conn.commit()
    return n


def watchlist_import(conn: sqlite3.Connection, path: Path, clock: Clock) -> int:
    with path.open(newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames or "event_id" not in reader.fieldnames:
            raise SystemExit(f"{path}: needs a header row with an 'event_id' column")
        return watchlist_add(conn, (r["event_id"] for r in reader), "csv", clock)


def watchlist_export(conn: sqlite3.Connection, path: Path) -> int:
    rows = conn.execute("SELECT event_id, added_at, source, event_date, active, deactivated_why, first_days_out "
                        "FROM watchlist ORDER BY event_date, event_id").fetchall()
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["event_id", "added_at", "source", "event_date", "active", "deactivated_why", "first_days_out"])
        w.writerows(rows)
    return len(rows)


# --------------------------------------------------------------------------- sweep (all events via search)


def _iso_z(t: datetime) -> str:
    return t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _store_sweep_event(conn: sqlite3.Connection, client: TMClient, ev: dict, snap_date: str, ts: datetime,
                       keep_raw: set[str], stats: RunStats) -> None:
    eid = ev.get("id")
    if not eid:
        return
    row, ranges = parse_event(ev, ts)
    raw = strip_apikey(json.dumps(ev, sort_keys=True, separators=(",", ":")), client.key)
    h = hashlib.sha1(raw.encode()).hexdigest()
    last = conn.execute("SELECT raw_hash FROM sweep_last WHERE event_id=?", (eid,)).fetchone()
    # Raw JSON only when the event changed, or always for watchlist events (they feed `snapshots`).
    blob = gzip.compress(raw.encode()) if (eid in keep_raw or not last or last[0] != h) else None
    cols = {"event_id": eid, "snap_date": snap_date, "snapshot_ts": ts.isoformat(), "http_status": 200, **row,
            "source_url": SWEEP_SOURCE_URL, "raw_json_gz": blob, "raw_hash": h}
    cur = conn.execute(f"INSERT OR IGNORE INTO sweep_snapshots({','.join(cols)}) VALUES "
                       f"({','.join('?' * len(cols))})", list(cols.values()))
    if not cur.rowcount:
        return  # already swept today (an event can shift between pages)
    conn.executemany("INSERT OR IGNORE INTO sweep_price_ranges(event_id, snap_date, idx, type, currency, min, max) "
                     "VALUES (?,?,?,?,?,?,?)",
                     [(eid, snap_date, r["idx"], r["type"], r["currency"], r["min"], r["max"]) for r in ranges])
    conn.execute("INSERT INTO sweep_last(event_id, raw_hash, snap_date) VALUES (?,?,?) "
                 "ON CONFLICT(event_id) DO UPDATE SET raw_hash=excluded.raw_hash, snap_date=excluded.snap_date",
                 (eid, h, snap_date))
    stats.snapshots_saved += 1
    stats.missing_price_ranges += not ranges


def sweep(conn: sqlite3.Connection, client: TMClient, clock: Clock, days_max: int = SWEEP_DAYS_MAX,
          country: str = "US", page_size: int = 200) -> RunStats:
    """Snapshot every upcoming music event, one UTC day window at a time. A window with more results than
    TM's deep-paging cap is split in half until it fits. Finished windows are recorded, so a rerun the same
    day (after a stop or network error) resumes without re-spending calls."""
    stats = RunStats()
    run_id = _start_run(conn, "sweep", clock)
    now = clock.now()
    snap_date = now.date().isoformat()
    day0 = datetime.combine(now.date(), datetime.min.time(), timezone.utc)
    queue = [(day0 + timedelta(days=i), day0 + timedelta(days=i + 1)) for i in range(days_max + 1)]
    keep_raw = {r[0] for r in conn.execute("SELECT event_id FROM watchlist WHERE active=1")}
    calls_before = client.budget.spent
    client.planned = max(client.planned, client.calls + 2 * len(queue))
    windows = 0
    try:
        while queue:
            a, b = queue.pop(0)
            if conn.execute("SELECT 1 FROM sweep_slices WHERE snap_date=? AND start_utc=? AND end_utc=?",
                            (snap_date, _iso_z(a), _iso_z(b))).fetchone():
                continue
            page, total, n, ok, split = 0, None, 0, True, False
            while True:
                params = {"classificationName": "music", "countryCode": country, "startDateTime": _iso_z(a),
                          "endDateTime": _iso_z(b), "size": page_size, "page": page, "sort": "id,asc"}
                try:
                    resp = client.search_events(params)
                except TransportError as exc:
                    stats.errors += 1
                    log.error("sweep: network error for %s page %d: %s", _iso_z(a), page, exc)
                    ok = False
                    break
                if resp.status != 200:
                    stats.errors += 1
                    log.error("sweep: HTTP %d for %s page %d (a rerun today retries it)", resp.status, _iso_z(a), page)
                    ok = False
                    break
                body = resp.json()
                total = int((body.get("page") or {}).get("totalElements") or 0)
                if page == 0 and total > DEEP_PAGING_CAP and b - a > timedelta(hours=1):
                    mid = a + (b - a) / 2
                    queue[:0] = [(a, mid), (mid, b)]
                    split = True
                    break
                ts = clock.now()
                for ev in (body.get("_embedded") or {}).get("events") or []:
                    _store_sweep_event(conn, client, ev, snap_date, ts, keep_raw, stats)
                    n += 1
                conn.commit()
                page += 1
                if page * page_size >= min(total, DEEP_PAGING_CAP):
                    break
            if ok and not split:
                if total and total > DEEP_PAGING_CAP:
                    log.warning("sweep: %s holds %d events (> cap %d) even at 1 h; %d not reachable",
                                _iso_z(a), total, DEEP_PAGING_CAP, total - DEEP_PAGING_CAP)
                conn.execute("INSERT OR IGNORE INTO sweep_slices VALUES (?,?,?,?,?,?)",
                             (snap_date, _iso_z(a), _iso_z(b), page, total, n))
                conn.commit()
                windows += 1
    except StopForToday as exc:
        stats.stopped_reason = str(exc)
        log.warning("sweep stopped: %s", exc)
        if isinstance(exc, AuthError):
            stats.calls_used = client.budget.spent - calls_before
            _finish_run(conn, run_id, stats, clock)
            raise
    stats.remaining_todo = len(queue)
    stats.calls_used = client.budget.spent - calls_before
    _finish_run(conn, run_id, stats, clock)
    log.info("sweep %s done: windows=%d events=%d missing_priceRanges=%d errors=%d calls=%d left=%d%s",
             snap_date, windows, stats.snapshots_saved, stats.missing_price_ranges, stats.errors,
             stats.calls_used, stats.remaining_todo, f" stopped={stats.stopped_reason}" if stats.stopped_reason else "")
    return stats


def near(conn: sqlite3.Connection, client: TMClient, clock: Clock, days: int = NEAR_DAYS, country: str = "US",
         page_size: int = 200) -> RunStats:
    """One intraday pass over shows dated today .. today+days. Not resumable by design: each pass is its own
    observation time; a window that fails is just missing from this pass."""
    stats = RunStats()
    run_id = _start_run(conn, "near", clock)
    calls_before = client.budget.spent
    now = clock.now()
    day0 = datetime.combine(now.date(), datetime.min.time(), timezone.utc)
    queue = [(day0 + timedelta(days=i), day0 + timedelta(days=i + 1)) for i in range(days + 1)]
    client.planned = max(client.planned, client.calls + 2 * len(queue))
    try:
        while queue:
            a, b = queue.pop(0)
            page = 0
            while True:
                try:
                    resp = client.search_events({"classificationName": "music", "countryCode": country,
                                                 "startDateTime": _iso_z(a), "endDateTime": _iso_z(b),
                                                 "size": page_size, "page": page, "sort": "id,asc"})
                except TransportError as exc:
                    stats.errors += 1
                    log.error("near: network error for %s: %s", _iso_z(a), exc)
                    break
                if resp.status != 200:
                    stats.errors += 1
                    log.error("near: HTTP %d for %s page %d", resp.status, _iso_z(a), page)
                    break
                body = resp.json()
                total = int((body.get("page") or {}).get("totalElements") or 0)
                if page == 0 and total > DEEP_PAGING_CAP and b - a > timedelta(hours=1):
                    mid = a + (b - a) / 2
                    queue[:0] = [(a, mid), (mid, b)]
                    break
                ts = clock.now()
                rows = []
                for ev in (body.get("_embedded") or {}).get("events") or []:
                    if not ev.get("id"):
                        continue
                    row, ranges = parse_event(ev, ts)
                    rows.append((ev["id"], ts.isoformat(), row["local_date"], row["event_status"], row["price_min"],
                                 row["price_max"], int(bool(ranges))))
                conn.executemany("INSERT OR IGNORE INTO near_snapshots VALUES (?,?,?,?,?,?,?)", rows)
                conn.commit()
                stats.snapshots_saved += len(rows)
                page += 1
                if page * page_size >= min(total, DEEP_PAGING_CAP):
                    break
    except StopForToday as exc:
        stats.stopped_reason = str(exc)
        log.warning("near stopped: %s", exc)
        if isinstance(exc, AuthError):
            stats.calls_used = client.budget.spent - calls_before
            _finish_run(conn, run_id, stats, clock)
            raise
    stats.calls_used = client.budget.spent - calls_before
    _finish_run(conn, run_id, stats, clock)
    log.info("near pass %s: %d shows, calls=%d errors=%d", now.isoformat(timespec="minutes"),
             stats.snapshots_saved, stats.calls_used, stats.errors)
    return stats


def promote_sweep(conn: sqlite3.Connection, snap_date: str) -> int:
    """Copy today's swept rows for active watchlist events into `snapshots`/`price_ranges` (skipping events
    that already have a snapshot today), with the same watchlist bookkeeping as a per-event call."""
    snap_cols = [r[1] for r in conn.execute("PRAGMA table_info(snapshots)")]
    ids = [r[0] for r in conn.execute(
        "SELECT s.event_id FROM sweep_snapshots s JOIN watchlist w ON w.event_id = s.event_id AND w.active = 1 "
        "WHERE s.snap_date = ? AND s.raw_json_gz IS NOT NULL AND s.event_id NOT IN "
        "(SELECT event_id FROM snapshots WHERE snap_date = ?)", (snap_date, snap_date))]
    cl = ",".join(snap_cols)
    for eid in ids:
        conn.execute(f"INSERT OR IGNORE INTO snapshots({cl}) SELECT {cl} FROM sweep_snapshots "
                     "WHERE event_id=? AND snap_date=?", (eid, snap_date))
        conn.execute("INSERT OR IGNORE INTO price_ranges SELECT * FROM sweep_price_ranges WHERE event_id=? AND snap_date=?",
                     (eid, snap_date))
        r = conn.execute("SELECT local_date, days_until_show, event_status FROM snapshots WHERE event_id=? AND snap_date=?",
                         (eid, snap_date)).fetchone()
        _watchlist_after_snapshot(conn, eid, {"local_date": r[0], "days_until_show": r[1], "event_status": r[2]})
    conn.commit()
    return len(ids)


def compare_numbers(conn: sqlite3.Connection, snap_date: str) -> dict[str, int]:
    """Per-event snapshots vs the sweep, same events, same day (0 and NULL prices both mean 'no price')."""
    q = lambda sql, *a: conn.execute(sql, a).fetchone()[0]  # noqa: E731
    j = """FROM snapshots a JOIN sweep_snapshots b ON a.event_id=b.event_id AND a.snap_date=b.snap_date
           WHERE a.snap_date=? AND a.http_status=200 AND a.source_url != ?"""
    close = f"{j} AND ABS(julianday(a.snapshot_ts) - julianday(b.snapshot_ts)) * 24 <= {GATE_MAX_HOURS_APART}"
    same = lambda c: f"COALESCE(NULLIF(a.{c}, 0), -1) = COALESCE(NULLIF(b.{c}, 0), -1)"  # noqa: E731
    return {
        "per_event": q("SELECT COUNT(*) FROM snapshots WHERE snap_date=? AND http_status=200 AND source_url != ?",
                       snap_date, SWEEP_SOURCE_URL),
        "swept": q("SELECT COUNT(*) FROM sweep_snapshots WHERE snap_date=?", snap_date),
        "both": q(f"SELECT COUNT(*) {j}", snap_date, SWEEP_SOURCE_URL),
        "close": q(f"SELECT COUNT(*) {close}", snap_date, SWEEP_SOURCE_URL),
        "same_price": q(f"SELECT COUNT(*) {close} AND {same('price_min')} AND {same('price_max')}", snap_date, SWEEP_SOURCE_URL),
        "same_status": q(f"SELECT COUNT(*) {close} AND a.event_status IS b.event_status", snap_date, SWEEP_SOURCE_URL),
    }


def gate_passes(n: dict[str, int]) -> bool:
    return (n["per_event"] >= 100 and n["both"] >= GATE_MIN_OVERLAP * n["per_event"] and n["close"] >= 100
            and min(n["same_price"], n["same_status"]) >= GATE_MIN_IDENTICAL * n["close"])


def daily_mode(conn: sqlite3.Connection, clock: Clock) -> str:
    """'sweep' once switched (sticky); otherwise switch when the last GATE_DAYS parallel days all pass."""
    row = conn.execute("SELECT value FROM collector_settings WHERE key='daily_mode'").fetchone()
    if row:
        return row[0]
    days = [r[0] for r in conn.execute(
        "SELECT DISTINCT snap_date FROM sweep_slices WHERE snap_date < ? ORDER BY snap_date DESC LIMIT ?",
        (clock.now().date().isoformat(), GATE_DAYS))]
    results = {d: gate_passes(compare_numbers(conn, d)) for d in days}
    if len(days) == GATE_DAYS and all(results.values()):
        conn.execute("INSERT INTO collector_settings VALUES ('daily_mode', 'sweep', ?)", (clock.now().isoformat(),))
        conn.commit()
        log.info("daily: sweep passed the parallel check on %s; switching to sweep mode for good", days)
        return "sweep"
    log.info("daily: parallel phase (sweep + per-event); gate so far %s", results or "no days yet")
    return "parallel"


def sweep_compare(conn: sqlite3.Connection, snap_date: str) -> str:
    """Parallel-run check: the sweep vs per-event snapshots of the same events on the same day."""
    q = lambda sql, *a: conn.execute(sql, a).fetchone()  # noqa: E731
    per = q("SELECT COUNT(*) FROM snapshots WHERE snap_date=? AND http_status=200 AND source_url != ?",
            snap_date, SWEEP_SOURCE_URL)[0]
    swept = q("SELECT COUNT(*) FROM sweep_snapshots WHERE snap_date=?", snap_date)[0]
    j = """FROM snapshots a JOIN sweep_snapshots b ON a.event_id=b.event_id AND a.snap_date=b.snap_date
           WHERE a.snap_date=? AND a.http_status=200 AND a.source_url != ?"""
    both = q(f"SELECT COUNT(*) {j}", snap_date, SWEEP_SOURCE_URL)[0]
    same = lambda c: f"COALESCE(NULLIF(a.{c}, 0), -1) = COALESCE(NULLIF(b.{c}, 0), -1)"  # 0 and NULL = no price
    p_same = q(f"SELECT COUNT(*) {j} AND {same('price_min')} AND {same('price_max')}", snap_date, SWEEP_SOURCE_URL)[0]
    s_same = q(f"SELECT COUNT(*) {j} AND a.event_status IS b.event_status", snap_date, SWEEP_SOURCE_URL)[0]
    missed = conn.execute(f"""SELECT a.event_id, a.event_status, a.local_date FROM snapshots a WHERE a.snap_date=?
        AND a.http_status=200 AND a.source_url != ? AND a.event_id NOT IN
        (SELECT event_id FROM sweep_snapshots WHERE snap_date=?) LIMIT 2000""",
        (snap_date, SWEEP_SOURCE_URL, snap_date)).fetchall()
    by_status: dict[str, int] = {}
    for _, st, _ in missed:
        by_status[st or "(none)"] = by_status.get(st or "(none)", 0) + 1
    diffs = conn.execute(f"""SELECT a.event_id, a.price_min, b.price_min, a.event_status, b.event_status,
        ROUND((julianday(b.snapshot_ts) - julianday(a.snapshot_ts)) * 24, 1) {j}
        AND NOT ({same('price_min')} AND {same('price_max')} AND a.event_status IS b.event_status) LIMIT 15""",
        (snap_date, SWEEP_SOURCE_URL)).fetchall()
    calls = q("SELECT COALESCE(SUM(calls_used),0) FROM runs WHERE snap_date=? AND command='sweep'", snap_date)[0]
    pct = lambda a, b: f"{100 * a / b:.2f}%" if b else "-"  # noqa: E731
    g = compare_numbers(conn, snap_date)
    out = [f"sweep vs per-event snapshots, {snap_date}  [gate: {'PASS' if gate_passes(g) else 'not passed'}; "
           f"within {GATE_MAX_HOURS_APART} h: {g['close']:,} pairs, identical price {pct(g['same_price'], g['close'])}, "
           f"status {pct(g['same_status'], g['close'])}]",
           f"  per-event snapshots: {per:,}   swept events: {swept:,} (sweep calls: {calls:,})",
           f"  in both: {both:,} ({pct(both, per)} of per-event)   per-event not in sweep: {per - both:,}",
           f"  identical price_min/max: {p_same:,} ({pct(p_same, both)})   identical status: {s_same:,} ({pct(s_same, both)})"]
    if by_status:
        out.append(f"  not-in-sweep by status: {by_status}")
    if diffs:
        out.append("  differences (event, per-event min, sweep min, per-event status, sweep status, hours apart):")
        out += [f"    {d}" for d in diffs]
    return "\n".join(out)


# --------------------------------------------------------------------------- feed (all US events, no prices)


def _b(x: Any) -> int | None:
    return None if x is None else int(bool(x))


def parse_feed_event(e: dict) -> dict[str, Any]:
    v = e.get("venue") or {}
    atts = [(a.get("attraction") or a) for a in e.get("attractions") or []]
    return {
        "event_id": e.get("eventId"), "name": e.get("eventName"), "local_date": e.get("eventStartLocalDate"),
        "start_utc": e.get("eventStartDateTime"), "venue_id": v.get("venueId"), "venue_name": v.get("venueName"),
        "city": v.get("venueCity"), "state": v.get("venueStateCode"),
        "attraction_ids": ",".join(a["attractionId"] for a in atts if a.get("attractionId")) or None,
        "genre": e.get("classificationGenre"), "subgenre": e.get("classificationSubGenre"),
        "event_status": e.get("eventStatus"), "hot_event": _b(e.get("hotEvent")),
        "transactable": _b(e.get("transactable")), "official_seller": _b(e.get("officialSeller")),
        "source": e.get("source"), "onsale_start": e.get("onsaleStartDateTime"),
        "onsale_end": e.get("onsaleEndDateTime"), "presales_n": len(e.get("presales") or []),
        "url": e.get("primaryEventUrl"),
    }


def feed(conn: sqlite3.Connection, client: TMClient, clock: Clock, country: str = "US") -> RunStats:
    """One call: the whole country's events. Music events update feed_state; tracked-field changes (and events
    leaving the feed) go to feed_changes. A feed TM hasn't republished since the last pull is not reprocessed."""
    stats = RunStats()
    run_id = _start_run(conn, "feed", clock)
    calls_before = client.budget.spent
    ts = clock.now().isoformat()
    try:
        resp = client.get_feed(country)
    except (StopForToday, TransportError) as exc:
        stats.stopped_reason = str(exc)
        stats.errors += isinstance(exc, TransportError)
        stats.calls_used = client.budget.spent - calls_before
        _finish_run(conn, run_id, stats, clock)
        if isinstance(exc, AuthError):
            raise
        log.warning("feed stopped: %s", exc)
        return stats
    stats.calls_used = client.budget.spent - calls_before
    if resp.status != 200:
        stats.errors += 1
        log.error("feed: HTTP %d", resp.status)
        _finish_run(conn, run_id, stats, clock)
        return stats
    lm = resp.header("Last-Modified")
    prev = conn.execute("SELECT last_modified FROM feed_runs WHERE skipped=0 ORDER BY run_ts DESC LIMIT 1").fetchone()
    if lm and prev and prev[0] == lm:
        conn.execute("INSERT INTO feed_runs VALUES (?,?,?,?,?,?,1)", (ts, lm, None, None, 0, 0))
        _finish_run(conn, run_id, stats, clock)
        log.info("feed: unchanged since last pull (Last-Modified %s); nothing to do", lm)
        return stats
    body = resp.body
    try:
        body = gzip.decompress(body)
    except OSError:
        pass  # already decoded by the transport
    events = json.loads(body.decode("utf-8")).get("events") or []
    music = [parse_feed_event(e) for e in events if e.get("classificationSegment") == "Music" and e.get("eventId")]
    old = {r[0]: r[1:] for r in conn.execute(f"SELECT event_id, {', '.join(FEED_TRACKED)} FROM feed_state")}
    changes, new = [], 0
    seen = set()
    for row in music:
        eid = row["event_id"]
        seen.add(eid)
        cur = {**row, "in_feed": 1}
        if eid in old:
            for f, was in zip(FEED_TRACKED, old[eid]):
                if was != cur[f]:
                    changes.append((eid, ts, f, None if was is None else str(was), None if cur[f] is None else str(cur[f])))
        else:
            new += 1
    gone = [eid for eid, vals in old.items() if eid not in seen and vals[FEED_TRACKED.index("in_feed")] == 1]
    changes += [(eid, ts, "in_feed", "1", "0") for eid in gone]
    cols = [c for c in music[0]] if music else []
    if music:
        upd = ", ".join(f"{c}=excluded.{c}" for c in cols if c != "event_id")
        conn.executemany(
            f"INSERT INTO feed_state({','.join(cols)}, first_seen_ts, last_seen_ts, in_feed) "
            f"VALUES ({','.join('?' * len(cols))}, ?, ?, 1) "
            f"ON CONFLICT(event_id) DO UPDATE SET {upd}, last_seen_ts=excluded.last_seen_ts, in_feed=1",
            [[r[c] for c in cols] + [ts, ts] for r in music])
    conn.executemany("UPDATE feed_state SET in_feed=0 WHERE event_id=?", [(g,) for g in gone])
    conn.executemany("INSERT INTO feed_changes VALUES (?,?,?,?,?)", changes)
    conn.execute("INSERT INTO feed_runs VALUES (?,?,?,?,?,?,0)", (ts, lm, len(events), len(music), new, len(changes)))
    stats.snapshots_saved = len(music)
    stats.added_to_watchlist = 0
    _finish_run(conn, run_id, stats, clock)
    log.info("feed %s: %d events, %d music, %d new, %d field changes (%d left the feed)",
             ts, len(events), len(music), new, len(changes), len(gone))
    return stats


def status(conn: sqlite3.Connection, clock: Clock) -> str:
    today = clock.now().date().isoformat()
    q = lambda sql, *a: conn.execute(sql, a).fetchone()[0]  # noqa: E731
    lines = [
        f"today (UTC): {today}",
        f"watchlist: {q('SELECT COUNT(*) FROM watchlist WHERE active=1')} active, "
        f"{q('SELECT COUNT(*) FROM watchlist')} total",
        f"  active with >=60 days still to go: "
        f"{q('SELECT COUNT(*) FROM watchlist WHERE active=1 AND event_date >= ?', (date.fromisoformat(today) + timedelta(days=60)).isoformat())}",
        f"  first observed >=60 days out: {q('SELECT COUNT(*) FROM watchlist WHERE first_days_out >= 60')}",
        f"  by selection: ranges-pool {q('SELECT COUNT(*) FROM watchlist WHERE active=1 AND selected_for_ranges=1')}, "
        f"random no-ranges {q('SELECT COUNT(*) FROM watchlist WHERE active=1 AND selected_for_ranges=0')}, "
        f"other/pilot {q('SELECT COUNT(*) FROM watchlist WHERE active=1 AND selected_for_ranges IS NULL')}; "
        f"promotions total {q('SELECT COUNT(*) FROM promotions')}",
        f"snapshots today: {q('SELECT COUNT(*) FROM snapshots WHERE snap_date=?', today)}",
        f"snapshots total: {q('SELECT COUNT(*) FROM snapshots')} over "
        f"{q('SELECT COUNT(DISTINCT snap_date) FROM snapshots')} day(s)",
        f"priceRanges fill rate (all HTTP-200 snapshots): "
        f"{q('SELECT ROUND(100.0*AVG(has_price_ranges),1) FROM snapshots WHERE http_status=200')}%",
        f"API calls today: {q('SELECT COALESCE(MAX(calls),0) FROM api_calls WHERE day=?', today)}",
        "last runs:",
    ]
    for r in conn.execute("SELECT run_id, command, started_at, finished_at, calls_used, snapshots_saved, "
                          "missing_price_ranges, not_found, errors, added_to_watchlist, remaining_todo, "
                          "stopped_reason FROM runs ORDER BY run_id DESC LIMIT 5"):
        lines.append(f"  #{r[0]} {r[1]} {r[2]} -> {r[3] or 'UNFINISHED'} calls={r[4]} saved={r[5]} "
                     f"missing_pr={r[6]} 404={r[7]} err={r[8]} added={r[9]} left={r[10]}"
                     + (f" stopped='{r[11]}'" if r[11] else ""))
    return "\n".join(lines)


FILL_BUCKETS = [(1, 6), (7, 13), (14, 29), (30, 44), (45, 59), (60, 89), (90, 120)]


def fill_report(conn: sqlite3.Connection, clock: Clock) -> str:
    """priceRanges fill on the discover candidate pool (Music, US, not excluded), by days out and genre."""
    today = clock.now().date()
    rows = [r for r in conn.execute(
        "SELECT name, local_date, genre, has_price_ranges, seen_on FROM discover_candidates "
        "WHERE COALESCE(segment,'Music')='Music' AND COALESCE(event_status,'') <> 'cancelled' AND local_date > ?",
        (today.isoformat(),)) if not EXCLUDE_NAME_RE.search(r[0] or "")]
    out = [f"priceRanges fill on {len(rows):,} candidate events (scans up to {today}; days out from today)", "",
           "| days out | events | fill % |", "|---|---|---|"]
    for lo, hi in FILL_BUCKETS:
        b = [r[3] for r in rows if lo <= (date.fromisoformat(r[1]) - today).days <= hi]
        out.append(f"| {lo}-{hi} | {len(b):,} | {100 * sum(b) / len(b):.1f} |" if b else f"| {lo}-{hi} | 0 | - |")
    b = [r[3] for r in rows if (date.fromisoformat(r[1]) - today).days >= 45]
    if b:
        out.append(f"| **>=45** | {len(b):,} | **{100 * sum(b) / len(b):.1f}** |")
    out += ["", "| genre | events | fill % |", "|---|---|---|"]
    by_g: dict[str, list[int]] = {}
    for r in rows:
        by_g.setdefault(r[2] or "(none)", []).append(r[3])
    for g, v in sorted(by_g.items(), key=lambda kv: -len(kv[1]))[:15]:
        out.append(f"| {g} | {len(v):,} | {100 * sum(v) / len(v):.1f} |")
    allv = [r[3] for r in rows]
    if allv:
        out.append(f"| **all** | {len(allv):,} | **{100 * sum(allv) / len(allv):.1f}** |")
    return "\n".join(out)


def prune(conn: sqlite3.Connection, keep_days: int, clock: Clock) -> int:
    cutoff = (clock.now().date() - timedelta(days=keep_days)).isoformat()
    conn.execute("DELETE FROM price_ranges WHERE snap_date < ?", (cutoff,))
    n = conn.execute("DELETE FROM snapshots WHERE snap_date < ?", (cutoff,)).rowcount
    conn.commit()
    conn.execute("VACUUM")
    return n


# --------------------------------------------------------------------------- CLI


def setup_logging(key: str | None, to_file: bool = True) -> None:
    log.setLevel(logging.INFO)
    log.handlers.clear()
    log.propagate = True  # so pytest's caplog sees records; root has no handler in normal runs
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    if to_file:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(LOG_DIR / f"forward_collector-{datetime.now(timezone.utc):%Y-%m}.log"))
    for h in handlers:
        h.setFormatter(fmt)
        h.addFilter(RedactFilter(key))
        log.addHandler(h)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--db", type=Path, default=DEFAULT_DB)
    p.add_argument("--env-file", type=Path, default=ROOT / ".env")
    p.add_argument("--budget", type=int, default=int(os.environ.get("TM_DAILY_BUDGET", DEFAULT_BUDGET)),
                   help=f"max API calls in any rolling 24 h (default {DEFAULT_BUDGET}, quota is {DAILY_QUOTA}/day)")
    p.add_argument("--max-wait-hours", type=float, default=DEFAULT_MAX_WAIT_S / 3600,
                   help="how long a run may wait for the rolling 24 h budget to free up")
    p.add_argument("--rate", type=float, default=DEFAULT_RATE, help="max requests/second (capped at DEFAULT_RATE)")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="snapshot every active watchlist event once today")
    r.add_argument("--limit", type=int)
    d = sub.add_parser("discover", help="add upcoming US music events to the watchlist")
    for sp in (d, sub.add_parser("daily", help="run, then discover if due (for launchd)")):
        sp.add_argument("--target", type=int, default=DEFAULT_TARGET, help="active watchlist size to aim for")
        sp.add_argument("--max-calls", type=int, default=700, help="max search calls for discover")
        sp.add_argument("--days-min", type=int, default=1)
        sp.add_argument("--days-max", type=int, default=120)
        sp.add_argument("--far-share", type=float, default=DEFAULT_FAR_SHARE,
                        help="share of new slots for shows >= 60 days out")
        sp.add_argument("--mode", choices=["detail", "sweep", "auto"], default="detail",
                        help="daily only: 'sweep' = feed + search sweep, per-event calls only for watchlist events "
                             "it missed; 'auto' = sweep + per-event in parallel until GATE_DAYS days pass "
                             "`sweep-compare`, then 'sweep' for good")
    w = sub.add_parser("watchlist")
    wsub = w.add_subparsers(dest="wcmd", required=True)
    wsub.add_parser("add").add_argument("ids", nargs="+")
    wsub.add_parser("import").add_argument("csv", type=Path)
    wsub.add_parser("export").add_argument("csv", type=Path)
    sw = sub.add_parser("sweep", help="snapshot every upcoming US music event via search pages")
    sw.add_argument("--days-max", type=int, default=SWEEP_DAYS_MAX)
    sc = sub.add_parser("sweep-compare", help="parallel-run check: sweep vs per-event snapshots")
    sc.add_argument("--date", default=None, help="UTC snap date (default today)")
    sub.add_parser("feed", help="pull the Discovery Feed (all US events, one call) and log field changes")
    sub.add_parser("near", help="intraday pass over shows in their final week (price + status)")
    sub.add_parser("status")
    sub.add_parser("fill-report", help="priceRanges fill on the candidate pool by days out and genre")
    pr = sub.add_parser("prune", help="delete snapshots older than N days (storage-terms hygiene)")
    pr.add_argument("--keep-days", type=int, required=True)
    return p


def main(argv: list[str] | None = None, transport: Transport | None = None, clock: Clock | None = None,
         log_to_file: bool = True) -> int:
    args = build_parser().parse_args(argv)
    clock = clock or SystemClock()
    needs_key = args.cmd in ("run", "discover", "daily", "sweep", "feed", "near")
    key = load_api_key(args.env_file) if needs_key else None
    setup_logging(key, to_file=log_to_file and needs_key)
    if needs_key and not key:
        print(NO_KEY_MESSAGE, file=sys.stderr)
        log.error("no TICKETMASTER_API_KEY; exiting without fetching")
        return EXIT_NO_KEY
    if needs_key and transport is None:
        # Campus DNS fails now and then (30 "network error" events on 2026-10-20): reuse the last good answer.
        sys.path.insert(0, str(ROOT / "src"))
        import sticky_dns  # noqa: F401
    rate = min(args.rate, DEFAULT_RATE)
    budget_limit = min(args.budget, DAILY_QUOTA)
    if args.cmd in ("sweep", "feed", "near") or getattr(args, "mode", None) in ("sweep", "auto"):
        budget_limit = max(budget_limit, SWEEP_BUDGET) if "--budget" not in (argv or sys.argv) else budget_limit

    conn = connect(args.db)
    try:
        if args.cmd == "watchlist":
            if args.wcmd == "add":
                print(f"added/reactivated {watchlist_add(conn, args.ids, 'manual', clock)}")
            elif args.wcmd == "import":
                print(f"added/reactivated {watchlist_import(conn, args.csv, clock)}")
            else:
                print(f"exported {watchlist_export(conn, args.csv)} rows to {args.csv}")
            return EXIT_OK
        if args.cmd == "status":
            print(status(conn, clock))
            return EXIT_OK
        if args.cmd == "sweep-compare":
            print(sweep_compare(conn, args.date or clock.now().date().isoformat()))
            return EXIT_OK
        if args.cmd == "fill-report":
            print(fill_report(conn, clock))
            return EXIT_OK
        if args.cmd == "prune":
            print(f"deleted {prune(conn, args.keep_days, clock)} snapshots older than {args.keep_days} days")
            return EXIT_OK

        assert key is not None
        client = TMClient(key, transport or RequestsTransport(), clock, CallBudget(conn, clock, budget_limit, args.max_wait_hours * 3600), rate)
        try:
            if args.cmd == "sweep":
                sweep(conn, client, clock, args.days_max)
            elif args.cmd == "feed":
                feed(conn, client, clock)
            elif args.cmd == "near":
                near(conn, client, clock)
            elif args.cmd in ("run", "daily"):
                mode = getattr(args, "mode", "detail")
                if mode == "auto" and args.cmd == "daily":
                    mode = daily_mode(conn, clock)
                if mode in ("sweep", "parallel"):
                    feed(conn, client, clock)
                    sw = sweep(conn, client, clock)
                if mode == "sweep":
                    n = promote_sweep(conn, clock.now().date().isoformat())
                    log.info("daily: %d watchlist snapshots from the sweep; per-event calls only for the rest%s",
                             n, f" (sweep stopped: {sw.stopped_reason})" if sw.stopped_reason else "")
                stats = run_snapshots(conn, client, clock, getattr(args, "limit", None), command=args.cmd)
                # Discover every day: only stale (>= 7 days) or new day-slices are searched, so this is
                # a few calls most days and a full rescan (incl. promotions) once a week.
                if args.cmd == "daily" and not stats.stopped_reason:
                    max_calls = min(args.max_calls, client.budget.remaining())
                    if max_calls > 0:
                        d = discover(conn, client, clock, args.target, args.days_min, args.days_max,
                                     max_calls, args.far_share)
                        if not d.stopped_reason:
                            # Catch-up: day 0 for new adds, plus events lost to network errors above.
                            run_snapshots(conn, client, clock, command="daily-new")
            elif args.cmd == "discover":
                discover(conn, client, clock, args.target, args.days_min, args.days_max, args.max_calls,
                         args.far_share)
        except AuthError as exc:
            print(str(exc), file=sys.stderr)
            return EXIT_AUTH
        if client.rate_limited:
            print("stopped on HTTP 429 (see the log and `status`); report it before the next run", file=sys.stderr)
            return EXIT_RATE_LIMITED
        return EXIT_OK
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
