"""Skeptic review 4 (task 9 PATH): independent recompute of P1 from the raw forward DB (read-only)."""
import sqlite3
import numpy as np
import pandas as pd
from statsmodels.stats.proportion import proportion_confint

con = sqlite3.connect("file:data/forward/tm_forward.sqlite?mode=ro", uri=True)
cols = [r[1] for r in con.execute("PRAGMA table_info(snapshots)")]
print("snapshot cols:", [c for c in cols if c in ("event_id", "snap_date", "http_status", "price_min", "price_max", "days_until_show", "hours_until_show", "event_status")])
s = pd.read_sql("select event_id, snap_date, http_status, price_min, price_max, days_until_show, hours_until_show, event_status from snapshots", con)
w = pd.read_sql("select event_id, source, selected_for_ranges from watchlist", con)
s = s[s.http_status == 200].copy()
print("200 snapshots:", len(s), "events:", s.event_id.nunique(), "days:", sorted(s.snap_date.unique()))
s = s[~(s.hours_until_show.notna() & (s.hours_until_show <= 0))]
print("after dropping at/after show start:", len(s))
s["priced"] = s.price_min.notna() & (s.price_min > 0)
s["d"] = pd.to_datetime(s.snap_date)
s = s.sort_values(["event_id", "d"])
g = s.groupby("event_id")
s["prev_d"] = g.d.shift(); s["pmin"] = g.price_min.shift(); s["pmax"] = g.price_max.shift(); s["ppriced"] = g.priced.shift()
p = s[(s.d - s.prev_d).dt.days == 1]
pp = p[p.priced & p.ppriced.astype(bool)]
mv = ((pp.price_min - pp.pmin).abs() > 0.005) | ((pp.price_max - pp.pmax).abs() > 0.005)
lo, hi = proportion_confint(int(mv.sum()), len(pp), method="wilson")
print(f"day-pairs {len(p)}, priced pairs {len(pp)}, moves {int(mv.sum())} = {mv.mean():.4%} [{lo:.4%}, {hi:.4%}]")
ev = pp.assign(m=mv).groupby("event_id").m.any()
print("events moved:", int(ev.sum()), "of", len(ev), "| moves per moving event:", pp.assign(m=mv).groupby("event_id").m.sum()[ev].value_counts().to_dict())
# who moved: days out, and is the share 'near show' driven by few events?
print("moves by days_until_show:", pp[mv].days_until_show.describe()[["min", "50%", "max"]].to_dict())
# share of priced pairs > 30 days out
print("share of priced pairs >= 30 days out: %.3f" % (pp.days_until_show >= 30).mean())
# early-data contamination: pairs from snapshot dates <= 2026-10-21
print("priced pairs with later snapshot <= 2026-10-21:", int((pp.d <= "2026-10-21").sum()))
