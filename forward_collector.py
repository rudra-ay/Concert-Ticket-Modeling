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

Limits (official API, documented: 5 req/s, 5,000 calls/day): token bucket at <= 4 req/s, a persistent
per-UTC-day call budget (default 4,500), and on 429 we honor Retry-After for at most 3 retries, then
stop for the day. A 401/403 (bad key) stops immediately. The API key is never written to the DB, logs
or saved URLs.

Usage:
  .venv/bin/python forward_collector.py daily
  .venv/bin/python forward_collector.py run [--limit N]
  .venv/bin/python forward_collector.py discover [--target 3000] [--max-calls 700]
  .venv/bin/python forward_collector.py watchlist add <event_id>... | import <csv> | export <csv>
  .venv/bin/python forward_collector.py status
  .venv/bin/python forward_collector.py prune --keep-days 365
"""
from __future__ import annotations

import argparse
import csv
import email.utils
import gzip
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
DEFAULT_BUDGET = 4500          # 90% of the quota; the rest is safety margin
DEFAULT_RATE = 4.0             # req/s, below TM's 5 req/s
MAX_RETRIES = 3
MAX_RETRY_WAIT_S = 120         # a Retry-After longer than this means "come back tomorrow"
RESERVE_AVAILABLE = 250        # stop if TM's Rate-Limit-Available header drops to this
DEEP_PAGING_CAP = 1000         # TM: size * page < 1000
DISCOVER_EVERY_DAYS = 7
DEACTIVATE_AFTER_404S = 3

EXIT_OK, EXIT_NO_KEY, EXIT_AUTH = 0, 3, 5

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
    """Per-UTC-day call counter persisted in SQLite, so reruns and retries all count."""

    def __init__(self, conn: sqlite3.Connection, clock: Clock, limit: int) -> None:
        self.conn, self.clock, self.limit = conn, clock, limit

    def day(self) -> str:
        return self.clock.now().date().isoformat()

    def used(self) -> int:
        row = self.conn.execute("SELECT calls FROM api_calls WHERE day = ?", (self.day(),)).fetchone()
        return row[0] if row else 0

    def remaining(self) -> int:
        return max(0, self.limit - self.used())

    def spend(self) -> None:
        if self.used() >= self.limit:
            raise StopForToday(f"daily call budget of {self.limit} reached")
        self.conn.execute(
            "INSERT INTO api_calls(day, calls) VALUES (?, 1) "
            "ON CONFLICT(day) DO UPDATE SET calls = calls + 1",
            (self.day(),),
        )
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

    def _get(self, path: str, params: dict[str, Any]) -> Response:
        url = API_BASE + path
        for attempt in range(self.max_retries + 1):
            self.budget.spend()
            self.bucket.acquire()
            resp = self.transport.get(url, {**params, "apikey": self.key})
            avail = resp.header("Rate-Limit-Available")
            if avail and avail.strip().lstrip("-").isdigit():
                self.last_available = int(avail)
                if self.last_available <= RESERVE_AVAILABLE and resp.status != 429:
                    log.warning("Rate-Limit-Available=%s <= reserve %s; stopping after this call",
                                avail, RESERVE_AVAILABLE)
                    self.budget.limit = self.budget.used()  # no more calls today
            if resp.status in (401, 403):
                raise AuthError(f"Ticketmaster returned HTTP {resp.status}: the API key was rejected "
                                "or access is forbidden. Check TICKETMASTER_API_KEY; not retrying.")
            if resp.status == 429:
                body = resp.body[:2000].decode("utf-8", "replace").lower()
                if "quota" in body:
                    raise StopForToday("Ticketmaster reports the daily quota is used up (429 quota)")
                wait = parse_retry_after(resp.header("Retry-After"), self.clock.now())
                if wait is None:
                    wait = float(2 ** (attempt + 1))
                if attempt == self.max_retries or wait > MAX_RETRY_WAIT_S:
                    raise StopForToday(f"HTTP 429 after {attempt + 1} attempt(s) "
                                       f"(Retry-After={resp.header('Retry-After')}); stopping for the day")
                log.warning("429 on %s; waiting %.1fs (retry %d/%d)", path, wait, attempt + 1, self.max_retries)
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
CREATE VIEW IF NOT EXISTS missing_price_ranges AS
    SELECT event_id, snap_date, name, event_status, days_until_show
    FROM snapshots WHERE http_status = 200 AND has_price_ranges = 0;
"""


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    return conn


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
    calls_before = client.budget.used()
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
            stats.calls_used = client.budget.used() - calls_before
            _finish_run(conn, run_id, stats, clock)
            raise
    stats.remaining_todo = len(todo) - done
    stats.calls_used = client.budget.used() - calls_before
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
    conn.execute("UPDATE watchlist SET event_date=COALESCE(?, event_date), not_found_streak=0, "
                 "first_days_out=COALESCE(first_days_out, ?) WHERE event_id=?",
                 (row["local_date"], row["days_until_show"], event_id))
    if row["event_status"] == "cancelled":
        conn.execute("UPDATE watchlist SET active=0, deactivated_why='cancelled' WHERE event_id=?", (event_id,))
    elif row["days_until_show"] is not None and row["days_until_show"] < 0:
        conn.execute("UPDATE watchlist SET active=0, deactivated_why='show date passed' WHERE event_id=?",
                     (event_id,))
    conn.commit()


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
                c = _candidate_from_search(ev, today)
                conn.execute(f"INSERT OR REPLACE INTO discover_candidates({','.join(c)}) "
                             f"VALUES ({','.join('?' * len(c))})", list(c.values()))
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


