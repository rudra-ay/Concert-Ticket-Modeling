"""Tests for forward_collector.py. No network: a fake transport serves Discovery-shaped fixtures."""
from __future__ import annotations

import copy
import gzip
import json
import sqlite3
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import forward_collector as fc  # noqa: E402

FIX = Path(__file__).parent / "fixtures" / "tm"
KEY = "TESTKEY_abc123SECRET"
T0 = datetime(2026, 10, 18, 12, 0, tzinfo=timezone.utc)


def load(name: str) -> dict:
    return json.loads((FIX / name).read_text())


class FakeClock:
    def __init__(self, start: datetime = T0) -> None:
        self.start = start
        self.t = 0.0
        self.sleeps: list[float] = []

    def now(self) -> datetime:
        return self.start + timedelta(seconds=self.t)

    def monotonic(self) -> float:
        return self.t

    def sleep(self, s: float) -> None:
        self.sleeps.append(s)
        self.t += max(0.0, s)

    def advance_days(self, n: int) -> None:
        self.start += timedelta(days=n)


class FakeTransport:
    """Routes /events/{id}.json to `events` (dict or list of queued responses) and /events.json to `search`."""

    def __init__(self, clock: FakeClock, events: dict | None = None, search=None) -> None:
        self.clock = clock
        self.events = events or {}
        self.search = search
        self.calls: list[tuple[float, str, dict]] = []

    def get(self, url: str, params: dict) -> fc.Response:
        self.calls.append((self.clock.monotonic(), url, dict(params)))
        assert params.get("apikey") == KEY
        if url.endswith("/events.json"):
            return self.search(params)
        eid = url.rsplit("/", 1)[1].removesuffix(".json")
        val = self.events.get(eid)
        if isinstance(val, list):
            val = val.pop(0) if len(val) > 1 else val[0]
        if val is None:
            return fc.Response(404, {}, json.dumps(load("error_404.json")).encode())
        if isinstance(val, fc.Response):
            return val
        body = copy.deepcopy(val)
        body["id"] = eid
        return fc.Response(200, {"Rate-Limit-Available": "4000"}, json.dumps(body).encode())


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def conn(tmp_path) -> sqlite3.Connection:
    c = fc.connect(tmp_path / "t.sqlite")
    yield c
    c.close()


def make_client(conn, clock, transport, budget=4500) -> fc.TMClient:
    return fc.TMClient(KEY, transport, clock, fc.CallBudget(conn, clock, budget))


# ------------------------------------------------------------------ parsing


def test_parse_event_with_ranges():
    row, ranges = fc.parse_event(load("event_with_ranges.json"), T0)
    assert row["name"].startswith("Fictional Band")
    assert row["event_status"] == "onsale"
    assert row["local_date"] == "2026-12-19" and row["start_utc"] == "2026-12-20T01:00:00Z"
    assert row["days_until_show"] == 62  # 2026-10-18 (NY) -> 2026-12-19
    assert row["hours_until_show"] == pytest.approx((datetime(2026, 12, 20, 1, tzinfo=timezone.utc) - T0).total_seconds() / 3600)
    assert row["public_sale_start"] == "2026-08-01T14:00:00Z"
    assert json.loads(row["presales_json"])[0]["name"] == "Artist Presale"
    assert (row["venue_id"], row["city"], row["state"], row["country"]) == ("KovZpTestVenue1", "New York", "NY", "US")
    assert row["venue_lat"] == pytest.approx(40.75)
    assert row["attraction_ids"] == "K8vZTestAttr01"
    assert (row["segment"], row["genre"], row["subgenre"]) == ("Music", "Rock", "Pop")
    assert row["has_price_ranges"] == 1 and row["price_min"] == 49.5 and row["price_max"] == 241.1
    assert [(r["type"], r["currency"], r["min"], r["max"]) for r in ranges] == [
        ("standard", "USD", 49.5, 199.5), ("standard including fees", "USD", 62.35, 241.1)]


