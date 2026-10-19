# features_calendar.parquet

One row per `show_id` in `shows_base.parquet`. Built by `src/features_calendar.py`, fully offline, from the show date plus the `holidays` PyPI package (v0.106, MIT; source A10). Every feature is known when the tour is announced, so there is **no leakage**.

The show date is the local calendar date as reported in the tour table. No time of day is assumed.

| column | type | unit / values | source | null meaning |
|---|---|---|---|---|
| show_id | string | | spine | never null |
| year | Int16 | | date | show date missing |
| month | Int16 | 1-12 | date | show date missing |
| quarter | Int16 | 1-4 | date | show date missing |
| day_of_week | Int16 | 0 = Mon … 6 = Sun | date | show date missing |
| day_name | string | Monday … | date | show date missing |
| day_type | string | `mon_thu`, `fri_sat`, `sunday` | date | show date missing |
| is_fri_sat | boolean | Friday or Saturday night | date | show date missing |
| is_sunday | boolean | kept separate from Fri/Sat (next day is a workday) | date | show date missing |
| season_nh | string | winter (DJF), spring (MAM), summer (JJA), fall (SON) | month | show date missing |
| season_local | string | as `season_nh`, flipped for southern-hemisphere countries AU, NZ, AR, CL, UY, PY, ZA, BR | month + country | show date missing |
| is_dec_holiday_period | boolean | Dec 15 – Jan 2 | date | show date missing |
| holiday_calendar_available | boolean | the country is supported by `holidays` | country | show date missing |
| is_public_holiday | boolean | the date is a public holiday in the show's country | `holidays` | country unknown or unsupported |
| public_holiday_name | string | e.g. `Independence Day` | `holidays` | not a holiday, or no calendar |
| is_holiday_eve | boolean | the **next** day is a public holiday (a "Saturday-like" night) | `holidays` | no calendar |
| is_holiday_adjacent | boolean | holiday on the date, the day before, or the day after | `holidays` | no calendar |
| is_long_weekend | boolean | the date falls in a long weekend: a Monday holiday → Fri–Mon; a Friday holiday → Thu–Sun | `holidays` | no calendar |
| long_weekend_holiday | string | the holiday that creates the long weekend | `holidays` | not in a long weekend, or no calendar |
| is_us | boolean | country is US | spine | never null (False when country unknown) |
| us_holiday_weekend | string | `memorial_day`, `labor_day` (Fri–Mon), `thanksgiving` (Wed–Sun), `july_4th` (Jul 3–5, extended to the adjoining weekend when the 4th is Mon/Tue/Thu/Fri), `new_years_eve` (Dec 30 – Jan 1) | fixed rules in code | non-US show, or not a named holiday weekend |
| is_us_holiday_weekend | boolean | `us_holiday_weekend` is set | rules | non-US show |
| is_us_summer_break_proxy | boolean | **proxy**: June 15 – August 25 inclusive | fixed rule | non-US show |

## Choices and caveats
- **US holidays** are the federal calendar (no state subdivision), including observed days such as `(observed)` Fridays and Mondays. State holidays (e.g. Patriots' Day) are not included.
- **UK holidays** use England (`subdiv=ENG`), because most UK shows are in England. Scottish, Welsh and Northern Irish bank holidays differ slightly. Other countries use their national calendar only, with no regional holidays.
- Countries the `holidays` package doesn't support, and rows whose country couldn't be mapped to ISO2, have null holiday fields (`holiday_calendar_available = False`).
- **School calendars: no clean national source exists** (SOURCES.md gap 6). `is_us_summer_break_proxy` is a fixed-date proxy. Real US districts end between late May and late June and restart between early August and early September, so the edges are noisy. Non-US shows get null. Use it as a coarse control, not as a measured break.
- New Year's Eve and Christmas fall under `is_dec_holiday_period` for every country. `us_holiday_weekend = new_years_eve` is set only for US shows.
- Seasons are meteorological and hemisphere-adjusted by country, not by latitude. Tropical venues (e.g. Mexico City, Singapore) still get temperate season labels. Use weather features for actual conditions.
