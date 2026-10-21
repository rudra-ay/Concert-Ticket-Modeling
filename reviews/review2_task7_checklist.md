# Skeptic checklist for task 7 (LEVEL), plus early problems from the provisional pipeline

Pre-check script: `src/review/r2_level_precheck.py`. These are the checks I'll run on the submitted LEVEL analysis.

## Checklist (each must pass)
1. **Data:** built from the shows.parquet that passes review 1, with items 1–10 resolved (new split, dedupe, recoded leakage, fixed null-country flag).
2. **Targets:** log_avg_price_real, and price_rel_tour (with long pseudo-tours split, amendment A1). price_rel_artist_era uses tour-start buckets and year FE. The deprecated target is used nowhere.
3. **Predictors:** no TARGET/OUTCOME/EXPOST/SHOWDAY/POST_ONSALE column in the predictive model. I'll check this against the *recoded* dictionary. Hypothesis regressors that carry those codes are labeled as associations and never presented as causal or used in predictive claims.
4. **Effect sizes:** each comes with a 95% CI, in % (binary) or % per 1 SD (continuous).
5. **Standard errors:** clustered by split_key. Regressors that vary at metro or venue level need two-way clustering (split_key × metro, or split_key × venue). Inference uses t with df = (clusters with variation − 1). Hypotheses with fewer than 30 effective clusters need a wild cluster bootstrap.
6. **BH family:** fixed before results are seen and listed in the report. It contains every planned LEVEL hypothesis, including not-testable or preliminary ones, which are reported as excluded *with a reason set a priori*. The family can't change after results are seen.
7. **Holdout:** the artist-held-out test is touched once, on the final split, with a pre-registered spec hash. Every touch is reported, including touch #1.
8. **Sensitivities:** US-only (country_iso2 == "US"), excluding usd_assumed_non_us (after the null-country fix), 2016+, excluding aggregates, weighting by nights, IPW for coverage, high-coverage tours only, and excluding pseudo-tours. Also leave-one-cluster-out influence for G < 30.
9. **Year control:** year FE (or tour FE) in every spec, the power table included.
10. **Wording:** no causal language for EXPOST, OUTCOME or POST_ONSALE regressors, and every conclusion is conditional on the big-tour sample.

## Early problems found in the provisional pipeline (sent to the analyst)
See the SendMessage to analyst on 2026-10-19. P1–P8 are summarized there.
