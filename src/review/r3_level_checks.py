"""Skeptic review 3 (task 7): judgment checks beyond autocheck.
(a) H1a with tour-unit FE and a within-tour permutation (tour shocks vs metro labels)
(b) H8b reunion: which artists, gap control, artist-specific linear trends
(c) F21: ListenBrainz-snapshot ablation on the VALID split only (test untouched)
"""
import json
import sys
import numpy as np
import pandas as pd
sys.path.insert(0, "src")
from analysis.fe import demean, drop_singletons, fe_ols
from analysis.level_data import load_sample, predictive_features

rng = np.random.default_rng(7)
s = load_sample()

# (a) ------------------------------------------------------------------------
def dispersion(d, fe, perm_group, n_perm=199):
    mk = d.groupby("metro_key").agg(n=("show_id", "size"), a=("artist_key", "nunique"))
    elig = mk[(mk.n >= 30) & (mk.a >= 5)].index
    d = d.assign(metro_e=d.metro_key.where(d.metro_key.isin(elig), "_other"))
    d = drop_singletons(d.dropna(subset=["y"] + fe), fe)
    X = pd.get_dummies(d.metro_e, dtype=float).drop(columns="_other")
    X = X.loc[:, X.sum() > 0]
    r = fe_ols(pd.concat([d, X], axis=1), "y", list(X.columns), fe, "split_key")
    b, se = r.coef.to_numpy(), r.se.to_numpy()
    sd = float(np.sqrt(max(np.var(b) - np.mean(se ** 2), 0)))
    yr = demean(d, ["y"], fe)["y"].to_numpy()
    codes = pd.factorize(d.metro_e)[0]
    other = codes[d.metro_e.to_numpy() == "_other"][0]
    def ss(c):
        sums, cnt = np.bincount(c, weights=yr), np.bincount(c)
        k = np.arange(len(cnt)) != other
        return float((sums[k] ** 2 / np.maximum(cnt[k], 1)).sum())
    stat = ss(codes)
    grp = pd.factorize(d[perm_group])[0]
    order = np.argsort(grp, kind="stable")
    blocks = np.split(order, np.flatnonzero(np.diff(grp[order])) + 1)
    perm = []
    for _ in range(n_perm):
        c = codes.copy()
        for blk in blocks:
            c[blk] = codes[rng.permutation(blk)]
        perm.append(ss(c))
    p = (1 + sum(v >= stat for v in perm)) / (n_perm + 1)
    return sd, p, len(X.columns), r.n, stat / np.mean(perm)

for lab, fe, pg in [("artist+year FE, perm within artist (as reported)", ["artist_key", "year"], "artist_key"),
                    ("artist+year FE, perm within tour_unit", ["artist_key", "year"], "tour_unit"),
                    ("tour_unit+year FE, perm within tour_unit", ["tour_unit", "year"], "tour_unit")]:
    sd, p, k, n, ratio = dispersion(s, fe, pg)
    print(f"H1a {lab}: SD {sd:.3f}, p {p:.3f}, metros {k}, n {n}, stat/perm-mean {ratio:.2f}")
us = s[s.us]
sd, p, k, n, ratio = dispersion(us, ["tour_unit", "year"], "tour_unit")
print(f"H1a US, tour_unit+year FE, perm within tour: SD {sd:.3f}, p {p:.3f}, metros {k}")

# (b) ------------------------------------------------------------------------
s["reunion"] = s.reunion_flag.astype(float)
var = s.groupby("artist_key").reunion.transform("nunique") > 1
r_art = s[var].groupby("artist_key").agg(name=("artist_name", "first"), n=("show_id", "size"),
                                         reunion_years=("year", lambda x: sorted(set(x[s.loc[x.index, "reunion"] == 1]))[:1]),
                                         other_years=("year", lambda x: (int(x[s.loc[x.index, "reunion"] == 0].min()), int(x[s.loc[x.index, "reunion"] == 0].max()))))
print("\nH8b artists with variation:\n", r_art.to_string())
base = fe_ols(s, "y", ["reunion"], ["artist_key", "year"], "split_key")
print("H8b base b=%.3f se=%.3f n=%d" % (base.coef["reunion"], base.se["reunion"], base.n))
s["log_gap"] = np.log1p(s.days_since_prev_show_artist.astype(float))
g = fe_ols(s, "y", ["reunion", "log_gap"], ["artist_key", "year"], "split_key")
print("H8b + log gap since previous show: b=%.3f se=%.3f (gap b=%.3f) n=%d" % (g.coef["reunion"], g.se["reunion"], g.coef["log_gap"], g.n))
# artist-specific linear trends (centred year x artist dummies) for the artists with variation and >= 3 tour units
s["t"] = s.year - s.groupby("artist_key").year.transform("mean")
tu = s.groupby("artist_key").tour_unit.nunique()
trend_art = [a for a in s.loc[var, "artist_key"].unique() if tu[a] >= 3]
tr_cols = []
for a in s.artist_key.unique():
    if tu[a] >= 3:
        c = f"tr_{len(tr_cols)}"
        s[c] = np.where(s.artist_key == a, s.t, 0.0)
        tr_cols.append(c)
t = fe_ols(s, "y", ["reunion"] + tr_cols, ["artist_key", "year"], "split_key")
print("H8b + artist-specific linear trends (all artists with >=3 tour units, %d trends): b=%.3f se=%.3f; reunion artists with a trend: %d of %d"
      % (len(tr_cols), t.coef["reunion"], t.se["reunion"], len(trend_art), int(var.groupby(s.artist_key).any().sum())))
s.drop(columns=tr_cols, inplace=True)
# placebo: the artist's LAST non-reunion tour unit (late-career) for non-reunion artists
last = s.groupby("artist_key").tour_unit.transform(lambda x: x == x.iloc[np.argmax(s.loc[x.index, "show_date"].values)])
s["last_tour"] = last.astype(float)
pl = fe_ols(s[s.reunion == 0], "y", ["last_tour"], ["artist_key", "year"], "split_key")
print("placebo: artist's last tour unit vs its other tours (non-reunion rows): b=%.3f se=%.3f" % (pl.coef["last_tour"], pl.se["last_tour"]))

# (c) ------------------------------------------------------------------------
from sklearn.ensemble import HistGradientBoostingRegressor
src = open("src/analysis/level_model.py").read()
from analysis import level_model as lm
num, cat = predictive_features(s)
best = json.load(open("reports/level_tables/test_touch_log.jsonl".replace(".jsonl", ".jsonl"))) if False else None
log = [json.loads(x) for x in open("reports/level_tables/test_touch_log.jsonl") if x.strip()]
params = log[-1]["params"]["y"]
tr, va = s[s.artist_split == "train"], s[s.artist_split == "valid"]
for lab, drop in [("all features", []), ("without ListenBrainz", ["log_lb_listens", "log_lb_users"]),
                  ("without LB and career vars", ["log_lb_listens", "log_lb_users", "years_active_at_show", "career_start_year",
                                                 "n_tours_started_before_show_year"])]:
    n2 = [c for c in num if c not in drop]
    enc = lm.Encoder(n2, cat).fit(tr)
    m = HistGradientBoostingRegressor(random_state=lm.SEED, early_stopping=False, **params).fit(enc.transform(tr), tr.y)
    e = np.abs(m.predict(enc.transform(va)) - va.y)
    print(f"F21 valid MAE {lab}: {e.mean():.3f}")
