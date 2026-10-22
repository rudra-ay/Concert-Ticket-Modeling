"""PATH pre-registration power analysis (review 4, F4): simulated, artist-clustered MDEs for the
family {H20a, H9p, H37} at N = 500 and N = 1,000 complete priced 30-day paths.

DECISION RULE (fixed in this docstring before any simulation was run, 2026-10-21):
- MDE = the smallest absolute increase in the daily move probability (percentage points) that
  the registered estimator detects with >= 80% power at alpha = 0.05/3 (Bonferroni bound on the
  3-member BH family; one-sided for H20a and H37, two-sided for H9p).
- A test is "underpowered at N" if its MDE > 1.0 pp (about 3x the base move rate observed so far).
- N_TEST = 500 if every family member is powered at 500; else 1,000. All members run together,
  once, at N_TEST (one final touch).
- A member still underpowered at N = 1,000 leaves the family now and is reported descriptively.

Simulation design (inputs measured from the panel as of 2026-10-21; no outcome model fitted):
- Events: N complete paths, each with 30 day-pairs whose later snapshot is 29..0 days before
  the show. Artists: event counts per artist resampled from the watchlist's distribution.
- Outcome: Bernoulli(p0 + delta * x), with p0 = the observed daily move rate (P1). Event-level
  heterogeneity: p_event ~ Beta with mean p0 and concentration 20 (an assumption; the 3-day data
  can't identify it).
- H20a: x = 1[0-6 days]; LPM with event FE + bucket dummies (reference 21-29 days).
- H9p: x = wide spread (event-level, share measured); LPM with bucket dummies.
- H37: x = 1[pair's later snapshot 1-3 days after a sale-phase date]; the share of events with a
  sale-phase date inside [show - 30 d, show) is measured from the panel; LPM with event FE + buckets.
- SE: CR1 clustered by artist, t(G - 1). 400 replications per grid point, seeded.
Run: .venv/bin/python src/analysis/path_power.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from analysis.path_common import TABLES  # noqa: E402
from analysis.path_panel import PANEL  # noqa: E402

ALPHA = 0.05 / 3
POWER = 0.80
MDE_LIMIT_PP = 1.0
REPS = 400
DELTAS_PP = [0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 4.0, 6.0]
NS = [500, 1000]
PAIRS = 30
CONC = 20.0


def inputs() -> dict:
    p = pd.read_parquet(PANEL)
    first = p.sort_values("snap_date").groupby("event_id").first()
    sizes = first.groupby("artist").size().to_numpy()
    priced = first[first.price_min > 0]
    wide = float(((priced.price_max / priced.price_min) >= 3).mean())

    def phase_dates(r) -> list[pd.Timestamp]:
        out = []
        if isinstance(r.public_sale_start, str) and r.public_sale_start:
            out.append(pd.Timestamp(r.public_sale_start))
        if isinstance(r.presales_json, str):
            for x in json.loads(r.presales_json or "[]"):
                for k in ("startDateTime", "endDateTime"):
                    if x.get(k):
                        out.append(pd.Timestamp(x[k]))
        return [d.tz_convert("UTC") if d.tzinfo else d.tz_localize("UTC") for d in out]

    show = pd.to_datetime(first.show_time, utc=True)
    in_win = [sum(1 for d in phase_dates(r) if s - pd.Timedelta(days=30) <= d < s) for r, s in
              zip(first.itertuples(), show)]
    in_win = np.array(in_win)
    summ = json.loads((TABLES / "tm_moves_summary.json").read_text())
    return {"p0": summ["move_rate_pct"] / 100, "artist_sizes": sizes.tolist(), "wide_share": round(wide, 4),
            "sale_phase_event_share": round(float((in_win > 0).mean()), 4),
            "sale_phase_dates_per_event_if_any": round(float(in_win[in_win > 0].mean()), 2) if (in_win > 0).any() else 0.0,
            "events_measured": int(len(first))}


def draw_design(n: int, inp: dict, rng: np.random.Generator) -> pd.DataFrame:
    sizes = np.array(inp["artist_sizes"])
    art, total = [], 0
    while total < n:
        k = int(rng.choice(sizes))
        art.extend([len(set(art)) + 1] * k)
        total += k
    art = np.array(art[:n])
    ev = np.repeat(np.arange(n), PAIRS)
    days = np.tile(np.arange(PAIRS - 1, -1, -1), n)
    d = pd.DataFrame({"event": ev, "artist": np.repeat(art, PAIRS), "days": days})
    d["b0"] = (d.days <= 6).astype(float)
    d["b1"] = ((d.days >= 7) & (d.days <= 13)).astype(float)
    d["b2"] = ((d.days >= 14) & (d.days <= 20)).astype(float)
    wide_ev = rng.random(n) < inp["wide_share"]
    d["wide"] = wide_ev[d.event].astype(float)
    has_phase = rng.random(n) < inp["sale_phase_event_share"]
    phase_day = rng.integers(3, PAIRS, n)  # a sale-phase date at this many days before the show
    lag = phase_day[d.event] - d.days     # days since the sale-phase date
    d["near"] = (has_phase[d.event] & (lag >= 1) & (lag <= 3)).astype(float)
    return d


def demean(a: np.ndarray, g: np.ndarray) -> np.ndarray:
    s = np.bincount(g, weights=a)
    c = np.bincount(g)
    return a - (s / np.maximum(c, 1))[g]


def cr1_t(y: np.ndarray, X: np.ndarray, cl: np.ndarray, j: int) -> tuple[float, int]:
    XtX_inv = np.linalg.pinv(X.T @ X)
    b = XtX_inv @ X.T @ y
    u = y - X @ b
    G = int(cl.max()) + 1
    S = np.zeros((G, X.shape[1]))
    np.add.at(S, cl, X * u[:, None])
    n, k = X.shape
    V = XtX_inv @ (S.T @ S) @ XtX_inv * (G / (G - 1)) * ((n - 1) / (n - k))
    se = np.sqrt(max(V[j, j], 1e-30))
    return b[j] / se, G


def one(hid: str, d: pd.DataFrame, delta: float, inp: dict, rng: np.random.Generator) -> bool:
    n = int(d.event.max()) + 1
    a = CONC * inp["p0"]
    pe = rng.beta(a, CONC - a, n)
    x = {"H20a": d.b0, "H9p": d.wide, "H37": d.near}[hid].to_numpy()
    prob = np.clip(pe[d.event] + delta * x, 0, 1)
    y = (rng.random(len(d)) < prob).astype(float)
    cl = pd.factorize(d.artist)[0]
    if hid == "H9p":
        X = np.column_stack([np.ones(len(d)), x, d.b0, d.b1, d.b2])
        t, G = cr1_t(y, X, cl, 1)
        return 2 * stats.t.sf(abs(t), G - 1) < ALPHA
    g = d.event.to_numpy()
    cols = [x, d.b0.to_numpy(), d.b1.to_numpy(), d.b2.to_numpy()] if hid == "H37" else [x, d.b1.to_numpy(), d.b2.to_numpy()]
    X = np.column_stack([demean(c, g) for c in cols])
    t, G = cr1_t(demean(y, g), X, cl, 0)
    return stats.t.sf(t, G - 1) < ALPHA


def main() -> dict:
    inp = inputs()
    rng = np.random.default_rng(20261021)
    rows, mde = [], {}
    for N in NS:
        for hid in ("H20a", "H9p", "H37"):
            found = None
            for dpp in DELTAS_PP:
                hits = 0
                for _ in range(REPS):
                    d = draw_design(N, inp, rng)
                    hits += one(hid, d, dpp / 100, inp, rng)
                pw = hits / REPS
                rows.append({"N": N, "hid": hid, "delta_pp": dpp, "power": round(pw, 3)})
                if pw >= POWER and found is None:
                    found = dpp
                    break
            mde[f"{hid}_N{N}"] = found
            print(N, hid, found, flush=True)
    powered = {h: {N: (mde[f"{h}_N{N}"] is not None and mde[f"{h}_N{N}"] <= MDE_LIMIT_PP) for N in NS}
               for h in ("H20a", "H9p", "H37")}
    n_test = 500 if all(v[500] for v in powered.values()) else 1000
    drop = [h for h, v in powered.items() if not v[1000]]
    out = {"rule": {"alpha": ALPHA, "power": POWER, "mde_limit_pp": MDE_LIMIT_PP, "reps": REPS, "pairs_per_path": PAIRS,
                    "beta_concentration": CONC},
           "inputs": {k: v for k, v in inp.items() if k != "artist_sizes"},
           "artists_measured": len(inp["artist_sizes"]), "mde_pp": mde, "powered": powered,
           "n_test": n_test, "moved_out_of_family": drop}
    pd.DataFrame(rows).to_csv(TABLES / "power_grid.csv", index=False)
    (TABLES / "power.json").write_text(json.dumps(out, indent=2))
    print(json.dumps(out, indent=1))
    return out


if __name__ == "__main__":
    main()