def test_parse_event_missing_ranges_and_sparse_fields():
    row, ranges = fc.parse_event(load("event_no_ranges.json"), T0)
    assert ranges == [] and row["has_price_ranges"] == 0 and row["price_min"] is None
    # Snapshot at 12:00 UTC is 05:00 in Portland on 10-18; show is 11-01 local.
    assert row["days_until_show"] == 14
    row, _ = fc.parse_event({"id": "x"}, T0)  # nothing at all must not crash
    assert row["days_until_show"] is None and row["has_price_ranges"] == 0


def test_days_until_uses_venue_timezone():
    ev = load("event_no_ranges.json")
    late_utc = datetime(2026, 10, 19, 3, 0, tzinfo=timezone.utc)  # still 10-18 evening in LA
    row, _ = fc.parse_event(ev, late_utc)
    assert row["days_until_show"] == 14


# ------------------------------------------------------------------ run: storage, missing ranges, idempotency


def seed(conn, clock, ids):
    fc.watchlist_add(conn, ids, "manual", clock)


def test_run_saves_snapshots_and_logs_missing_ranges(conn, clock, caplog):
    t = FakeTransport(clock, {"E1": load("event_with_ranges.json"), "E2": load("event_no_ranges.json")})
    seed(conn, clock, ["E1", "E2"])
    with caplog.at_level("INFO", logger="forward_collector"):
        stats = fc.run_snapshots(conn, make_client(conn, clock, t), clock)
    assert (stats.snapshots_saved, stats.missing_price_ranges, stats.errors) == (2, 1, 0)
    assert conn.execute("SELECT COUNT(*) FROM price_ranges WHERE event_id='E1'").fetchone()[0] == 2
    assert conn.execute("SELECT event_id FROM missing_price_ranges").fetchall() == [("E2",)]
    assert any("missing_priceRanges event=E2" in r.getMessage() for r in caplog.records)
    run = conn.execute("SELECT missing_price_ranges, snapshots_saved, calls_used FROM runs").fetchone()
    assert run == (1, 2, 2)
    raw = conn.execute("SELECT raw_json_gz FROM snapshots WHERE event_id='E1'").fetchone()[0]
    assert json.loads(gzip.decompress(raw))["name"].startswith("Fictional Band")
    assert conn.execute("SELECT first_days_out FROM watchlist WHERE event_id='E1'").fetchone()[0] == 62


def test_rerun_same_day_is_idempotent_and_spends_nothing(conn, clock):
    t = FakeTransport(clock, {"E1": load("event_with_ranges.json"), "E2": load("event_no_ranges.json")})
    seed(conn, clock, ["E1", "E2"])
    client = make_client(conn, clock, t)
    fc.run_snapshots(conn, client, clock)
    n_calls = len(t.calls)
    stats = fc.run_snapshots(conn, client, clock)
    assert len(t.calls) == n_calls and stats.snapshots_saved == 0
    assert conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0] == 2
    assert conn.execute("SELECT COUNT(*) FROM price_ranges").fetchone()[0] == 2
    clock.advance_days(1)  # next day: new snapshots
    fc.run_snapshots(conn, client, clock)
    assert conn.execute("SELECT COUNT(DISTINCT snap_date) FROM snapshots").fetchone()[0] == 2


def test_404_recorded_once_then_deactivated(conn, clock):
    t = FakeTransport(clock, {})
    seed(conn, clock, ["GONE1"])
    client = make_client(conn, clock, t)
    for _ in range(fc.DEACTIVATE_AFTER_404S):
        fc.run_snapshots(conn, client, clock)
        fc.run_snapshots(conn, client, clock)  # same-day rerun: no second 404 call
        clock.advance_days(1)
    assert len(t.calls) == fc.DEACTIVATE_AFTER_404S
    assert conn.execute("SELECT active, deactivated_why FROM watchlist").fetchone() == (0, "404 repeatedly")


