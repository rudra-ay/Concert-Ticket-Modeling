"""Generate data/DATA_DICTIONARY.md for data/shows.parquet.

Units and meanings come from the collectors' dictionaries (data/interim/*.md),
parsed from their markdown tables; derived columns are described here. Called
by build_shows.py; can also be run alone after a build.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from analysis.targets import ROOT  # noqa: E402

MD_FOR_TABLE = {
    "shows_base": "shows_base.md",
    "artist": "features_artist.md",
    "artist_show": "features_artist.md",
    "venue": "features_venue.md",
    "metro": "features_metro.md",
    "venue_metro": "features_metro.md",
    "calendar": "features_calendar.md",
    "tour_context": "features_tour_context.md",
    "bill": "features_bill.md",
    "weather": "features_weather.md",
}

DERIVED = {
    "agg_group_id": ("", "show_id of the aggregate's figure-carrying row, for every member of a multi-show aggregate (rebuilt from spine row order; NA for members that couldn't be placed and for single shows)"),
    "agg_n_venues": ("venues", "distinct venue_ids in the aggregate group"),
    "agg_span_days": ("days", "first to last date of the aggregate group"),
    "agg_last_date": ("date", "last date of the aggregate group"),
    "is_aggregate_unit": ("", "row carries a figure covering aggregate_n_shows > 1 shows (one unit of analysis)"),
    "tickets_sold_per_show": ("tickets", "tickets_sold / aggregate_n_shows on figure-carrying rows (equal split assumed)"),
    "tickets_available_per_show": ("tickets", "tickets_available / aggregate_n_shows on figure-carrying rows"),
    "gross_usd_per_show": ("nominal USD", "gross_usd / aggregate_n_shows on figure-carrying rows"),
    "dup_boxoffice_group": ("", "duplicate box office group `<date>|<first show_id>`: same date and either an identical gross, or identical tickets (> 1,000) with gross within 5%, across or within artists, any venue spelling"),
    "dup_boxoffice_drop": ("", "True on rows dropped by the hand-checked decision in data/manual/boxoffice_dedupe.csv"),
    "dup_boxoffice_resolved": ("", "the reason recorded in data/manual/boxoffice_dedupe.csv"),
    "country_final": ("ISO2", "country_iso2, else the venue's Wikidata country, else the spine country text (doubled tokens collapsed), else the text after the city's last comma, else US when the venue matched a US Census metro. **Use this for US-only filters.**"),
    "country_final_source": ("", "`spine`, `venue_wikidata`, `spine_text_city_or_metro`, `unknown`"),
    "non_performer": ("", "act is not a performer (Cirque du Soleil, TV-franchise and cast tours, sponsor packages, various artists): data/manual/non_performers.csv; excluded from the sample"),
    "dup_unreviewed": ("", "duplicate group not covered by data/manual/boxoffice_dedupe.csv (fallback rule applied); should be all False"),
    "dup_figure_copy": ("", "same artist, identical gross and tickets on a different date: a figure copied between rows; all copies excluded"),
    "cpi_deflate_date": ("date", "date used for deflation: show_date, or the midpoint of the aggregate's span for aggregate units"),
    "tour_n_analysis": ("shows", "tour_key's rows in the analysis sample"),
    "price_rel_tour": ("log points", "**Target (primary relative).** log_avg_price_real − median over the same tour_unit (analysis sample; units with ≥ 5 shows). Recompute in folds with `analysis.targets.tour_relative_target(df, train_mask)`"),
    "year_bucket_5": ("year", "5-year bucket of the tour unit's START year (2015 = tours starting 2015–19); amendment A2"),
    "tour_unit": ("", "tour_key, split for keys spanning > 2 years (list articles, residencies, long pauses) at gaps > 90 days, then by calendar year: `<tour_key>#<k>`. Use for tour FE. Counts of split keys/rows are reported over analysis_sample in reports/level_findings.md (Method); a key can carry a split label yet have one unit inside the sample"),
    "tour_unit_start_year": ("year", "first show date year of the tour unit (all played rows)"),
    "tour_unit_span_days": ("days", "first to last show of the tour unit"),
    "price_rel_artist_era": ("log points", "**Target (secondary relative).** log_avg_price_real − median over the same artist_key × year_bucket_5 (cells ≥ 5 and artist_keys ≥ 5 shows). Use with year FE. `analysis.targets.artist_era_target`"),
    "is_cancelled_spine": ("", "status_note contains 'cancel' (available for all rows, unlike tour_context's is_cancelled)"),
    "usd_assumed_non_us": ("", "gross_currency USD at a non-US show: a bare `$` may be local dollars (AU/CA/MX/...)"),
    "cpi_base_month": ("YYYY-MM", "constant-dollar base month (2026-09, latest published CPI-U)"),
    "cpi_show_month": ("index", "CPI-U NSA (1982-84=100) of the show month; pre-1980 from the raw BLS file"),
    "cpi_month_imputed": ("", "show month's CPI is interpolated (only 2025-10, BLS shutdown gap)"),
    "avg_price_real": ("2026-09 USD/ticket", "avg_price_usd × CPI(2026-09) / CPI(show month)"),
    "gross_usd_real": ("2026-09 USD", "gross_usd deflated the same way"),
    "gross_usd_real_per_show": ("2026-09 USD", "gross_usd_real / aggregate_n_shows on figure-carrying rows"),
    "log_avg_price_real": ("ln(2026-09 USD)", "**Target.** ln(avg_price_real)"),
    "log_avg_price_nominal": ("ln(USD)", "ln(avg_price_usd), for robustness checks"),
    "analysis_exclusion_reason": ("", "first failing rule: unpriced, non_usd, implausible, tour_outlier, cancelled, dup_boxoffice, aggregate_multi_venue, no_cpi; NA = in sample"),
    "analysis_sample": ("", "priced, USD, not implausible/tour_outlier, not cancelled, not a duplicate box office copy, not a multi-venue aggregate, CPI available"),
    "split_key": ("", "group of artist_ids sharing any performer (QID or headliner wikilink); the unit hashed into artist_split"),
    "artist_key": ("", "performer identity for artist-level statistics: the QID (else cleaned slug) for single-headliner acts, `act:<artist_id>` for co-headline packages"),
    "artist_split": ("", "train / valid / test by md5('seatprice-v1:' + split_key), 70/15/15 of split groups. The holdout is by artist (performer)"),
    "artist_median_log_price_real": ("ln(2026-09 USD)", "median log_avg_price_real per artist_key over the whole analysis sample (NA outside the sample)"),
    "artist_n_analysis": ("shows", "artist_key's rows in the analysis sample"),
    "price_rel_artist_median": ("log points", "**DEPRECATED (career-time confounded, corr 0.65 with year relative to the artist's median year).** log_avg_price_real − artist_median_log_price_real (per artist_key). Recompute in folds with `analysis.targets.artist_relative_target(df, train_mask)`"),
    "unit_n_shows": ("shows", "aggregate_n_shows on analysis rows: shows the observation covers (weight option)"),
}

# Spine/feature columns missing from their source dictionary.
UNDOCUMENTED = {
    "artist_wikilink": ("", "headliner link target(s) from the tour infobox, \" | \"-joined (co-headliners); used by features_artist (not in shows_base.md)"),
    "opener_names": ("", "\" | \"-joined opener link targets (raw names if unlinked); null = no openers known"),
    "opener_pv_status": ("", "bill-table audit field: state of the opener pageview lookup (not in features_bill.md)"),
    "wikidata_status": ("", "bill-table audit field: state of the opener/album Wikidata lookup (not in features_bill.md)"),
    "state_usps": ("", "two-letter US state of the matched Census place (venue_metro crosswalk); null for non-US or unmatched venues"),
}

# Leakage codes: EXPOST = uses information after the show / the tour as finally
# played; OUTCOME = same-show sales outcome or derived from it; TARGET = derived
# from the target; SHOWDAY = known only on the show day; POST_ONSALE = window ends
# the day before the show, i.e. after typical on-sale; SNAPSHOT = current value,
# not point-in-time (anachronistic for old shows).
LEAK = {
    "EXPOST": [
        "tour_end_date", "tour_infobox_number_of_legs", "tour_infobox_number_of_shows", "aggregate_n_shows", "agg_n_venues", "agg_span_days", "agg_last_date",
        "tour_n_shows", "tour_span_days", "tour_n_legs", "tour_n_countries", "tour_progress",
        "is_last_show_of_tour", "is_last_show_of_leg", "leg_n_shows", "leg_span_days", "days_to_next_show_artist",
        "metro_n_dates_tour", "venue_n_dates_tour", "venue_run_length", "is_multi_night_run", "is_added_date_proxy",
        "n_shows_in_spine", "artist_n_shows_in_spine", "n_shows", "n_tour_articles",
        "n_tours_started_by_show_year", "venue_run_position",
        "is_cancelled", "is_cancelled_spine", "status_note", "farewell_flag", "farewell_match",
        "reunion_flag", "reunion_match", "is_aggregate_unit", "unit_n_shows",
        "tour_key", "tour_inferred", "leg_number", "leg_inferred", "leg_show_number", "is_first_show_of_leg",
    ],
    "OUTCOME": [
        "tickets_sold", "gross", "gross_usd", "sellout_ratio", "avg_price_flag", "capacity_bucket",
        "attendance_raw", "revenue_raw", "tickets_sold_per_show", "gross_usd_per_show", "gross_usd_real",
        "gross_usd_real_per_show", "dup_boxoffice_group", "dup_boxoffice_drop", "dup_boxoffice_resolved",
        "analysis_sample", "analysis_exclusion_reason", "wx_priced_show", "venue_n_priced_shows",
        "tickets_available", "tickets_available_per_show", "n_priced_shows", "artist_n_analysis",
        "tour_n_analysis", "has_venue", "has_weather", "dup_figure_copy", "dup_unreviewed",
    ],
    "TARGET": [
        "tour_infobox_gross", "tour_infobox_attendance", "price_rel_tour", "price_rel_artist_era",
        "avg_price_usd", "avg_price_real", "log_avg_price_real", "log_avg_price_nominal",
        "artist_median_log_price_real", "price_rel_artist_median",
    ],
    "ID": [
        "show_id", "artist_id", "venue_id", "tour_page_id", "tour_revid", "rev_timestamp", "table_index",
        "agg_group_id", "split_key", "artist_key", "artist_qid", "venue_qid", "tour_key", "mbid",
    ],
    "POST_ONSALE": [
        "pv_mean_90d", "pv_mean_365d", "pv_momentum", "pv_spike_ratio", "pv_spike_flag",
        "opener_pv_mean_90d_max", "opener_pv_mean_90d_sum", "album_pv_mean_90d", "album_pv_momentum",
    ],
    "SNAPSHOT": [
        "lb_total_listen_count", "lb_total_user_count", "lb_snapshot_date", "genres_wikidata", "genre_coarse",
        "mb_genre_tags", "mb_genre_coarse", "genre_coarse_final", "genre_coarse_source", "tour_category",
        "capacity", "capacity_config", "capacity_max", "capacity_n_configs", "capacity_all", "venue_type",
        "indoor_outdoor", "metro_median_hh_income", "metro_median_hh_income_moe", "metro_population",
        "metro_log_population", "metro_college_share", "is_college_town", "county_median_hh_income",
        "county_population", "county_college_share", "place_median_hh_income", "place_population",
    ],
}
LEAK_NOTE = {
    "tickets_available": "capacity as sold/configured; partly an outcome (production holds, added seats)",
    "capacity_bucket": "from tickets_available, else tickets_sold (outcome)",
    "aggregate_n_shows": "number of nights reported together, known after the stand",
    "is_added_date_proxy": "2nd+ night of a run; whether it was added is only known later",
    "farewell_flag": "categories can be applied in hindsight",
    "tour_infobox_gross": "tour total gross / attendance = the tour's average price, which includes this show (corr 0.71 with log price)",
    "tour_infobox_attendance": "see tour_infobox_gross",
    "n_priced_shows": "counts reported (priced) shows",
    "has_venue": "venues were resolved priced-first",
    "has_weather": "weather was fetched priced-first",
    "tour_page_id": "an ID; proxies era (within-artist r 0.26), blocked from models",
    "n_tours_started_by_show_year": "counts tours that start later in the same year",
    "venue_run_position": "> 1 reveals a multi-night run",
    "genre_coarse_final": "current labels, whole career",
    "status_note": "cancelled/rescheduled is known after announcement",
    "leg_show_number": "legs are inferred from the full schedule",
    "tour_key": "tour grouping as finally played",
}
LEAK_COL = {c: code for code, cols in LEAK.items() for c in cols}
for c in [f"wx_{x}" for x in [
    "coord_source", "query_lat", "query_lon", "status", "grid_lat", "grid_lon", "timezone", "elevation_m",
    "temp_max_c", "temp_min_c", "precip_mm", "precip_hours", "wind_max_kmh", "weather_code", "snow_day",
    "eve_temp_mean_c", "eve_precip_mm", "eve_precip_hours", "eve_wind_max_kmh", "eve_weather_code_max",
    "eve_thunderstorm", "eve_hours_covered"]]:
    if c not in ("wx_coord_source", "wx_query_lat", "wx_query_lon", "wx_status", "wx_timezone", "wx_elevation_m",
                 "wx_grid_lat", "wx_grid_lon"):
        LEAK_COL[c] = "SHOWDAY"

KNOWN_ISSUES = """\
## Known issues carried forward

