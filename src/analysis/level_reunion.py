"""H8b reunion: robustness checks requested in review 3 (E3). Train/valid/test split not involved.

`.venv/bin/python src/analysis/level_reunion.py` -> reports/level_tables/reunion_artists.csv,
reports/level_tables/reunion_checks.csv.

Base spec as in level_hypotheses (artist_key + year FE, clustered by split_key), plus:
- gap control: years since the artist's previous show (log1p), so "long-gap return" is held fixed
- artist-specific linear trends: artist_key x (year - artist's mean year) for every artist with
  >= 2 distinct years, so a reunion can't stand in for an artist's own price trajectory
- last-tour placebo: among artists without a reunion tour, flag each artist's last tour unit as a
  fake "reunion"; a real reunion effect should not appear for an arbitrary late tour
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from analysis.fe import fe_ols, wild_cluster_p  # noqa: E402
from analysis.level_data import OUT_TABLES, load_sample  # noqa: E402

SEED = 20261019


def row(name: str, r, var: str, p_wild: float = np.nan) -> dict:
    lo, hi = r.ci(var)
    return {"spec": name, "coef": float(r.coef[var]), "se": float(r.se[var]), "ci_lo": float(lo), "ci_hi": float(hi),
            "pct": 100 * (np.exp(r.coef[var]) - 1), "p": r.p(var), "p_wild": p_wild, "n": r.n}


def main() -> tuple[pd.DataFrame, pd.DataFrame]:
    s = load_sample()
    s = s[s.reunion_flag.notna()].copy()
    fe = ["artist_key", "year"]
    varying = s.groupby("artist_key").reunion_flag.transform("nunique") > 1
    # who carries the contrast
    a = s[varying].groupby(["artist_key", "reunion_flag"]).agg(
        artist=("artist_name", "first"), n=("y", "size"), first_year=("year", "min"), last_year=("year", "max")).reset_index()
    art = (a.pivot(index="artist_key", columns="reunion_flag", values=["artist", "n", "first_year", "last_year"]))
    artists = pd.DataFrame({
        "artist": art[("artist", 1.0)],
        "reunion_shows": art[("n", 1.0)].astype(int), "reunion_years": art[("first_year", 1.0)].astype(int).astype(str) + "–" + art[("last_year", 1.0)].astype(int).astype(str),
        "comparison_shows": art[("n", 0.0)].astype(int), "comparison_years": art[("first_year", 0.0)].astype(int).astype(str) + "–" + art[("last_year", 0.0)].astype(int).astype(str),
    }).reset_index()
    artists["comparison_only_after"] = art[("first_year", 0.0)].to_numpy() > art[("last_year", 1.0)].to_numpy()
    artists.to_csv(OUT_TABLES / "reunion_artists.csv", index=False)

    rows = []
    r = fe_ols(s, "y", ["reunion_flag"], fe, "split_key")
    r.df_clusters = int(s.loc[varying, "split_key"].nunique())
    rows.append(row("base (artist + year FE)", r, "reunion_flag"))
    # gap control
    s["log_gap"] = np.log1p(s.days_since_prev_show_artist.astype(float) / 365.25)
    rg = fe_ols(s, "y", ["reunion_flag", "log_gap"], fe, "split_key")
    rg.df_clusters = r.df_clusters
    rows.append(row("+ gap since the artist's previous show (log years)", rg, "reunion_flag",
                    wild_cluster_p(s, "y", ["reunion_flag", "log_gap"], fe, "split_key", "reunion_flag", seed=SEED)))
    # artist-specific linear trends. Primary: artists with >= 3 tour units, where a linear trend is
    # identified separately from a two-period reunion contrast. Variant: every artist with >= 2
    # distinct years; for two-period artists (Spice Girls, 2NE1) the trend is nearly collinear with
    # the reunion flag and absorbs the contrast being tested, so it is disclosed, not primary.
    yc = s.year - s.groupby("artist_key").year.transform("mean")
    n_units = s.groupby("artist_key").tour_unit.transform("nunique")
    n_years = s.groupby("artist_key").year.transform("nunique")
    for label, keep in [("artists with >= 3 tour units", n_units >= 3), ("variant: artists with >= 2 distinct years", n_years > 1)]:
        cols = {}
        for k, idx in s[keep].groupby("artist_key").groups.items():
            col = pd.Series(0.0, index=s.index)
            col[idx] = yc[idx]
            cols[f"tr_{len(cols)}"] = col
        st = pd.concat([s, pd.DataFrame(cols)], axis=1)
        rt = fe_ols(st, "y", ["reunion_flag", *cols], fe, "split_key")
        rt.df_clusters = r.df_clusters
        rows.append(row(f"+ artist-specific linear trends, {label} ({len(cols)} trends)", rt, "reunion_flag"))
    # last-tour placebo among artists without a reunion tour
    no_re = ~s.groupby("artist_key").reunion_flag.transform("max").astype(bool)
    last_start = s[no_re].groupby("artist_key").tour_unit_start_year.transform("max")
    s = s.copy()
    s["placebo_last_tour"] = 0.0
    s.loc[no_re[no_re].index, "placebo_last_tour"] = (s.loc[no_re, "tour_unit_start_year"] == last_start).astype(float)
    sp = s[no_re]
    rp = fe_ols(sp, "y", ["placebo_last_tour"], fe, "split_key")
    rp.df_clusters = int(sp.loc[sp.groupby("artist_key").placebo_last_tour.transform("nunique") > 1, "split_key"].nunique())
    rows.append(row("placebo: each non-reunion artist's last tour flagged", rp, "placebo_last_tour"))
    checks = pd.DataFrame(rows)
    checks.to_csv(OUT_TABLES / "reunion_checks.csv", index=False)
    return artists, checks


if __name__ == "__main__":
    a, c = main()
    print(a.to_string())
    print(c.round(4).to_string())