def test_cancelled_and_past_events_deactivate(conn, clock):
    t = FakeTransport(clock, {"C1": load("event_cancelled.json")})
    seed(conn, clock, ["C1", "OLD"])
    conn.execute("UPDATE watchlist SET event_date='2026-10-01' WHERE event_id='OLD'")
    fc.run_snapshots(conn, make_client(conn, clock, t), clock)
    assert [c[1] for c in t.calls] == [fc.API_BASE + "/events/C1.json"]  # OLD expired without a call
    rows = dict(conn.execute("SELECT event_id, deactivated_why FROM watchlist").fetchall())
    assert rows == {"C1": "cancelled", "OLD": "show date passed"}
    assert conn.execute("SELECT event_status FROM snapshots").fetchone()[0] == "cancelled"


def test_server_error_saves_nothing_so_rerun_retries(conn, clock):
    t = FakeTransport(clock, {"E1": [fc.Response(500), fc.Response(500), fc.Response(500), fc.Response(500),
                                     load("event_with_ranges.json")]})
    seed(conn, clock, ["E1"])
    client = make_client(conn, clock, t)
    stats = fc.run_snapshots(conn, client, clock)
    assert stats.errors == 1 and len(t.calls) == 1 + fc.MAX_RETRIES
    assert fc.run_snapshots(conn, client, clock).snapshots_saved == 1


# ------------------------------------------------------------------ API key hygiene


def test_api_key_never_stored_or_logged(conn, clock, caplog, tmp_path, capsys):
    ev = load("event_with_ranges.json")
    ev["_links"]["self"]["href"] = f"/discovery/v2/events/E1?apikey={KEY}&locale=en-us"
    ev["info"] = f"echo of key {KEY}"
    t = FakeTransport(clock, {"E1": ev, "E2": fc.Response(503)})
    seed(conn, clock, ["E1", "E2"])
    fc.setup_logging(KEY, to_file=False)
    with caplog.at_level("INFO", logger="forward_collector"):
        fc.run_snapshots(conn, make_client(conn, clock, t), clock)
        fc.log.info("request url https://x/y?apikey=%s&size=1", KEY)
    dump = "\n".join(conn.iterdump())
    raw = gzip.decompress(conn.execute("SELECT raw_json_gz FROM snapshots WHERE event_id='E1'").fetchone()[0]).decode()
    assert KEY not in dump and KEY not in raw and "apikey=REDACTED" in raw
    assert all("apikey" not in u for (u,) in conn.execute("SELECT source_url FROM snapshots"))
    out = capsys.readouterr().out + "".join(r.getMessage() for r in caplog.records)
    assert KEY not in out and "apikey=REDACTED" in out


def test_strip_apikey():
    assert fc.strip_apikey("https://a/b?x=1&apikey=abc&y=2") == "https://a/b?x=1&apikey=REDACTED&y=2"
    assert fc.strip_apikey("APIKEY=zzz") == "APIKEY=REDACTED"
    assert fc.strip_apikey("raw zzz", "zzz") == "raw REDACTED"


