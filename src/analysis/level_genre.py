"""H9 (descriptive, outside the BH family): genre price differences net of year.

`.venv/bin/python src/analysis/level_genre.py` -> reports/level_tables/genre.csv, reports/charts/level_genre.png.

Genre is fixed per artist, so these are between-artist contrasts: log real price on genre
dummies (reference: pop) with year FE, SEs clustered by split_key. The effective n is the
number of artists per genre, so the CIs are wide and nothing here is a test.
"""
from __future__ import annotations

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from analysis.data_quality import AXIS, INK2, S1, SURFACE  # noqa: E402,F401
from analysis.fe import fe_ols  # noqa: E402
from analysis.level_data import CHARTS, OUT_TABLES, load_sample  # noqa: E402

REFERENCE = "pop"


def main() -> pd.DataFrame:
    s = load_sample()
    s = s[s.genre_coarse_final.notna()].copy()
    genres = [g for g in s.genre_coarse_final.value_counts().index if g != REFERENCE]
    for g in genres:
        s[f"g_{g}"] = s.genre_coarse_final.eq(g).astype(float)
    xs = [f"g_{g}" for g in genres]
    r = fe_ols(s, "y", xs, ["year"], "split_key")
    art = s.groupby("genre_coarse_final").artist_key.nunique()
    rows = []
    for g, x in zip(genres, xs):
        lo, hi = r.ci(x)
        rows.append({"genre": g, "artists": int(art[g]), "shows": int(s[x].sum()), "coef": r.coef[x], "se": r.se[x],
                     "pct": 100 * (np.exp(r.coef[x]) - 1), "pct_lo": 100 * (np.exp(lo) - 1),
                     "pct_hi": 100 * (np.exp(hi) - 1), "p": r.p(x)})
    t = pd.DataFrame(rows).sort_values("pct")
    t.attrs["reference_artists"] = int(art[REFERENCE])
    t.to_csv(OUT_TABLES / "genre.csv", index=False)
    fig, ax = plt.subplots(figsize=(8, 5))
    yv = np.arange(len(t))
    ax.axvline(0, color=AXIS, linewidth=1)
    ax.hlines(yv, t.pct_lo, t.pct_hi, color=S1, linewidth=2)
    ax.plot(t.pct, yv, "o", color=S1, markersize=6)
    ax.set_yticks(yv, [f"{g} ({a} artists)" for g, a in zip(t.genre, t.artists)], fontsize=9)
    ax.set_xlabel(f"price vs. pop ({int(art[REFERENCE])} artists), %, year FE, 95% CI")
    ax.set_title("Genre differences (descriptive, between artists)")
    ax.grid(axis="y", visible=False)
    fig.tight_layout()
    fig.savefig(CHARTS / "level_genre.png", dpi=150)
    plt.close(fig)
    return t


if __name__ == "__main__":
    print(main().round(3).to_string())