- **`days_announce_to_show` is ~empty**: the concert infobox has no announcement field, so `tour_announced_date` is almost always null. There is no lead-time feature.
- **`is_college_town` is sparse**: it is US-only and needs a CBSA match; the threshold (college share ≥ 15%) flags ~5% of CBSAs. Use `metro_college_share` for sensitivity checks.
- **Metro (Census) features are US-only**: every `metro_*`, `county_*` and `place_*` column is null outside the US (`metro_scope = non_us`). They use a single 2024 ACS vintage for all years (SNAPSHOT).
- **Weather is partial**: rows still `pending` are re-fetched when the weather build resumes. Non-US venues without Wikidata coordinates never get weather. Weather is SHOWDAY information.
- **Set-list popularity is missing**: setlist.fm needs permission. The only proxy is album attention (`album_pv_*`, bill table).
- **Spotify is prohibited**: `pv_momentum` (English-Wikipedia pageview momentum) substitutes for follower growth. It measures attention, not fandom, and is null before mid-2015.
- **CPI October 2025 is interpolated** (`cpi_month_imputed`). CPI before 1980 comes from the raw BLS file, not cpi.parquet. US CPI is applied to non-US shows (an approximation).
- **"$" is assumed to be USD**: see `usd_assumed_non_us`. Non-USD grosses (33 rows) are excluded; there is no local FX table to convert them.
- **Multi-night figures sit on the first night**: date and calendar features of an aggregate unit describe its first night only. For day-of-week or holiday tests, restrict to `aggregate_n_shows == 1` or check robustness.
- **Only big tours are covered**: Wikipedia box office tables exist mostly for Boxscore-reporting arena and stadium tours from ~2010 on, so every estimate is conditional on the selected sample (see reports/data_quality.md).
- **Feature tables may be built against an older spine**: see Coverage. A show missing from a show-keyed feature table has null features (`has_<table>` = False), not "feature absent".
"""

DECISIONS = """\
## Join decisions

