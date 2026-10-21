"""Skeptic review 1: look for performers that straddle artist_split despite split_key."""
import re
import unicodedata
from itertools import combinations
import pandas as pd

d = pd.read_parquet("data/shows.parquet")
s = d[d.analysis_sample]
a = (s.groupby("artist_id").agg(name=("artist_name", "first"), split=("artist_split", "first"),
                                 sk=("split_key", "first"), ak=("artist_key", "first"),
                                 qid=("artist_qid", "first"), link=("artist_wikilink", "first"),
                                 nh=("n_headliners", "first"), n=("show_id", "size"))
     .reset_index())

STOP = {"the", "and", "band", "of", "with", "featuring", "feat", "ft", "tour", "his", "her", "their",
        "e", "street", "orchestra", "live", "list", "performances", "concerts", "a", "y", "los", "las", "el", "la",
        "de", "les", "x", "vs"}


def toks(n: str) -> set[str]:
    n = unicodedata.normalize("NFKD", n).encode("ascii", "ignore").decode().lower()
    n = n.replace("!", "i")
    return {t for t in re.split(r"[^a-z0-9]+", n) if len(t) > 2 and t not in STOP}


a["toks"] = a.name.map(toks)
rows = []
for i, j in combinations(range(len(a)), 2):
    x, y = a.iloc[i], a.iloc[j]
    if x.sk == y.sk:
        continue
    common = x.toks & y.toks
    if not common:
        continue
    # require that the smaller name's tokens are mostly contained in the larger
    small = min(len(x.toks), len(y.toks)) or 1
    if len(common) / small >= 0.5:
        rows.append(dict(a=x.artist_id, a_split=x.split, a_n=x.n, b=y.artist_id, b_split=y.split, b_n=y.n,
                         common=" ".join(sorted(common)), cross=x.split != y.split))
r = pd.DataFrame(rows).sort_values(["cross", "common"], ascending=[False, True])
pd.set_option("display.width", 250)
pd.set_option("display.max_rows", 400)
print(r.to_string())
print("cross-split candidate pairs:", int(r.cross.sum()))

# components with >1 artist_id
comp = s.groupby("split_key").artist_id.unique()
print("\nmulti-id components:")
for k, v in comp[comp.map(len) > 1].items():
    print(k, list(v))

# headliner wikilinks that point to a performer present as its own artist under another split_key
print("\nartists with missing QID in sample:", a.qid.isna().sum(), "rows:", int(a.loc[a.qid.isna(), "n"].sum()))
print(a.loc[a.qid.isna(), ["artist_id", "n", "split", "link"]].to_string())
