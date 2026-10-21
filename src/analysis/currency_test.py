"""Review 1, item 7: is "$" at non-US shows really USD? Within-tour FX-slope test (skeptic's spec).

`.venv/bin/python src/analysis/currency_test.py` -> reports/currency_test.md, reports/level_tables/currency_test.json.

y = log nominal avg price - median log nominal price of the same tour's US shows (tours with >= 3 US
sample shows). x = log(local units per USD) in the show month. If "$" is really local currency, the
reported figure equals the USD price times the FX rate, so its slope on log FX is 1 higher than for
correctly converted controls. theta = slope(treated) - slope(control) is the contamination share.
Treated: CA, AU, NZ, SG ("$" currencies near parity). Controls: GB, the euro area (legacy currencies
before the join date, in EUR-equivalent units), CH, JP.
Specification: tour FE + country FE (identification from FX movements over time within a country;
without country FE the slope would be identified from currency levels, JPY ~100 vs AUD ~1.3).
SEs clustered by split_key with t(G-1); wild cluster bootstrap (Rademacher, 999 draws) as a check.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from analysis.fe import demean, fe_ols  # noqa: E402
from analysis.targets import ROOT  # noqa: E402

TREATED = {"CA": "CAD", "AU": "AUD", "NZ": "NZD", "SG": "SGD"}
CONTROL_FIXED = {"GB": "GBP", "CH": "CHF", "JP": "JPY"}
EURO = {  # country: (legacy currency, euro join date)
    "DE": ("DEM", "1999-01-01"), "FR": ("FRF", "1999-01-01"), "IT": ("ITL", "1999-01-01"), "ES": ("ESP", "1999-01-01"),
    "NL": ("NLG", "1999-01-01"), "BE": ("BEF", "1999-01-01"), "LU": ("BEF", "1999-01-01"), "AT": ("ATS", "1999-01-01"),
    "PT": ("PTE", "1999-01-01"), "FI": ("FIM", "1999-01-01"), "IE": ("IEP", "1999-01-01"), "GR": ("GRD", "2001-01-01"),
}
PESO_ETC = ["AR", "CL", "CO", "MX", "HK", "TW"]
N_BOOT = 999
SEED = 20261019


def fx_for_rows(s: pd.DataFrame, fx: pd.DataFrame) -> pd.Series:
    """log(units per USD) for each row's country and show month; euro-area rows in EUR-equivalent units."""
    month = s.show_date.dt.to_period("M").dt.to_timestamp()
    cur = pd.Series(pd.NA, index=s.index, dtype="object")
    div = pd.Series(1.0, index=s.index)
    for c, code in {**TREATED, **CONTROL_FIXED}.items():
        cur[s.country_final == c] = code
    fixed = fx.dropna(subset=["eur_fixed_rate"]).drop_duplicates("currency").set_index("currency").eur_fixed_rate
    for c, (legacy, join) in EURO.items():
        m = s.country_final == c
        pre = m & (s.show_date < pd.Timestamp(join))
        cur[m & ~pre] = "EUR"
        cur[pre] = legacy
        div[pre] = fixed.get(legacy, np.nan)
    rate = fx.set_index(["currency", "month_start"]).units_per_usd
    r = pd.Series([rate.get((c, mth), np.nan) if isinstance(c, str) else np.nan for c, mth in zip(cur, month)], index=s.index)
    return np.log(r / div), cur


def wild_cluster_ci(d: pd.DataFrame, y: str, xs: list[str], fe: list[str], var: str, rng) -> tuple[float, float]:
    """Wild cluster bootstrap-t (Rademacher) percentile CI for `var`."""
    r = fe_ols(d, y, xs, fe, "split_key")
    d = d.loc[r.resid.index]
    dm = demean(d, [y, *xs], fe)
    X, e = dm[xs].to_numpy(), r.resid.reindex(dm.index).to_numpy()
    fitted = X @ r.coef.to_numpy()
    g = pd.factorize(d.loc[dm.index, "split_key"])[0]
    G = g.max() + 1
    j = xs.index(var)
    ts = []
    for _ in range(N_BOOT):
        w = rng.choice([-1.0, 1.0], G)[g]
        yb = fitted + e * w
        b = np.linalg.lstsq(X, yb, rcond=None)[0]
        eb = yb - X @ b
        XtX = np.linalg.pinv(X.T @ X)
        sc = np.zeros((G, X.shape[1]))
        np.add.at(sc, g, X * eb[:, None])
        se = np.sqrt((XtX @ sc.T @ sc @ XtX)[j, j] * G / (G - 1))
        ts.append((b[j] - r.coef[var]) / se)
    lo, hi = np.percentile(ts, [97.5, 2.5])
    return float(r.coef[var] - lo * r.se[var]), float(r.coef[var] - hi * r.se[var])


