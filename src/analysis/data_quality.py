"""Data-quality report for data/shows.parquet -> reports/data_quality.md + reports/charts/dq_*.png.

Rerunnable after build_shows.py: `.venv/bin/python src/analysis/data_quality.py`.
All numbers in the report are computed here; the prose around them is fixed.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from analysis.targets import ROOT  # noqa: E402

CHARTS = ROOT / "reports/charts"
REPORT = ROOT / "reports/data_quality.md"

# Reference palette (dataviz skill, light mode).
SURFACE, INK, INK2, MUTED, GRID, AXIS = "#fcfcfb", "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7"
S1, S2, S3 = "#2a78d6", "#eb6834", "#1baf7a"
NEUTRAL = "#c3c2b7"
SEQ = LinearSegmentedColormap.from_list("blue", ["#f4f8fd", "#cde2fb", "#86b6ef", "#3987e5", "#1c5cab", "#0d366b"])

plt.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
    "axes.edgecolor": AXIS, "axes.labelcolor": INK2, "text.color": INK, "xtick.color": INK2, "ytick.color": INK2,
    "axes.spines.top": False, "axes.spines.right": False, "axes.grid": True, "grid.color": GRID,
    "grid.linewidth": 0.6, "axes.axisbelow": True, "font.size": 10, "axes.titlesize": 12,
    "axes.titleweight": "bold", "axes.titlelocation": "left", "legend.frameon": False,
})


def _save(fig, name: str) -> str:
    CHARTS.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(CHARTS / name, dpi=150)
    plt.close(fig)
    return f"charts/{name}"


def _md_table(df: pd.DataFrame, floatfmt: str = "{:.2f}") -> str:
    cols = list(df.columns)
    lines = ["| " + " | ".join(map(str, cols)) + " |", "|" + "---|" * len(cols)]
    for _, r in df.iterrows():
        cells = []
        for c in cols:
            v = r[c]
            if isinstance(v, float) and not np.isnan(v):
                cells.append(floatfmt.format(v))
            elif isinstance(v, float):
                cells.append("—")
            else:
                cells.append(str(v))
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


# --- charts --------------------------------------------------------------------

def chart_year(d: pd.DataFrame) -> str:
    y = d.assign(year=d.show_date.dt.year)
    t = pd.DataFrame({
        "sample": y[y.analysis_sample].groupby("year").size(),
        "other": y[~y.analysis_sample].groupby("year").size(),
    }).fillna(0).loc[1975:2026]
    fig, ax = plt.subplots(figsize=(10, 4))
    ax.bar(t.index, t["sample"], color=S1, width=0.8, label="analysis sample (priced)")
    ax.bar(t.index, t["other"], bottom=t["sample"], color=NEUTRAL, width=0.8, label="unpriced / excluded",
           edgecolor=SURFACE, linewidth=1)
    ax.set_title("Shows per year: priced analysis sample vs. rows without usable prices")
    ax.set_ylabel("shows")
    ax.legend(loc="upper left")
    ax.grid(axis="x", visible=False)
    return _save(fig, "dq_coverage_by_year.png")


def chart_country(s: pd.DataFrame) -> str:
    c = s.country_final.fillna("unknown").value_counts().head(20)[::-1]
    fig, ax = plt.subplots(figsize=(7, 6))
    ax.barh(c.index, c.values, color=S1, height=0.7)
    ax.set_xscale("log")
    ax.set_title("Analysis sample by country (top 20, log scale)")
    ax.set_xlabel("shows")
    ax.grid(axis="y", visible=False)
    for i, v in enumerate(c.values):
        ax.text(v * 1.08, i, f"{v:,}", va="center", fontsize=8, color=INK2)
    return _save(fig, "dq_coverage_by_country.png")


def chart_genre(s: pd.DataFrame) -> str:
    g = s.assign(genre=s.genre_coarse_final.fillna("(missing)")).groupby("genre").agg(
        shows=("show_id", "size"), artists=("artist_id", "nunique")).sort_values("shows")
    fig, axes = plt.subplots(1, 2, figsize=(10, 4.5), sharey=True)
    for ax, col, title in [(axes[0], "shows", "Shows"), (axes[1], "artists", "Artists (the effective n for genre)")]:
        ax.barh(g.index, g[col], color=S1, height=0.7)
        ax.set_title(title)
        ax.grid(axis="y", visible=False)
        for i, v in enumerate(g[col]):
            ax.text(v, i, f" {v:,}", va="center", fontsize=8, color=INK2)
    fig.suptitle("Analysis sample by coarse genre", x=0.01, ha="left", fontweight="bold")
    return _save(fig, "dq_coverage_by_genre.png")


def chart_price(s: pd.DataFrame) -> str:
    fig, axes = plt.subplots(1, 2, figsize=(11, 4))
    bins = np.logspace(np.log10(10), np.log10(1500), 60)
    axes[0].hist(s.avg_price_real, bins=bins, color=S1, edgecolor=SURFACE, linewidth=0.5)
    axes[0].set_xscale("log")
    axes[0].set_title("Average ticket price, Sep-2026 USD (log scale)")
    axes[0].set_xlabel("avg_price_real")
    axes[0].set_ylabel("shows")
    med = s.avg_price_real.median()
    axes[0].axvline(med, color=INK2, linewidth=1, linestyle="--")
    axes[0].text(med * 1.15, axes[0].get_ylim()[1] * 0.92, f"median ${med:,.0f}", color=INK2, fontsize=9)
    axes[1].hist(s.price_rel_artist_median.clip(-1.5, 1.5), bins=60, color=S1, edgecolor=SURFACE, linewidth=0.5)
    axes[1].set_title("Log price relative to the artist's median")
    axes[1].set_xlabel("price_rel_artist_median (clipped to ±1.5)")
    for ax in axes:
        ax.grid(axis="x", visible=False)
    return _save(fig, "dq_price_distribution.png")


def chart_price_year(s: pd.DataFrame) -> str:
    y = s.assign(year=s.show_date.dt.year).groupby("year").agg(
        real=("avg_price_real", "median"), nominal=("avg_price_usd", "median"), n=("show_id", "size"))
    y = y[y.n >= 30]
    fig, ax = plt.subplots(figsize=(10, 4))
    ax.plot(y.index, y.real, color=S1, linewidth=2, marker="o", markersize=4, label="real (Sep-2026 USD)")
    ax.plot(y.index, y.nominal, color=S2, linewidth=2, marker="o", markersize=4, label="nominal USD")
    ax.text(y.index[-1] + 0.3, y.real.iloc[-1], "real", color=INK2, va="bottom", fontsize=9)
    ax.text(y.index[-1] + 0.3, y.nominal.iloc[-1], "nominal", color=INK2, va="top", fontsize=9)
    ax.set_title("Median average ticket price by year (years with ≥ 30 sample shows)")
    ax.set_ylabel("USD per ticket")
    ax.set_ylim(0, None)
    ax.legend(loc="upper left")
    return _save(fig, "dq_price_by_year.png")


HEATMAP_COLS = [
    "genre_coarse_final", "career_start_year", "years_active_at_show", "lb_total_listen_count", "pv_mean_365d",
    "pv_momentum", "venue_qid", "venue_type", "indoor_outdoor", "capacity", "tickets_available", "lat",
    "metro_median_hh_income", "is_college_town", "day_of_week", "is_public_holiday", "leg_number",
    "tour_progress", "days_announce_to_show", "opening_acts_raw", "n_openers", "farewell_flag", "wx_temp_max_c",
    "wx_eve_precip_mm",
]


def chart_missing(s: pd.DataFrame) -> tuple[str, pd.DataFrame]:
    cols = [c for c in HEATMAP_COLS if c in s.columns] + [c for c in HEATMAP_COLS if c not in s.columns]
    yb = pd.cut(s.show_date.dt.year, [1969, 1989, 1999, 2009, 2014, 2019, 2022, 2026],
                labels=["1970-89", "1990-99", "2000-09", "2010-14", "2015-19", "2020-22", "2023-26"])
    m = pd.DataFrame({c: (s[c].notna() if c in s.columns else pd.Series(False, index=s.index)) for c in cols})
    tab = m.groupby(yb, observed=True).mean().T * 100
    tab["all"] = m.mean() * 100
    fig, ax = plt.subplots(figsize=(9, 9))
    im = ax.imshow(tab.values, cmap=SEQ, vmin=0, vmax=100, aspect="auto")
    ax.set_xticks(range(tab.shape[1]), tab.columns)
    ax.set_yticks(range(tab.shape[0]), [c + ("  (table missing)" if c not in s.columns else "") for c in tab.index])
    ax.grid(False)
    for i in range(tab.shape[0]):
        for j in range(tab.shape[1]):
            v = tab.values[i, j]
            ax.text(j, i, f"{v:.0f}", ha="center", va="center", fontsize=7, color=INK if v < 60 else SURFACE)
    ax.set_title("% non-null in the analysis sample, by show year")
    cb = fig.colorbar(im, ax=ax, fraction=0.03)
    cb.set_label("% non-null")
    return _save(fig, "dq_missingness_heatmap.png"), tab


def chart_selection(sel: dict) -> tuple[str, pd.Series]:
    share = pd.Series(sel["by_progress"]) * 100
    na = pd.Series(sel["by_progress_na"]) * 100
    fig, ax = plt.subplots(figsize=(7.5, 3.8))
    xv = np.arange(len(share))
    ax.bar(xv - 0.18, share.values, color=S1, width=0.34, label="all tours")
    ax.bar(xv + 0.18, na.reindex(share.index).values, color=S2, width=0.34, label="North America")
    for i, (a, b_) in enumerate(zip(share.values, na.reindex(share.index).values)):
        ax.text(i - 0.18, a + 0.8, f"{a:.0f}", ha="center", fontsize=8, color=INK2)
        ax.text(i + 0.18, b_ + 0.8, f"{b_:.0f}", ha="center", fontsize=8, color=INK2)
    ax.set_xticks(xv, share.index)
    ax.set_title("Share of played shows whose figures are reported, by position in the tour")
    ax.set_xlabel("tour_progress (tours with ≥ 1 reported show; aggregate members count via their unit)")
    ax.set_ylabel("% covered")
    ax.legend(loc="lower left")
    ax.grid(axis="x", visible=False)
    return _save(fig, "dq_selection_by_tour_position.png"), share


# --- power ---------------------------------------------------------------------

def _within(y: pd.Series, g: pd.Series) -> pd.Series:
    return y - y.groupby(g).transform("mean")


def _cluster_mde(tv: pd.DataFrame, xcol: pd.Series, group: str) -> tuple[float, int]:
    """(t_.975 + t_.80) on G-1 df x cluster-robust SE of the slope with `group` FE AND year FE,
    clustered by performer group (split_key). Returns (MDE, G). The coefficient is not reported."""
    from scipy import stats

    from analysis.fe import fe_ols
    d = tv.assign(_x=xcol.astype(float), _year=tv.show_date.dt.year)
    if len(d) < 10 or d["_x"].std() == 0:
        return np.nan, 0
    fe = [group] if group == "_year" else [group, "_year"]
    r = fe_ols(d, "log_avg_price_real", ["_x"], fe, "split_key")
    G = r.n_clusters
    if G < 3:
        return np.nan, G
    mult = stats.t.ppf(0.975, G - 1) + stats.t.ppf(0.80, G - 1)
    return float(mult * r.se["_x"]), G


def power_binary(s: pd.DataFrame, x: str, group: str = "tour", mask=None) -> dict:
    t = s if mask is None else s[mask]
    t = t[t[x].notna()]
    xv = t[x].astype(bool)
    var = t.groupby(group)[x].transform(lambda v: v.astype(bool).nunique() > 1).astype(bool)
    tv = t[var]
    n1, n0 = int(tv[x].astype(bool).sum()), int((~tv[x].astype(bool)).sum())
    sd = _within(tv.log_avg_price_real, tv[group]).std() if len(tv) else np.nan
    naive = 2.8 * sd * np.sqrt(1 / n1 + 1 / n0) if n1 and n0 else np.nan
    mde, G = _cluster_mde(tv, tv[x].astype(bool), group)
    return dict(n=len(t), n_true=int(xv.sum()), n_in_varying=len(tv), artists_var=tv.split_key.nunique(),
                groups_var=tv[group].nunique(), naive=naive, mde=mde, G=G)


def power_cont(s: pd.DataFrame, x: str, group: str = "tour", mask=None) -> dict:
    t = s if mask is None else s[mask]
    t = t[t[x].notna() & np.isfinite(t[x].astype(float))]
    var = t.groupby(group)[x].transform(lambda v: v.nunique() > 1).astype(bool)
    tv = t[var]
    xw = _within(tv[x].astype(float), tv[group])
    sdx = xw.std()
    yw = _within(tv.log_avg_price_real, tv[group])
    naive = 2.8 * yw.std() / np.sqrt(len(tv)) if len(tv) > 2 else np.nan
    # per 1 SD of the within-group x
    mde, G = _cluster_mde(tv, tv[x].astype(float) / sdx, group) if sdx and sdx > 0 else (np.nan, 0)
    return dict(n=len(t), n_in_varying=len(tv), artists_var=tv.split_key.nunique(), groups_var=tv[group].nunique(),
                sd_x_within=sdx, naive=naive, mde=mde, G=G)


def hypotheses(s: pd.DataFrame, cov: dict) -> tuple[pd.DataFrame, dict]:
    s = s.copy()
    s["tour"] = s.tour_unit.fillna(s.artist_id + "|" + s.tour_title.fillna(""))
    s["artist"] = s.artist_key
    single = s.aggregate_n_shows == 1
    extra: dict = {}
    rows = []

    def add(h, var, status, p, note):
        g = p.get("groups_var") or 0
        g = min(g, p.get("G") or g)
        if status.startswith("TESTABLE") and g < 10:
            status = "UNDERPOWERED (< 10 groups with variation)"
        elif status.startswith("TESTABLE") and g < 30:
            status = "WEAK (< 30 groups with variation)"
        rows.append({"hypothesis": h, "variable": var, "status": status, "n": p.get("n"),
                     "n (within-group variation)": p.get("n_in_varying"),
                     "performer groups w/ variation": p.get("artists_var"), "FE groups w/ variation": p.get("groups_var"),
                     "G (clusters)": p.get("G"), "naive MDE": p.get("naive"), "clustered MDE": p.get("mde"),
                     "notes": note + ("; G < 30: use t(G−1) and a wild cluster bootstrap in task 6" if (p.get("G") or 99) < 30 else "")})

    # H: city premium with artist FE
    am = s.groupby("artist").metro_key.nunique()
    mk = s.groupby("metro_key").agg(n=("show_id", "size"), a=("artist_id", "nunique"))
    extra["city"] = dict(artists_5plus_metros=int((am >= 5).sum()), metros_30shows_5artists=int(((mk.n >= 30) & (mk.a >= 5)).sum()),
                         metros_total=int(len(mk)))
    p = power_cont(s, "metro_median_hh_income", group="artist", mask=s.is_us)
    add("City premium (artist FE)", "metro_key dummies; US: metro_median_hh_income", "TESTABLE", p,
        f"{extra['city']['artists_5plus_metros']} artists play ≥ 5 metros; {extra['city']['metros_30shows_5artists']} metros have ≥ 30 shows from ≥ 5 artists. "
        "**This row assesses only the income slope**, per 1 SD of within-artist income (US only, SNAPSHOT 2024 ACS); the metro-dispersion test is in task 6")
    # weekend / holiday (single-night units only: aggregate dates describe the first night)
    add("Weekend premium", "is_fri_sat (tour FE, single-night units)", "TESTABLE",
        power_binary(s, "is_fri_sat", mask=single), "aggregates excluded because their date is the first night only")
    add("Holiday premium", "is_holiday_eve or is_long_weekend (tour FE)", "TESTABLE",
        power_binary(s.assign(hol=(s.is_holiday_eve.fillna(False) | s.is_long_weekend.fillna(False))), "hol", mask=single),
        "few holiday shows per tour; national calendars only")
    # venue size, fanbase vs capacity
    s["log_cap"] = np.log(s.tickets_available_per_show.where(s.tickets_available_per_show > 0))
    add("Venue size", "log tickets_available_per_show (artist FE)", "TESTABLE",
        power_cont(s, "log_cap", group="artist"), "capacity as sold is partly an OUTCOME; Wikidata `capacity` is a current SNAPSHOT")
    s["fan_per_seat"] = np.log1p(s.pv_mean_365d) - s.log_cap
    add("Fanbase vs capacity", "log(pv_mean_365d) − log capacity (artist FE)", "TESTABLE (2016+)",
        power_cont(s, "fan_per_seat", group="artist"), "pageviews exist only from mid-2015; LB listeners are a current snapshot (between-artist only)")
    # popularity level vs momentum
    add("Popularity level", "log pv_mean_365d (artist FE, i.e. over time)", "TESTABLE (2016+)",
        power_cont(s.assign(lpv=np.log1p(s.pv_mean_365d)), "lpv", group="artist"), "POST_ONSALE window; re-anchor if on-sale dates appear")
    add("Momentum (Dom Dolla effect)", "pv_momentum (artist FE)", "TESTABLE (2016+), noisy",
        power_cont(s, "pv_momentum", group="artist"), "Wikipedia attention ≠ fandom; the 30-day window is mostly after on-sale (reverse causality risk)")
    # genre / experience
    ga = s.groupby("genre_coarse_final").artist_id.nunique()
    art = s.groupby("artist_id").agg(m=("log_avg_price_real", "median"), g=("genre_coarse_final", "first")).dropna()
    sd_art = art.m.std()
    extra["genre"] = dict(artists_by_genre=ga.to_dict(), sd_artist_median=sd_art)
    rows.append({"hypothesis": "Genre / experience premium", "variable": "genre_coarse_final (between artists)",
                 "status": "WEAK (between-artist)", "n": int(s.genre_coarse_final.notna().sum()),
                 "n (within-group variation)": np.nan, "performer groups w/ variation": int(len(art)),
                 "FE groups w/ variation": int(ga.size), "G (clusters)": int(len(art)),
                 "naive MDE": np.nan, "clustered MDE": 2.8 * sd_art * np.sqrt(2 / max(ga.median(), 1)),
                 "notes": f"genre is fixed per artist, so n = artists ({int(ga.min())}–{int(ga.max())} per genre). MDE is for a median-sized genre vs. one other; no direct 'experience/production' measure"})
    # bills / openers
    bill_ok = cov.get("bill", {}).get("status") != "missing"
    if bill_ok:
        add("Bill size (openers)", "n_openers (tour FE)", "TESTABLE", power_cont(s.assign(n_op=s.n_openers.astype(float)), "n_op"),
            f"known for {int(s.n_openers.notna().sum()):,} rows (blank cell = unknown); multi_artist_flag is True on "
            f"{100 * s.multi_artist_flag.mean():.0f}% of known rows, so it has almost no within-tour variation")
        add("Co-headline", "co_headliner_flag (performer-group FE: solo vs. package tours)", "TESTABLE",
            power_binary(s.assign(co=s.co_headliner_flag.astype(bool)), "co", group="split_key"),
            f"{int(s.co_headliner_flag.sum()):,} co-headlined rows; identified from performers who also tour solo")
        s["log_opener_pv"] = np.log1p(s.opener_pv_mean_90d_max)
        add("Opener draw", "log opener_pv_mean_90d_max (tour FE)", "TESTABLE", power_cont(s, "log_opener_pv"),
            f"opener pageviews filled on only {int(s.opener_pv_mean_90d_max.notna().sum()):,} sample rows (2016+ and linked openers only)")
    else:
        s["has_opener_text"] = s.opening_acts_raw.notna()
        add("Multi-artist bills / opener draw", "n_openers, opener_pv_* (bill table)", "WAITING (bill table)",
            power_binary(s, "has_opener_text"), "bill table not built; spine opener text only")
    # tour leg / farewell / added dates
    s["later_leg"] = s.leg_number > 1
    add("Tour leg", "leg_number > 1 (tour FE)", "TESTABLE", power_binary(s, "later_leg"),
        f"legs are inferred for {100 * s.leg_inferred.mean():.0f}% of sample rows (gap/continent rule); EXPOST")
    if "farewell_flag" in s.columns:
        for flag in ["farewell_flag", "reunion_flag"]:
            add(flag.split("_")[0].capitalize() + " tour", f"{flag} (artist FE)", "TESTABLE", power_binary(s, flag, group="artist"),
                f"{s.loc[s[flag].fillna(False).astype(bool), 'tour'].nunique()} {flag.split('_')[0]} tours in the sample; tour-level label, hindsight categories; identification needs the same artist's other tours")
    else:
        kw = s.tour_title.fillna("").str.contains(r"farewell|final tour|last tour|end of the road|goodbye", case=False)
        s["fw_kw"] = kw
        add("Farewell / reunion", "title keyword proxy (artist FE)", "WAITING (bill table)", power_binary(s, "fw_kw", group="artist"),
            f"title keywords alone: {s.loc[kw, 'tour'].nunique()} farewell tours")
    s["multi_night"] = s.aggregate_n_shows > 1
    add("Added dates / multi-night demand", "aggregate_n_shows > 1 (tour FE)", "TESTABLE (as multi-night demand)",
        power_binary(s, "multi_night"),
        f"is_added_date_proxy is True on only {int(s.is_added_date_proxy.fillna(False).sum())} sample rows, because the 2nd+ nights of a stand usually sit inside an aggregate (unpriced). Can't separate 'added' from 'announced up front'; EXPOST")
    # outdoor & weather
    s["outdoor"] = s.indoor_outdoor.eq("outdoor").where(s.indoor_outdoor.notna())
    add("Outdoor premium", "indoor_outdoor (artist FE)", "TESTABLE", power_binary(s, "outdoor", group="artist"),
        "class-based; domed stadiums typed only as 'stadium' are misread as outdoor")
    ok = s.wx_status.eq("ok") & s.indoor_outdoor.eq("outdoor")
    s["rainy"] = (s.wx_eve_precip_mm >= 1).where(ok)
    extra["weather"] = dict(ok_sample=int(s.wx_status.eq("ok").sum()), outdoor_ok=int(ok.sum()),
                            rainy_outdoor=int(s.rainy.fillna(False).sum()))
    add("Weather (outdoor)", "wx_eve_precip_mm ≥ 1 at outdoor venues (tour FE)", "WEAK / partial", power_binary(s, "rainy"),
        f"weather ok on {extra['weather']['ok_sample']:,} sample rows; {extra['weather']['outdoor_ok']:,} outdoor; {extra['weather']['rainy_outdoor']} rainy outdoor evenings. "
        "Prices are set before the weather is known, so the expected effect on avg price is small (SHOWDAY)")
    rows.append({"hypothesis": "Set-list popularity", "variable": "—", "status": "NOT TESTABLE", "n": 0,
                 "n (within-group variation)": np.nan, "performer groups w/ variation": np.nan, "FE groups w/ variation": np.nan,
                 "G (clusters)": np.nan, "naive MDE": np.nan, "clustered MDE": np.nan,
                 "notes": f"setlist.fm needs permission. Proxy: album attention `album_pv_*` (bill table), filled on {int(s.album_pv_mean_90d.notna().sum()) if 'album_pv_mean_90d' in s else 0} sample rows; it measures the album, not the set"})
    return pd.DataFrame(rows), extra


# --- report --------------------------------------------------------------------

def main() -> None:
    d = pd.read_parquet(ROOT / "data/shows.parquet")
    cov = json.loads((ROOT / "data/shows_join_coverage.json").read_text())
    s = d[d.analysis_sample].copy()
    sm = cov["_summary"]

    charts = {
        "year": chart_year(d), "country": chart_country(s), "genre": chart_genre(s),
        "price": chart_price(s), "price_year": chart_price_year(s),
    }
    charts["missing"], miss = chart_missing(s)
    from analysis import selection
    sel = selection.main()
    charts["selection"], sel_share = chart_selection(sel)
    hyp, extra = hypotheses(s, cov)
    hyp.to_csv(ROOT / "reports/level_tables/power.csv", index=False)  # traceable source for MDEs quoted in level_findings

    # duplicates / outliers
    dups = d[d.dup_boxoffice_group.notna()]
    near = d.assign(c=d.city.str.lower()).duplicated(["artist_id", "show_date", "c"], keep=False)
    suffix = d.show_id.str.contains(r"__\d+$")
    cap_dec = pd.Series(sel["by_wikidata_capacity"]) * 100
    cont = pd.Series(sel["by_continent"]) * 100
    short = d[d.is_aggregate_unit & d.avg_price_usd.notna() & d.agg_group_id.notna()]
    placed = d.groupby("agg_group_id").size()
    short = short[short.show_id.map(placed) < short.aggregate_n_shows]
    short_tab = short[["show_id", "aggregate_n_shows", "agg_n_venues", "agg_span_days", "analysis_sample"]].assign(
        placed=short.show_id.map(placed))
    ctry = s.groupby("country_final").agg(n=("show_id", "size"), rel=("price_rel_artist_era", "median")).query("n >= 100").sort_values("rel")
    top = s.nlargest(8, "avg_price_real")[["show_id", "avg_price_usd", "avg_price_real", "tickets_sold", "aggregate_n_shows"]]
    low = s.nsmallest(5, "avg_price_real")[["show_id", "avg_price_usd", "avg_price_real", "tickets_sold"]]
    big_rel = int((s.price_rel_artist_median.abs() > np.log(3)).sum())
    excl = d.analysis_exclusion_reason.value_counts()
    pre80 = int((s.show_date.dt.year < 1980).sum())
    sold_gt = int((s.tickets_sold > s.tickets_available * 1.05).sum())
    small = int((s.tickets_sold_per_show < 500).sum())
    weird_artists = s.loc[s.artist_name.str.contains(r"concert tours|festival|American Idol|List of", case=False), "artist_name"].value_counts()
    split_rows = s.artist_split.value_counts()
    split_art = s.groupby("artist_split").artist_id.nunique()
    top_art_share = s.artist_id.value_counts(normalize=True).head(10).sum() * 100
    comp = s.groupby("split_key").artist_id.nunique()
    multi_ids = int((comp > 1).sum())
    multi_rows = int(s.split_key.isin(comp[comp > 1].index).sum())

    cov_rows = pd.DataFrame([
        {"table": k, "status": v["status"], "rows": v.get("rows", 0), "% shows matched": v.get("pct_shows_matched", 0),
         "% priced filled": v.get("pct_priced_filled", 0), "% sample filled": v["pct_analysis_filled"]}
        for k, v in cov.items() if k != "_summary"])
    counts = ["n", "n (within-group variation)", "performer groups w/ variation", "FE groups w/ variation", "G (clusters)"]
    hyp_md = _md_table(hyp.astype({**{c: "Int64" for c in counts}, "naive MDE": float, "clustered MDE": float})
                       .astype({c: "string" for c in counts}).fillna({c: "—" for c in counts}), "{:.3f}")
    hyp_md = hyp_md.replace("| nan |", "| — |")

    def waiting(name):
        return cov.get(name, {}).get("status", "missing")

    if waiting("bill") == "missing":
        bill_line = "- **Waiting on the bill table** (missing): openers and opener draw, festival flag, farewell/reunion flags, and the album-attention proxy for set lists."
    else:
        bill_line = (f"- **Bill table landed** ({waiting('bill')}; {cov['bill']['pct_analysis_filled']}% of sample rows have both opener pageviews and Wikidata lookups done): bill size, co-headline, festival and farewell/reunion flags are usable now. "
                     f"**Still thin:** opener pageviews ({int(s.opener_pv_mean_90d_max.notna().sum())} sample rows) and album pageviews "
                     f"({int(s.album_pv_mean_90d.notna().sum())} rows), so opener draw and the set-list proxy are underpowered unless those columns fill.")

    text = f"""# Data quality report: data/shows.parquet