- **Spine:** `data/interim/shows_base.parquet`, one row per `show_id`. Every feature table is left-joined (many-to-one, validated) on `show_id`, `artist_id` or `venue_id` per SHOW_KEY.md. Spine-copy columns (`venue_name`, `city`, `country` in the venue table; `artist_name`; `artist_id` in artist_show) are dropped. A feature column whose name already exists gets its table prefix (e.g. `artist_country_iso2` is the artist's origin country; `venue_country_iso2` is Wikidata's; `cal_is_us`, `bill_n_headliners`). Only `state_usps` is taken from venue_metro; the rest duplicates features_metro.
- **Constant dollars:** CPI-U NSA, base month **2026-09** (the latest published). `real = nominal × CPI(2026-09) / CPI(show month)`. Nominal values are kept (`avg_price_usd`, `gross_usd`).
- **Multi-show aggregates (32,892 rows in aggregate groups):** **treat each aggregate as one unit.** The figure-carrying row is the observation. Its `avg_price_usd` = gross / tickets over the whole stand is already a valid per-ticket price, so averaging per show would not change it. Copying it to each night would create pseudo-replicates with identical prices and overstate n. The other nights stay in the table unpriced. `unit_n_shows` can serve as a weight, and `*_per_show` columns split volume measures equally. Aggregates spanning more than one venue (`agg_n_venues > 1`, mostly leg totals) are excluded, because venue and city features would be wrong.
- **Duplicate box office** (review 1): two priced rows on one date with an identical gross, or identical tickets (> 1,000) and gross within 5%, are one box office line, whatever the venue spelling and whether across or within artists. Every group is resolved by hand in `data/manual/boxoffice_dedupe.csv` (keep/drop with a reason): the headliner is kept only when its opening-act cell names the other act, co-bills without an identifiable headliner and festival totals are dropped entirely, and the Smashing Pumpkins/Marilyn Manson dates are kept under the co-headline act key. Same-artist identical figures on different dates are copy errors; all copies are excluded (`dup_figure_copy`).
- **Non-performers** (Cirque du Soleil, TV-franchise and cast tours, sponsor packages, Various Artists; `data/manual/non_performers.csv`) are excluded.
- **Country:** `country_final` fills null spine countries from the venue's Wikidata country, the doubled spine text, the city suffix, or a US Census match. US-only = `country_final == "US"`. `usd_assumed_non_us` uses it. The FX test in reports/currency_test.md finds no local-currency contamination.
- **`analysis_sample`:** priced (USD gross and tickets sold), `gross_currency == USD`, not `implausible` or `tour_outlier`, not cancelled, not a dropped duplicate or copied figure, not a multi-venue aggregate, not a non-performer, CPI available. "Converted" currencies: none; no local FX source.
- **`artist_split`:** a deterministic md5 hash (salt `seatprice-v1`) of `split_key` into train/valid/test, 70/15/15 **of performer groups**. `split_key` is the connected component of artist_ids linked by a shared QID or headliner wikilink, a Wikidata P527/P463/P361 edge whose both ends are artists in the data (band ↔ member, duo ↔ partner), or a manual relation (`data/manual/artist_relations.csv`). So a performer's solo, band and package shows always share a split (tested for every pair in review 1). Row shares differ from 70/15/15 because performers have very different show counts.
- **Artist-level statistics use `artist_key`**, not artist_id: one key per performer for single-headliner acts (QID inherited through the headliner wikilink; manual aliases merged), and its own key for each co-headline package.
- **CPI for aggregates:** deflated at the midpoint month of the stand (`cpi_deflate_date`), not the first night.
- **Relative targets (review 1, item 5):** `price_rel_tour` (minus the same tour unit's median; units with ≥ 5 sample shows) is the primary relative target. `price_rel_artist_era` (minus the artist_key × tour-start 5-year median; cells and artist_keys with ≥ 5 shows) is the secondary one, always used with year FE. Both have ~0 correlation with career time. `price_rel_artist_median` is DEPRECATED (corr 0.65 with year relative to the artist's median year).
- **Relative-target leakage:** all relative targets subtract a median that includes the row itself and (for era/artist versions) later shows. With the by-performer split this can't leak across splits, but within-split CV must recompute the median on training rows only (`tour_relative_target`, `artist_era_target`, `artist_relative_target` take a fit mask). They are targets only, never features.
"""


def parse_md_tables(path: Path) -> dict[str, tuple[str, str]]:
    """column -> (unit, meaning) from every markdown table with a 'column' header."""
    out: dict[str, tuple[str, str]] = {}
    if not path.exists():
        return out
    lines = path.read_text().splitlines()
    header = None
    for line in lines:
        if not line.startswith("|"):
            header = None
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if header is None:
            if cells and cells[0].lower() == "column":
                header = [c.lower() for c in cells]
            continue
        if set(line.replace("|", "").strip()) <= set("-: "):
            continue
        # cells may contain escaped pipes "\|"; re-split
        raw = re.split(r"(?<!\\)\|", line.strip().strip("|"))
        cells = [c.strip().replace("\\|", "|") for c in raw]
        if len(cells) < len(header):
            continue
        row = dict(zip(header, cells))
        unit = next((row[h] for h in header if "unit" in h), "")
        meaning = next((row[h] for h in header if h in ("meaning / null meaning", "meaning", "definition")), "")
        if not meaning:
            meaning = next((row[h] for h in header if h == "source"), "")
        null = next((row[h] for h in header if h == "null meaning"), "")
        if "meaning / null" in " ".join(header):
            null = ""
        text = meaning if not null else (f"{meaning}; null: {null}" if meaning else f"null: {null}")
        names = re.split(r"\s*(?:,|/)\s*", cells[0].replace("`", ""))
        for n in names:
            n = n.strip()
            if n and re.match(r"^[a-z_0-9*]+$", n):
                out[n] = (unit, text)
    return out


def _short(s: str, n: int = 220) -> str:
    s = re.sub(r"\s+", " ", s).replace("|", "\\|")
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def _dtype(s: pd.Series) -> str:
    return str(s.dtype).replace("datetime64[ms]", "datetime").replace("datetime64[ns]", "datetime")


def write_dictionary(df: pd.DataFrame, coverage: dict, origin: dict) -> Path:
    md_cache = {t: parse_md_tables(ROOT / "data/interim" / f) for t, f in MD_FOR_TABLE.items()}
    s = df["analysis_sample"]
    priced = df["avg_price_usd"].notna()
    rows = []
    for col in df.columns:
        table, orig = origin.get(col, ("derived", col))
        if table == "derived":
            unit, meaning = DERIVED.get(col, ("", ""))
            if col.startswith("has_"):
                meaning = f"the row's key is present in the {col[4:]} table (False = table missing or built on an older spine)"
        else:
            meta = md_cache.get(table, {})
            unit, meaning = meta.get(orig) or next(
                (v for k, v in meta.items() if k.endswith("*") and orig.startswith(k[:-1])), ("", ""))
            unit, meaning = UNDOCUMENTED.get(col, (unit, meaning))
        leak = LEAK_COL.get(col) or LEAK_COL.get(orig, "")
        note = LEAK_NOTE.get(col) or LEAK_NOTE.get(orig, "")
        rows.append(
            f"| `{col}` | {table if table != 'derived' else 'derived (build_shows)'} | {_dtype(df[col])} | "
            f"{_short(unit, 40)} | {100 * df[col].notna().mean():.1f} | {100 * df.loc[priced, col].notna().mean():.1f} | "
            f"{100 * df.loc[s, col].notna().mean():.1f} | {leak}{(': ' + note) if note else ''} | {_short(meaning)} |"
        )

    sm = coverage["_summary"]
    cov_lines = ["| table | key | status | rows | built (UTC) | % shows matched | % priced filled | % analysis filled |",
                 "|---|---|---|---|---|---|---|---|"]
    for name, info in coverage.items():
        if name == "_summary":
            continue
        cov_lines.append(
            f"| {name} | {info['key']} | **{info['status']}** | {info.get('rows', 0)} | {info.get('modified', '—')} | "
            f"{info.get('pct_shows_matched', 0)} | {info.get('pct_priced_filled', 0)} | {info['pct_analysis_filled']} |")

    text = f"""# DATA_DICTIONARY: data/shows.parquet

