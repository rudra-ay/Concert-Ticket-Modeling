# Skeptic review 1: task 5 dataset (data/shows.parquet, build 2026-10-19T23:34Z)

Verdict: **NOT APPROVED.** Problems 1–6 block task 7. Problems 7–8 must be fixed before the related results are reported. Item 9 (CPI) and the aggregate-as-unit decision (10) are approved with minor fixes.

Check scripts (all read-only on data/): `src/review/r1_*.py`.

## Verified correct
- price_rel_artist_median: my independent recompute matches the stored column exactly (max diff 0.0). `artist_relative_target(df, train_mask)` matches stored values on train rows and gives NaN for valid/test rows. artist_key is nested in split_key, and no artist_key spans two splits.
- CPI: the splice of cpi.parquet and the raw BLS file is exact (0 difference over 561 overlapping months). Deflation reproduces exactly. Oct-2025 = midpoint of Sep and Nov (324.461) and affects 38 sample rows. 496 pre-1980 rows use the same series. There are no priced rows after the base month.
- Power clustering: my recompute reproduces every clustered MDE to 3 decimals. FE groups are nested in the split_key clusters, so no df adjustment is needed.

## Problems
1. **Target-derived columns are mislabeled.** `tour_infobox_gross` / `tour_infobox_attendance` are coded EXPOST, but their ratio is the tour's average price, which includes this show. corr = 0.71 with log nominal price (7,168 rows), and 0.37 with price_rel. Recode them as TARGET/OUTCOME and put them on a hard predictor blocklist. Also: `n_priced_shows` (venue), `artist_n_analysis`, `has_venue`/`has_weather` and venue resolution (done priced-first) depend on reporting, so code them OUTCOME. `tour_page_id` is an ID that proxies era (r_within 0.26), so block it. Minor: `n_tours_started_by_show_year` counts tours that start later in the same year (EXPOST), and `venue_run_position` > 1 reveals a multi-night run (EXPOST).
2. **The duplicate box office rule misses venue-name variants.** There are 30 sample rows (15 pairs, 11 cross-split) where different artists share the same date and tickets_sold: Stones/Van Halen 1978 Superdome, Stones/Santana 1978 Oakland, Journey/Santana 1982 ×3, Police/Santana 1982, ZZ Top/Santana 1990, Foo Fighters/Marilyn Manson 2015-06-05 ($12.86M / 75,000, a festival total, so exclude both), Aldean/Chesney Denver 2015, Katy Perry/Lali Buenos Aires 2015, Imagine Dragons/AJR 2023 ×3. The same problem occurs within one artist: Rush has 14 shows listed twice under venue variants (28 rows, same date and gross). Fix: match on show_date + (metro_key or normalized city) + (gross within 1% or equal tickets_sold), both across and within artist_key. Separately, audit 68 rows where one artist has the same gross and tickets on different dates (e.g. Metallica 2025-11-12 Brisbane = 2026-06-03 Bologna = $6.3M / 45,900; Scorpions Hamburg 2016-03 = 2016-11; Queen+AL ACC 07-13 = 07-28).
3. **The duplicate attribution rule misassigns identifiable cases.** `most_priced_shows` kept Van Halen over Black Sabbath for 5 shows in 1978 (Van Halen opened on Never Say Die!). It kept Aldean as a solo act for 9 Chesney/Aldean 2015 stadium co-bills, and Marilyn Manson as a solo act for 2 shows from the co-headlined End Times tour with the Smashing Pumpkins. Fleetwood Mac/Santana 1976 Mile High was a multi-act stadium bill. Fix: resolve every group by hand in a checked-in CSV with a reason. Co-bills go to a co-headline act key (or are excluded), and festival bills are excluded.
4. **Split leakage through band/member pairs and duo packages.** split_key misses these pairs (train vs held-out):
   - The Carters (train, 56 rows) vs Beyoncé (test, 256) and Jay-Z (valid, 31)
   - NSYNC (train) vs Justin Timberlake (valid)
   - One Direction (test) vs Niall Horan (valid), Harry Styles and Louis Tomlinson (train)
   - BTS (test) vs Jin and Suga (valid)
   - Fleetwood Mac (train) vs Stevie Nicks (test)
   - Genesis (train) vs Phil Collins (valid)
   - Pink Floyd (train) vs Roger Waters (test)
   - Take That (train) vs Robbie Williams (valid)
   - Michael Jackson (train) vs The Jacksons (test)
   - Queen (train) vs Queen + Adam Lambert and Adam Lambert (valid)
   - Jonas Brothers (train) vs Demi Lovato & Nick Jonas (test)

   Aliases are also not merged in artist_key: `the-eagles` (slug) vs `eagles` (Q189635), and `selena-gomez-the-scene` vs `selena-gomez` (different split_keys too). Fix: add Wikidata P527/P463 edges (from Special:EntityData, which is allowed) to the union-find, and let artist_key inherit the QID through the headliner wikilink. Rerun, report how many rows move, and use the new split for primary held-out metrics. No tribute acts were found, but non-performer "acts" should be excluded or flagged: Cirque du Soleil, American Idol, Glee cast, the HSM cast, various-artists, Honda Civic Tour.