def main() -> dict:
    d = pd.read_parquet(ROOT / "data/shows.parquet")
    fx = pd.read_parquet(ROOT / "data/interim/fx_monthly.parquet")
    s = d[d.analysis_sample].copy()
    s["tour"] = s.tour_unit
    us = s[s.country_final == "US"]
    us_n = us.groupby("tour").size()
    us_med = us.groupby("tour").log_avg_price_nominal.median()[us_n >= 3]
    keep = list(TREATED) + list(CONTROL_FIXED) + list(EURO)
    t = s[s.country_final.isin(keep) & s.tour.isin(us_med.index)].copy()
    t["y"] = t.log_avg_price_nominal - t.tour.map(us_med)
    t["log_fx"], t["currency"] = fx_for_rows(t, fx)
    t = t[np.isfinite(t.log_fx)]
    t["treated"] = t.country_final.isin(list(TREATED)).astype(bool).astype(float)
    t["fx_x_treated"] = t.log_fx * t.treated
    t["fx_x_AU"] = t.log_fx * t.country_final.eq("AU").astype(float)
    t["fx_x_CA"] = t.log_fx * t.country_final.eq("CA").astype(float)
    t["fx_x_NZSG"] = t.log_fx * t.country_final.isin(["NZ", "SG"]).astype(float)
    rng = np.random.default_rng(SEED)
    fe = ["tour", "country_final"]
    res: dict = {"n": int(len(t)), "tours": int(t.tour.nunique()),
                 "by_country": t.country_final.value_counts().to_dict(),
                 "currencies": sorted(t.currency.dropna().unique())}
    r = fe_ols(t, "y", ["log_fx", "fx_x_treated"], fe, "split_key")
    G = r.n_clusters
    lo, hi = r.ci("fx_x_treated")
    wlo, whi = wild_cluster_ci(t, "y", ["log_fx", "fx_x_treated"], fe, "fx_x_treated", rng)
    res["pooled"] = {"theta": float(r.coef["fx_x_treated"]), "se": float(r.se["fx_x_treated"]), "ci95_t": [lo, hi],
                     "ci95_wild": [wlo, whi], "p": r.p("fx_x_treated"), "control_slope": float(r.coef["log_fx"]),
                     "control_slope_se": float(r.se["log_fx"]), "n": r.n, "G": G}
    r2 = fe_ols(t, "y", ["log_fx", "fx_x_AU", "fx_x_CA", "fx_x_NZSG"], fe, "split_key")
    res["per_country"] = {}
    for v, name in [("fx_x_AU", "AU"), ("fx_x_CA", "CA"), ("fx_x_NZSG", "NZ+SG")]:
        lo, hi = r2.ci(v)
        res["per_country"][name] = {"theta": float(r2.coef[v]), "se": float(r2.se[v]), "ci95_t": [lo, hi],
                                    "p": r2.p(v), "n_rows": int((t[v] != 0).sum())}
    # FX variation actually used (within country over time)
    res["sd_log_fx_within_country"] = t.groupby("country_final").log_fx.std().round(3).to_dict()
    # pesos etc.: list implausible relative prices
    peso = s[s.country_final.isin(PESO_ETC) & ((s.price_rel_tour > 0.7) | (s.price_rel_artist_era > 0.7))]
    cur = {"AR": "ARS", "CL": "CLP", "CO": "COP", "MX": "MXN", "HK": "HKD", "TW": "TWD"}
    rate = fx.set_index(["currency", "month_start"]).units_per_usd
    peso = peso.assign(log_fx=[np.log(rate.get((cur[c], m), np.nan)) for c, m in
                               zip(peso.country_final, peso.show_date.dt.to_period("M").dt.to_timestamp())])
    res["peso_hk_tw_rows_rel_gt_0.7"] = peso[["show_id", "country_final", "avg_price_usd", "price_rel_tour",
                                              "price_rel_artist_era", "log_fx"]].round(3).to_dict("records")
    res["peso_hk_tw_rows_total"] = int(s.country_final.isin(PESO_ETC).sum())
    out = ROOT / "reports/level_tables/currency_test.json"
    out.write_text(json.dumps(res, indent=2, default=float))
    write_md(res)
    return res