def test_missing_key_exits_cleanly(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("TICKETMASTER_API_KEY", raising=False)
    env = tmp_path / ".env"
    env.write_text("TICKETMASTER_API_KEY=\n")
    rc = fc.main(["--db", str(tmp_path / "x.sqlite"), "--env-file", str(env), "daily"], log_to_file=False)
    assert rc == fc.EXIT_NO_KEY
    assert "TICKETMASTER_API_KEY is not set" in capsys.readouterr().err
    assert not (tmp_path / "x.sqlite").exists()  # nothing created, nothing fetched


def test_key_from_env_file_and_cli_run(tmp_path, monkeypatch, clock):
    monkeypatch.delenv("TICKETMASTER_API_KEY", raising=False)
    env = tmp_path / ".env"
    env.write_text(f"TICKETMASTER_API_KEY={KEY}\n")
    db = tmp_path / "x.sqlite"
    assert fc.main(["--db", str(db), "watchlist", "add", "E1"], log_to_file=False) == 0
    t = FakeTransport(clock, {"E1": load("event_with_ranges.json")})
    assert fc.main(["--db", str(db), "--env-file", str(env), "run"], transport=t, clock=clock, log_to_file=False) == 0
    assert sqlite3.connect(db).execute("SELECT COUNT(*) FROM snapshots").fetchone()[0] == 1


def test_auth_error_stops_with_exit_code(tmp_path, monkeypatch, clock):
    monkeypatch.setenv("TICKETMASTER_API_KEY", KEY)
    db = tmp_path / "x.sqlite"
    fc.main(["--db", str(db), "watchlist", "add", "E1", "E2"], log_to_file=False)
    t = FakeTransport(clock, {"E1": fc.Response(401), "E2": load("event_with_ranges.json")})
    assert fc.main(["--db", str(db), "run"], transport=t, clock=clock, log_to_file=False) == fc.EXIT_AUTH
    assert len(t.calls) == 1  # no retry on 401, no further events


# ------------------------------------------------------------------ rate limiting, 429, quota


def test_token_bucket_never_exceeds_4_per_second(conn, clock):
    t = FakeTransport(clock, {f"E{i}": load("event_with_ranges.json") for i in range(60)})
    seed(conn, clock, [f"E{i}" for i in range(60)])
    fc.run_snapshots(conn, make_client(conn, clock, t), clock)
    times = [c[0] for c in t.calls]
    assert len(times) == 60
    for i, start in enumerate(times):
        in_window = [x for x in times[i:] if x < start + 1.0 - 1e-9]
        assert len(in_window) <= 4, (start, in_window)
    assert times[-1] >= (60 - 1) / 4 - 1e-6  # really throttled, not just lucky


def test_token_bucket_spacing_and_default_rate():
    clock = FakeClock()
    b = fc.TokenBucket(4.0, clock)
    for _ in range(9):
        b.acquire()
    assert clock.t == pytest.approx(2.0)
    assert fc.DEFAULT_RATE <= 3.0  # lowered after spike-arrest 429s at 4 req/s


def test_rate_flag_is_capped(tmp_path, monkeypatch, clock):
    monkeypatch.setenv("TICKETMASTER_API_KEY", KEY)
    db = tmp_path / "x.sqlite"
    fc.main(["--db", str(db), "watchlist", "add", "E1", "E2", "E3"], log_to_file=False)
    t = FakeTransport(clock, AnyEvent())
    assert fc.main(["--db", str(db), "--rate", "50", "run"], transport=t, clock=clock, log_to_file=False) == 0
    gaps = [b[0] - a[0] for a, b in zip(t.calls, t.calls[1:])]
    assert min(gaps) >= 1 / fc.DEFAULT_RATE - 1e-9


def test_429_with_retry_after_stops_and_reports(conn, clock):
    r429 = fc.Response(429, {"Retry-After": "7"}, b'{"fault":{"faultstring":"Spike arrest violation"}}')
    t = FakeTransport(clock, {"E1": [r429, load("event_with_ranges.json")], "E2": load("event_with_ranges.json")})
    seed(conn, clock, ["E1", "E2"])
    client = make_client(conn, clock, t)
    stats = fc.run_snapshots(conn, client, clock)
    assert "Retry-After=7" in stats.stopped_reason and len(t.calls) == 1 and client.rate_limited
    assert not clock.sleeps or max(clock.sleeps) < 1


def test_rare_transient_429_is_retried_once(conn, clock):
    ids = [f"E{i:03d}" for i in range(200)]
    events = {i: load("event_with_ranges.json") for i in ids}
    events["E050"] = [fc.Response(429, {}, b"{}"), load("event_with_ranges.json")]
    t = FakeTransport(clock, events)
    seed(conn, clock, ids)
    client = make_client(conn, clock, t)
    stats = fc.run_snapshots(conn, client, clock)
    assert stats.snapshots_saved == 200 and stats.stopped_reason is None and not client.rate_limited
    assert 2.0 in clock.sleeps


def test_more_than_1pct_429s_stops(conn, clock):
    ids = [f"E{i:03d}" for i in range(100)]
    events = {i: load("event_with_ranges.json") for i in ids}
    events["E010"] = [fc.Response(429, {}, b"{}"), load("event_with_ranges.json")]
    events["E020"] = [fc.Response(429, {}, b"{}"), load("event_with_ranges.json")]
    t = FakeTransport(clock, events)
    seed(conn, clock, ids)
    client = make_client(conn, clock, t)
    stats = fc.run_snapshots(conn, client, clock)
    assert "2 of" in stats.stopped_reason and client.rate_limited
    assert stats.snapshots_saved == 20  # E000..E009, E010 after retry, E011..E019


def test_429_persisting_through_retries_stops(conn, clock):
    ids = [f"E{i:03d}" for i in range(500)]
    events = {i: load("event_with_ranges.json") for i in ids}
    events["E000"] = [fc.Response(429, {}, b"{}")]
    t = FakeTransport(clock, events)
    seed(conn, clock, ids)
    stats = fc.run_snapshots(conn, make_client(conn, clock, t), clock)
    assert "persisted" in stats.stopped_reason
    assert len(t.calls) == 1 + fc.MAX_RETRIES and [x for x in clock.sleeps if x >= 1] == [2.0, 4.0, 8.0]
    assert stats.remaining_todo == 500


def test_rate_limit_stop_exit_code(tmp_path, monkeypatch, clock):
    monkeypatch.setenv("TICKETMASTER_API_KEY", KEY)
    db = tmp_path / "x.sqlite"
    fc.main(["--db", str(db), "watchlist", "add", "E1"], log_to_file=False)
    t = FakeTransport(clock, {"E1": fc.Response(429, {"Retry-After": "30"}, b"{}")})
    assert fc.main(["--db", str(db), "daily"], transport=t, clock=clock, log_to_file=False) == fc.EXIT_RATE_LIMITED


def test_429_quota_body_stops_immediately(conn, clock):
    t = FakeTransport(clock, {"E1": fc.Response(429, {}, json.dumps(load("error_429_quota.json")).encode())})
    seed(conn, clock, ["E1", "E2"])
    stats = fc.run_snapshots(conn, make_client(conn, clock, t), clock)
    assert "quota" in stats.stopped_reason and len(t.calls) == 1


def test_retry_after_http_date():
    assert fc.parse_retry_after("Sun, 18 Oct 2026 12:00:30 GMT", T0) == pytest.approx(30)
    assert fc.parse_retry_after("garbage", T0) is None


def test_daily_budget_stops_and_persists_across_reruns(conn, clock):
    ids = [f"E{i}" for i in range(10)]
    t = FakeTransport(clock, {i: load("event_with_ranges.json") for i in ids})
    seed(conn, clock, ids)
    stats = fc.run_snapshots(conn, make_client(conn, clock, t, budget=5), clock)
    assert stats.snapshots_saved == 5 and "budget" in stats.stopped_reason and stats.remaining_todo == 5
    stats = fc.run_snapshots(conn, make_client(conn, clock, t, budget=5), clock)  # rerun: counter persisted
    assert stats.snapshots_saved == 0 and len(t.calls) == 5
    clock.advance_days(1)
    stats = fc.run_snapshots(conn, make_client(conn, clock, t, budget=5), clock)
    assert stats.snapshots_saved == 5


def test_low_rate_limit_available_header_stops(conn, clock):
    low = fc.Response(200, {"Rate-Limit-Available": "100"}, json.dumps(load("event_with_ranges.json")).encode())
    t = FakeTransport(clock, {"E1": low, "E2": load("event_with_ranges.json")})
    seed(conn, clock, ["E1", "E2"])
    stats = fc.run_snapshots(conn, make_client(conn, clock, t), clock)
    assert stats.snapshots_saved == 1 and "budget" in stats.stopped_reason


# ------------------------------------------------------------------ discover


def search_responder(per_day: int, today: date):
    """Fake search: `per_day` events per UTC day, spread over states/genres/venues/artists."""
    states, genres = ["NY", "CA", "TX", "IL", "GA", "WA"], ["Rock", "Pop", "Country", "Hip-Hop/Rap", "Jazz"]
    template = load("event_with_ranges.json")

    def respond(params: dict) -> fc.Response:
        assert params["classificationName"] == "music" and params["countryCode"] == "US"
        assert params["size"] * (params["page"] + 1) <= fc.DEEP_PAGING_CAP
        day = params["startDateTime"][:10]
        size, page = params["size"], params["page"]
        idx = range(page * size, min(per_day, (page + 1) * size))
        evs = []
        for i in idx:
            ev = copy.deepcopy(template)
            ev["id"] = f"D{day.replace('-', '')}N{i:04d}"
            ev["name"] = "Parking Pass - Somebody" if i == 0 else f"Artist {i % 37} live"
            ev["dates"]["start"]["localDate"] = day
            ev["_embedded"]["venues"][0]["id"] = f"V{i % 23}"
            ev["_embedded"]["venues"][0]["state"]["stateCode"] = states[i % len(states)]
            ev["_embedded"]["attractions"][0]["id"] = f"A{i % 37}"
            ev["classifications"][0]["genre"]["name"] = genres[i % len(genres)]
            evs.append(ev)
        total_pages = -(-per_day // size)
        body = {"page": {"size": size, "totalElements": per_day, "totalPages": total_pages, "number": page}}
        if evs:
            body["_embedded"] = {"events": evs}
        return fc.Response(200, {}, json.dumps(body).encode())

    return respond


def test_discover_pages_diversifies_and_respects_caps(conn, clock):
    t = FakeTransport(clock, search=search_responder(per_day=450, today=T0.date()))
    stats = fc.discover(conn, make_client(conn, clock, t), clock, target=200, days_min=1, days_max=90,
                        max_calls=1000, far_share=0.6)
    # 450 events/day at size 200 -> 3 pages per day.
    assert stats.calls_used == 90 * 3
    assert stats.added_to_watchlist == 200
    rows = conn.execute("SELECT w.event_id, w.event_date, c.venue_id, c.attraction_ids, c.name FROM watchlist w "
                        "JOIN discover_candidates c USING(event_id)").fetchall()
    assert not any("Parking" in r[4] for r in rows)
    far = [r for r in rows if (date.fromisoformat(r[1]) - T0.date()).days >= 60]
    assert len(far) == 120
    from collections import Counter
    # 23 venues x 37 artists in the fixture: caps start at 3 and relax only as needed.
    assert max(Counter(r[2] for r in rows).values()) <= 12
    assert len(set(r[2] for r in rows)) == 23 and len(set(r[3] for r in rows)) == 37
    # Rerun the same day: slices are fresh, so no search calls, and the watchlist is full.
    n = len(t.calls)
    stats = fc.discover(conn, make_client(conn, clock, t), clock, target=200, days_max=90)
    assert len(t.calls) == n and stats.added_to_watchlist == 0


def test_discover_respects_max_calls_and_deep_paging(conn, clock):
    t = FakeTransport(clock, search=search_responder(per_day=5000, today=T0.date()))
    stats = fc.discover(conn, make_client(conn, clock, t), clock, target=50, days_min=1, days_max=120,
                        max_calls=12, max_pages_per_day=10)
    assert stats.calls_used == 12
    pages = [c[2]["page"] for c in t.calls]
    assert max(pages) == 4  # pages 0..4 of 200 = the 1000-item cap
    assert stats.added_to_watchlist == 50


def test_discover_empty_day(conn, clock):
    t = FakeTransport(clock, search=lambda p: fc.Response(200, {}, (FIX / "search_empty.json").read_bytes()))
    stats = fc.discover(conn, make_client(conn, clock, t), clock, target=10, days_min=1, days_max=3)
    assert stats.calls_used == 3 and stats.added_to_watchlist == 0


class AnyEvent(dict):
    def get(self, key, default=None):
        return load("event_with_ranges.json")


def test_daily_discover_searches_only_stale_slices(tmp_path, monkeypatch, clock):
    monkeypatch.setenv("TICKETMASTER_API_KEY", KEY)
    db = tmp_path / "x.sqlite"
    t = FakeTransport(clock, AnyEvent(), search=search_responder(per_day=10, today=T0.date()))
    args = ["--db", str(db), "daily", "--target", "20", "--days-max", "5"]
    assert fc.main(args, transport=t, clock=clock, log_to_file=False) == 0
    n_search = sum(1 for c in t.calls if c[1].endswith("/events.json"))
    assert n_search == 5
    db_ = sqlite3.connect(db)
    assert db_.execute("SELECT COUNT(*) FROM watchlist").fetchone()[0] == 20
    assert db_.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0] == 20  # new adds snapshotted on day 0
    clock.advance_days(1)
    assert fc.main(args, transport=t, clock=clock, log_to_file=False) == 0
    # Next day: discover runs again but only searches the one new day-slice (others are < 7 days old).
    assert sum(1 for c in t.calls if c[1].endswith("/events.json")) == n_search + 1
    assert db_.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0] == 40


