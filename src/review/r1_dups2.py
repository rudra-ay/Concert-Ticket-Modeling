"""Skeptic review 1: quantify duplicates missed by venue_id-exact matching."""
import pandas as pd
pd.set_option("display.width", 250)
d = pd.read_parquet("data/shows.parquet")
s = d[d.analysis_sample]
# A. same artist_key, same date, same gross -> one show listed twice (venue spelling / two articles)
a = s[s.duplicated(["artist_key", "show_date", "gross_usd"], keep=False)]
print("A. same artist_key+date+gross in sample:", len(a), "rows,", a.groupby(["artist_key", "show_date"]).ngroups, "groups")
print(a.artist_key.value_counts().head(10).to_dict())
print(a.groupby(["artist_key", "show_date"]).tour_title.nunique().value_counts().to_dict(), "(n distinct tour articles per group)")
# B. same artist_key, same gross & tickets, different date -> copy/paste suspects
b = s[s.duplicated(["artist_key", "gross_usd", "tickets_sold"], keep=False)]
b = b[~b.index.isin(a.index)]
print("B. same artist_key+gross+tickets, different date:", len(b), "rows")
# C. cross-artist: same date, same tickets_sold (>1000), any venue spelling
c = s[s.tickets_sold.gt(1000)]
c = c.groupby(["show_date", "tickets_sold"]).filter(lambda g: g.artist_key.nunique() > 1)
known = d.dup_boxoffice_group.notna()
print("C. cross-artist same date+tickets in sample:", len(c), "rows; cross-split groups:",
      int(c.groupby(["show_date", "tickets_sold"]).artist_split.nunique().gt(1).sum()))
# full-table (incl. not-in-sample) count of same artist, same date, priced twice
p = d[d.avg_price_usd.notna()]
print("priced rows same artist_id+date (any venue):", int(p.duplicated(["artist_id", "show_date"], keep=False).sum()))
