"""Task 6, part 2: predictive model for unseen artists, SHAP, PDPs, interactions.

`.venv/bin/python src/analysis/level_model.py`:
- features: the whitelist in level_data (no EXPOST/OUTCOME/TARGET/SHOWDAY/POST_ONSALE columns; asserted)
- HistGradientBoosting, tuned on valid (artist-held-out), refit on train+valid, evaluated ONCE on test
- baselines: global median, year median, genre x 5-year median; reference: the artist's own
  leave-one-out median (not available for unseen artists; shows what artist identity is worth)
- SHAP (TreeExplainer) summed back to original features; PDPs for the top 10; SHAP interaction screen
Writes reports/level_tables/model_*.csv|json and reports/charts/level_{holdout,shap,pdp,interactions}.png.
"""
from __future__ import annotations

import itertools
import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import shap  # noqa: E402
from sklearn.ensemble import HistGradientBoostingRegressor  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from analysis.data_quality import AXIS, INK2, NEUTRAL, S1, S2, S3, SURFACE  # noqa: E402,F401
from analysis.level_data import CHARTS, OUT_TABLES, load_sample, predictive_features  # noqa: E402

SEED = 20261019
GRID = {
    "learning_rate": [0.01, 0.03, 0.08],
    "max_iter": [100, 300, 800],
    "max_leaf_nodes": [15, 31, 63],
    "min_samples_leaf": [20, 80],
    "l2_regularization": [0.0, 1.0],
}
MIN_LEVEL = 50
N_BOOT = 1000


class Encoder:
    """One-hot categoricals (levels with >= MIN_LEVEL fit rows, rest -> other); numerics as float."""

    def __init__(self, num: list[str], cat: list[str]):
        self.num, self.cat = num, cat

    def fit(self, d: pd.DataFrame) -> "Encoder":
        self.levels = {c: [v for v, n in d[c].value_counts().items() if n >= MIN_LEVEL] for c in self.cat}
        return self

    def transform(self, d: pd.DataFrame) -> pd.DataFrame:
        out = {c: d[c].astype(float) for c in self.num}
        self.groups = {c: [c] for c in self.num}
        for c in self.cat:
            cols = []
            v = d[c]
            for lev in self.levels[c]:
                name = f"{c}={lev}"
                out[name] = (v == lev).astype(float).where(v.notna())
                cols.append(name)
            name = f"{c}=other"
            out[name] = (~v.isin(self.levels[c])).astype(float).where(v.notna())
            cols.append(name)
            self.groups[c] = cols
        return pd.DataFrame(out, index=d.index)


