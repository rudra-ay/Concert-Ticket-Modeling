"""Task 6, part 1: fixed-effects tests of the LEVEL hypotheses.

`.venv/bin/python src/analysis/level_hypotheses.py` writes
reports/level_tables/hypotheses.csv (one row per hypothesis x sensitivity spec),
reports/level_tables/metro_effects.csv and reports/charts/level_{forest,sensitivity,metros}.png.

Every spec: y = log_avg_price_real (Sep-2026 $), FEs absorbed, SEs clustered by
split_key (performer group, which nests artist and tour). Hypotheses whose input
columns are missing or too sparse are skipped and reported as such, so the script
can be rerun as the venue, bill and weather tables fill.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from analysis.data_quality import AXIS, GRID, INK, INK2, MUTED, NEUTRAL, S1, S2, SURFACE  # noqa: E402,F401
from analysis.fe import bh, demean, drop_singletons, effective_clusters, fe_ols, wild_cluster_p  # noqa: E402
from analysis.level_data import CHARTS, OUT_TABLES, load_sample  # noqa: E402

CLUSTER = "split_key"
# Hypotheses fed by a table that is still filling: flagged preliminary and kept out
# of the BH family until the table reaches its milestone (rerun then).
DEPENDS = {"H5w": "venue", "H5o": "venue"}
MILESTONE_PCT = 95.0
MIN_CLUSTERS = 5
DESCRIPTIVE_BELOW = 10  # fewer FE groups with variation: estimate shown, kept out of the BH family
N_PERM = 999
SEED = 20261019


@dataclass
class Spec:
    hid: str
    name: str
    x: str                      # headline regressor
    fe: list[str]
    controls: list[str] = field(default_factory=list)
    mask: str | None = None     # boolean column restricting the base sample
    kind: str = "binary"        # binary | continuous
    label: str = ""             # leakage label of the headline regressor
    note: str = ""
    cat_controls: list[str] = field(default_factory=list)  # categorical controls -> dummies
    cluster2: str | None = None  # second clustering dimension for regressors varying at metro/venue level


SPECS = [
    Spec("H1b", "Metro income (US)", "log_metro_income", ["artist_key", "year"], ["log_metro_pop"], "us",
         "continuous", "SNAPSHOT", "elasticity; 2024 ACS for all years; controls metro population", cluster2="metro_key"),
    Spec("H1c", "Metro size (US)", "log_metro_pop", ["artist_key", "year"], ["log_metro_income"], "us",
         "continuous", "SNAPSHOT", "per log point of metro population; controls income", cluster2="metro_key"),
    Spec("H2a", "Fri/Sat vs Mon–Thu", "is_fri_sat", ["tour", "year"], ["is_sunday"], "single", "binary", "",
         "within tour; single-night units only"),
    Spec("H2b", "Holiday eve / long weekend", "holiday", ["tour", "year"], ["is_fri_sat", "is_sunday"], "single",
         "binary", "", "within tour; national calendars; controls day of week"),
    Spec("H3", "Later tour leg (leg > 1)", "later_leg", ["tour", "year"], [], None, "binary", "EXPOST",
         "within tour; controls continent; legs inferred for many tours", ["continent"]),
    Spec("H4", "Multi-night stand", "multi_night", ["tour", "year"], [], None, "binary", "EXPOST",
         "within tour; aggregate figure covering ≥ 2 nights vs single-night shows", ["continent"]),
    Spec("H5", "Venue size (tickets per show), association", "log_cap_sold", ["artist_key", "year"], [], None, "continuous",
         "OUTCOME", "tickets available per show is configured in response to demand: an association, not a test", cluster2="venue_id"),
    Spec("H5w", "Venue size (Wikidata capacity), primary", "log_capacity_wd", ["artist_key", "year"], [], None,
         "continuous", "SNAPSHOT", "per log point of current Wikidata capacity", cluster2="venue_id"),
    Spec("H5o", "Outdoor venue", "outdoor", ["artist_key", "year"], ["log_capacity_wd"], None, "binary", "SNAPSHOT",
         "artist + year FE; controls Wikidata capacity (not the OUTCOME tickets per show)", cluster2="venue_id"),
    Spec("H5f", "Fanbase vs capacity (2016+), association", "fan_per_seat", ["artist_key", "year"], [], "post2015",
         "continuous", "POST_ONSALE + OUTCOME", "log(pageviews) − log(tickets per show), ratio only; see extras.json for the test that pageviews and capacity enter with equal and opposite signs"),
    Spec("H7a", "Bill size (number of openers)", "n_openers_f", ["tour", "year"], [], None, "continuous", "",
         "within tour; rows with a known opener cell only (blank = unknown)"),
    Spec("H7b", "Co-headline package vs solo", "co_headliner_flag", ["split_key", "year"], [], None, "binary", "",
         "within performer group: the same performers' co-headline vs solo tours"),
    Spec("H7c", "Opener draw (opener pageviews)", "log_opener_pv", ["tour", "year"], [], None, "continuous",
         "POST_ONSALE", "within tour: log(1 + max opener mean daily views, 90 d before the show); linked openers, 2016+ windows"),
    Spec("H10", "Rain at an outdoor show", "rain_outdoor", ["tour", "year"], ["rain_eve", "outdoor"], "single_wx",
         "binary", "SHOWDAY", "within tour, single-night shows: evening rain ≥ 1 mm at an outdoor venue, beyond rain at indoor venues"),
    Spec("H8a", "Farewell tour", "farewell_flag", ["artist_key", "year"], [], None, "binary", "EXPOST",
         "within artist: farewell-labelled tour vs the artist's other tours; tour-level label, hindsight categories"),
    Spec("H8b", "Reunion tour", "reunion_flag", ["artist_key", "year"], [], None, "binary", "EXPOST",
         "within artist: reunion-labelled tour vs the artist's other tours"),
    Spec("H6a", "Popularity level (pageviews, 2016+)", "log_pv365", ["artist_key", "year"], ["pv_momentum"],
         "post2015", "continuous", "POST_ONSALE", "per log point of mean daily views (365 d before show); controls momentum"),
    Spec("H6b", "Momentum (pageviews, 2016+)", "pv_momentum", ["artist_key", "year"], ["log_pv365"], "post2015",
         "continuous", "POST_ONSALE", "per log point of 30-d vs 90–61-d views; controls level"),
]

SENS = [
    ("base", None, None),
    ("US only", "us", None),
    ("excl. $ outside US", "usd_ok", None),
    ("2016+", "post2015", None),
    ("excl. aggregates", "single", None),
    ("weighted by nights", None, "unit_n_shows"),
    ("IPW (selection)", None, "ipw"),
    ("tours ≥ 80% covered", "cov80", None),
    ("excl. split pseudo-tours", "not_split_tour", None),
]
# spec-specific extra sensitivity: (name, extra controls, mask)
SENS_EXTRA = {
    "H2a": [("+ metro size control (US)", ["log_metro_pop"], "us")],
    "H2b": [("+ metro size control (US)", ["log_metro_pop"], "us")],
}

# The BH family, fixed in advance (review 2, P3): every planned LEVEL hypothesis. Members
# without a result yet enter BH with p = 1 (conservative) until they land; exclusions carry
# a reason decided before seeing their estimates.
FAMILY = ["H1a", "H1b", "H1c", "H2a", "H2b", "H3", "H4", "H5w", "H5o", "H6a", "H6b", "H7a", "H7b", "H7c", "H8b", "H10"]
EXCLUDED = {
    "H5": "regressor is OUTCOME (capacity configured in response to demand): reported as an association",
    "H5f": "uses the OUTCOME regressor tickets per show: reported as an association",
    "H8a": "fewer than 10 artists carry the contrast (task-5 power table: 7): descriptive",
    "H9": "genre is fixed per artist (between-artist only, MDE ~42%): descriptive table (level_genre.py)",
    "H11": "set-list popularity: not testable (setlist.fm needs permission)",
}
PENDING = {}  # all family members now have data (final collection, 2026-10-20)
WILD_BELOW = 30  # FE groups with variation below this -> wild cluster bootstrap p


def _design(s: pd.DataFrame, spec: Spec) -> tuple[pd.DataFrame, list[str]]:
    d = s if spec.mask is None else s[s[spec.mask].fillna(False).astype(bool)]
    xs = [spec.x, *spec.controls]
    for c in spec.cat_controls:
        dummies = pd.get_dummies(d[c].fillna("unknown"), prefix=c, drop_first=True, dtype=float)
        dummies = dummies.loc[:, dummies.sum() >= 30]
        d = pd.concat([d, dummies], axis=1)
        xs += list(dummies.columns)
    return d, xs


def run_spec(s: pd.DataFrame, spec: Spec, sens_mask: str | None, weights: str | None,
             extra_controls: list[str] | None = None) -> dict:
    d = s if sens_mask is None else s[s[sens_mask].fillna(False).astype(bool)]
    if spec.x not in d.columns or d[spec.x].notna().sum() < 100:
        return {"status": "skipped: input missing or < 100 rows"}
    d, xs = _design(d, spec)
    xs += [c for c in (extra_controls or []) if c not in xs]
    if weights:
        d = d[d[weights].notna()]
        d = d.assign(**{weights: d[weights].astype(float)})
    # variation of the headline regressor within FE groups
    g = spec.fe[0]
    dd = d[d[spec.x].notna()]
    var_groups = int((dd.groupby(g)[spec.x].nunique() > 1).sum())
    if var_groups < MIN_CLUSTERS:
        return {"status": f"skipped: {var_groups} {g} groups with variation"}
    r = fe_ols(d, "y", xs, spec.fe, CLUSTER, weights, cluster2=spec.cluster2)
    used = d.loc[r.resid.index]
    g_eff = effective_clusters(used, spec.x, g, CLUSTER)
    if spec.cluster2:
        g_eff = min(g_eff, effective_clusters(used, spec.x, g, spec.cluster2))
    r.df_clusters = g_eff
    b, se = r.coef[spec.x], r.se[spec.x]
    lo, hi = r.ci(spec.x)
    sd_x = float(used[spec.x].std())
    p_wild = wild_cluster_p(d, "y", xs, spec.fe, CLUSTER, spec.x, weights, n_boot=1999, seed=SEED) \
        if g_eff < WILD_BELOW else np.nan
    loo_min = loo_max = np.nan
    loo_sign = np.nan
    if g_eff < WILD_BELOW or var_groups < WILD_BELOW:  # leave-one-group-out over the groups that carry the variation
        varying = dd.groupby(g)[spec.x].nunique()
        coefs = []
        for grp in varying[varying > 1].index:
            rr = fe_ols(d[d[g] != grp], "y", xs, spec.fe, CLUSTER, weights)
            coefs.append(rr.coef[spec.x])
        loo_min, loo_max = float(np.min(coefs)), float(np.max(coefs))
        loo_sign = float(np.mean(np.sign(coefs) == np.sign(b)))
    return dict(status="ok", coef=b, se=se, ci_lo=lo, ci_hi=hi, p=r.p(spec.x), p_wild=p_wild, n=r.n,
                clusters=r.n_clusters, effective_clusters=g_eff, cluster2=spec.cluster2 or "",
                groups_with_variation=var_groups, sd_x=sd_x, r2_within=r.r2_within,
                loo_min=loo_min, loo_max=loo_max, loo_same_sign_share=loo_sign)


def metro_dispersion(s: pd.DataFrame, rng: np.random.Generator, sens: str = "base") -> tuple[dict, pd.DataFrame]:
    """H1a: do cities differ beyond artist and year? Metro dummies with artist + year FE.

    Metros with >= 30 shows from >= 5 artists get a dummy; all other metros are
    the pooled reference. Effect size = bias-corrected SD of the metro premiums.
    p-value: permutation of metro labels within artist (199 draws).
    """
    mk = s.groupby("metro_key").agg(n=("show_id", "size"), a=("artist_key", "nunique"))
    elig = mk[(mk.n >= 30) & (mk.a >= 5)].index
    d = s.copy()
    d["metro_e"] = d["metro_key"].where(d["metro_key"].isin(elig), "_other")
    d = drop_singletons(d[["y", "artist_key", "year", "metro_e", CLUSTER, "metro_label", "metro_key"]].dropna(
        subset=["y"]), ["artist_key", "year"])

    X = pd.get_dummies(d["metro_e"], dtype=float).drop(columns="_other")
    r = fe_ols(pd.concat([d, X], axis=1), "y", list(X.columns), ["artist_key", "year"], CLUSTER)
    b, se = r.coef.to_numpy(), r.se.to_numpy()
    sd_true = float(np.sqrt(max(np.var(b) - np.mean(se**2), 0)))
    # Permutation test (Freedman-Lane style): residualize y on the reduced model
    # (artist + year FE) once, then permute metro labels within artist. Statistic:
    # between-metro sum of squares of the residuals over the eligible metros.
    yr = demean(d, ["y"], ["artist_key", "year"])["y"].to_numpy()
    codes = pd.factorize(d["metro_e"])[0]
    other = codes[d["metro_e"].to_numpy() == "_other"][0]
    art = pd.factorize(d["artist_key"])[0]

    def between_ss(c: np.ndarray) -> float:
        sums = np.bincount(c, weights=yr)
        cnt = np.bincount(c)
        keep = np.arange(len(cnt)) != other
        return float((sums[keep] ** 2 / np.maximum(cnt[keep], 1)).sum())

    stat = between_ss(codes)
    order = np.argsort(art, kind="stable")
    bounds = np.flatnonzero(np.diff(art[order])) + 1
    blocks = np.split(order, bounds)
    perm = []
    for _ in range(N_PERM):
        c = codes.copy()
        for blk in blocks:
            c[blk] = codes[rng.permutation(blk)]
        perm.append(between_ss(c))
    p = (1 + sum(v >= stat for v in perm)) / (N_PERM + 1)
    labels = d.groupby("metro_e").metro_label.agg(lambda v: v.mode().iloc[0])
    eff = pd.DataFrame({"metro_key": X.columns, "metro": labels.reindex(X.columns).to_numpy(), "coef": b, "se": se,
                        "n": d.metro_e.value_counts().reindex(X.columns).to_numpy()})
    eff["ci_lo"] = eff.coef - 1.96 * eff.se
    eff["ci_hi"] = eff.coef + 1.96 * eff.se
    eff["p"] = [r.p(c) for c in X.columns]
    eff["q_within_metros"] = bh(eff.p).to_numpy()
    eff = eff.sort_values("coef")
    res = dict(hid="H1a", name="City premium: dispersion of metro effects", sens=sens, status="ok", fe="artist_key + year",
               coef=sd_true, se=np.nan, ci_lo=np.nan, ci_hi=np.nan, p=p, n=r.n, clusters=r.n_clusters,
               groups_with_variation=len(X.columns), kind="sd", label="",
               note=f"bias-corrected SD of {len(X.columns)} metro premiums (artist + year FE; reference = other metros); "
                    f"p from {N_PERM} within-artist permutations of metro labels on artist+year-FE residuals; raw SD {np.std(b):.3f}")
    return res, eff


def tour_unit_and_split_counts(s: pd.DataFrame) -> dict:
    """Counts quoted in the report (review 1 item 4 and amendment A1), computed on analysis_sample rows."""
    from analysis.targets import artist_keys, artist_split
    lab = s["tour_unit"].ne(s["tour_key"])
    n_units = s.groupby("tour_key")["tour_unit"].nunique()
    multi = n_units[n_units > 1].index
    span = s.groupby("tour_unit")["show_date"].agg(lambda x: (x.max() - x.min()).days / 365.25)
    d = pd.read_parquet(OUT_TABLES.parents[1] / "data/shows.parquet")
    old_key, _ = artist_keys(d)  # pre-review split: no Wikidata edges, no manual relations
    moved = (artist_split(old_key) != d["artist_split"]) & d["analysis_sample"]
    return {"tour_units": {"keys_with_split_label": int(s.loc[lab, "tour_key"].nunique()), "rows_with_split_label": int(lab.sum()),
                           "keys_with_2plus_units_in_sample": int(len(multi)),
                           "rows_in_keys_with_2plus_units": int(s["tour_key"].isin(multi).sum()),
                           "max_unit_span_years": float(span.max())},
            "split_moves": {"sample_rows_changed_split": int(moved.sum()),
                            "artist_ids_changed_split": int(d.loc[moved, "artist_id"].nunique())}}


def pct(b: float) -> float:
    return 100 * (np.exp(b) - 1)


def chart_forest(h: pd.DataFrame) -> None:
    base = h[(h.sens == "base") & (h.status == "ok") & (h.kind != "sd")].copy()
    # effect in % for binary; for continuous per 1 SD of x
    base["scale"] = np.where(base.kind == "continuous", base.sd_x, 1.0)
    base["eff"] = pct(base.coef * base.scale)
    base["lo"] = pct(base.ci_lo * base.scale)
    base["hi"] = pct(base.ci_hi * base.scale)
    base = base.iloc[::-1]
    fig, ax = plt.subplots(figsize=(10, 0.62 * len(base) + 1.5))
    yv = np.arange(len(base))
    ax.axvline(0, color=AXIS, linewidth=1)
    col = [NEUTRAL if bool(r.get("descriptive", False)) else S1 for _, r in base.iterrows()]
    ax.hlines(yv, base.lo, base.hi, color=col, linewidth=2)
    ax.scatter(base.eff, yv, color=col, s=45, edgecolors=SURFACE, linewidths=1.5, zorder=3)
    def qtxt(r):
        if r.get("preliminary", False):
            return "preliminary"
        if r.get("descriptive", False):
            return "outside BH family"
        return f"q={r.q:.3f}" + (" (wild p)" if pd.notna(r.get("p_wild", np.nan)) else "")
    lab = [f"{r.hid} {r['name']}" + (" /SD" if r.kind == "continuous" else "") +
           (f" [{r.label}]" if isinstance(r.label, str) and r.label else "") + f"\n{r.eff:+.1f}% [{r.lo:+.1f}, {r.hi:+.1f}], {qtxt(r)}"
           for _, r in base.iterrows()]
    ax.set_yticks(yv, lab, fontsize=8)
    ax.set_xlabel("effect on average price, % (95% CI)\nSEs by performer group (two-way with metro/venue where the\n"
                  "regressor varies at that level); gray = outside the BH family")
    ax.set_title("LEVEL hypotheses: base-spec estimates")
    ax.grid(axis="y", visible=False)
    fig.tight_layout()
    fig.savefig(CHARTS / "level_forest.png", dpi=150)
    plt.close(fig)


def chart_sensitivity(h: pd.DataFrame) -> None:
    ok = h[(h.status == "ok") & (h.kind != "sd")].copy()
    ok["scale"] = np.where(ok.kind == "continuous", ok.sd_x, 1.0)
    ok["eff"] = pct(ok.coef * ok.scale)
    ok["lo"] = pct(ok.ci_lo * ok.scale)
    ok["hi"] = pct(ok.ci_hi * ok.scale)
    hids = list(dict.fromkeys(ok.hid))
    sens = [x[0] for x in SENS]
    fig, axes = plt.subplots(len(hids), 1, figsize=(9, 1.25 * len(hids) + 0.8), sharex=False)
    axes = np.atleast_1d(axes)
    for ax, hid in zip(axes, hids):
        t = ok[ok.hid == hid].set_index("sens").reindex(sens)
        yv = np.arange(len(sens))[::-1]
        ax.axvline(0, color=AXIS, linewidth=1)
        ax.hlines(yv, t.lo, t.hi, color=S1, linewidth=1.5)
        ax.plot(t.eff, yv, "o", color=S1, markersize=5)
        status = h[h.hid == hid].set_index("sens").status.reindex(sens).fillna("")
        ax.set_yticks(yv, [f"{n} ({st})" if st and st != "ok" else n for n, st in zip(sens, status)], fontsize=7)
        ax.set_title(f"{hid} {ok[ok.hid == hid].name.iloc[0]}", fontsize=9)
        ax.grid(axis="y", visible=False)
        ax.tick_params(axis="x", labelsize=7)
    axes[-1].set_xlabel("effect, % (binary) or % per 1 SD (continuous), 95% CI")
    fig.tight_layout()
    fig.savefig(CHARTS / "level_sensitivity.png", dpi=150)
    plt.close(fig)


def chart_metros(eff: pd.DataFrame) -> None:
    t = pd.concat([eff.head(12), eff.tail(12)])
    fig, ax = plt.subplots(figsize=(8, 8))
    yv = np.arange(len(t))
    e, lo, hi = pct(t.coef), pct(t.ci_lo), pct(t.ci_hi)
    ax.axvline(0, color=AXIS, linewidth=1)
    ax.hlines(yv, lo, hi, color=S1, linewidth=1.5)
    ax.plot(e, yv, "o", color=S1, markersize=5)
    ax.set_yticks(yv, [f"{m[:38]} (n={n})" for m, n in zip(t.metro, t.n)], fontsize=8)
    ax.axhline(11.5, color=GRID, linewidth=1, linestyle="--")
    ax.set_xlabel("premium vs. other metros, % (artist + year FE, 95% CI)")
    ax.set_title("City premium: the 12 cheapest and 12 priciest metros")
    ax.grid(axis="y", visible=False)
    fig.tight_layout()
    fig.savefig(CHARTS / "level_metros.png", dpi=150)
    plt.close(fig)


def main() -> pd.DataFrame:
    OUT_TABLES.mkdir(parents=True, exist_ok=True)
    s = load_sample()
    rng = np.random.default_rng(SEED)
    rows = []
    h1a, eff = metro_dispersion(s, rng)
    rows.append(h1a)
    for sname, smask, w in SENS[1:]:
        if smask in ("us", "usd_ok", "post2015", "single", "cov80", "not_split_tour"):
            rows.append(metro_dispersion(s[s[smask].fillna(False).astype(bool)], rng, sname)[0])
        elif w:
            rows.append(dict(hid="H1a", name="City premium: dispersion of metro effects", sens=sname, fe="artist_key + year",
                             status="not applicable (the permutation statistic is unweighted)", kind="sd", label=""))
    eff.to_csv(OUT_TABLES / "metro_effects.csv", index=False)
    for spec in SPECS:
        for sname, smask, w in SENS:
            if (smask and spec.mask == smask) or (spec.mask == "us" and smask == "usd_ok") \
                    or (spec.mask in ("single", "single_wx") and (w == "unit_n_shows" or smask == "single")):
                res = {"status": "same as base"}
            elif sname == "excl. aggregates" and spec.x == "multi_night":
                res = {"status": "not applicable (the regressor is the aggregate flag)"}
            else:
                res = run_spec(s, spec, smask, w)
            rows.append(dict(hid=spec.hid, name=spec.name, sens=sname, kind=spec.kind, label=spec.label,
                             note=spec.note, fe=" + ".join(spec.fe), **res))
        for sname, ctrl, smask in SENS_EXTRA.get(spec.hid, []):
            res = run_spec(s, spec, smask, None, ctrl)
            rows.append(dict(hid=spec.hid, name=spec.name, sens=sname, kind=spec.kind, label=spec.label,
                             note=spec.note, fe=" + ".join(spec.fe), **res))
    h = pd.DataFrame(rows)
    import json
    cov = json.loads((OUT_TABLES.parents[1] / "data/shows_join_coverage.json").read_text())
    prelim = {hid for hid, tab in DEPENDS.items() if cov.get(tab, {}).get("pct_analysis_filled", 0) < MILESTONE_PCT}
    h["preliminary"] = h.hid.isin(prelim)
    h["in_family"] = h.hid.isin(FAMILY)
    h["descriptive"] = h.hid.isin(EXCLUDED)
    h["excluded_reason"] = h.hid.map(EXCLUDED)
    base_ok = (h.sens == "base") & h.in_family
    h["q"] = np.nan
    # few clusters carry the variation -> the wild bootstrap p enters BH
    h["p_used"] = h["p_wild"].where(h["p_wild"].notna(), h["p"]) if "p_wild" in h else h["p"]
    fam = h.loc[base_ok, ["hid", "p_used"]].set_index("hid")["p_used"]
    fam = fam.where(h.loc[base_ok].set_index("hid")["status"].eq("ok"), 1.0)  # skipped/not yet run -> p = 1
    pending = pd.Series(1.0, index=[x for x in FAMILY if x not in fam.index])  # members with no row yet
    q = bh(pd.concat([fam, pending]))
    h.loc[base_ok, "q"] = h.loc[base_ok, "hid"].map(q).to_numpy()
    (OUT_TABLES / "bh_family.json").write_text(json.dumps({
        "family": FAMILY, "excluded": EXCLUDED, "pending_p1": {k: PENDING.get(k, "no result") for k in pending.index},
        "q": {k: float(v) for k, v in q.items()}}, indent=2))
    h["effect_pct"] = np.where(h.kind == "binary", pct(h.coef), np.where(h.kind == "continuous", pct(h.coef * h.sd_x), np.nan))
    h["effect_pct_lo"] = np.where(h.kind == "binary", pct(h.ci_lo), np.where(h.kind == "continuous", pct(h.ci_lo * h.sd_x), np.nan))
    h["effect_pct_hi"] = np.where(h.kind == "binary", pct(h.ci_hi), np.where(h.kind == "continuous", pct(h.ci_hi * h.sd_x), np.nan))
    h.to_csv(OUT_TABLES / "hypotheses.csv", index=False)
    # scarcity restriction for H5f: price ~ b1 log_pv + b2 log_cap with b1 = -b2
    d = s[s.post2015]
    r = fe_ols(d, "y", ["log_pv365", "log_cap_sold"], ["artist_key", "year"], CLUSTER)
    diff = r.coef.sum()
    se = float(np.sqrt(r.cov.to_numpy().sum()))
    from scipy import stats
    extras = {"H5f_unrestricted": {"b_log_pv365": float(r.coef["log_pv365"]), "se_log_pv365": float(r.se["log_pv365"]),
                                    "b_log_cap_sold": float(r.coef["log_cap_sold"]), "se_log_cap_sold": float(r.se["log_cap_sold"]),
                                    "b_sum": float(diff), "p_equal_opposite": float(2 * stats.t.sf(abs(diff / se), r.n_clusters - 1)),
                                    "n": r.n, "clusters": r.n_clusters},
              "H1a_metros": int(len(eff)), "coverage_venue_pct_sample": cov.get("venue", {}).get("pct_analysis_filled"),
              "preliminary": sorted(prelim),
              **tour_unit_and_split_counts(s)}
    (OUT_TABLES / "extras.json").write_text(json.dumps(extras, indent=2))
    chart_forest(h)
    chart_sensitivity(h)
    chart_metros(eff)
    return h


if __name__ == "__main__":
    if "--charts-only" in sys.argv:
        h = pd.read_csv(OUT_TABLES / "hypotheses.csv", keep_default_na=False, na_values=[""])
        for c in ["descriptive", "preliminary"]:
            if c in h:
                h[c] = h[c].astype(str).eq("True")
        chart_forest(h)
        chart_sensitivity(h)
        chart_metros(pd.read_csv(OUT_TABLES / "metro_effects.csv"))
        raise SystemExit
    pd.set_option("display.width", 250)
    h = main()
    cols = ["hid", "sens", "status", "coef", "ci_lo", "ci_hi", "p", "q", "effect_pct", "n", "clusters", "groups_with_variation"]
    print(h[cols].round(4).to_string())
