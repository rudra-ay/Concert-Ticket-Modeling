"""Calendar features per show (A10) -> data/interim/features_calendar.parquet (+ .md).

Fully offline: the `holidays` package (MIT). No network.
All features are known long before the show date (no leakage).
"""
from __future__ import annotations

import datetime as dt
import warnings

import holidays
import pandas as pd

from context_http import out_dir, load_spine

SOUTHERN_HEMISPHERE = {"AU", "NZ", "AR", "CL", "UY", "PY", "ZA", "BR"}
SEASON_NH = {12: "winter", 1: "winter", 2: "winter", 3: "spring", 4: "spring", 5: "spring",
             6: "summer", 7: "summer", 8: "summer", 9: "fall", 10: "fall", 11: "fall"}
FLIP = {"winter": "summer", "summer": "winter", "spring": "fall", "fall": "spring"}

DEFAULT_SUBDIV = {"GB": "ENG"}
SUPPORTED = set(holidays.list_supported_countries())

# US summer-break proxy (no national school-calendar source exists): Jun 15 .. Aug 25 inclusive.
SUMMER_START = (6, 15)
SUMMER_END = (8, 25)


def _holiday_calendar(country: str, years: list[int]) -> holidays.HolidayBase | None:
    if country not in SUPPORTED:
        return None
    # US: federal calendar (no subdiv), including "(observed)" days.
    # GB: England (most UK shows; Scotland/Wales/NI bank holidays differ slightly).
    subdiv = DEFAULT_SUBDIV.get(country)
    with warnings.catch_warnings():  # out-of-range years are nulled per row in build()
        warnings.simplefilter("ignore", UserWarning)
        return holidays.country_holidays(country, subdiv=subdiv, years=years)


def _long_weekend_days(cal: holidays.HolidayBase) -> dict[dt.date, str]:
    """Days that belong to a long weekend created by a public holiday on Mon or Fri.

    Holiday on Monday -> Fri..Mon. Holiday on Friday -> Fri..Sun (plus Thu evening).
    Value is the holiday name driving the long weekend.
    """
    out: dict[dt.date, str] = {}
    for day, name in cal.items():
        wd = day.weekday()
        if wd == 0:
            span = [day - dt.timedelta(days=k) for k in (3, 2, 1, 0)]
        elif wd == 4:
            span = [day + dt.timedelta(days=k) for k in (-1, 0, 1, 2)]
        else:
            continue
        for d in span:
            out.setdefault(d, name)
    return out


def _us_named_weekend(d: dt.date) -> str | None:
    """Named US holiday weekends (fixed rules, independent of the holidays lib)."""
    y = d.year

    def nth_weekday(month: int, weekday: int, n: int) -> dt.date:
        first = dt.date(y, month, 1)
        return first + dt.timedelta(days=(weekday - first.weekday()) % 7 + 7 * (n - 1))

    def last_weekday(month: int, weekday: int) -> dt.date:
        nxt = dt.date(y + (month == 12), month % 12 + 1, 1)
        last = nxt - dt.timedelta(days=1)
        return last - dt.timedelta(days=(last.weekday() - weekday) % 7)

    memorial = last_weekday(5, 0)
    labor = nth_weekday(9, 0, 1)
    thanks = nth_weekday(11, 3, 4)
    if memorial - dt.timedelta(days=3) <= d <= memorial:
        return "memorial_day"
    if labor - dt.timedelta(days=3) <= d <= labor:
        return "labor_day"
    if thanks - dt.timedelta(days=1) <= d <= thanks + dt.timedelta(days=3):  # Wed..Sun
        return "thanksgiving"
    # July 4th: Jul 3-5, extended to the adjoining weekend when the 4th is Thu/Fri/Mon/Tue.
    j4 = dt.date(y, 7, 4)
    lo, hi = dt.date(y, 7, 3), dt.date(y, 7, 5)
    if j4.weekday() in (3, 4):
        hi = j4 + dt.timedelta(days=6 - j4.weekday())
    elif j4.weekday() in (0, 1):
        lo = j4 - dt.timedelta(days=j4.weekday() + 2)
    if lo <= d <= hi:
        return "july_4th"
    if (d.month == 12 and d.day >= 30) or (d.month == 1 and d.day == 1):
        return "new_years_eve"
    return None