def discover(conn: sqlite3.Connection, client: TMClient, clock: Clock, target: int = 3000,
             days_min: int = 1, days_max: int = 120, max_calls: int = 700, far_share: float = 0.6,
             max_pages_per_day: int = 5) -> RunStats:
    stats = RunStats()
    run_id = _start_run(conn, "discover", clock)
    today = clock.now().date()
    calls_before = client.budget.used()
    try:
        fetch_candidates(conn, client, clock, days_min, days_max, max_calls, max_pages_per_day)
    except StopForToday as exc:
        stats.stopped_reason = str(exc)
        log.warning("discover stopped: %s", exc)
    stats.calls_used = client.budget.used() - calls_before

    active = conn.execute("SELECT COUNT(*) FROM watchlist WHERE active=1").fetchone()[0]
    slots = max(0, target - active)
    lo, hi = (today + timedelta(days=days_min)).isoformat(), (today + timedelta(days=days_max)).isoformat()
    cols = ["event_id", "name", "local_date", "event_status", "segment", "genre", "venue_id", "state",
            "attraction_ids"]
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
    chosen = select_diverse(cands, slots, today, far_share, seed=today.isoformat(),
                            existing=existing) if slots else []
    now = clock.now().isoformat()
    by_id = {c["event_id"]: c for c in cands}
    conn.executemany("INSERT OR IGNORE INTO watchlist(event_id, added_at, source, event_date) VALUES (?,?,?,?)",
                     [(e, now, "discover", by_id[e]["local_date"]) for e in chosen])
    conn.commit()
    stats.added_to_watchlist = len(chosen)
    _finish_run(conn, run_id, stats, clock)
    log.info("discover: %d candidates in window, %d active, added %d (target %d), calls=%d%s",
             len(cands), active, len(chosen), target, stats.calls_used,
             f" stopped={stats.stopped_reason}" if stats.stopped_reason else "")
    return stats


