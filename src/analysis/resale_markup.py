"""Resale vs face for 2023-24 US shows: Landers' SeatGeek end-of-sale prices joined to Wikipedia tour-table face prices.

Input (local, not committed): data/raw/landers/event_labels_1_18_2025_last_N_days.csv, from
github.com/jonland82/seatgeek-beta-modeling (CC BY-NC 4.0; cite arXiv 2507.23767). Each row is one show's SeatGeek
low/median/high listing price averaged over its last 14 daily snapshots (the repo's create_seatgeek_training_dataset
notebook), so it says nothing about timing within the sales window.
Face: data/shows.parquet avg_price_usd (reported gross / tickets sold, no fees). Join: normalized artist + show date.
Output: reports/resale_markup.md (aggregates only).
"""
import re
import unicodedata
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "data/raw/landers/event_labels_1_18_2025_last_N_days.csv"


def norm(s):
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]", "", re.sub(r"^the\s+", "", s))


def build():
    lan = pd.read_csv(SRC)
    lan["d"], lan["k"] = pd.to_datetime(lan.date).dt.date, lan.act.map(norm)
    s = pd.read_parquet(ROOT / "data/shows.parquet", columns=["artist_name", "show_date", "is_us", "avg_price_usd",
                                                               "sellout_ratio", "day_of_week", "tour_title"])
    s = s[s.is_us == True]  # noqa: E712
    s["d"], s["k"] = pd.to_datetime(s.show_date).dt.date, s.artist_name.map(norm)
    m = lan.merge(s, on=["k", "d"]).dropna(subset=["avg_price_usd"])
    m = m[m.avg_price_usd > 0].drop_duplicates("event_id")
    return m.assign(r_low=m.lowest_price / m.avg_price_usd, r_med=m.median_price / m.avg_price_usd), len(lan)


def main():
    m, n_lan = build()
    q = lambda x: f"{x.median():.2f} (middle half {x.quantile(.25):.2f}–{x.quantile(.75):.2f})"  # noqa: E731
    acts = (m.groupby("act").agg(n=("event_id", "size"), face=("avg_price_usd", "median"), low=("lowest_price", "median"),
                                 med=("median_price", "median"), r_med=("r_med", "median"), r_low=("r_low", "median"))
            .query("n >= 4").sort_values("r_med", ascending=False))
    rows = "\n".join(f"| {a} | {r.n} | ${r.face:.0f} | ${r.low:.0f} | ${r.med:.0f} | {r.r_low:.2f} | {r.r_med:.2f} |"
                     for a, r in acts.iterrows())
    so = m.assign(g=m.sellout_ratio >= 0.99).groupby("g").r_med.agg(["size", "median"])
    wk = m.assign(g=m.day_of_week.astype(str).isin(["Friday", "Saturday", "4", "5"])).groupby("g").r_med.agg(["size", "median"])
    out = f"""# Resale vs face, 2023–24 US shows (end of sales window)

Data: {len(m)} shows ({m.act.nunique()} acts, {m.tour_title.nunique()} tours) matched out of {n_lan:,} in Landers'
SeatGeek file (arXiv 2507.23767, CC BY-NC 4.0) to face prices from Wikipedia tour tables (gross ÷ tickets, no fees).
Resale = SeatGeek listing prices **averaged over each show's last 14 days**. One number per show, so this says how
far resale ends from face, not **when** in the sales window prices move. Listings are asking prices, and whether
SeatGeek's figures include fees isn't stated. Treat ratios as approximate.

| Measure (resale ÷ average face) | Median |
|---|---|
| Median listing | {q(m.r_med)} |
| Cheapest listing | {q(m.r_low)} |

- The median listing was above face on {(m.r_med > 1).mean():.0%} of shows.
- The cheapest listing was **below** the average face price on {(m.r_low < 1).mean():.0%} of shows. In the last two
  weeks, a get-in seat usually cost less than the average ticket sold at face (the average includes premium seats).
- Sold-out shows (≥99% sold): median ratio {so.loc[True, 'median']:.2f} (n={so.loc[True, 'size']}) vs
  {so.loc[False, 'median']:.2f} (n={so.loc[False, 'size']}).
- Friday/Saturday: {wk.loc[True, 'median']:.2f} (n={wk.loc[True, 'size']}) vs other days {wk.loc[False, 'median']:.2f}
  (n={wk.loc[False, 'size']}).

By act (≥4 matched shows; medians):

| Act | Shows | Face avg | Resale low | Resale median | Low ÷ face | Median ÷ face |
|---|---|---|---|---|---|---|
{rows}

Limits: 17 big acts only, one season, so this isn't a market-wide estimate and has no time path. The daily
series behind it is in the request to Landers (price-timeline `docs/DATA_REQUESTS.md` 4d).
"""
    (ROOT / "reports/resale_markup.md").write_text(out)
    print(out)


if __name__ == "__main__":
    main()
