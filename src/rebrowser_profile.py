"""Profile the downloaded Rebrowser preview datasets (data/raw/rebrowser/) for PATH suitability.

For each dataset/entity: rows, files, columns, which fields are locked ("[PREMIUM]"), date coverage
of the daily files and of _firstSeenAt/_lastSeenAt, events covered, concert share, and how many
events have listings observed across >= 2 / >= 7 distinct snapshot days and how far before the show.

Usage: .venv/bin/python src/rebrowser_profile.py > data/interim/rebrowser_profile.txt
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "rebrowser"
PREMIUM = "[PREMIUM]"


def load(entity_dir: Path) -> pd.DataFrame:
    files = sorted(entity_dir.glob("data/*.parquet")) or sorted(entity_dir.glob("*.parquet"))
    if not files:
        return pd.DataFrame()
    frames = []
    for f in files:
        df = pd.read_parquet(f)
        df["_file"] = f.stem
        frames.append(df)
    return pd.concat(frames, ignore_index=True)


def locked_cols(df: pd.DataFrame) -> list[str]:
    out = []
    for c in df.columns:
        s = df[c].dropna().astype(str)
        if len(s) and (s == PREMIUM).mean() > 0.99:
            out.append(c)
    return out


def ts(s: pd.Series) -> pd.Series:
    return pd.to_datetime(s, errors="coerce", utc=True)


def profile_entity(name: str, df: pd.DataFrame) -> None:
    print(f"\n## {name}: {len(df):,} rows, {df['_file'].nunique() if '_file' in df else 0} file(s)")
    if df.empty:
        return
    print("columns:", ", ".join(c for c in df.columns if c != "_file"))
    print("LOCKED ([PREMIUM]):", ", ".join(locked_cols(df)) or "none")
    if "_file" in df and df["_file"].str.match(r"\d{4}-\d{2}-\d{2}").any():
        print(f"daily files: {df['_file'].min()} .. {df['_file'].max()}")
    for c in ("_firstSeenAt", "_lastSeenAt", "createdAt"):
        if c in df:
            t = ts(df[c])
            print(f"{c}: {t.min()} .. {t.max()}")
    if "_firstSeenAt" in df and "_lastSeenAt" in df:
        life = (ts(df["_lastSeenAt"]) - ts(df["_firstSeenAt"])).dt.total_seconds() / 86400
        print(f"record lifetime (lastSeen - firstSeen, days): median {life.median():.2f}, "
              f"p90 {life.quantile(.9):.2f}, share 0: {(life <= 0.01).mean():.0%}")
    if "eventId" in df:
        print(f"distinct eventId: {df['eventId'].nunique():,}")
        if "_file" in df:
            per_ev = df.groupby("eventId")["_file"].nunique()
            print(f"events seen on >=2 daily files: {(per_ev >= 2).sum():,}; >=7: {(per_ev >= 7).sum():,}; "
                  f"max days for one event: {per_ev.max()}")
    for c in ("category", "taxonomyName", "type", "eventCategory"):
        if c in df:
            print(f"{c} counts:", df[c].value_counts().head(8).to_dict())
    unlocked_price_proxies = [c for c in ("medianPriceBucket", "isUnderHundred", "dealBucket", "deal",
                                          "hasActiveListings", "eventAvailabilityState") if c in df]
    if unlocked_price_proxies:
        print("unlocked coarse price/availability proxies:", unlocked_price_proxies)
        for c in unlocked_price_proxies:
            print(f"  {c}:", df[c].astype(str).value_counts(dropna=False).head(6).to_dict())


def path_check_stubhub() -> None:
    ev = load(RAW / "stubhub-dataset" / "events")
    li = load(RAW / "stubhub-dataset" / "event-listings")
    if ev.empty or li.empty:
        return
    print("\n## StubHub PATH check (listings joined to events)")
    ev = ev.assign(eventId=ev["eventId"].astype("Int64").astype(str))
    start = ev.drop_duplicates("eventId").set_index("eventId")["eventStartDatetime"]
    li = li.assign(eventId=li["eventId"].astype(str))
    joined = li["eventId"].isin(start.index)
    print(f"listing rows whose event is in the events sample: {joined.mean():.1%}")
    j = li[joined].copy()
    if j.empty:
        return
    j["days_out"] = (ts(j["eventId"].map(start)) - ts(j["_firstSeenAt"])).dt.total_seconds() / 86400
    print("days from listing firstSeen to show:", j["days_out"].describe(percentiles=[.1, .5, .9]).round(1).to_dict())
    per = j.groupby("eventId").agg(n=("listingId", "size"), days=("_file", "nunique"),
                                   span=("days_out", lambda s: s.max() - s.min()))
    print(f"events with listings: {len(per):,}; listings/event median {per['n'].median():.0f}; "
          f"events with >=7 snapshot days: {(per['days'] >= 7).sum()}; span of days_out p90 {per['span'].quantile(.9):.1f}")
    # medianPriceBucket over time per event (the only unlocked price signal on events)
    if "medianPriceBucket" in ev:
        e = ev.assign(days_out=(ts(ev["eventStartDatetime"]) - pd.to_datetime(ev["_file"], utc=True)).dt.days)
        multi = e.groupby("eventId")["medianPriceBucket"].nunique()
        print(f"events tracked on >=2 days: {(e.groupby('eventId')['_file'].nunique() >= 2).sum():,}; "
              f"of which medianPriceBucket ever changes: {(multi > 1).sum():,}")


def main() -> int:
    if not RAW.exists():
        print("no data/raw/rebrowser; run src/rebrowser_download.py first", file=sys.stderr)
        return 1
    for ds in sorted(p for p in RAW.iterdir() if p.is_dir() and p.name.endswith("-dataset")):
        print(f"\n# {ds.name}")
        for ent in sorted(p for p in ds.iterdir() if p.is_dir()):
            profile_entity(f"{ds.name}/{ent.name}", load(ent))
    path_check_stubhub()
    return 0


if __name__ == "__main__":
    sys.exit(main())