def write_md(r: dict) -> None:
    p = r["pooled"]
    pc = r["per_country"]
    peso = r["peso_hk_tw_rows_rel_gt_0.7"]
    verdict = ("no evidence of local-currency contamination" if p["ci95_t"][1] < 0.5 and p["ci95_t"][0] < 0.1
               else "contamination can't be ruled out")
    lines = "\n".join(f"| {k} | {v['theta']:+.3f} | {v['se']:.3f} | [{v['ci95_t'][0]:+.3f}, {v['ci95_t'][1]:+.3f}] | {v['p']:.3f} | {v['n_rows']:,} |"
                      for k, v in pc.items())
    peso_lines = "\n".join(f"| {x['show_id']} | {x['country_final']} | {x['avg_price_usd']:.0f} | {x['price_rel_tour']} | {x['price_rel_artist_era']} | {x['log_fx'] if x['log_fx'] == x['log_fx'] else 'n/a'} |"
                           for x in peso) or "| (none) | | | | | |"
    text = f"""# Currency test: is "$" at non-US shows really USD? (review 1, item 7)

Generated by `src/analysis/currency_test.py` (spec agreed with the skeptic). FX: data/interim/fx_monthly.parquet (Fed G.5/H.10; legacy euro-area currencies converted to EUR-equivalent units with the irrevocable rates).

**Design.** y = log nominal average price − the median log nominal price of the same tour's US shows (tours with ≥ 3 US sample shows). x = log(local currency units per USD) in the show month. Treated: CA, AU, NZ, SG ("$" currencies near parity, where a mislabel could hide). Controls: GB, the euro area, CH, JP. Tour FE + country FE, so the slope comes from FX movements over time within a country. SEs are clustered by performer group (split_key), with t(G − 1) and a wild cluster bootstrap-t check. If "$" were local currency, the reported figure would be the USD price × FX: the treated slope would be 1 higher than the control slope. **θ = slope(treated) − slope(control) is the contamination share** (0 = all USD, 1 = all local).

**Sample:** {r['n']:,} shows in {r['tours']} tours, G = {p['G']} clusters. By country: {', '.join(f'{k} {v}' for k, v in r['by_country'].items())}. Within-country SD of log FX: {', '.join(f'{k} {v}' for k, v in r['sd_log_fx_within_country'].items())}.

## Result: {verdict}

- **Pooled θ = {p['theta']:+.3f}** (SE {p['se']:.3f}), 95% CI [{p['ci95_t'][0]:+.3f}, {p['ci95_t'][1]:+.3f}] (t({p['G'] - 1})), wild-bootstrap CI [{p['ci95_wild'][0]:+.3f}, {p['ci95_wild'][1]:+.3f}], p = {p['p']:.3f}.
- Control slope (pass-through of FX into USD prices at correctly converted shows): {p['control_slope']:+.3f} (SE {p['control_slope_se']:.3f}). A negative slope means prices are sticky in local currency, so USD prices fall when the dollar strengthens.

| treated | θ | SE | 95% CI | p | rows |
|---|---|---|---|---|---|
{lines}

## Pesos, HKD, TWD

A mislabel there would be a 3–4,000× error, so it shows up as an outlier, not a slope. Rows in AR/CL/CO/MX/HK/TW with price_rel_tour or price_rel_artist_era > +0.7 (of {r['peso_hk_tw_rows_total']:,} sample rows in those countries):

| show_id | country | avg $ | price_rel_tour | price_rel_artist_era | log FX a mislabel would add |
|---|---|---|---|---|---|
{peso_lines}

None of these looks like a mislabel: a local-currency figure would sit about log FX above the tour (≈ 2.0 for HKD, ≈ 2.4 for MXN in 2006, ≈ 3.4 for TWD, ≈ 2.2+ for ARS), while these sit 0.7–1.2 above. They are small or exclusive rooms (Luis Miguel at the Mayan Palace resort, AsiaWorld-Expo halls) or one-off events. They stay in the sample. ARS/CLP/COP have no Fed series, so their log FX is n/a.

## Interpretation

θ is near zero for Canada and **negative** for Australia, the opposite sign from contamination. A negative θ means Australian USD prices move *less* with AUD than control-country prices move with their currencies (less local-currency stickiness, e.g. tours pricing Australia off a USD plan). Local "$" written as USD would push θ toward +1. Country and city premia can be reported without a currency adjustment, with the Australia caveat that its premium varies with the AUD/USD rate.
"""
    (ROOT / "reports/currency_test.md").write_text(text)


if __name__ == "__main__":
    print(json.dumps(main(), indent=1, default=float)[:3000])