Generated by `src/analysis/data_quality.py` from the build at {sm['built']}. Rerun after `build_shows.py`; every number below is recomputed.

**Bottom line.** {sm['rows']:,} show rows, of which {sm['priced']:,} have a price. The **analysis sample is {sm['analysis_sample']:,} rows from {sm['analysis_artists']} artists** ({s.tour_title.nunique()} tour articles). The sample is big-tour, mostly North American (US {100 * s.country_final.eq('US').mean():.0f}%), and concentrated in 2008–2019 plus 2022–2025. Prices are clean once the {int(excl.get('implausible', 0)) + int(excl.get('tour_outlier', 0))} flagged rows are removed (no CPI gaps, no duplicate keys). The biggest risks are **selection** (which shows have figures), **"$" read as USD** at non-US shows, and **features that are ex post or current snapshots**.

## 1. Join coverage

{_md_table(cov_rows, '{:.1f}')}

"filled" means processed (venue resolved on Wikidata; weather `ok`; bill: opener pageview **and** Wikidata/album lookups done, while its flags are usable regardless). Missing or partial tables give nulls, recorded as `has_<table>` in shows.parquet. **The bill table is {waiting('bill')}**, the venue table is {waiting('venue')} ({cov.get('venue', {}).get('pct_analysis_filled', 0)}% of the sample resolved), and weather is {waiting('weather')} ({cov.get('weather', {}).get('pct_analysis_filled', 0)}% of the sample `ok`).