Built by `src/analysis/build_shows.py` at {sm['built']} (rerunnable; this file is regenerated by each build).
One row per `show_id` in `data/interim/shows_base.parquet`: **{sm['rows']:,} rows**, {df.shape[1]} columns.
Priced: {sm['priced']:,}. **Analysis sample: {sm['analysis_sample']:,} rows, {sm['analysis_artists']} artists.**
Split (artists): {json.dumps(sm['split_artists'])}; split (rows): {json.dumps(sm['split_rows'])}.
Exclusions (first failing rule): {json.dumps(sm['exclusions'])}.

**Targets:** `log_avg_price_real` and `price_rel_artist_median`. Filter on `analysis_sample`. Hold out by `artist_split`.

Licenses are inherited from the inputs (Wikipedia text CC BY-SA 4.0; MusicBrainz tags CC BY-NC-SA 3.0; Open-Meteo CC BY 4.0, non-commercial; Rebrowser not used here). See each `data/interim/features_*.md`.

## Coverage of each input table

"% shows matched" = the show's key exists in the table. "% filled" = also processed (venue: resolved on Wikidata; weather: `wx_status == ok`; bill: `opener_pv_status` and `wikidata_status` both `done`, while the bill flags are filled for every row; others = matched). Partial tables give null features to unmatched rows.

