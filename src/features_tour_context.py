"""Tour-context features per show, derived only from shows_base -> data/interim/features_tour_context.parquet.

No network. Metro grouping uses data/interim/venue_metro.parquet (written by features_metro.py) when it
exists, otherwise country + city slug.
"""
from __future__ import annotations

import re

import pandas as pd

from context_http import out_dir, load_spine, slugify

TOUR_GAP_DAYS = 180     # inferred tours: split an artist's shows at gaps longer than this
LEG_GAP_DAYS = 21       # inferred legs: split at gaps longer than this, or on a continent change
ADDED_RUN_GAP_DAYS = 7  # same venue, same tour, within this many days of the previous date -> one "run"
# shows_base `leg` is the nearest section heading; these headings are layout, not legs.
GENERIC_LEG = re.compile(r"^\s*(tour dates?|dates|shows|concerts?|concert dates|list of (concerts|shows|tour dates)|"
                         r"box ?office( data| score)?|schedule|setlists?|cancell?ed( shows| dates| concerts)?|"
                         r"postponed.*|rescheduled.*|headlining|headline shows?|festivals?|fan concerts?|concert tours?|"
                         r"opening acts?|supporting acts?|other (shows|performances)|one-off.*)\s*$", re.IGNORECASE)
CANCELLED = re.compile(r"cancel", re.IGNORECASE)

CONTINENT = {
    **dict.fromkeys("US CA MX PR".split(), "north_america"),
    **dict.fromkeys("GT CR PA DO BR AR CL CO PE UY PY EC VE".split(), "latin_america"),
    **dict.fromkeys(("GB IE FR DE NL BE LU CH AT IT ES PT DK SE NO FI IS PL CZ HU SK SI HR RS RO BG GR TR "
                     "RU UA EE LV LT").split(), "europe"),
    **dict.fromkeys("IL AE SA QA BH KW EG ZA MA NG KE".split(), "mea"),
    **dict.fromkeys("IN JP KR CN HK TW SG MY TH ID PH VN".split(), "asia"),
    **dict.fromkeys("AU NZ".split(), "oceania"),
}


