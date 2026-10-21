"""Linear fixed-effects regression with cluster-robust SEs (no extra dependencies).

Fixed effects are absorbed by alternating projections (weighted demeaning by each
FE until convergence), then OLS/WLS on the demeaned data with a CR1 cluster-robust
covariance. Clusters should nest the FEs (here: split_key nests artist and tour),
so no degrees-of-freedom correction for absorbed FEs is needed.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from scipy import stats


@dataclass
class FEResult:
    coef: pd.Series
    se: pd.Series
    cov: pd.DataFrame
    n: int
    n_clusters: int
    fe: list[str]
    dropped_singletons: int = 0
    r2_within: float = np.nan
    resid: pd.Series = field(default=None, repr=False)
    df_clusters: int | None = None  # clusters used for the t df (default n_clusters); see set_effective_clusters

    @property
    def tdf(self) -> int:
        return max((self.df_clusters or self.n_clusters) - 1, 1)

    def ci(self, var: str, level: float = 0.95) -> tuple[float, float]:
        z = stats.t.ppf(0.5 + level / 2, self.tdf)
        return self.coef[var] - z * self.se[var], self.coef[var] + z * self.se[var]

    def p(self, var: str) -> float:
        return float(2 * stats.t.sf(abs(self.coef[var] / self.se[var]), self.tdf))

    def wald(self, vars_: list[str]) -> tuple[float, float]:
        """Cluster-robust Wald F test that all `vars_` are zero (F, p)."""
        b = self.coef[vars_].to_numpy()
        V = self.cov.loc[vars_, vars_].to_numpy()
        q = len(vars_)
        f = float(b @ np.linalg.pinv(V) @ b) / q
        return f, float(stats.f.sf(f, q, self.tdf))


def demean(df: pd.DataFrame, cols: list[str], fe: list[str], w: pd.Series | None = None,
           tol: float = 1e-10, max_iter: int = 500) -> pd.DataFrame:
    """Absorb categorical FEs from `cols` by alternating (weighted) projections."""
    x = df[cols].astype(float).copy()
    if not fe:
        return x
    wv = np.ones(len(df)) if w is None else w.astype(float).to_numpy()
    codes = [pd.factorize(df[f])[0] for f in fe]
    ws = [np.bincount(c, weights=wv) for c in codes]
    a = x.to_numpy().copy()
    for _ in range(max_iter):
        delta = 0.0
        for c, wsum in zip(codes, ws):
            # group means via bincount per column (np.add.at was ~half the hypotheses runtime)
            means = np.column_stack([np.bincount(c, weights=a[:, j] * wv, minlength=len(wsum))
                                     for j in range(a.shape[1])]) / wsum[:, None]
            adj = means[c]
            delta = max(delta, float(np.abs(adj).max()))
            a -= adj
        if delta < tol:
            break
    x.loc[:, :] = a
    return x


def drop_singletons(df: pd.DataFrame, fe: list[str]) -> pd.DataFrame:
    """Iteratively drop observations that are alone in some FE group (they carry no within info)."""
    out = df
    while True:
        keep = pd.Series(True, index=out.index)
        for f in fe:
            keep &= out.groupby(f)[f].transform("size") > 1
        if keep.all():
            return out
        out = out[keep]


def _cr1(X: np.ndarray, u: np.ndarray, groups: np.ndarray, XtX_inv: np.ndarray) -> tuple[np.ndarray, int]:
    """CR1 sandwich for one clustering; u = weighted residual score multiplier."""
    g = pd.factorize(groups)[0]
    G = g.max() + 1
    scores = np.zeros((G, X.shape[1]))
    np.add.at(scores, g, X * u[:, None])
    n, k = X.shape
    c = G / (G - 1) * (n - 1) / max(n - k, 1)
    return c * XtX_inv @ (scores.T @ scores) @ XtX_inv, int(G)


def fe_ols(df: pd.DataFrame, y: str, x: list[str], fe: list[str], cluster: str,
           weights: str | None = None, cluster2: str | None = None) -> FEResult:
    """FE regression; SEs clustered by `cluster`, or two-way by `cluster` x `cluster2`
    (Cameron, Gelbach & Miller 2011: V_a + V_b - V_ab, eigenvalues floored at 0). With two-way
    clustering, n_clusters is the smaller of the two cluster counts."""
    cols = [y, *x]
    need = list(dict.fromkeys(cols + fe + [cluster] + ([cluster2] if cluster2 else []) + ([weights] if weights else [])))
    d = df[need].dropna()
    d = d[np.isfinite(d[cols].astype(float)).all(axis=1)]
    n0 = len(d)
    d = drop_singletons(d, fe)
    w = d[weights].astype(float) if weights else None
    dm = demean(d, cols, fe, w)
    Y = dm[y].to_numpy()
    X = dm[x].to_numpy()
    wv = np.ones(len(d)) if w is None else w.to_numpy()
    sw = np.sqrt(wv)
    Xw, Yw = X * sw[:, None], Y * sw
    XtX_inv = np.linalg.pinv(Xw.T @ Xw)
    b = XtX_inv @ Xw.T @ Yw
    e = Y - X @ b
    u = wv * e
    V, G = _cr1(X, u, d[cluster].to_numpy(), XtX_inv)
    if cluster2:
        V2, G2 = _cr1(X, u, d[cluster2].to_numpy(), XtX_inv)
        inter = d[cluster].astype(str).to_numpy() + "||" + d[cluster2].astype(str).to_numpy()
        V12, _ = _cr1(X, u, inter, XtX_inv)
        V = V + V2 - V12
        ev, evec = np.linalg.eigh(V)
        V = evec @ np.diag(np.clip(ev, 0, None)) @ evec.T
        G = min(G, G2)
    se = np.sqrt(np.clip(np.diag(V), 0, None))
    r2w = 1 - float((wv * e**2).sum() / (wv * Y**2).sum()) if (wv * Y**2).sum() > 0 else np.nan
    return FEResult(
        coef=pd.Series(b, index=x), se=pd.Series(se, index=x), cov=pd.DataFrame(V, index=x, columns=x),
        n=len(d), n_clusters=int(G), fe=fe, dropped_singletons=n0 - len(d), r2_within=r2w,
        resid=pd.Series(e, index=d.index),
    )


def effective_clusters(df: pd.DataFrame, x: str, group: str, cluster: str) -> int:
    """Clusters containing at least one FE group in which `x` varies (they identify the slope)."""
    d = df[list(dict.fromkeys([x, group, cluster]))].dropna()
    varying = d.groupby(group)[x].transform("nunique") > 1
    return int(d.loc[varying, cluster].nunique())


def bh(p: pd.Series) -> pd.Series:
    """Benjamini-Hochberg q-values."""
    p = p.astype(float)
    ok = p.notna()
    v = p[ok].sort_values()
    m = len(v)
    q = (v * m / np.arange(1, m + 1))[::-1].cummin()[::-1].clip(upper=1)
    return q.reindex(p.index)


WEBB = np.array([-np.sqrt(1.5), -1.0, -np.sqrt(0.5), np.sqrt(0.5), 1.0, np.sqrt(1.5)])


def wild_cluster_p(df: pd.DataFrame, y: str, x: list[str], fe: list[str], cluster: str, var: str,
                   weights: str | None = None, n_boot: int = 1999, seed: int = 0) -> float:
    """Null-imposed wild cluster bootstrap (WCR, Webb 6-point weights) p-value for `var` = 0.

    Use when few clusters carry the variation (Cameron, Gelbach & Miller 2008; Webb 2023).
    """
    full = fe_ols(df, y, x, fe, cluster, weights)
    d = df.loc[full.resid.index]
    t_obs = full.coef[var] / full.se[var]
    others = [c for c in x if c != var]
    w = d[weights].astype(float).to_numpy() if weights else np.ones(len(d))
    dm = demean(d, [y, *x], fe, d[weights] if weights else None)
    X = dm[x].to_numpy()
    Xr = dm[others].to_numpy() if others else np.zeros((len(d), 0))
    Y = dm[y].to_numpy()
    sw = np.sqrt(w)
    if others:
        br = np.linalg.lstsq(Xr * sw[:, None], Y * sw, rcond=None)[0]
        fit_r = Xr @ br
    else:
        fit_r = np.zeros(len(d))
    e_r = Y - fit_r
    g = pd.factorize(d[cluster])[0]
    G = g.max() + 1
    j = x.index(var)
    Xw = X * sw[:, None]
    XtX_inv = np.linalg.pinv(Xw.T @ Xw)
    n, k = X.shape
    c = G / (G - 1) * (n - 1) / max(n - k, 1)
    rng = np.random.default_rng(seed)
    exceed = 0
    for _ in range(n_boot):
        ystar = fit_r + e_r * rng.choice(WEBB, G)[g]
        b = XtX_inv @ Xw.T @ (ystar * sw)
        e = ystar - X @ b
        xe = X * (w * e)[:, None]
        sc = np.column_stack([np.bincount(g, weights=xe[:, i], minlength=G) for i in range(k)])
        se = np.sqrt(c * (XtX_inv @ sc.T @ sc @ XtX_inv)[j, j])
        exceed += abs(b[j] / se) >= abs(t_obs)
    return float((1 + exceed) / (n_boot + 1))