def discover_due(conn: sqlite3.Connection, today: date) -> bool:
    row = conn.execute("SELECT MAX(snap_date) FROM runs WHERE command='discover' AND finished_at IS NOT NULL "
                       "AND stopped_reason IS NULL").fetchone()
    return not row[0] or (today - date.fromisoformat(row[0])).days >= DISCOVER_EVERY_DAYS


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
        f"snapshots today: {q('SELECT COUNT(*) FROM snapshots WHERE snap_date=?', today)}",
        f"snapshots total: {q('SELECT COUNT(*) FROM snapshots')} over "
        f"{q('SELECT COUNT(DISTINCT snap_date) FROM snapshots')} day(s)",
        f"priceRanges fill rate (all 200 snapshots): "
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
                   help=f"max API calls per UTC day (default {DEFAULT_BUDGET}, quota is {DAILY_QUOTA})")
    p.add_argument("--rate", type=float, default=DEFAULT_RATE, help="max requests/second (<= 4)")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="snapshot every active watchlist event once today")
    r.add_argument("--limit", type=int)
    d = sub.add_parser("discover", help="add upcoming US music events to the watchlist")
    for sp in (d, sub.add_parser("daily", help="run, then discover if due (for launchd)")):
        sp.add_argument("--target", type=int, default=3000, help="active watchlist size to aim for")
        sp.add_argument("--max-calls", type=int, default=700, help="max search calls for discover")
        sp.add_argument("--days-min", type=int, default=1)
        sp.add_argument("--days-max", type=int, default=120)
        sp.add_argument("--far-share", type=float, default=0.6, help="share of new slots for shows >= 60 days out")
    w = sub.add_parser("watchlist")
    wsub = w.add_subparsers(dest="wcmd", required=True)
    wsub.add_parser("add").add_argument("ids", nargs="+")
    wsub.add_parser("import").add_argument("csv", type=Path)
    wsub.add_parser("export").add_argument("csv", type=Path)
    sub.add_parser("status")
    pr = sub.add_parser("prune", help="delete snapshots older than N days (storage-terms hygiene)")
    pr.add_argument("--keep-days", type=int, required=True)
    return p


def main(argv: list[str] | None = None, transport: Transport | None = None, clock: Clock | None = None,
         log_to_file: bool = True) -> int:
    args = build_parser().parse_args(argv)
    clock = clock or SystemClock()
    needs_key = args.cmd in ("run", "discover", "daily")
    key = load_api_key(args.env_file) if needs_key else None
    setup_logging(key, to_file=log_to_file and needs_key)
    if needs_key and not key:
        print(NO_KEY_MESSAGE, file=sys.stderr)
        log.error("no TICKETMASTER_API_KEY; exiting without fetching")
        return EXIT_NO_KEY
    rate = min(args.rate, DEFAULT_RATE)
    budget_limit = min(args.budget, DAILY_QUOTA)

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
        if args.cmd == "prune":
            print(f"deleted {prune(conn, args.keep_days, clock)} snapshots older than {args.keep_days} days")
            return EXIT_OK

        assert key is not None
        client = TMClient(key, transport or RequestsTransport(), clock, CallBudget(conn, clock, budget_limit), rate)
        try:
            if args.cmd in ("run", "daily"):
                stats = run_snapshots(conn, client, clock, getattr(args, "limit", None), command=args.cmd)
                if args.cmd == "daily" and not stats.stopped_reason and discover_due(conn, clock.now().date()):
                    max_calls = min(args.max_calls, client.budget.remaining())
                    if max_calls > 0:
                        d = discover(conn, client, clock, args.target, args.days_min, args.days_max,
                                     max_calls, args.far_share)
                        if d.added_to_watchlist and not d.stopped_reason:
                            run_snapshots(conn, client, clock, command="daily-new")  # day 0 for new adds
            elif args.cmd == "discover":
                discover(conn, client, clock, args.target, args.days_min, args.days_max, args.max_calls,
                         args.far_share)
        except AuthError as exc:
            print(str(exc), file=sys.stderr)
            return EXIT_AUTH
        return EXIT_OK
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