{chr(10).join(cov_lines)}

{DECISIONS}
## Leakage codes

| code | meaning | use for LEVEL explanation | use for purchase-time prediction |
|---|---|---|---|
| EXPOST | uses the tour or schedule as finally played, or information after the show | yes, with care | no |
| OUTCOME | the show's own sales outcome or derived from it | no (it's on the left-hand side) | no |
| TARGET | the target or derived from it | target only | no |
| SHOWDAY | known only on the show day (weather) | yes (context) | no |
| ID | an identifier (or proxies one, e.g. tour_page_id ~ era) | no | no (hard-blocked) |
| POST_ONSALE | windows end the day before the show, after a typical on-sale | yes | re-anchor to the on-sale date first |
| SNAPSHOT | a current value, not point-in-time (anachronistic for old shows) | yes, as a noisy proxy | with care |

{KNOWN_ISSUES}
## Columns

"% non-null" is over all rows / priced rows (`avg_price_usd` present) / analysis_sample. Unit and meaning are abridged from the source dictionary; see `data/interim/<table>.md` for the full text.

| column | source table | type | unit | % all | % priced | % sample | leakage | meaning |
|---|---|---|---|---|---|---|---|---|
{chr(10).join(rows)}
"""
    out = ROOT / "data/DATA_DICTIONARY.md"
    out.write_text(text)
    return out


if __name__ == "__main__":
    df = pd.read_parquet(ROOT / "data/shows.parquet")
    cov = json.loads((ROOT / "data/shows_join_coverage.json").read_text())
    org = {k: tuple(v) for k, v in json.loads((ROOT / "data/shows_column_origin.json").read_text()).items()}
    print(write_dictionary(df, cov, org))