# ------------------------------------------------------------------ option (b): ranges-tilted stratified panel


def make_cands(n: int, today: date, seed: int = 0) -> list[dict]:
    import random as _r
    rng = _r.Random(seed)
    out = []
    for i in range(n):
        out.append({"event_id": f"C{i:05d}", "name": f"Show {i}",
                    "local_date": (today + timedelta(days=rng.choice([10, 30, 70, 100]))).isoformat(),
                    "state": rng.choice(["NY", "CA", "TX"]), "genre": rng.choice(["Rock", "Jazz"]),
                    "venue_id": f"V{i}", "attraction_ids": f"A{i}",
                    "has_price_ranges": int(rng.random() < 0.25)})
    return out


def test_select_panel_80_20_split_strata_and_probabilities():
    today = T0.date()
    cands = make_cands(4000, today)
    picks = fc.select_panel(cands, 1000, today, far_share=0.6, seed="x")
    assert len(picks) == 1000 and len({p["event_id"] for p in picks}) == 1000
    by_id = {c["event_id"]: c for c in cands}
    far = [p for p in picks if p["stratum"].startswith("far|")]
    assert len(far) == 600
    for band in (far, [p for p in picks if p["stratum"].startswith("near|")]):
        flagged = sum(p["selected_for_ranges"] for p in band)
        assert flagged == round(len(band) * fc.RANGES_SHARE)
    for p in picks:
        assert p["selected_for_ranges"] == p["has_ranges_at_selection"] == by_id[p["event_id"]]["has_price_ranges"]
        assert p["stratum"].count("|") == 2 and 0 < p["selection_prob"] <= 1
    # selection_prob = selected / available in (stratum, pool)
    from collections import Counter
    sel = Counter((p["stratum"], p["selected_for_ranges"]) for p in picks)
    avail = Counter((fc._stratum(c, today), c["has_price_ranges"]) for c in cands)
    for p in picks:
        k = (p["stratum"], p["selected_for_ranges"])
        assert p["selection_prob"] == pytest.approx(sel[k] / avail[k], abs=1e-6)
    # The no-ranges draw is proportional: within a band, probabilities are (nearly) equal across strata.
    for band in ("far|", "near|"):
        probs = {p["stratum"]: p["selection_prob"] for p in picks
                 if p["stratum"].startswith(band) and p["selected_for_ranges"] == 0}
        assert max(probs.values()) - min(probs.values()) < 0.02
    # Deterministic for a seed.
    assert fc.select_panel(cands, 1000, today, 0.6, seed="x") == picks