5. **price_rel_artist_median is dominated by within-artist time trend.** corr(price_rel, year − artist's median year) = 0.645, and 8,587 rows come from artists whose sample spans 20 years or more. Fitting the median on pre-2015 rows gives 2015+ rows +0.29 on average (vs +0.11 stored). Required: (a) add a tour-relative target (minus the tour median, or minus an artist × 5-year median), (b) put year FE in every model on this target, (c) drop artist_keys with n < 5 (39 keys, 105 rows) from relative-target work, since 171 rows are exactly 0 by construction.
6. **The selection section is miscomputed, and the "strong nights" claim is unsupported.**
   (a) Members of priced aggregates are counted as unpriced. Counted as covered, coverage rises from 34.2% to 44.8%. Recompute everything on "covered".
   (b) The capacity-bucket shares are built from tickets_sold/available, so they exist only where attendance was reported. They're P(gross | attendance), not coverage by size. Use Wikidata capacity on resolved venues instead (resolution itself is biased toward priced shows).
   (c) In tours with at least 1 priced show, coverage falls from 63% to 48% over the tour, and from 70% to 55% in North America alone. In a within-tour LPM (artist-clustered): tour_progress −0.15 (0.02), log metro pop +0.034 (0.004), Fri/Sat ≈ 0.
   (d) Among NA reported shows (year FE), sellout_ratio is *higher* in high-coverage tours (+0.099 per unit coverage, SE 0.015), and price_rel is unrelated to coverage (+0.03, SE 0.06). Restate "skews to strong nights" as untested, and report the supported finding: selection on price-relevant observables (tour progress, metro size).
   Feasible fixes: IPW on P(covered | tour, progress, continent, metro pop, capacity, weekend, year) with trimmed weights; a sensitivity check on tours with coverage ≥ 0.8; bounds for the leg and city contrasts. No Heckman (no exclusion restriction).
7. **Currency.** In an exploratory FX-era test (premium vs the same tour's US median): AU/NZ is +0.41 at AUD parity (2010–13, 30 tours) vs +0.10 in weak-AUD eras (98 tours). CA is +0.06 vs −0.10, and the GB+DE control is 0.00 vs −0.12. Contamination predicts the opposite sign, so there's no evidence of systematic local "$". Required before reporting country premia: a monthly FX table (Fed H.10/FRED, public domain; a collector task), then a within-tour regression of log(price / US tour median) on log(LCU per USD) for $-currency countries vs non-$ controls, with tour FE and clustered SEs. The difference in slopes is the contamination share, reported with a CI. Country and city premia in task 7 need FX or country × year controls. **Bug:** 831 sample rows have a null country_iso2, so they're not flagged. At least 87 are non-US by venue_country_iso2, and the country text is often doubled ("Germany Germany"). Fall back to venue_country_iso2 and dedupe repeated tokens. Define US-only as country_iso2 == "US".
8. **The power table omits year FE.** The report itself calls year FE mandatory. With year FE: venue size 0.035 → 0.022, income 0.012 → 0.007, farewell 0.725 → 0.171, co-headline 0.362 → 0.169; the rest are unchanged. Recompute with year FE, use t(G−1) critical values for G < 30 (farewell 0.205, co-headline 0.177) and a wild cluster bootstrap there, report G (split_key clusters) instead of artist_id counts, and note that the city row assesses only the income slope.
9. **CPI** is approved, with one minor fix: deflate aggregates at their midpoint month. Katy Perry's Resorts World unit is 80 shows over 675 days, and the first-month deflator is 6.5% off. 4 units span more than 60 days.
10. **Aggregates as one unit** are approved. Minor: hand-check the 7 priced units whose placed member count is below aggregate_n_shows, because agg_n_venues may be undercounted for them.

## Round 3 (item 5)

Verdict: **APPROVED.** Checked against the rebuilt data/shows.parquet (2026-10-20 18:51, 23,323 sample rows) with `src/review/r1e_item5.py`.

- **A1 (pseudo-tours):** `tour_unit` leaves 0 units of 5 or more shows spanning more than 3 years (max 1.87 yr, p90 1.18 yr). In the analysis sample, 53 tour_keys (3,614 rows) are split. The analyst's 63 keys / 3,807 rows count beyond the sample. No unit spans two artist_keys or two splits.
- **The leg contrast survives the split:** 433 tour units have leg variation, vs 450 tour_keys.
- **price_rel_tour:** my independent recompute matches exactly (22,933 rows, max diff 0.0). corr(price_rel_tour, show year − tour-unit median year) = 0.024, down from 0.095.
- **A2 (era buckets):** `year_bucket_5` is constant within every tour unit. price_rel_artist_era also matches my recompute exactly (23,168 rows). Its residual correlation with within-cell year is 0.169, so **year FE remains mandatory** in every era model, as the analyst already committed.
- The old target `price_rel_artist_median` is deprecated and must not appear in task 7.

With this, review 1 is fully approved (items 1–10).
