"""fe.fe_ols agrees with statsmodels OLS on explicit dummies."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.formula.api as smf

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from analysis.fe import bh, fe_ols  # noqa: E402


def _panel(seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    n = 1500
    cl = rng.integers(0, 40, n)
    tour = cl * 3 + rng.integers(0, 3, n)          # tours nested in clusters
    year = rng.integers(2000, 2010, n)              # crossed with tours
    x1 = rng.normal(size=n) + 0.3 * (tour % 5)
    x2 = (rng.random(n) < 0.4).astype(float)
    a = rng.normal(size=tour.max() + 1)
    y = 0.5 * x1 - 0.2 * x2 + a[tour] + 0.05 * (year - 2000) + rng.normal(size=n) + rng.normal(size=40)[cl]
    return pd.DataFrame(dict(y=y, x1=x1, x2=x2, tour=tour, year=year, cl=cl, w=rng.integers(1, 4, n)))


def test_matches_statsmodels_two_way():
    d = _panel()
    r = fe_ols(d, "y", ["x1", "x2"], ["tour", "year"], "cl")
    m = smf.ols("y ~ x1 + x2 + C(tour) + C(year)", d).fit(cov_type="cluster", cov_kwds={"groups": d.cl})
    assert np.allclose(r.coef[["x1", "x2"]], m.params[["x1", "x2"]], atol=1e-6)
    # statsmodels counts the FE dummies in K; we don't (FEs nested in clusters)
    n, k_all = len(d), m.df_model + 1
    adj = np.sqrt((n - k_all) / (n - 2))
    assert np.allclose(r.se[["x1", "x2"]] / adj, m.bse[["x1", "x2"]], rtol=0.01)


def test_weighted_matches_wls():
    d = _panel(1)
    r = fe_ols(d, "y", ["x1"], ["tour"], "cl", weights="w")
    m = smf.wls("y ~ x1 + C(tour)", d, weights=d.w).fit()
    assert np.isclose(r.coef["x1"], m.params["x1"], atol=1e-6)


def test_bh():
    q = bh(pd.Series([0.01, 0.04, 0.03, 0.5]))
    assert np.allclose(q.to_numpy(), [0.04, 0.0533333, 0.0533333, 0.5], atol=1e-6)


def test_wild_cluster_p_null_and_alt():
    from analysis.fe import wild_cluster_p
    d = _panel(2)
    rng = np.random.default_rng(5)
    d["noise"] = rng.normal(size=len(d))
    p_null = wild_cluster_p(d, "y", ["x1", "noise"], ["tour"], "cl", "noise", n_boot=999, seed=1)
    p_alt = wild_cluster_p(d, "y", ["x1", "noise"], ["tour"], "cl", "x1", n_boot=999, seed=1)
    p_analytic = fe_ols(d, "y", ["x1", "noise"], ["tour"], "cl").p("noise")
    assert abs(p_null - p_analytic) < 0.08  # G = 40: bootstrap and t(G-1) agree
    assert p_alt < 0.01


def test_two_way_cluster_matches_manual_cgm():
    d = _panel(3)
    d["cl2"] = d["year"]
    one = fe_ols(d, "y", ["x1"], ["tour"], "cl")
    two = fe_ols(d, "y", ["x1"], ["tour"], "cl", cluster2="cl2")
    alt = fe_ols(d, "y", ["x1"], ["tour"], "cl2")
    d["cl12"] = d["cl"].astype(str) + "_" + d["year"].astype(str)
    both = fe_ols(d, "y", ["x1"], ["tour"], "cl12")
    v = one.se["x1"] ** 2 + alt.se["x1"] ** 2 - both.se["x1"] ** 2
    assert np.isclose(two.se["x1"], np.sqrt(max(v, 0)), rtol=1e-6)
    assert two.n_clusters == min(one.n_clusters, alt.n_clusters)