def test_select_panel_short_pools_overflow():
    today = T0.date()
    cands = make_cands(300, today)
    with_r = sum(c["has_price_ranges"] for c in cands)
    picks = fc.select_panel(cands, 300, today, 0.6, seed="y")
    assert len(picks) == 300 and sum(p["selected_for_ranges"] for p in picks) == with_r
    only_without = [dict(c, has_price_ranges=0) for c in cands]
    assert sum(p["selected_for_ranges"] for p in fc.select_panel(only_without, 50, today, 0.6)) == 0


def test_promotion_logged_when_candidate_gains_ranges(conn, clock):
    """Week 1 scan: no ranges, not selected (target full). Week 2: ranges appear and a slot frees up."""
    today = T0.date()
    ev = load("event_no_ranges.json")
    ev["dates"]["start"]["localDate"] = (today + timedelta(days=80)).isoformat()
    state = {"ranges": False}

    def search(params):
        if params["startDateTime"][:10] != ev["dates"]["start"]["localDate"]:
            return fc.Response(200, {}, (FIX / "search_empty.json").read_bytes())
        e = copy.deepcopy(ev)
        e["id"] = "PROMO1"
        if state["ranges"]:
            e["priceRanges"] = [{"type": "standard", "currency": "USD", "min": 40.0, "max": 90.0}]
        body = {"page": {"size": 200, "totalElements": 1, "totalPages": 1, "number": 0},
                "_embedded": {"events": [e]}}
        return fc.Response(200, {}, json.dumps(body).encode())

    t = FakeTransport(clock, search=search)
    fc.discover(conn, make_client(conn, clock, t), clock, target=0, days_min=79, days_max=81)
    assert conn.execute("SELECT first_has_ranges, ranges_seen_on FROM discover_candidates").fetchone() == (0, None)
    clock.advance_days(7)
    state["ranges"] = True
    fc.discover(conn, make_client(conn, clock, t), clock, target=5, days_min=72, days_max=74)
    row = conn.execute("SELECT source, selected_for_ranges, has_ranges_at_selection FROM watchlist "
                       "WHERE event_id='PROMO1'").fetchone()
    assert row == ("promotion", 1, 1)
    p = conn.execute("SELECT promoted_on, first_seen_on, ranges_seen_on, days_out_at_promotion FROM promotions").fetchone()
    assert p == ((today + timedelta(days=7)).isoformat(), today.isoformat(), (today + timedelta(days=7)).isoformat(), 73)
    assert conn.execute("SELECT first_has_ranges FROM discover_candidates").fetchone()[0] == 0  # first-seen kept