def baselines(fit: pd.DataFrame, ev: pd.DataFrame, target: str = "y") -> dict[str, pd.Series]:
    g = fit[target].median()
    yr = fit.groupby("year")[target].median()
    fit = fit.assign(yb=(fit.year // 5) * 5, genre=fit.genre_coarse_final.fillna("unknown"))
    ev = ev.assign(yb=(ev.year // 5) * 5, genre=ev.genre_coarse_final.fillna("unknown"))
    gy = fit.groupby(["genre", "yb"])[target].agg(["median", "size"])
    gy = gy[gy["size"] >= 20]["median"]
    gen = fit.groupby("genre")[target].median()
    year_pred = ev.year.map(yr).fillna(g)
    gy_pred = pd.Series([gy.get((a, b), np.nan) for a, b in zip(ev.genre, ev.yb)], index=ev.index)
    gy_pred = gy_pred.fillna(year_pred + ev.genre.map(gen).fillna(g) - g)
    return {"global median": pd.Series(g, index=ev.index), "year median": year_pred, "genre × 5-yr median": gy_pred}


def loo_artist_median(d: pd.DataFrame, target: str = "y") -> pd.Series:
    """Leave-one-out median of the same artist_key (reference only)."""
    out = pd.Series(np.nan, index=d.index)
    for _, g in d.groupby("artist_key"):
        if len(g) < 2:
            continue
        v = g[target].to_numpy()
        out.loc[g.index] = [np.median(np.delete(v, i)) for i in range(len(v))]
    return out


def errors(pred: pd.Series, d: pd.DataFrame, target: str = "y") -> dict:
    e = (pred - d[target]).abs()
    if target == "y":
        dollars = (np.exp(pred) - d["avg_price_real"]).abs()
    else:  # relative target: map back through the artist's median
        dollars = (d["avg_price_real"] * (np.exp(pred - d[target]) - 1)).abs()
    return {"mae_log": float(e.mean()), "medae_log": float(e.median()), "mae_usd": float(dollars.mean()),
            "medae_usd": float(dollars.median()), "n": int(pred.notna().sum())}


def cluster_boot_diff(a: pd.Series, b: pd.Series, clusters: pd.Series, rng) -> tuple[float, float, float]:
    """MAE(a) - MAE(b) with a cluster (performer-group) bootstrap 95% CI."""
    df = pd.DataFrame({"a": a, "b": b, "c": clusters.to_numpy()})
    agg = df.groupby("c").agg(sa=("a", "sum"), sb=("b", "sum"), n=("a", "size"))
    k = len(agg)
    diffs = []
    for _ in range(N_BOOT):
        idx = rng.integers(0, k, k)
        t = agg.iloc[idx]
        diffs.append(t.sa.sum() / t.n.sum() - t.sb.sum() / t.n.sum())
    return float(a.mean() - b.mean()), float(np.percentile(diffs, 2.5)), float(np.percentile(diffs, 97.5))


def tune(Xtr, ytr, Xva, yva) -> tuple[dict, pd.DataFrame]:
    rows = []
    keys = list(GRID)
    for vals in itertools.product(*GRID.values()):
        params = dict(zip(keys, vals))
        m = HistGradientBoostingRegressor(random_state=SEED, early_stopping=False, **params).fit(Xtr, ytr)
        rows.append({**params, "valid_mae": float(np.abs(m.predict(Xva) - yva).mean())})
    t = pd.DataFrame(rows).sort_values("valid_mae")
    best = {k: (int(v) if k in ("max_iter", "max_leaf_nodes", "min_samples_leaf") else float(v))
            for k, v in t.iloc[0][keys].items()}
    return best, t


def shap_by_feature(model, X: pd.DataFrame, groups: dict[str, list[str]]) -> pd.DataFrame:
    sv = shap.TreeExplainer(model).shap_values(X)
    sv = pd.DataFrame(sv, columns=X.columns, index=X.index)
    return pd.DataFrame({f: sv[cols].sum(axis=1) for f, cols in groups.items()})


def partial_dependence(model, X: pd.DataFrame, enc: Encoder, f: str, raw: pd.DataFrame) -> pd.DataFrame:
    """Mean prediction when feature f is set to each grid value (manual, works for one-hot groups)."""
    rows = []
    if f in enc.cat:
        for lev in enc.levels[f] + ["other"]:
            Z = X.copy()
            for c in enc.groups[f]:
                Z[c] = 0.0
            Z[f"{f}={lev}"] = 1.0
            rows.append({"value": str(lev), "pd": float(model.predict(Z).mean()),
                         "share": float((raw[f] == lev).mean()) if lev != "other" else np.nan})
    else:
        v = raw[f].dropna()
        grid = np.unique(np.quantile(v, np.linspace(0.02, 0.98, 25))) if v.nunique() > 25 else np.sort(v.unique())
        for g in grid:
            Z = X.copy()
            Z[f] = g
            rows.append({"value": g, "pd": float(model.predict(Z).mean()), "share": np.nan})
    return pd.DataFrame(rows)


FINAL_SPEC = OUT_TABLES / "final_spec.json"
TARGETS = ["y", "price_rel_tour"]


def current_spec() -> dict:
    """Everything that defines the final model; its hash is registered before the test touch."""
    import hashlib
    s = load_sample()
    num, cat = predictive_features(s)
    from analysis.targets import ROOT
    cov = json.loads((ROOT / "data/shows_join_coverage.json").read_text())
    split_hash = hashlib.sha256(
        s.sort_values("show_id")[["show_id", "artist_split"]].to_csv(index=False).encode()).hexdigest()
    return {"features_numeric": num, "features_categorical": cat, "grid": GRID, "targets": TARGETS,
            "seed": SEED, "min_level": MIN_LEVEL, "data_built": cov["_summary"]["built"],
            "n_sample": int(len(s)), "split_rows_sha256": split_hash}


def spec_hash(spec: dict) -> str:
    import hashlib
    return hashlib.sha256(json.dumps(spec, sort_keys=True, default=str).encode()).hexdigest()


def freeze_spec() -> str:
    spec = current_spec()
    h = spec_hash(spec)
    FINAL_SPEC.write_text(json.dumps({"sha256": h, "spec": spec}, indent=2, default=str))
    return h


def check_final_allowed() -> str:
    """--final runs only against a frozen spec that matches the current code and data, and only once."""
    if not FINAL_SPEC.exists():
        raise SystemExit("refusing --final: no frozen spec (run with --freeze first)")
    frozen = json.loads(FINAL_SPEC.read_text())
    h = spec_hash(current_spec())
    if h != frozen["sha256"]:
        raise SystemExit(f"refusing --final: current spec {h[:12]} != frozen {frozen['sha256'][:12]}")
    log = OUT_TABLES / "test_touch_log.jsonl"
    if log.exists() and any(json.loads(x).get("kind") == "final" for x in log.read_text().splitlines()):
        raise SystemExit("refusing --final: a final test touch is already logged")
    return h


def log_test_touch(results: dict, note: str, sha: str = "") -> None:
    """Append every evaluation on the test split to an audit log."""
    from datetime import datetime, timezone
    entry = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "kind": "final", "spec_sha256": sha, "note": note,
             "n": results["n"], "features": results["features_numeric"] + results["features_categorical"],
             "params": {k: results[k]["best_params"] for k in ("y", "price_rel_tour")},
             "test_mae_log": {k: {m: v["mae_log"] for m, v in results[k]["test"].items()} for k in ("y", "price_rel_tour")}}
    with open(OUT_TABLES / "test_touch_log.jsonl", "a") as f:
        f.write(json.dumps(entry, default=float) + "\n")


def main(final: bool = False, note: str = "") -> dict:
    sha = check_final_allowed() if final else ""
    OUT_TABLES.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(SEED)
    s = load_sample()
    num, cat = predictive_features(s)
    tr, va, te = (s[s.artist_split == k] for k in ("train", "valid", "test"))
    trva = pd.concat([tr, va])
    results: dict = {"features_numeric": num, "features_categorical": cat,
                     "n": {"train": len(tr), "valid": len(va), "test": len(te)},
                     "artist_keys": {k: int(x.artist_key.nunique()) for k, x in [("train", tr), ("valid", va), ("test", te)]}}

    out_models = {}
    for target in ["y", "price_rel_tour"]:
        trt, vat = tr[tr[target].notna()], va[va[target].notna()]
        enc = Encoder(num, cat).fit(trt)
        best, grid = tune(enc.transform(trt), trt[target], enc.transform(vat), vat[target])
        grid.to_csv(OUT_TABLES / f"model_tuning_{target}.csv", index=False)
        # valid-set comparison (used for model choice only)
        m_tr = HistGradientBoostingRegressor(random_state=SEED, early_stopping=False, **best).fit(enc.transform(trt), trt[target])
        pv = pd.Series(m_tr.predict(enc.transform(vat)), index=vat.index)
        valid = {"GBM": errors(pv, vat, target)}
        if target == "y":
            vb = baselines(trt, vat)
            for k, v in vb.items():
                valid[k] = errors(v, vat)
            ref = loo_artist_median(vat)
            valid["reference: artist's own LOO median (not available for unseen artists)"] = errors(ref[ref.notna()], vat[ref.notna()])
            bb = min(vb, key=lambda k: valid[k]["mae_log"])
            diff = cluster_boot_diff((pv - vat.y).abs(), (vb[bb] - vat.y).abs(), vat.split_key, rng)
            results["valid_gbm_vs_best_baseline"] = {"baseline": bb, "mae_diff_log": diff[0], "ci95": [diff[1], diff[2]]}
        else:
            zero = pd.Series(0.0, index=vat.index)
            valid["zero (tour median)"] = errors(zero, vat, target)
            diff = cluster_boot_diff((pv - vat[target]).abs(), vat[target].abs(), vat.split_key, rng)
            results["valid_rel_gbm_vs_zero"] = {"mae_diff_log": diff[0], "ci95": [diff[1], diff[2]]}
        # final: refit on train+valid; the test split is evaluated only with --final
        trvat, tet = trva[trva[target].notna()], te[te[target].notna()]
        enc = Encoder(num, cat).fit(trvat)
        Xtrva, Xte = enc.transform(trvat), enc.transform(tet)
        model = HistGradientBoostingRegressor(random_state=SEED, early_stopping=False, **best).fit(Xtrva, trvat[target])
        out_models[target] = (model, enc, Xtrva, trvat)
        if not final:
            results[target] = {"best_params": best, "valid": valid, "test": {}}
            continue
        pred = pd.Series(model.predict(Xte), index=tet.index)
        test = {"GBM": errors(pred, tet, target)}
        if target == "y":
            base = baselines(trvat, tet)
            for k, v in base.items():
                test[k] = errors(v, tet)
            ref = loo_artist_median(tet)
            ref_ok = ref.notna()
            test["reference: artist's own LOO median (not available for unseen artists)"] = errors(ref[ref_ok], tet[ref_ok])
            best_base = min(base, key=lambda k: test[k]["mae_log"])
            diff = cluster_boot_diff((pred - tet.y).abs(), (base[best_base] - tet.y).abs(), tet.split_key, rng)
            results["gbm_vs_best_baseline"] = {"baseline": best_base, "mae_diff_log": diff[0], "ci95": [diff[1], diff[2]]}
        else:
            zero = pd.Series(0.0, index=tet.index)
            test["zero (tour median)"] = errors(zero, tet, target)
            diff = cluster_boot_diff((pred - tet[target]).abs(), zero.abs().sub(tet[target]).abs(), tet.split_key, rng)
            results["rel_gbm_vs_zero"] = {"mae_diff_log": diff[0], "ci95": [diff[1], diff[2]]}
        results[target] = {"best_params": best, "valid": valid, "test": test}

    # --- explanation on the log-price model (fit on train+valid) ----------------
    model, enc, Xtrva, trva = out_models["y"]
    samp = Xtrva.sample(min(4000, len(Xtrva)), random_state=SEED)
    sh = shap_by_feature(model, samp, enc.groups)
    imp = sh.abs().mean().sort_values(ascending=False)
    imp.rename("mean_abs_shap").to_csv(OUT_TABLES / "model_shap_importance.csv")
    top = list(imp.index[:10])
    pdps = {f: partial_dependence(model, samp.sample(min(1500, len(samp)), random_state=SEED), enc, f, trva.loc[samp.index])
            for f in top}
    pd.concat([p.assign(feature=f) for f, p in pdps.items()]).to_csv(OUT_TABLES / "model_pdp.csv", index=False)

    # interaction screen: SHAP interaction values summed to feature-group pairs
    isamp = samp.sample(min(600, len(samp)), random_state=SEED)
    iv = shap.TreeExplainer(model).shap_interaction_values(isamp)
    cols = list(isamp.columns)
    gidx = {f: [cols.index(c) for c in cs] for f, cs in enc.groups.items()}
    feats = list(imp.index[:15])
    pairs = []
    for a, b in itertools.combinations(feats, 2):
        v = iv[:, gidx[a]][:, :, gidx[b]].sum(axis=(1, 2)) * 2  # symmetric off-diagonal
        pairs.append({"a": a, "b": b, "mean_abs_interaction": float(np.abs(v).mean())})
    inter = pd.DataFrame(pairs).sort_values("mean_abs_interaction", ascending=False)
    inter.to_csv(OUT_TABLES / "model_interactions.csv", index=False)
    results["shap_top10"] = imp.head(10).round(4).to_dict()
    results["interactions_top10"] = inter.head(10).round(4).to_dict("records")
    (OUT_TABLES / "model_results_valid.json").write_text(json.dumps(results, indent=2, default=float))
    if final:
        (OUT_TABLES / "model_results.json").write_text(json.dumps(results, indent=2, default=float))
    if final:
        log_test_touch(results, note, sha)
        chart_holdout(results)
    chart_shap(imp, sh, trva.loc[samp.index])
    chart_pdp(pdps, enc)
    chart_interactions(inter.head(12))
    return results


def chart_holdout(r: dict) -> None:
    t = pd.DataFrame(r["y"]["test"]).T
    t = t.sort_values("mae_log")
    fig, axes = plt.subplots(1, 2, figsize=(11, 3.6), sharey=True)
    names = [n.replace(" (not available for unseen artists)", "\n(not available for unseen artists)") for n in t.index]
    colors = [S2 if n.startswith("reference") else (S1 if n == "GBM" else NEUTRAL) for n in t.index]
    for ax, col, title, fmt in [(axes[0], "mae_log", "MAE, log points", "{:.3f}"), (axes[1], "mae_usd", "MAE, Sep-2026 $ per ticket", "${:.0f}")]:
        ax.barh(names, t[col], color=colors, height=0.6)
        for i, v in enumerate(t[col]):
            ax.text(v, i, " " + fmt.format(v), va="center", fontsize=8, color=INK2)
        ax.set_title(title)
        ax.grid(axis="y", visible=False)
    axes[0].invert_yaxis()
    fig.suptitle("Artist-held-out test error (test touched once; model refit on train+valid)", x=0.01, ha="left", fontweight="bold")
    fig.tight_layout()
    fig.savefig(CHARTS / "level_holdout.png", dpi=150)
    plt.close(fig)


def chart_shap(imp: pd.Series, sh: pd.DataFrame, raw: pd.DataFrame) -> None:
    top = imp.head(20)[::-1]
    fig, ax = plt.subplots(figsize=(8, 6.5))
    ax.barh(top.index, top.values, color=S1, height=0.7)
    for i, v in enumerate(top.values):
        ax.text(v, i, f" {v:.3f}", va="center", fontsize=8, color=INK2)
    ax.set_xlabel("mean |SHAP| (log points of price)")
    ax.set_title("What drives predicted price for an unseen artist (top 20)")
    ax.grid(axis="y", visible=False)
    fig.tight_layout()
    fig.savefig(CHARTS / "level_shap.png", dpi=150)
    plt.close(fig)


def chart_pdp(pdps: dict, enc: Encoder | None = None, cat: set[str] | None = None) -> None:
    from matplotlib.ticker import FuncFormatter, MaxNLocator
    cat = cat if cat is not None else set(enc.cat)
    fig, axes = plt.subplots(2, 5, figsize=(16, 6.5))
    for ax, (f, p) in zip(axes.ravel(), pdps.items()):
        base = p.pd.mean()
        eff = 100 * (np.exp(p.pd - base) - 1)
        if f in cat:
            ax.bar(range(len(p)), eff, color=S1, width=0.7)
            ax.set_xticks(range(len(p)), [str(v)[:10] for v in p.value], rotation=60, fontsize=7)
            ax.axhline(0, color=AXIS, linewidth=1)
        else:
            ax.plot(p.value.astype(float), eff, color=S1, linewidth=2)
            ax.tick_params(labelsize=7)
            ax.xaxis.set_major_locator(MaxNLocator(5))
            if p.value.astype(float).abs().max() >= 10_000:
                ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v / 1000:.0f}k"))
        ax.set_title(f, fontsize=9)
        ax.grid(axis="x", visible=False)
    for ax in axes[:, 0]:
        ax.set_ylabel("% vs. average prediction")
    fig.suptitle("Partial dependence, top 10 features by SHAP (GBM on log real price)", x=0.01, ha="left", fontweight="bold")
    fig.tight_layout()
    fig.savefig(CHARTS / "level_pdp.png", dpi=150)
    plt.close(fig)


def chart_interactions(inter: pd.DataFrame) -> None:
    t = inter[::-1]
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.barh([f"{a} × {b}" for a, b in zip(t.a, t.b)], t.mean_abs_interaction, color=S1, height=0.7)
    ax.set_xlabel("mean |SHAP interaction| (log points)")
    ax.set_title("Interaction screen: strongest feature pairs")
    ax.grid(axis="y", visible=False)
    fig.tight_layout()
    fig.savefig(CHARTS / "level_interactions.png", dpi=150)
    plt.close(fig)


def redraw_pdp_from_csv() -> None:
    d = pd.read_csv(OUT_TABLES / "model_pdp.csv")
    pdps, cat = {}, set()
    for f, g in d.groupby("feature", sort=False):
        if pd.to_numeric(g.value, errors="coerce").isna().any():
            cat.add(f)
        pdps[f] = g.reset_index(drop=True)
    chart_pdp(pdps, cat=cat)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--final", action="store_true", help="evaluate on the test split (logged)")
    ap.add_argument("--note", default="")
    ap.add_argument("--freeze", action="store_true", help="register the final spec (hash) and exit")
    ap.add_argument("--redraw-pdp", action="store_true", help="redraw the PDP chart from model_pdp.csv and exit")
    a = ap.parse_args()
    if a.redraw_pdp:
        redraw_pdp_from_csv()
        raise SystemExit
    if a.freeze:
        print("frozen spec sha256:", freeze_spec())
        raise SystemExit
    r = main(final=a.final, note=a.note)
    for target in ["y", "price_rel_tour"]:
        print(target, r[target]["best_params"])
        print(pd.DataFrame(r[target]["valid"]).T.round(3).to_string())
        if a.final:
            print(pd.DataFrame(r[target]["test"]).T.round(3).to_string())
    print(json.dumps({k: r.get(k) for k in ("valid_gbm_vs_best_baseline", "valid_rel_gbm_vs_zero", "gbm_vs_best_baseline", "rel_gbm_vs_zero", "shap_top10")}, indent=1, default=float))
    print(pd.DataFrame(r["interactions_top10"]).to_string())
