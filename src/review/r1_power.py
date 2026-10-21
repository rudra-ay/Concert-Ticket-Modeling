"""Skeptic review 1: recompute clustered MDEs (a) as in data_quality.py, (b) with year FE added
(two-way demeaning by group and year via alternating projections), (c) with t(G-1) critical values."""
import sys
import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy import stats

sys.path.insert(0, "src")
d = pd.read_parquet("data/shows.parquet")
s = d[d.analysis_sample].copy()
s["tour"] = s.artist_id + "|" + s.tour_title.fillna("")
s["artist"] = s.artist_id
s["yr"] = s.show_date.dt.year


def demean(v, gs, it=50):
    v = v.astype(float).copy()
    for _ in range(it):
        for g in gs:
            v = v - v.groupby(g).transform("mean")
    return v


def mde(t, x, group, year):
    gs = [t[group]] + ([t.yr] if year else [])
    yw = demean(t.log_avg_price_real, gs)
    xw = demean(t[x].astype(float), gs)
    xw = xw / xw.std()  # per 1 SD of residual x (binary: rescaled back below)
    G = t.split_key.nunique()
    r = sm.OLS(yw.to_numpy(), xw.to_numpy()).fit(cov_type="cluster", cov_kwds={"groups": pd.factorize(t.split_key)[0]})
    return r.bse[0], G, xw


def run(name, x, group, mask=None, binary=False):
    t = s if mask is None else s[mask]
    t = t[t[x].notna() & np.isfinite(t[x].astype(float))]
    var = t.groupby(group)[x].transform(lambda v: v.nunique() > 1).astype(bool)
    t = t[var]
    out = {"hypothesis": name, "n": len(t)}
    for yr in [False, True]:
        se, G, xw = mde(t, x, group, yr)
        if binary:  # convert back to a 0->1 contrast: coefficient per unit of x = per-SD / sd(resid x)
            sdx = demean(t[x].astype(float), [t[group]] + ([t.yr] if yr else [])).std()
            se = se / sdx
        k = "yrFE" if yr else "noYr"
        out[f"MDE_{k}_z"] = round(2.8 * se, 3)
        out[f"MDE_{k}_t(G-1)"] = round((stats.t.ppf(.975, G - 1) + stats.t.ppf(.8, G - 1)) * se, 3)
        out["G"] = G
    return out


s["log_cap"] = np.log(s.tickets_available_per_show.where(s.tickets_available_per_show > 0))
s["lpv"] = np.log1p(s.pv_mean_365d)
s["later_leg"] = (s.leg_number > 1).astype(float)
s["multi_night"] = (s.aggregate_n_shows > 1).astype(float)
s["fs"] = s.is_fri_sat.astype(float)
s["fw"] = s.farewell_flag.astype(float)
s["co"] = s.co_headliner_flag.astype(float)
rows = [
    run("Venue size (artist FE)", "log_cap", "artist"),
    run("Popularity level (artist FE)", "lpv", "artist"),
    run("Momentum (artist FE)", "pv_momentum", "artist"),
    run("City income (artist FE, US)", "metro_median_hh_income", "artist", mask=s.is_us.fillna(False).astype(bool)),
    run("Weekend (tour FE, single)", "fs", "tour", mask=s.aggregate_n_shows.eq(1), binary=True),
    run("Tour leg (tour FE)", "later_leg", "tour", binary=True),
    run("Multi-night (tour FE)", "multi_night", "tour", binary=True),
    run("Farewell (artist FE)", "fw", "artist", binary=True),
    run("Co-headline (split_key FE)", "co", "split_key", binary=True),
]
pd.set_option("display.width", 250)
print(pd.DataFrame(rows).to_string(index=False))