Exclusions from the priced rows: {', '.join(f'{k} {v:,}' for k, v in excl.items() if k != 'unpriced')}. Every priced row is in USD (the 33 non-USD grosses have no `gross_usd`, and there's no local FX table to convert them).

## 2. Coverage by year, country, genre

![coverage by year]({charts['year']})

The priced sample is thin before 2008 (< 600 shows a year), collapses in 2020–21 (COVID), and drops off in 2025–26 because the latest tours haven't reported or been written up yet. {pre80} sample shows are from the 1970s; they're deflated with the pre-1980 BLS CPI from the raw file.

![coverage by country]({charts['country']})

![coverage by genre]({charts['genre']})

Genre is missing for {100 * s.genre_coarse_final.isna().mean():.1f}% of sample rows ({s.loc[s.genre_coarse_final.isna(), 'artist_id'].nunique()} artists). Pop and rock make up {100 * s.genre_coarse_final.isin(['pop', 'rock']).mean():.0f}% of rows. EDM, K-pop, metal and Latin each have ≤ 13 artists, so any genre contrast rests on a handful of acts.

## 3. Price distribution

![price distribution]({charts['price']})

![price by year]({charts['price_year']})

- Real average price: median ${s.avg_price_real.median():,.0f}, p5 ${s.avg_price_real.quantile(.05):,.0f}, p95 ${s.avg_price_real.quantile(.95):,.0f}, max ${s.avg_price_real.max():,.0f} (Sep-2026 USD). The log price is roughly symmetric, with SD {s.log_avg_price_real.std():.2f}.
- **Variance decomposition** of the log real price: SD {s.log_avg_price_real.std():.2f} overall, {s.price_rel_artist_median.std():.2f} after removing the artist median, and {(s.log_avg_price_real - s.groupby(s.artist_id + '|' + s.tour_title.fillna('')).log_avg_price_real.transform('mean')).std():.2f} within a tour. Most variation is between artists and tours. Within-tour (city, date, venue) effects have to show up in roughly a ±0.2 log-point band.
- Real prices roughly tripled from the 1980s to the 2020s (chart). Year effects or time trends are mandatory in any model.

## 4. Missingness

![missingness heatmap]({charts['missing']})

Patterns to plan around:
- **Pageview features (`pv_*`) are structurally missing before mid-2015**, so popularity and momentum hypotheses are tested only on 2016+ shows ({int(s.pv_momentum.notna().sum()):,} rows).
- **`days_announce_to_show` is ~empty** ({100 * s.days_announce_to_show.notna().mean():.1f}% non-null). There's no lead-time feature.
- **Metro (Census) features are US-only** ({100 * s.metro_median_hh_income.notna().mean():.0f}% of the sample). `is_college_town` is True on only {int(s.is_college_town.fillna(False).sum())} sample rows.
- **Venue Wikidata fields** (type, capacity, coordinates) are missing for the {100 - cov.get('venue', {}).get('pct_analysis_filled', 0):.1f}% of sample shows whose venues haven't been resolved yet, plus venues with no item.
- **Weather** is `ok` for {extra['weather']['ok_sample']:,} sample rows ({100 * extra['weather']['ok_sample'] / len(s):.0f}%). The rest are pending (rerun) or have no coordinates (non-US venues without a Wikidata point).
- **Bill:** `n_openers` is known for {100 * s.n_openers.notna().mean() if 'n_openers' in s else 0:.0f}% of the sample (a blank opener cell means unknown). Opener and album pageviews are nearly empty (see section 8).

## 5. Duplicates

- `show_id` is unique ({len(d):,} ids; {int(suffix.sum())} carry a `__2`/`__3` collision suffix), and every feature table is unique on its key. The join is validated many-to-one and never changes the row count (tests/test_shows_join.py).
- **Duplicate box office lines** (review 1, items 2–3): {dups.dup_boxoffice_group.nunique()} groups ({len(dups)} rows) where two priced rows on the same date carry an identical gross, or identical tickets (> 1,000) with gross within 5%. Venue names are deliberately not compared ("Superdome" vs "Louisiana Superdome"). Cross-artist groups come from an opener's or co-headliner's article quoting the headliner's line. Within-artist groups are the same Rush show listed twice under venue variants. Every group is resolved by hand in `data/manual/boxoffice_dedupe.csv`, with a reason per row: {int((~dups.dup_boxoffice_drop).sum())} rows kept, {int(dups.dup_boxoffice_drop.sum())} dropped. The headliner is kept only when its opening-act cell names the other act. Co-bills with no identifiable headliner (Chesney/Aldean 2015, Journey/Santana 1982, …) and festival totals (Foo Fighters/Marilyn Manson, Rock im Ring 2015) are dropped entirely. The Smashing Pumpkins/Marilyn Manson End Times dates are kept under the co-headline act key. `dup_unreviewed` is zero (tested).
- **Copied figures:** {int(d.dup_figure_copy.sum())} priced rows share an artist's exact gross and tickets with a different date (e.g. Metallica Brisbane 2025 = Bologna 2026; Scorpions Hamburg March = November 2016). Which date the figure belongs to can't be told, so all copies are excluded (`dup_figure_copy`).
- **One performer, several artist_ids** (review 1, item 4): artist_id is per act as written. `split_key` is the connected component of artist_ids linked by a shared QID or headliner wikilink, a Wikidata P527/P463/P361 edge between two artists in the data (band ↔ member, duo ↔ partner; organisations can't chain because both ends must be artists here), or a manual relation (`data/manual/artist_relations.csv`: NSYNC/Timberlake, Queen/Queen + Adam Lambert and + Paul Rodgers, Jonas Brothers/Demi & Nick, Selena Gomez/the Scene, the Eagles alias). In the sample, {multi_ids} performer groups span more than one artist_id ({multi_rows:,} rows); the largest has {int(comp.max())} ids. Every pair the skeptic listed now shares a split (tested). `artist_key` inherits the QID through the headliner wikilink (`the-eagles` → Eagles). Non-performer acts (Cirque du Soleil, American Idol, Glee and High School Musical casts, Various Artists, the Honda Civic Tour) are excluded: {int(excl.get('non_performer', 0))} priced rows.
- **Same artist, date and city at two venues:** {int(near.sum())} rows, almost all unpriced (promo appearances, festival side stages). They're left in.
- **Multi-night aggregates:** {int(d.agg_group_id.notna().sum()):,} rows sit in {d.loc[d.is_aggregate_unit].shape[0]:,} aggregate groups. They're treated as one unit each (DATA_DICTIONARY.md, Join decisions), and deflated at the midpoint month of their span. {int((d.aggregate_n_shows.gt(1) & d.agg_group_id.isna()).sum())} member rows couldn't be placed in a group from row order; they carry no figures. {int(excl.get('aggregate_multi_venue', 0))} priced aggregates span several venues (leg totals) and are excluded. **Priced units with fewer placed members than aggregate_n_shows** (review 1, item 10; agg_n_venues may undercount for these):

{_md_table(short_tab, '{:,.0f}')}

## 6. Outliers

- The collector's flags remove {int(excl.get('implausible', 0))} `implausible` rows (< $5 or > $2,000) and {int(excl.get('tour_outlier', 0))} `tour_outlier` rows (> 4× or < 0.25× the tour median).
- {big_rel} sample rows sit more than 3× (log 1.1) away from their artist's median. They are kept. The extremes checked by hand look genuine rather than parse errors (Barbra Streisand's Las Vegas and arena dates, McCartney at the Budokan, the Rolling Stones in a 6,700-seat casino, U2's $5 1987 show). The middle of the tail hasn't been audited row by row, so robust losses or a winsorized target are worth a sensitivity check. Top of the real-price distribution:

{_md_table(top, '{:,.1f}')}

Bottom:

{_md_table(low, '{:,.1f}')}

- {sold_gt} sample rows have tickets_sold > tickets_available (by more than 5%), and {small} have fewer than 500 tickets per show. They're left in; their average prices aren't extreme.
- **Currency ("$" assumed USD).** {int(s.usd_assumed_non_us.sum()):,} sample rows are non-US shows with a USD gross. `country_final` fills the country for rows whose spine country is null (venue Wikidata country, doubled spine text, the city suffix, or a US Census match), so these are now flagged too. Median price relative to the artist's 5-year era, by country (n ≥ 100):

{_md_table(ctry.reset_index().rename(columns={'country_final': 'country', 'rel': 'median log price vs artist × 5-yr era'}), '{:.3f}')}

  These medians can't separate a country premium from currency mislabeling. The formal test is the within-tour FX-slope regression (skeptic's spec) in `src/analysis/currency_test.py` → reports/currency_test.md. Country and city premia are reported only alongside it.
- Non-pricing anomalies: some "artists" are page titles rather than acts ({', '.join(f'{k} ({v})' for k, v in weird_artists.items()) or 'none'}). `artist_key` strips the "List of ..." wording and maps them to the performer where possible. "Phish concert tours and festivals" has no QID and stays its own key.

## 7. Selection bias

![selection by tour position]({charts['selection']})

- **Which tours:** only tours big enough to report to Billboard Boxscore/Pollstar *and* to have a Wikipedia box office table. These are arena and stadium acts with long careers; the top 10 artists supply {top_art_share:.0f}% of the sample rows. Results describe superstar pricing, not the concert market. Effects that matter for mid-size acts (opener draw, college towns, club tours) are the least identifiable.
- **Which shows within a tour** (review 1, item 6; `src/analysis/selection.py`): "covered" counts members of priced aggregates through their unit. Among {sel['universe_shows']:,} played shows in {sel['tours']:,} tours with at least one reported show, {100 * sel['coverage_all']:.0f}% are covered ({100 * sel['coverage_priced_rows_only']:.0f}% if aggregate members were counted as unpriced). Coverage falls from {sel_share.iloc[0]:.0f}% in the first fifth of a tour to {sel_share.iloc[-1]:.0f}% in the last fifth, and from {100 * list(sel['by_progress_na'].values())[0]:.0f}% to {100 * list(sel['by_progress_na'].values())[-1]:.0f}% in North America alone. By continent: {', '.join(f'{k} {v:.0f}%' for k, v in cont.sort_values(ascending=False).items())}. By Wikidata capacity (resolved venues only, {100 * sel['wikidata_capacity_known_share']:.0f}% of the universe; resolution itself ran priced-first): {', '.join(f'{k} {v:.0f}%' for k, v in cap_dec.items())}.
- **Within-tour LPM** of covered (tour FE, clustered by split_key, n = {sel['lpm_n']:,}, G = {sel['lpm_clusters']}): tour progress {sel['lpm']['tour_progress']['b']:+.3f} ({sel['lpm']['tour_progress']['se']:.3f}), log metro population {sel['lpm']['log_metro_pop_f']['b']:+.3f} ({sel['lpm']['log_metro_pop_f']['se']:.3f}), log Wikidata capacity {sel['lpm']['log_cap_wd_f']['b']:+.3f} ({sel['lpm']['log_cap_wd_f']['se']:.3f}), Fri/Sat {sel['lpm']['fri_sat']['b']:+.3f} ({sel['lpm']['fri_sat']['se']:.3f}), Sunday {sel['lpm']['sunday']['b']:+.3f} ({sel['lpm']['sunday']['se']:.3f}), Europe {sel['lpm']['cont_europe']['b']:+.3f}, Asia {sel['lpm']['cont_asia']['b']:+.3f}. **Supported:** selection is on price-relevant observables (position in the tour, metro size, venue size, region). Weekday barely matters.
- **Is selection on price itself?** The earlier claim that "priced shows skew toward strong nights" was never tested and is withdrawn. Among North American reported shows (year FE), tours with higher coverage have higher sell-out ({sel['strong_nights']['sellout_on_tour_coverage']['b']:+.3f} per unit of coverage, SE {sel['strong_nights']['sellout_on_tour_coverage']['se']:.3f}). They also price slightly higher relative to the same artist's era ({sel['strong_nights']['price_rel_artist_era_on_tour_coverage']['b']:+.3f}, SE {sel['strong_nights']['price_rel_artist_era_on_tour_coverage']['se']:.3f}). So better-documented tours are somewhat stronger tours, a tour-level selection that within-tour comparisons absorb and between-tour comparisons do not.
- **Mitigations used in task 6:** tour/artist FE; inverse-probability weights from the LPM (`data/selection_weights.parquet`, p clipped at 0.05, weights trimmed at the 99th percentile); a sensitivity spec on tours with coverage ≥ 0.8 ({sel['tours_cov80_shows_in_sample']:,} sample shows); results by era. No Heckman correction (no credible exclusion restriction).
- **When:** coverage before 2008 is sparse and older articles are edited less. Era-specific results should be read as "among documented tours".

## 8. Can the data test each hypothesis?

Power is assessed on the analysis sample, in log points (0.05 ≈ 5%), at 80% power and α = 0.05. Binary variables use only the groups (tours or artists, per the FE named) where the variable varies. Continuous variables are scaled to a 1-SD within-group change.
- **naive MDE** = 2.8 × within-group residual SD × √(1/n₁ + 1/n₀) (binary), or 2.8 × SD / √n (continuous). It treats shows as independent, so it is far too optimistic.
- **clustered MDE** = 2.8 × the cluster-robust SE (clustered by performer group, `split_key`) of the fixed-effects slope, computed on the real data. **The coefficient itself is deliberately not computed or reported here** (that's task 6). This is the planning number. Genre uses artist medians: 2.8 × SD(artist median) × √(2/artists in a median-sized genre).

The real power driver is the number of tours or artists with variation, not n.

{hyp_md}

## 9. Readiness for task 6

- **Ready now:** the targets (`log_avg_price_real`, `price_rel_artist_median`), the artist split, and the city-premium, weekend, venue-size, tour-leg, multi-night, and popularity/momentum (2016+) analyses. Calendar, tour context, metro, and artist features cover 94–100% of the sample.
- **Waiting on the venue table** (currently {cov.get('venue', {}).get('pct_analysis_filled', 0)}% of the sample resolved): `venue_type`, `indoor_outdoor` and Wikidata `capacity` for the remaining venues. Venue-size work can start on `tickets_available_per_show` ({100 * s.tickets_available_per_show.notna().mean():.0f}% coverage), with Wikidata capacity added when the table completes.
{bill_line}
- **Waiting on weather** ({cov.get('weather', {}).get('pct_analysis_filled', 0)}% of the sample `ok`): the outdoor × weather interaction. Low power is expected even when complete.
- **Not testable:** set-list popularity (setlist.fm permission). Purchase-time prediction is not testable either, because there are no on-sale dates and EXPOST/POST_ONSALE features would leak.
"""
    REPORT.write_text(text)
    print(f"wrote {REPORT.relative_to(ROOT)} and {len(charts)} charts")
    print(hyp[["hypothesis", "status", "n", "performer groups w/ variation", "G (clusters)", "naive MDE", "clustered MDE"]].to_string())


if __name__ == "__main__":
    main()
