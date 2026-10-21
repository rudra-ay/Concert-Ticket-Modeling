"""Shared helpers for the PATH analysis (task 8).

The forward Ticketmaster panel (data/forward/tm_forward.sqlite) is opened READ-ONLY
(sqlite URI mode=ro) and is never copied into tracked files. Row-level output is not
written anywhere; only aggregates go into reports/ (Ticketmaster storage terms,
FORWARD_COLLECTOR.md section 6).

Prices in the panel are PRIMARY-market face-value ranges (`standard`, USD, no fees),
not resale prices.
"""
from __future__ import annotations

import math
import sqlite3
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from analysis.targets import ROOT  # noqa: E402

DB = ROOT / "data/forward/tm_forward.sqlite"
CHARTS = ROOT / "reports/charts"
TABLES = ROOT / "reports/path_tables"

# Reference palette (dataviz skill, light mode), same as data_quality.py / level charts.
SURFACE, INK, INK2, MUTED, GRID, AXIS = "#fcfcfb", "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7"
S1, S2, S3 = "#2a78d6", "#eb6834", "#1baf7a"
NEUTRAL = "#c3c2b7"

plt.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
    "axes.edgecolor": AXIS, "axes.labelcolor": INK2, "text.color": INK, "xtick.color": INK2, "ytick.color": INK2,
    "axes.spines.top": False, "axes.spines.right": False, "axes.grid": True, "grid.color": GRID,
    "grid.linewidth": 0.6, "axes.axisbelow": True, "font.size": 10, "axes.titlesize": 12,
    "axes.titleweight": "bold", "axes.titlelocation": "left", "legend.frameon": False,
})

DAYS_BUCKETS = [(0, 6, "0-6"), (7, 13, "7-13"), (14, 29, "14-29"), (30, 59, "30-59"), (60, 89, "60-89"),
                (90, 10_000, "90+")]


def connect_ro() -> sqlite3.Connection:
    return sqlite3.connect(f"file:{DB}?mode=ro", uri=True)


def days_bucket(d: float) -> str | None:
    if d is None or (isinstance(d, float) and math.isnan(d)) or d < 0:
        return None
    for lo, hi, lab in DAYS_BUCKETS:
        if lo <= d <= hi:
            return lab
    return None


def wilson(k: int, n: int, z: float = 1.959964) -> tuple[float, float]:
    """95% Wilson score interval for a proportion k/n (returns (lo, hi) in [0, 1])."""
    if n == 0:
        return (float("nan"), float("nan"))
    p = k / n
    den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return (max(0.0, c - h), min(1.0, c + h))


def save(fig, name: str) -> str:
    CHARTS.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(CHARTS / name, dpi=150)
    plt.close(fig)
    return f"charts/{name}"


def md_table(df: pd.DataFrame) -> str:
    cols = [str(c) for c in df.columns]
    out = ["| " + " | ".join(cols) + " |", "|" + "|".join("---" for _ in cols) + "|"]
    for _, r in df.iterrows():
        out.append("| " + " | ".join("" if pd.isna(v) else str(v) for v in r.values) + " |")
    return "\n".join(out)
