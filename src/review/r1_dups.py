"""Skeptic review 1: near-duplicate box office rows the exact (venue_id, date, gross) rule misses."""
import pandas as pd
pd.set_option("display.width", 250); pd.set_option("display.max_rows", 200)
d = pd.read_parquet("data/shows.parquet")
s = d[d.analysis_sample].copy()
s["city_n"] = s.city.fillna("").str.lower().str.replace(r"[^a-z]", "", regex=True)
# same date & tickets_sold, different artist_id (venue/gross may be spelled/rounded differently)
k = s[s.duplicated(["show_date", "tickets_sold"], keep=False) & s.tickets_sold.gt(1000)]
k = k.groupby(["show_date", "tickets_sold"]).filter(lambda g: g.artist_id.nunique() > 1)
print("same date+tickets_sold, >1 artist:", len(k))
print(k.sort_values(["show_date", "tickets_sold"])[["show_id", "artist_id", "artist_split", "venue_id", "gross_usd", "tickets_sold"]].head(60).to_string())
# same date & city & gross within 1%
s["g_r"] = (s.gross_usd / 1000).round()
k2 = s.groupby(["show_date", "city_n", "g_r"]).filter(lambda g: g.artist_id.nunique() > 1)
print("\nsame date+city+gross(1k rounding), >1 artist:", len(k2))
print(k2.sort_values(["show_date"])[["show_id", "artist_id", "artist_split", "gross_usd", "tickets_sold"]].head(60).to_string())
# within-artist duplicates (same artist, same gross+tickets, different date) -> copy/paste errors
k3 = s[s.duplicated(["artist_key", "gross_usd", "tickets_sold"], keep=False)]
print("\nsame artist_key, same gross+tickets, different rows:", len(k3))
print(k3.sort_values(["artist_key", "gross_usd"])[["show_id", "gross_usd", "tickets_sold", "aggregate_n_shows"]].head(40).to_string())
