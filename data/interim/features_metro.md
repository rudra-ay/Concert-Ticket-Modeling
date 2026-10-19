# features_metro.parquet (+ venue_metro.parquet)

One row per `venue_id` in `shows_base.parquet`. Built by `src/features_metro.py`. `venue_metro.parquet` is the venue → place → county → CBSA crosswalk (also used by features_tour_context and features_weather).

**Sources** (cached in `data/raw/census_acs/`, downloaded from www2.census.gov; robots.txt allows all; US government works, public domain. Source: U.S. Census Bureau, American Community Survey. Not endorsed by the Census Bureau.)
- ACS **2024 5-year** table-based summary file (survey years 2020–2024): B19013 median household income (2024 inflation-adjusted dollars), B01003 total population, B14001 school enrollment by level.
- OMB **July 2023** CBSA delineation (list1_2023.xlsx). Its CBSA codes match the ACS 2024 CBSA geography (`310M700US…`).
- 2024 Census Gazetteer places (name, state, internal point) and county subdivisions (New England towns are county subdivisions, not places).

**Vintage choice:** one fixed vintage (2024 5-year) for all shows, 2010–2026. Rationale: a single consistent CBSA geography and delineation, and metro income rank and size are slow-moving. Income is in **2024 dollars**, so treat it as a cross-sectional metro affluence measure. Don't deflate it to the show year. Older shows (e.g. 2012) get today's metro characteristics, so expect measurement error for fast-changing metros (e.g. Austin, Nashville).

**Non-US venues:** every Census column is null and `metro_scope = non_us`. Use `is_us` to restrict to US-only models.

| column | type | unit | null meaning |
|---|---|---|---|
| venue_id | string | | never null |
| is_us | bool | country US or PR | never null |
| metro_scope | string | `metropolitan`, `micropolitan`, `us_outside_cbsa`, `us_unmatched`, `non_us` | never null |
| cbsa_code / cbsa_title / cbsa_type | string | OMB 2023 | non-US, unmatched, or outside any CBSA |
| csa_code / csa_title | string | combined statistical area | not in a CSA |
| metro_median_hh_income | float | USD (2024 $) | no CBSA |
| metro_median_hh_income_moe | float | USD, 90% margin of error | no CBSA |
| metro_population | float | persons | no CBSA |
| metro_log_population | float | ln(persons) | no CBSA |
| metro_college_share | float | (enrolled undergraduate + graduate/professional students, B14001_008 + 009) ÷ total population (B01003) | no CBSA |
| is_college_town | boolean | **metro_college_share ≥ 0.15** | no CBSA |
| county_fips | string | 5-digit county holding the largest population share of the matched place | unmatched |
| county_median_hh_income / county_population / county_college_share | float | the same measures for the county (useful outside CBSAs) | unmatched |
| place_geoid | string | Census place GEOID (7 digits) | unmatched, or matched through a county subdivision |
| place_median_hh_income / place_population | float | the municipality itself (city proper) | unmatched or suppressed |
| match_method | string | `coords_nearest_place` (venue coordinates within 15 km of a place internal point, in the same state if known), `name_state` (city + state from shows_base), `name_default_state` (no state given; a hand list of ambiguous venue towns, e.g. Pasadena → CA, Morrison → CO, Arlington → TX), `name_only_most_populous` (no state; the top same-name place is ≥ 3× the next), `name_state_county_subdivision` (no Census place has that name in the state, but a county subdivision does, e.g. New England towns like Mansfield MA; maps straight to its county, so place columns are null), `ambiguous_name` (no state and no clear winner: **left unmatched** rather than guessed; candidates in `match_note`), `unmatched`, `non_us` | never null |
| match_note | string | the matched place, plus ambiguity and distance notes | non-US or unmatched |
| acs_vintage | string | `2024 5-year (2020-2024)` | never null |

## College-town threshold
Across the 935 CBSAs, the college-student share has median 4.9%, p90 10.5%, p95 14.9% and max 34% (Rexburg, ID). A cut at **15%** selects 47 CBSAs, roughly the top 5%. This keeps the textbook college towns: Ithaca, State College, Ames, Champaign-Urbana, Bloomington IN, College Station, Lawrence and Iowa City (all at 18% or more), plus Ann Arbor (17.7%), Gainesville FL (17.5%) and Athens GA (16.9%). It excludes big or mixed metros with large universities but lower shares: Durham–Chapel Hill 10.8%, Madison WI 9.6%, Boston 8.1% and Austin 7.0%. The continuous `metro_college_share` is kept for sensitivity checks.

## Matching and risks
- Venue → place uses venue coordinates from collector-features (`features_venue.parquet`) when present. Otherwise it uses the city name plus state, with aliases for e.g. NYC boroughs, Honolulu, Nashville and Washington DC. Wikipedia tour tables usually give **no state**. Then a city name takes the most populous US place with that name **only if** it has ≥ 3× the runner-up's population (e.g. Portland → OR, 9.5×). Close calls are left unmatched (`ambiguous_name`) unless the town is in the hand list `CITY_DEFAULT_STATE`. Found in testing: without this guard, Pasadena (Rose Bowl) went to Pasadena TX and Morrison (Red Rocks) to Morrison IL. Spot-check `name_only_most_populous` rows. Small towns that share a name with a big city can still go wrong if the venue town isn't in the hand list.
- Place → county takes the county with the largest share of the place's population (ACS summary level 155). For multi-county cities (NYC, Kansas City) every county is in the same CBSA, so this rarely matters.
- Venues in unincorporated areas (e.g. the Las Vegas Strip in Paradise CDP) match through name only if the tour table says the CDP name. Coordinates fix this.

- Name matching uses `region` from shows_base (filled for US rows from wikilinks) or collector-features' `us_state`. Place names are normalised by dropping "(balance)" and government-form suffixes, then one place-type suffix (`Salt Lake City city` → `salt lake city`).