def _metro_keys(df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    city_key = df.country_iso2.fillna("xx").str.lower() + ":" + df.city.fillna("").map(slugify)
    source = pd.Series("city", index=df.index)
    path = out_dir() / "venue_metro.parquet"
    if path.exists():
        vm = pd.read_parquet(path)[["venue_id", "cbsa_code"]].dropna().drop_duplicates("venue_id")
        cbsa = df.venue_id.map(vm.set_index("venue_id").cbsa_code)
        has = cbsa.notna()
        city_key = city_key.where(~has, "cbsa:" + cbsa.astype("string"))
        source = source.where(~has, "cbsa")
    return city_key, source


def _split_on_gaps(dates: pd.Series, gap_days: int, extra_break: pd.Series | None = None) -> pd.Series:
    brk = dates.diff().dt.days.gt(gap_days)
    if extra_break is not None:
        brk |= extra_break
    return brk.cumsum()


def _usable_legs(legs: pd.Series) -> bool:
    """Source legs are used only when every show has one, there are >= 2, and none is a generic heading."""
    legs = legs.astype("string").str.strip()
    return bool(legs.notna().all() and legs.nunique() >= 2 and not legs.str.match(GENERIC_LEG).any())


def build(spine: pd.DataFrame) -> pd.DataFrame:
    df_all = spine.dropna(subset=["date"]).copy()
    note = df_all["status_note"] if "status_note" in df_all else pd.Series(pd.NA, index=df_all.index)
    df_all["is_cancelled"] = note.astype("string").str.contains(CANCELLED).fillna(False).astype(bool)
    cancelled = df_all.loc[df_all.is_cancelled, ["show_id"]].assign(is_cancelled=True)
    df = df_all[~df_all.is_cancelled].copy()  # positions and counts describe shows that were played
    df["continent"] = df.country_iso2.map(CONTINENT)
    df["metro_key"], df["metro_key_source"] = _metro_keys(df)
    df = df.sort_values(["artist_id", "date", "show_id"]).reset_index(drop=True)

    # Tour: the reported tour name when present; otherwise infer from date gaps within the artist.
    has_tour = df.tour.notna() & (df.tour.astype("string").str.strip() != "")
    inferred = df.groupby("artist_id", group_keys=False).date.apply(
        lambda s: _split_on_gaps(s, TOUR_GAP_DAYS)).astype(int)
    df["tour_key"] = (df.artist_id + "::" + df.tour.astype("string").fillna("")).where(
        has_tour, df.artist_id + "::inferred-" + inferred.astype(str))
    df["tour_inferred"] = ~has_tour

    # Leg: the reported leg when present (in date order); otherwise date gaps or a continent change.
    leg_ids, inferred_tours = [], set()
    for key, g in df.groupby("tour_key", sort=False):
        if _usable_legs(g.leg):
            first_seen = g.leg.astype("string").drop_duplicates().tolist()
            leg_ids.append(g.leg.astype("string").map({lg: i for i, lg in enumerate(first_seen)}))
        else:
            cont = g.continent.fillna("unknown")
            inferred_tours.add(key)
            leg_ids.append(_split_on_gaps(g.date, LEG_GAP_DAYS, cont.ne(cont.shift()) & g.index.to_series().ne(g.index[0])))
    df["leg_number"] = pd.concat(leg_ids).loc[df.index].astype(int) + 1
    df["leg_inferred"] = df.tour_key.isin(inferred_tours)

    t = df.groupby("tour_key")
    df["tour_n_shows"] = t.show_id.transform("size")
    df["tour_show_number"] = t.cumcount() + 1
    df["tour_start"] = t.date.transform("min")
    df["tour_end"] = t.date.transform("max")
    df["tour_span_days"] = (df.tour_end - df.tour_start).dt.days
    df["tour_n_legs"] = t.leg_number.transform("max")
    df["tour_n_countries"] = t.country_iso2.transform("nunique")
    df["days_since_tour_start"] = (df.date - df.tour_start).dt.days
    df["tour_progress"] = (df.tour_show_number - 1) / (df.tour_n_shows - 1).where(df.tour_n_shows > 1)
    df["is_first_show_of_tour"] = df.tour_show_number == 1
    df["is_last_show_of_tour"] = df.tour_show_number == df.tour_n_shows

    lg = df.groupby(["tour_key", "leg_number"])
    df["leg_n_shows"] = lg.show_id.transform("size")
    df["leg_show_number"] = lg.cumcount() + 1
    df["leg_span_days"] = (lg.date.transform("max") - lg.date.transform("min")).dt.days
    df["is_first_show_of_leg"] = df.leg_show_number == 1
    df["is_last_show_of_leg"] = df.leg_show_number == df.leg_n_shows

    a = df.groupby("artist_id")
    df["days_since_prev_show_artist"] = a.date.diff().dt.days
    df["days_to_next_show_artist"] = -a.date.diff(-1).dt.days

    m = df.groupby(["tour_key", "metro_key"])
    df["metro_n_dates_tour"] = m.show_id.transform("size")
    df["metro_date_rank"] = m.cumcount() + 1
    v = df.groupby(["tour_key", "venue_id"])
    df["venue_n_dates_tour"] = v.show_id.transform("size")
    df["venue_date_rank"] = v.cumcount() + 1

    # Added-date proxy: 2nd+ date of a run at the same venue (gaps <= ADDED_RUN_GAP_DAYS).
    run_break = v.date.diff().dt.days.gt(ADDED_RUN_GAP_DAYS) | df.venue_date_rank.eq(1)
    df["venue_run_id"] = run_break.groupby([df.tour_key, df.venue_id]).cumsum()
    r = df.groupby(["tour_key", "venue_id", "venue_run_id"])
    df["venue_run_length"] = r.show_id.transform("size")
    df["venue_run_position"] = r.cumcount() + 1
    df["is_added_date_proxy"] = df.venue_run_position >= 2
    df["is_multi_night_run"] = df.venue_run_length >= 2

    ann = df.tour_announced_date if "tour_announced_date" in df else pd.Series(pd.NaT, index=df.index)
    days = (df.date - pd.to_datetime(ann)).dt.days
    df["days_announce_to_show"] = days.where(days >= 0)

    df["is_cancelled"] = False
    cols = ["show_id", "is_cancelled", "tour_key", "tour_inferred", "leg_number", "leg_inferred", "continent",
            "tour_n_shows", "tour_show_number", "tour_span_days", "tour_n_legs", "tour_n_countries",
            "days_since_tour_start", "tour_progress", "is_first_show_of_tour", "is_last_show_of_tour",
            "leg_n_shows", "leg_show_number", "leg_span_days", "is_first_show_of_leg", "is_last_show_of_leg",
            "days_since_prev_show_artist", "days_to_next_show_artist",
            "metro_key", "metro_key_source", "metro_n_dates_tour", "metro_date_rank",
            "venue_n_dates_tour", "venue_date_rank", "venue_run_length", "venue_run_position",
            "is_multi_night_run", "is_added_date_proxy", "days_announce_to_show"]
    out = pd.concat([df[cols], cancelled], ignore_index=True)
    # Cancelled rows carry nulls, so use nullable dtypes throughout.
    for c in out.columns:
        if c.startswith(("is_", "tour_inferred", "leg_inferred")):
            out[c] = out[c].astype("boolean")
        elif c in ("tour_progress",):
            continue
        elif c.startswith(("tour_n", "tour_show", "tour_span", "leg_n", "leg_show", "leg_span", "leg_number",
                           "days_", "metro_n", "metro_date", "venue_")):
            out[c] = out[c].astype("Int32")
    return out


def main() -> None:
    spine = load_spine()
    out = build(spine)
    missing = len(spine) - len(out)
    path = out_dir() / "features_tour_context.parquet"
    out.to_parquet(path, index=False)
    print(f"wrote {path}: {len(out)} rows ({missing} spine rows without a date dropped)")
    print(out.notna().mean().round(3).to_string())


if __name__ == "__main__":
    main()
