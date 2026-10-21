"""Skeptic review 1, round 2: verify the analyst's fixes on the rebuilt shows.parquet."""
import re
import numpy as np
import pandas as pd
pd.set_option("display.width", 250)
d = pd.read_parquet("data/shows.parquet")
s = d[d.analysis_sample].copy()
print("rows", len(d), "sample", len(s), "artist_ids", s.artist_id.nunique(), "split_keys", s.split_key.nunique())
# 1. leak codes
codes = {}
for line in open("data/DATA_DICTIONARY.md"):
    if line.startswith("| `"):
        p = [x.strip() for x in line.split("|")]
        codes[p[1].strip("`")] = p[8]
for c in ["tour_infobox_gross", "tour_infobox_attendance", "n_priced_shows", "artist_n_analysis", "has_venue", "has_weather",
          "tour_page_id", "n_tours_started_by_show_year", "venue_run_position", "price_rel_artist_median", "price_rel_tour", "price_rel_artist_era"]:
    print(f"  {c}: {codes.get(c, 'MISSING')[:60]}")
# 2. dup re-scan on the new sample
k = s[s.tickets_sold.gt(1000)].groupby(["show_date", "tickets_sold"]).filter(lambda g: g.artist_key.nunique() > 1)
print("cross-artist same date+tickets remaining:", len(k))
if len(k): print(k[["show_id", "gross_usd", "tickets_sold"]].to_string())
a = s[s.duplicated(["artist_key", "show_date", "gross_usd"], keep=False)]
print("same artist+date+gross remaining:", len(a))
b = s[s.duplicated(["artist_key", "gross_usd", "tickets_sold"], keep=False)]
print("same artist+gross+tickets (any date) remaining:", len(b))
m = pd.read_csv("data/manual/boxoffice_dedupe.csv")
print("manual dedupe rows:", len(m), "| cols:", list(m.columns)[:8])
# 4. split pairs
pairs = [("nsync", "justin-timberlake"), ("one-direction", "niall-horan"), ("one-direction", "harry-styles"), ("one-direction", "louis-tomlinson"),
         ("bts", "jin"), ("bts", "suga"), ("fleetwood-mac", "stevie-nicks"), ("genesis", "phil-collins"), ("pink-floyd", "roger-waters"),
         ("pink-floyd", "david-gilmour"), ("take-that", "robbie-williams"), ("michael-jackson", "the-jacksons"), ("queen", "queen-adam-lambert"),
         ("queen", "adam-lambert"), ("the-carters", "beyonce"), ("the-carters", "jay-z"), ("jonas-brothers", "demi-lovato-and-nick-jonas"),
         ("eagles", "the-eagles"), ("selena-gomez", "selena-gomez-the-scene"), ("the-police", "sting"), ("oasis", "noel-gallagher-s-high-flying-birds"),
         ("bigbang", "g-dragon"), ("backstreet-boys", "nkotbsb")]
sp = d.groupby("artist_id").artist_split.first()
bad = [(x, y, sp.get(x), sp.get(y)) for x, y in pairs if x in sp and y in sp and sp[x] != sp[y]]
print("cross-split pairs remaining:", bad)
ak = d.groupby("artist_id").artist_key.first()
print("alias keys: eagles", ak.get("eagles"), "the-eagles", ak.get("the-eagles"), "| selena", ak.get("selena-gomez"), ak.get("selena-gomez-the-scene"))
print("non-performers in sample:", [x for x in ["cirque-du-soleil", "american-idol", "glee-cast", "various-artists", "honda-civic-tour",
      "vanessa-hudgens-ashley-tisdale-lucas-grabeel-corbin-bleu-monique-coleman-and-drew-seeley", "ramin-djawadi", "american-idol-finalists"] if x in set(s.artist_id)])
print("split rows:", s.artist_split.value_counts().to_dict())
# 5. targets
for t in ["price_rel_tour", "price_rel_artist_era"]:
    if t in s:
        print(t, "non-null", int(s[t].notna().sum()))
tk = "tour_key"
span = s.groupby(tk).show_date.agg(lambda x: (x.max() - x.min()).days / 365.25)
n = s.groupby(tk).size()
print("tour_keys with >=5 shows spanning >3y:", int(((span > 3) & (n >= 5)).sum()), "rows", int(s[tk].isin(span[(span > 3) & (n >= 5)].index).sum()))
print(span[(span > 3) & (n >= 5)].sort_values(ascending=False).head(8).round(1).to_dict())
if "price_rel_tour" in s:
    yr = s.show_date.dt.year + s.show_date.dt.dayofyear / 366
    yw = yr - yr.groupby(s[tk]).transform("median")
    mm = s.price_rel_tour.notna()
    print("corr(price_rel_tour, within-tour year):", round(float(np.corrcoef(s.price_rel_tour[mm], yw[mm])[0, 1]), 3))
era_cols = [c for c in s.columns if "era" in c]
print("era cols:", era_cols)
# 6/7/9
print("country_final unknown in sample:", int(s.country_final.isna().sum()) if "country_final" in s else "no col",
      "| usd_assumed_non_us:", int(s.usd_assumed_non_us.sum()))
w = pd.read_parquet("data/selection_weights.parquet")
print("weights:", w.shape, list(w.columns)[:6]); print(w.describe().round(3).to_string())
print("cpi_deflate_date present:", "cpi_deflate_date" in s, "| katy residency deflate date:",
      s.loc[s.show_id.str.startswith("katy-perry__2021-12-29"), "cpi_deflate_date"].tolist() if "cpi_deflate_date" in s else None)
