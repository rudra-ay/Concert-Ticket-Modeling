# Skeptic review 3: task 7 (LEVEL), round 1

Input: reports/level_findings.md (23 findings, [L1]–[L23]), data build 2026-10-21T01:51Z (shows.parquet 18:51 local), final test touch 2026-10-21T17:54Z.
Mechanical checks: `src/review/autocheck.py --level` → 41 PASS, 0 FAIL, 0 WARN.
Judgment checks: `src/review/r3_level_checks.py`.

## Judgment checks run
- **H1a, tour shocks vs metro labels.** The reported permutation is within artist, and tour-level shocks could correlate with which metros a tour visits. Rerun with tour_unit + year FE and the permutation within tour unit: SD 0.102 (vs 0.108), p 0.005 at 199 draws (the floor); US-only SD 0.073. The city premium survives within tour. No change required.
- **H8b, reunion = late-career trend?** The 10 artists: Guns N' Roses, Kiss, Jonas Brothers, Genesis, 2NE1, the Police, RBD, Pink Floyd (1987), Spice Girls, Springsteen & E Street Band (1999).
  - + log days since the artist's previous show: 0.220 (SE 0.046).
  - + artist-specific linear trends (118 artists with ≥ 3 tour units, including 8 of the 10): 0.169 (SE 0.063).
  - Placebo (the artist's last tour vs its other tours, non-reunion rows): 0.001 (SE 0.029).
  - Survives, but smaller once trends are allowed.
- **F21, the ListenBrainz snapshot.** Valid-split ablation with the frozen params (test untouched): MAE 0.212 with all features, 0.222 without ListenBrainz, 0.240 without ListenBrainz and the career variables.

## Verdicts

L1 (H1a, metro premiums differ beyond artist and year; SD 10.8 log pts, US 7.9): APPROVED
L2 (H1b, metro income not supported once two-way clustered): APPROVED
L3 (H1c, bigger US metros +2.9% per SD, total association): APPROVED
L4 (H2a, weekend): PENDING edit E1
L5 (H2b, holiday not supported): APPROVED
L6 (H3, later leg not supported; EXPOST): APPROVED
L7 (H4, multi-night stands +5.3%, association, reverse causality stated): APPROVED
L8 (H5, tickets per show −2.8%/SD, association only, outside family): APPROVED
L9 (H5w, Wikidata venue size not supported): APPROVED
L10 (H5o, outdoor not supported): APPROVED
L11 (H5f, fanbase/capacity ratio, association carried by the capacity side): APPROVED
L12 (H7a, bill size): PENDING edit E2
L13 (H7b, co-headline not supported, G_eff 23, wild p): APPROVED
L14 (H7c, opener draw not supported after BH; POST_ONSALE): APPROVED
L15 (H10, rain at outdoor shows not supported; SHOWDAY): APPROVED
L16 (H8a, farewell, descriptive, 7 artists): APPROVED
L17 (H8b, reunion): PENDING edit E3
L18 (H6a, popularity level not supported; POST_ONSALE): APPROVED
L19 (H6b, momentum not supported; POST_ONSALE): APPROVED
L20 (H9, genre descriptive): PENDING edit E4
L21 (unseen-artist prediction): PENDING edit E5
L22 (within-tour prediction, some skill, test −0.019 [−0.026, −0.009]): APPROVED
L23 (SHAP/PDP descriptive): PENDING edit E6

## Required edits (text only; no reruns, test stays untouched)
- **E1 (L4):** "NOT SUPPORTED" reads as "no weekend effect". Use: "Not significant after BH (q = 0.052). Small and positive in every sensitivity (+1.2% to +2.0%; US +1.8%, p 0.001). Consistent with a weekend premium of 1–2%, at the edge of detectability (MDE ≈ 1.3%)."
- **E2 (L12):** stale text: "Opener *draw* … waits on the bill table's lookup phase" contradicts F14. Point to F14 instead.
- **E3 (L17):**
  - List the 10 artists with their reunion and comparison years.
  - Add the three checks above as sensitivity rows (gap control 0.220; artist trends 0.169 [SE 0.063]; last-tour placebo 0.001).
  - Headline: "+25% (+18% allowing artist-specific trends)".
  - Note that Pink Floyd 1987 (post-Waters) and Guns N' Roses 2016 (compared only with later tours) are unusual "reunions". Keep "association".
- **E4 (L20):** label the p column "nominal, 10 unadjusted contrasts". Only country survives a Bonferroni correction across those 10 (0.001 × 10 = 0.01), so say that if you want the claim.
- **E5 (L21):** scope sentence. "Unseen artist" here means an artist with no price history, described by 2026 snapshot features (ListenBrainz, Wikidata). For past shows, those snapshots postdate the show, so this is not a forecast available at on-sale time. Add the valid-split ablation: 0.212 → 0.222 without ListenBrainz, 0.240 also without career variables.
- **E6 (L23):** "the descriptive genre gap is mostly carried by artist scale and career variables" → "is consistent with genre mattering little once scale and career are known". A PDP span vs a raw gap is not a decomposition.
- **E7 (global, no tag):**
  - Line 3: "bill lookups pending" / "weather (addendum later)" are stale, since H7c and H10 are reported.
  - F10: "Outdoor × weather follows as an addendum" is stale too.
  - Data caveats: "Within-tour contrasts absorb this" is too strong, because coverage varies within tour (progress, metro size). Say "IPW and the ≥ 80%-coverage specs test it".

## Round 2 (edits E1–E7)

Verified on reports/level_findings.md after the edits. autocheck --level is 41/0/0. The test touch log is unchanged (2 entries; the final touch is still 2026-10-21T17:54Z). The new numbers trace to power.csv, reunion_checks.csv and ablation.csv. The reunion checks reproduce mine: gap 0.221, trends 0.169, placebo 0.002. The 196-trend variant (+9.3%) is shown, and it's correctly not primary: for artists observed in two periods, an artist-specific line exactly absorbs the reunion contrast.

L4 (H2a, weekend: not significant after BH, q 0.052; a consistent +1–2% at the edge of detectability): APPROVED
L12 (H7a, bill size not supported): APPROVED
L17 (H8b, reunion +25.0%, +18.4% with artist-specific trends; association, 10 artists): APPROVED
L20 (H9, genre descriptive; only country below pop survives Bonferroni across 10 contrasts): APPROVED
L21 (unseen-artist GBM test MAE 0.275 vs year median 0.347; 2026-snapshot scope, not an on-sale forecast): APPROVED
L23 (SHAP/PDP descriptive associations): APPROVED

Task 7 is fully approved: L1–L23.
