"""PATH hypothesis family (declared before any test statistic is computed), hypotheses.csv, and the
run-once confirmatory test (review 4, F1-F6).

The forward panel is PRIMARY face value (Ticketmaster priceRanges), not resale. Only hypotheses
about primary face-value dynamics can be tested from it; resale PATH hypotheses are excluded
with a reason. Every family member is PENDING: it enters BH at p = 1 until its pre-specified
test date, when run_final() below is run once on the data then available.

Disclosure: the family was declared on 2026-10-21 after the 3-day descriptive move rates
(path_tm_moves.py) had been computed; no estimate of any family member existed. Revised the same
day after skeptic review 4 (F1-F6), still before any estimate: H20b became descriptive (its 5%
threshold was set after a 0.47% rate was seen); H37 left the family under the power rule fixed in
path_power.py (MDE > 1 pp even at N = 1,000); every pair seen before registration is excluded.

This file IS the test code: final_spec.json holds its sha256, so any edit after --freeze makes
--final refuse to run. A second --final run is refused too (test_touch_log.jsonl).

Run: .venv/bin/python src/analysis/path_hypotheses.py            # declare: bh_family.json, hypotheses.csv
     .venv/bin/python src/analysis/path_hypotheses.py --freeze   # once: final_spec.json
     .venv/bin/python src/analysis/path_hypotheses.py --final    # once, on or after the test date
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from analysis.path_common import TABLES  # noqa: E402
from analysis.path_panel import PANEL  # noqa: E402

FINAL_SPEC = TABLES / "final_spec.json"
TOUCH_LOG = TABLES / "test_touch_log.jsonl"
RESULTS = TABLES / "path_test_results.json"

# sample rules and estimator parameters; all of this is in the frozen spec
PARAMS = {
    "horizon_days": 30,                 # complete priced 30-day path: snapshots 30..0 days before the show (local date)
    "max_missing_days": 3,              # of the 31 path days
    "seen_through": "2026-10-21",       # F2: pairs whose later snapshot is on or before this day are excluded
    "move_threshold_usd": 0.005,
    "wide_spread_ratio": 3,
    "near_sale_phase_days": 3,
    "pair_buckets": [[0, 6], [7, 13], [14, 20]],  # later snapshot's days to show; reference 21-29
    "alpha_family": 0.05,
    "wild_bootstrap_draws": 1999,
    "wild_below_clusters": 30,
    "ipw_stratum_min_events": 50,       # smaller selection-day strata merge into the previous selection day
    "seed": 20261021,
}
COMMON = ("Sample: events with a complete priced 30-day path (snapshots from 30 days before the show's local date through "
          "show day, a valid range on the first path day, at most 3 of 31 days missing). Unit: event-day pairs (consecutive "
          "days, both priced) whose later snapshot is 0-29 days before the show and AFTER 2026-10-21: every pair observed "
          "up to the registration date is excluded, so all tests run on unseen pairs. move = |change| > $0.005 in min or "
          "max face value. Weights: none in base. SE clustered by artist (first attraction id); p and 95% CI from "
          "t(G - 1); null-imposed wild cluster bootstrap (Webb, 1,999 draws) and leave-one-artist-out range if G < 30.")
IPW_NOTE = ("IPW sensitivities: 'IPW (selection)' pools all selection days with weights 1/selection_prob; 'IPW "
            "(selection-day strata)' estimates within each selection day (the cohorts have different far shares: 60% on "
            "2026-10-19, 30% from 2026-10-22; strata under 50 events merge into the previous day) and combines the "
            "estimates by each stratum's weight total. Pilot events have no selection_prob and drop out of both. Caveat: "
            "for the ranges pool, selection_prob is the realized share of a deliberate, diversity-capped pick, not a "
            "sampling probability, so IPW reweights toward the candidate pool's band mix and supports no statement about "
            "all US events.")

FAMILY = {
    "H20a": {"claim": "Primary face-value repricing becomes more frequent as the show approaches.",
             "test": "LPM: move ~ 1[0-6 days] + 1[7-13] + 1[14-20] (reference 21-29 days) + event FE + day-of-week "
                     "dummies (later snapshot), no date FE (F3: date FE + event FE would make days to show collinear). "
                     "One-sided test that the 0-6-day coefficient > 0.",
             "fe": "event + day of week", "source": "LITERATURE H20 (CMA 2025: tier releases)"},
    "H9p": {"claim": "Events with wide primary price spreads (max/min >= 3 on the path's first day, a proxy for "
                     "platinum/tiered pricing) reprice more often.",
            "test": "LPM: move ~ wide_spread + days-to-show bucket dummies + day-of-week dummies; two-sided test on "
                    "wide_spread. wide_spread is measured as of the first path day (no look-ahead).",
            "fe": "days bucket + day of week", "source": "LITERATURE H9, primary side"},
}
DESCRIPTIVE = {
    "H20b": {"claim": "Primary face-value changes are steps, not continuous drift.",
             "report": "daily move rate with a Wilson 95% CI on the confirmatory pairs; no test (F1: the 5% drift "
                       "threshold was set after a 0.47% rate had been seen)."},
    "H37": {"claim": "Primary face-value changes concentrate around scheduled sale-phase dates.",
            "report": "the H37 LPM (near_sale_phase within 3 days after a public_sale_start or presale start/end + "
                      "buckets + day of week) reported as an estimate with a CI, no p-value in BH: the registered power "
                      "rule removed it from the family (MDE above 1 pp even at N = 1,000; power.json)."},
}
RESALE = "resale-price hypothesis: the forward panel is PRIMARY face value; needs Rebrowser StubHub/Gametime or marketplace data"
EXCLUDED = {
    "H1": RESALE, "H2": RESALE, "H3": RESALE + " (listing-level)", "H4": RESALE, "H5": RESALE + " and sell-out status",
    "H7": RESALE + " (transaction volume)", "H9r": "resale half of H9 (resale premium/path flatness): " + RESALE,
    "H10": RESALE, "H11": RESALE, "H12": RESALE + " plus weather join", "H13": RESALE,
    "H14": RESALE + " at hourly resolution (the collector is daily)", "H17": RESALE + " (price variance)",
    "H18": "needs listing-format (auction vs fixed) data, which no approved source has",
    "H20b": "descriptive only (review 4 F1): threshold set after the rate was seen",
    "H21": RESALE, "H32p": "PATH half of H32 (state resale caps): " + RESALE,
    "H35": RESALE + " (resale premium by platform)", "H36": RESALE + " with section/tier",
    "H37": "descriptive only: underpowered at N = 1,000 under the registered power rule (power.json)",
}
LEVEL_ONLY = {"excl. $ outside US": "n/a: TM panel is US-only USD",
              "excl. aggregates": "n/a: LEVEL concept (multi-night box office aggregates)",
              "weighted by nights": "n/a: LEVEL concept",
              "tours ≥ 80% covered": "n/a: LEVEL concept (Wikipedia tour coverage)",
              "excl. split pseudo-tours": "n/a: LEVEL concept"}
SENS = ["base", "US only", "excl. $ outside US", "2016+", "excl. aggregates", "weighted by nights", "IPW (selection)",
        "IPW (selection-day strata)", "tours ≥ 80% covered", "excl. split pseudo-tours", "ranges pool only",
        "excl. pilot events", "60-day paths"]
RUN_SENS = ["base", "IPW (selection)", "IPW (selection-day strata)", "ranges pool only", "excl. pilot events"]


def power() -> dict:
    return json.loads((TABLES / "power.json").read_text())


def test_date() -> tuple[int, str]:
    n = int(power()["n_test"])
    rd = json.loads((TABLES / "readiness_summary.json").read_text())
    exp = rd["scenarios"]["C expand to 4,000 (far 30%)"]["dates"][f"h30_N{n}_priced"]
    return n, (f"first daily run on or after the date the panel reaches N >= {n:,} complete priced 30-day paths "
               f"(readiness_schedule.csv, scenario C, expected {exp}; moved from N >= 500 before any data because H9p "
               f"is underpowered at 500, power.json), run once")


# ---------------------------------------------------------------- sample

def complete_paths(p: pd.DataFrame, now: pd.Timestamp) -> pd.DataFrame:
    """One row per event with a complete priced 30-day path whose show is over."""
    h = PARAMS["horizon_days"]
    p = p.copy()
    p["days_before"] = (pd.to_datetime(p.local_date) - pd.to_datetime(p.snap_date)).dt.days
    w = p[(p.days_before >= 0) & (p.days_before <= h)]
    g = w.groupby("event_id")
    ev = pd.DataFrame({"n_days": g.snap_date.nunique(), "show_time": g.show_time.first()})
    first = w[(w.days_before == h) & w.valid_range & (w.price_max > 0)].drop_duplicates("event_id").set_index("event_id")
    ev = ev.join((first.price_max / first.price_min).rename("first_ratio"), how="inner")
    ev = ev[(ev.n_days >= h + 1 - PARAMS["max_missing_days"]) & (pd.to_datetime(ev.show_time, utc=True) < now)]
    ev["wide"] = (ev.first_ratio >= PARAMS["wide_spread_ratio"]).astype(float)
    return ev


def phase_dates(r) -> list[pd.Timestamp]:
    out = []
    if isinstance(r.public_sale_start, str) and r.public_sale_start:
        out.append(pd.Timestamp(r.public_sale_start))
    if isinstance(r.presales_json, str):
        for x in json.loads(r.presales_json or "[]"):
            out += [pd.Timestamp(x[k]) for k in ("startDateTime", "endDateTime") if x.get(k)]
    return [d.tz_convert("UTC") if d.tzinfo else d.tz_localize("UTC") for d in out]


def confirmatory_pairs(p: pd.DataFrame, now: pd.Timestamp) -> pd.DataFrame:
    ev = complete_paths(p, now)
    s = p[p.event_id.isin(ev.index)].sort_values(["event_id", "snap_date"]).copy()
    s["priced"] = s.valid_range & (s.price_max > 0)
    s["days_before"] = (pd.to_datetime(s.local_date) - pd.to_datetime(s.snap_date)).dt.days
    g = s.groupby("event_id")
    for c in ("snap_date", "priced", "price_min", "price_max", "public_sale_start", "presales_json"):
        s["prev_" + c] = g[c].shift()
    s = s[s.prev_snap_date.notna()]
    s = s[(pd.to_datetime(s.snap_date) - pd.to_datetime(s.prev_snap_date)).dt.days == 1]
    s = s[s.priced & s.prev_priced.astype(bool) & s.days_before.between(0, PARAMS["horizon_days"] - 1)]
    s = s[pd.to_datetime(s.snap_date) > pd.Timestamp(PARAMS["seen_through"])].copy()
    eps = PARAMS["move_threshold_usd"]
    s["y"] = (((s.price_min - s.prev_price_min).abs() > eps) | ((s.price_max - s.prev_price_max).abs() > eps)).astype(float)
    for i, (lo, hi) in enumerate(PARAMS["pair_buckets"]):
        s[f"b{i}"] = s.days_before.between(lo, hi).astype(float)
    s["dow"] = pd.to_datetime(s.snap_date).dt.dayofweek
    s["wide"] = s.event_id.map(ev.wide)
    snap = pd.to_datetime(s.snapshot_time, utc=True)
    k = PARAMS["near_sale_phase_days"]
    prev = pd.DataFrame({"public_sale_start": s.prev_public_sale_start, "presales_json": s.prev_presales_json})
    s["near"] = [float(any(pd.Timedelta(0) < t - d <= pd.Timedelta(days=k) for d in phase_dates(r)))
                 for r, t in zip(prev.itertuples(), snap)]  # as of the previous snapshot: no look-ahead
    s["cluster"] = s.artist.fillna("event:" + s.event_id)
    s["sel_day"] = pd.to_datetime(s.added_at).dt.strftime("%Y-%m-%d")
    return s


# ---------------------------------------------------------------- estimator

def demean(a: np.ndarray, g: np.ndarray) -> np.ndarray:
    return a - (np.bincount(g, weights=a) / np.bincount(g))[g]


def design(hid: str, d: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """Return (y, X) with the tested regressor in column 0; event FE are partialled out for H20a."""
    dow = pd.get_dummies(d.dow, prefix="dow", drop_first=True).astype(float).to_numpy()
    b = d[[f"b{i}" for i in range(len(PARAMS["pair_buckets"]))]].to_numpy()
    y = d.y.to_numpy()
    if hid == "H20a":
        X = np.column_stack([b, dow])
        g = pd.factorize(d.event_id)[0]
        return demean(y, g), np.column_stack([demean(c, g) for c in X.T])
    x = d.wide if hid == "H9p" else d.near
    return y, np.column_stack([x.to_numpy(), np.ones(len(d)), b, dow])


def cr1(y, X, cl, w) -> tuple[float, float, int]:
    sw = np.sqrt(w)
    Xw, yw = X * sw[:, None], y * sw
    inv = np.linalg.pinv(Xw.T @ Xw)
    b = inv @ Xw.T @ yw
    u = yw - Xw @ b
    G = int(cl.max()) + 1
    S = np.zeros((G, X.shape[1]))
    np.add.at(S, cl, Xw * u[:, None])
    n, k = X.shape
    V = inv @ (S.T @ S) @ inv * (G / (G - 1)) * ((n - 1) / max(n - k, 1))
    return float(b[0]), float(np.sqrt(max(V[0, 0], 0.0))), G


def wild_p(y, X, cl, w, t_obs, sided, rng) -> float:
    """Null-imposed wild cluster bootstrap (Webb 6-point weights) on the FWL-partialled regressor."""
    Z = X[:, 1:]
    sw = np.sqrt(w)

    def resid(v):
        if Z.shape[1] == 0:
            return v
        c, *_ = np.linalg.lstsq(Z * sw[:, None], v * sw, rcond=None)
        return v - Z @ c
    yt, xt = resid(y), resid(X[:, 0])
    webb = np.array([-np.sqrt(1.5), -1, -np.sqrt(.5), np.sqrt(.5), 1, np.sqrt(1.5)])
    G = int(cl.max()) + 1
    ts = []
    for _ in range(PARAMS["wild_bootstrap_draws"]):
        ys = yt * webb[rng.integers(0, 6, G)][cl]
        b, se, _ = cr1(ys, xt[:, None], cl, w)
        ts.append(b / se if se > 0 else 0.0)
    ts = np.array(ts)
    return float(np.mean(np.abs(ts) >= abs(t_obs)) if sided == 2 else np.mean(ts >= t_obs))


def estimate(hid: str, d: pd.DataFrame, w: np.ndarray | None = None, rng=None) -> dict:
    w = np.ones(len(d)) if w is None else w
    y, X = design(hid, d)
    cl = pd.factorize(d.cluster)[0]
    b, se, G = cr1(y, X, cl, w)
    t = b / se if se > 0 else 0.0
    sided = 2 if hid == "H9p" else 1
    p = float(2 * stats.t.sf(abs(t), G - 1) if sided == 2 else stats.t.sf(t, G - 1))
    q = stats.t.ppf(0.975, G - 1)
    out = {"coef": b, "se": se, "ci_lo": b - q * se, "ci_hi": b + q * se, "p": p, "clusters": G,
           "effective_clusters": G, "p_wild": None, "loo_min": None, "n_pairs": int(len(d)),
           "n_events": int(d.event_id.nunique())}
    if G < PARAMS["wild_below_clusters"]:
        out["p_wild"] = wild_p(y, X, cl, w, t, sided, rng or np.random.default_rng(PARAMS["seed"]))
        loo = []
        for a in d.cluster.unique():
            m = (d.cluster != a).to_numpy()
            yy, XX = design(hid, d[m])
            loo.append(cr1(yy, XX, pd.factorize(d.cluster[m])[0], w[m])[0])
        out["loo_min"], out["loo_max"] = float(min(loo)), float(max(loo))
    out["p_used"] = out["p_wild"] if out["p_wild"] is not None else p
    return out


def ipw_strata(hid: str, d: pd.DataFrame) -> dict:
    d = d[d.selection_prob.notna()].copy()
    merged, cur = {}, None
    for day in sorted(d.sel_day.unique()):  # strata under the minimum merge into the previous selection day
        n_ev = d.loc[d.sel_day == day, "event_id"].nunique()
        cur = day if cur is None or n_ev >= PARAMS["ipw_stratum_min_events"] else cur
        merged[day] = cur
    d["stratum"] = d.sel_day.map(merged)
    parts = {}
    for st, ds in d.groupby("stratum"):
        w = 1 / ds.selection_prob.to_numpy()
        parts[st] = (w.sum(), estimate(hid, ds, w))
    tot = sum(a for a, _ in parts.values())
    b = sum(a / tot * r["coef"] for a, r in parts.values())
    se = float(np.sqrt(sum((a / tot) ** 2 * r["se"] ** 2 for a, r in parts.values())))
    z = b / se if se > 0 else 0.0
    p = float(2 * stats.norm.sf(abs(z)) if hid == "H9p" else stats.norm.sf(z))
    return {"coef": b, "se": se, "ci_lo": b - 1.959964 * se, "ci_hi": b + 1.959964 * se, "p": p, "p_used": p,
            "strata": {k: r["n_events"] for k, (_, r) in parts.items()},
            "clusters": sum(r["clusters"] for _, r in parts.values()), "n_pairs": int(len(d))}


def run_member(hid: str, d: pd.DataFrame) -> dict:
    rng = np.random.default_rng(PARAMS["seed"])
    dw = d[d.selection_prob.notna()]
    return {"base": estimate(hid, d, rng=rng),
            "IPW (selection)": estimate(hid, dw, 1 / dw.selection_prob.to_numpy(), rng=rng),
            "IPW (selection-day strata)": ipw_strata(hid, d),
            "ranges pool only": estimate(hid, d[(d.source != "discover-pilot") & (d.selected_for_ranges == 1)], rng=rng),
            "excl. pilot events": estimate(hid, d[d.source != "discover-pilot"], rng=rng)}


def bh(p: dict[str, float]) -> dict[str, float]:
    ks = sorted(p, key=p.get)
    m, q, prev = len(ks), {}, 1.0
    for i in range(m - 1, -1, -1):
        prev = min(prev, p[ks[i]] * m / (i + 1))
        q[ks[i]] = prev
    return q


# ---------------------------------------------------------------- run once

def current_spec() -> dict:
    pw = power()
    n = int(pw["n_test"])  # the expected calendar date is a forecast that changes daily, so it is not hashed
    return {"test_code_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "params": PARAMS, "family": sorted(FAMILY), "definitions": FAMILY, "descriptive": DESCRIPTIVE,
            "common": COMMON, "ipw": IPW_NOTE, "sensitivities_run": RUN_SENS, "n_test_paths": n,
            "mde_pp": pw["mde_pp"], "power_rule": pw["rule"]}


def spec_hash(spec: dict) -> str:
    return hashlib.sha256(json.dumps(spec, sort_keys=True, default=str).encode()).hexdigest()


def freeze_spec() -> str:
    if FINAL_SPEC.exists():
        raise SystemExit("refusing --freeze: final_spec.json already exists (the spec is frozen once)")
    spec = current_spec()
    h = spec_hash(spec)
    FINAL_SPEC.write_text(json.dumps({"sha256": h, "frozen_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                                      "spec": spec}, indent=2, default=str))
    return h


def check_final_allowed() -> str:
    """--final runs only against a frozen spec that matches the current code, and only once."""
    if not FINAL_SPEC.exists():
        raise SystemExit("refusing --final: no frozen spec (run with --freeze first)")
    frozen = json.loads(FINAL_SPEC.read_text())
    h = spec_hash(current_spec())
    if h != frozen["sha256"]:
        raise SystemExit(f"refusing --final: current spec {h[:12]} != frozen {frozen['sha256'][:12]}")
    if TOUCH_LOG.exists() and any(json.loads(x).get("kind") == "final"
                                  for x in TOUCH_LOG.read_text().splitlines() if x.strip()):
        raise SystemExit("refusing --final: a final test touch is already logged")
    return h


def run_final() -> dict:
    sha = check_final_allowed()
    p = pd.read_parquet(PANEL)
    now = pd.Timestamp.now(tz="UTC")
    n_paths = len(complete_paths(p, now))
    n_need = current_spec()["n_test_paths"]
    if n_paths < n_need:  # counting paths does not look at outcomes; nothing is logged
        raise SystemExit(f"refusing --final: {n_paths} complete priced 30-day paths < {n_need} (test date not reached)")
    d = confirmatory_pairs(p, now)
    res = {h: run_member(h, d) for h in sorted(FAMILY)}
    q = bh({h: res[h]["base"]["p_used"] for h in res})
    desc = {"H20b": {"moves": int(d.y.sum()), "pairs": int(len(d))}, "H37": estimate("H37", d)}
    out = {"spec_sha256": sha, "n_paths": n_paths, "results": res, "q": q, "descriptive": desc}
    with open(TOUCH_LOG, "a") as f:
        f.write(json.dumps({"at": now.isoformat(timespec="seconds"), "kind": "final", "spec_sha256": sha,
                            "n": {"paths": n_paths, "pairs": int(len(d))}, "q": q}) + "\n")
    RESULTS.write_text(json.dumps(out, indent=2, default=str))
    return out


# ---------------------------------------------------------------- declaration

def main() -> None:
    TABLES.mkdir(parents=True, exist_ok=True)
    fam = sorted(FAMILY)
    n, date_txt = test_date()
    pw = power()
    done = json.loads(RESULTS.read_text()) if RESULTS.exists() else None
    pending = {} if done else {h: f"PENDING, enters BH at p = 1 until: {date_txt}" for h in fam}
    q = done["q"] if done else {h: 1.0 for h in fam}  # BH over all-ones p while pending
    (TABLES / "bh_family.json").write_text(json.dumps({
        "family": fam, "excluded": EXCLUDED, "pending_p1": pending, "q": q, "definitions": FAMILY,
        "descriptive": DESCRIPTIVE, "common": COMMON, "ipw": IPW_NOTE, "declared_on": "2026-10-21",
        "revised_on": "2026-10-21 (review 4 F1-F6, before any estimate)", "n_test_paths": n,
        "mde_pp": {h: {"N500": pw["mde_pp"][f"{h}_N500"], "N1000": pw["mde_pp"][f"{h}_N1000"]}
                   for h in ("H20a", "H9p", "H37")},
        "disclosure": "declared after the 3-day descriptive move rates were computed; no estimate of any member existed",
    }, indent=2, ensure_ascii=False))
    rows = []
    for h in fam:
        for s in SENS:
            r = (done or {}).get("results", {}).get(h, {}).get(s)
            if s in LEVEL_ONLY:
                status = LEVEL_ONLY[s]
            elif s in ("US only", "2016+"):
                status = "same as base (panel is US-only, 2026-27)"
            elif s == "60-day paths":
                status = "not in the final run (60-day paths reach N >= 1,000 later); descriptive then"
            else:
                status = "estimated (final touch)" if r else "pending (test date not reached)"
            r = r or {}
            base = s == "base"
            rows.append({"hid": h, "sens": s, "status": status, "fe": FAMILY[h]["fe"], "coef": r.get("coef", np.nan),
                         "se": r.get("se", np.nan), "ci_lo": r.get("ci_lo", np.nan), "ci_hi": r.get("ci_hi", np.nan),
                         "p": r.get("p", np.nan), "p_wild": r.get("p_wild", np.nan),
                         "p_used": r.get("p_used", 1.0) if base else r.get("p_used", np.nan),
                         "effective_clusters": r.get("effective_clusters", np.nan), "clusters": r.get("clusters", np.nan),
                         "cluster2": "", "in_family": base, "descriptive": False,
                         "q": q[h] if base else np.nan, "label": "SNAPSHOT", "loo_min": r.get("loo_min", np.nan)})
    # descriptive context from part 1 (not a test, not in the family)
    summ = json.loads((TABLES / "tm_moves_summary.json").read_text())
    rows.append({"hid": "H20-desc", "sens": "base", "status": "descriptive (3 snapshot days; not a test)",
                 "fe": "", "coef": summ["move_rate_pct"] / 100, "se": np.nan,
                 "ci_lo": summ["move_rate_ci95_pct"][0] / 100, "ci_hi": summ["move_rate_ci95_pct"][1] / 100,
                 "p": np.nan, "p_wild": np.nan, "p_used": np.nan, "effective_clusters": np.nan,
                 "clusters": np.nan, "cluster2": "", "in_family": False, "descriptive": True, "q": np.nan,
                 "label": "SNAPSHOT", "loo_min": np.nan})
    pd.DataFrame(rows).to_csv(TABLES / "hypotheses.csv", index=False)
    # design constants quoted in the findings (not results)
    (TABLES / "constants.json").write_text(json.dumps({
        "ci_level_pct": 95, "wide_spread_ratio": 3, "near_sale_phase_days": 3,
        "wild_bootstrap_draws": 1999, "wild_below_effective_clusters": 30, "move_threshold_usd": 0.005,
        "missing_day_share_allowed": 0.1, "discover_window_days": 120, "far_band_days": 60, "far_share_pct": 60,
        "far_share_new_pct": 30, "ranges_share_pct": 80, "tm_daily_quota": 5000, "collector_budget": 4500,
        "rate_limit_available_stop": 250, "catchup_max_wait_h": 3, "min_paths_summary": 500,
        "min_paths_moderators": 1000, "ipw_stratum_min_events": 50, "power_reps": pw["rule"]["reps"],
        "mde_limit_pp": pw["rule"]["mde_limit_pp"],
    }, indent=2))
    print(f"family {fam}; excluded {len(EXCLUDED)}; rows {len(rows)}; test at N >= {n}")


if __name__ == "__main__":
    if "--freeze" in sys.argv:
        print("frozen spec sha256:", freeze_spec())
    elif "--final" in sys.argv:
        print(json.dumps(run_final()["q"]))
    else:
        main()
