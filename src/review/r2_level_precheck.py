"""Skeptic pre-review of the task-7 LEVEL pipeline: quantify suspected issues."""
import sys
import numpy as np
import pandas as pd
sys.path.insert(0, "src")
from analysis.fe import fe_ols
from analysis.level_data import load_sample

s = load_sample()
# 1. effective clusters vs reported clusters
for x, fe in [("later_leg", "tour"), ("multi_night", "tour"), ("is_fri_sat", "tour"), ("log_metro_income", "artist_key")]:
    t = s[s[x].notna()]
    var = t.groupby(fe)[x].transform("nunique") > 1
    print(f"{x}: clusters total {t.split_key.nunique()}, clusters with within-{fe} variation {t[var].split_key.nunique()}")
# 2. long 'tours' (list articles / residencies) contribution to tour-FE specs
span = s.groupby("tour").show_date.agg(lambda d: (d.max() - d.min()).days / 365.25)
long = span[span > 3].index
for x in ["later_leg", "multi_night"]:
    t = s[s[x].notna()]
    var = t.groupby("tour")[x].transform("nunique") > 1
    print(f"{x}: rows in varying tours {int(var.sum())}, of which in >3y 'tours' {int((var & t.tour.isin(long)).sum())}")
# 3. weekend: does adding a metro-size control or year FE move it?
u = s[s.single]
for xs, fe in [(["is_fri_sat", "is_sunday"], ["tour"]), (["is_fri_sat", "is_sunday", "log_metro_pop"], ["tour"]),
               (["is_fri_sat", "is_sunday"], ["tour", "year"])]:
    r = fe_ols(u.assign(year=u.year), "y", xs, fe, "split_key")
    print("H2a", xs, fe, "b=%.4f se=%.4f n=%d" % (r.coef["is_fri_sat"], r.se["is_fri_sat"], r.n))
# 4. H1b: cluster by split_key vs by metro vs two-way (CGM: V_a + V_b - V_ab)
us = s[s.us].copy()
us["metro"] = us.cbsa_code.fillna(us.metro_key)
us["inter"] = us.split_key.astype(str) + "|" + us.metro.astype(str)
res = {c: fe_ols(us, "y", ["log_metro_income", "log_metro_pop"], ["artist_key", "year"], c) for c in ["split_key", "metro", "inter"]}
v2 = res["split_key"].se ** 2 + res["metro"].se ** 2 - res["inter"].se ** 2
print("H1b income: b=%.4f se(split_key)=%.4f se(metro)=%.4f se(two-way)=%.4f | G_metro=%d" % (
    res["split_key"].coef["log_metro_income"], res["split_key"].se["log_metro_income"], res["metro"].se["log_metro_income"],
    float(np.sqrt(max(v2["log_metro_income"], 0))), res["metro"].n_clusters))
print("H1c pop:    se(split_key)=%.4f se(metro)=%.4f se(two-way)=%.4f" % (
    res["split_key"].se["log_metro_pop"], res["metro"].se["log_metro_pop"], float(np.sqrt(max(v2["log_metro_pop"], 0)))))
# 5. null-country rows in the 'excl. $ outside US' sensitivity
print("usd_ok rows with null country_iso2:", int((s.usd_ok & s.country_iso2.isna()).sum()))