def build(spine: pd.DataFrame) -> pd.DataFrame:
    df = spine[["show_id", "date", "country_iso2"]].copy()
    years = sorted({int(y) for y in df.date.dt.year.dropna()})
    span = list(range(min(years) - 1, max(years) + 2)) if years else []
    cals = {c: _holiday_calendar(c, span) for c in df.country_iso2.dropna().unique()}
    longw = {c: _long_weekend_days(cal) for c, cal in cals.items() if cal is not None}

    rows = []
    for r in df.itertuples(index=False):
        rec: dict = {"show_id": r.show_id}
        if pd.isna(r.date):
            rows.append(rec)
            continue
        d = r.date.date()
        wd = d.weekday()
        season = SEASON_NH[d.month]
        rec.update(
            year=d.year, month=d.month, quarter=(d.month - 1) // 3 + 1,
            day_of_week=wd, day_name=r.date.day_name(),
            day_type="fri_sat" if wd in (4, 5) else "sunday" if wd == 6 else "mon_thu",
            is_fri_sat=wd in (4, 5), is_sunday=wd == 6,
            season_nh=season,
            season_local=FLIP[season] if r.country_iso2 in SOUTHERN_HEMISPHERE else season,
            is_dec_holiday_period=(d.month == 12 and d.day >= 15) or (d.month == 1 and d.day <= 2),
        )
        cal = cals.get(r.country_iso2)
        if cal is not None and not (getattr(cal, "start_year", 0) <= d.year <= getattr(cal, "end_year", 9999)):
            cal = None  # e.g. Germany before 1991: no calendar rather than "no holiday"
        if cal is None:
            rec["holiday_calendar_available"] = False
        else:
            prev, nxt = d - dt.timedelta(days=1), d + dt.timedelta(days=1)
            rec.update(
                holiday_calendar_available=True,
                is_public_holiday=d in cal,
                public_holiday_name=cal.get(d),
                is_holiday_eve=nxt in cal,  # the next day is off: a "Saturday-like" night
                is_holiday_adjacent=(d in cal) or (prev in cal) or (nxt in cal),
                is_long_weekend=d in longw[r.country_iso2],
                long_weekend_holiday=longw[r.country_iso2].get(d),
            )
        if r.country_iso2 == "US":
            named = _us_named_weekend(d)
            rec["us_holiday_weekend"] = named
            rec["is_us_holiday_weekend"] = named is not None
            rec["is_us_summer_break_proxy"] = SUMMER_START <= (d.month, d.day) <= SUMMER_END
        rows.append(rec)

    out = pd.DataFrame(rows)
    bool_cols = ["is_fri_sat", "is_sunday", "is_dec_holiday_period", "holiday_calendar_available",
                 "is_public_holiday", "is_holiday_eve", "is_holiday_adjacent", "is_long_weekend",
                 "is_us_holiday_weekend", "is_us_summer_break_proxy"]
    for c in bool_cols:
        if c not in out:
            out[c] = pd.NA
        out[c] = out[c].astype("boolean")
    for c in ["public_holiday_name", "long_weekend_holiday", "us_holiday_weekend"]:
        if c not in out:
            out[c] = pd.NA
        out[c] = out[c].astype("string")
    for c in ["year", "month", "quarter", "day_of_week"]:
        out[c] = out[c].astype("Int16")
    out["is_us"] = (df.country_iso2 == "US").astype("boolean").values
    return out


def main() -> None:
    spine = load_spine()
    out = build(spine)
    path = out_dir() / "features_calendar.parquet"
    out.to_parquet(path, index=False)
    print(f"wrote {path}: {len(out)} rows")
    print(out.notna().mean().round(3).to_string())


if __name__ == "__main__":
    main()