def test_migration_adds_columns_to_old_db(tmp_path):
    db = tmp_path / "old.sqlite"
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE watchlist (event_id TEXT PRIMARY KEY, added_at TEXT NOT NULL, source TEXT NOT NULL, "
              "event_date TEXT, active INTEGER NOT NULL DEFAULT 1, deactivated_why TEXT, "
              "not_found_streak INTEGER NOT NULL DEFAULT 0, first_days_out INTEGER)")
    c.execute("INSERT INTO watchlist(event_id, added_at, source) VALUES ('OLD1','x','discover')")
    c.commit(); c.close()
    conn = fc.connect(db)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(watchlist)")}
    assert {"selected_for_ranges", "stratum", "selection_prob", "has_ranges_at_selection"} <= cols
    assert conn.execute("SELECT selected_for_ranges FROM watchlist").fetchone() == (None,)


def test_fill_report(conn, clock):
    t = FakeTransport(clock, search=search_responder(per_day=10, today=T0.date()))
    fc.discover(conn, make_client(conn, clock, t), clock, target=0, days_min=1, days_max=70)
    rep = fc.fill_report(conn, clock)
    assert "| 60-89 |" in rep and "**>=45**" in rep and "| Rock |" in rep and "100.0" in rep


# ------------------------------------------------------------------ watchlist + status


def test_watchlist_import_export_and_status(tmp_path, conn, clock):
    csv_in = tmp_path / "in.csv"
    csv_in.write_text("event_id,note\nG5vYZ9abc,a\n bad id! ,b\nG5vYZ9abc,dup\nZ7xx_1-2,c\n")
    assert fc.watchlist_import(conn, csv_in, clock) == 2
    assert fc.watchlist_export(conn, tmp_path / "out.csv") == 2
    text = fc.status(conn, clock)
    assert "watchlist: 2 active" in text and "API calls today: 0" in text


def test_prune(conn, clock):
    t = FakeTransport(clock, {"E1": load("event_with_ranges.json")})
    seed(conn, clock, ["E1"])
    client = make_client(conn, clock, t)
    fc.run_snapshots(conn, client, clock)
    clock.advance_days(10)
    fc.run_snapshots(conn, client, clock)
    assert fc.prune(conn, 5, clock) == 1
    assert conn.execute("SELECT COUNT(*) FROM price_ranges").fetchone()[0] == 2
