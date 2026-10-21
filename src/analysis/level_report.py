"""Task 6, part 3: write reports/level_findings.md from the level_* tables.

Verdicts are rule-based so a rerun updates them:
- SUPPORTED (robust): base q < 0.05 and every sensitivity spec has the same sign with p < 0.05
- SUPPORTED (fragile: ...): base q < 0.05, but the listed specs have p >= 0.05 or flip sign
- NOT SUPPORTED: base q >= 0.05 (the CI is reported, so a precise null is distinguishable from no power)
- DESCRIPTIVE: fewer than 10 FE groups carry the variation; estimate shown, outside the BH family
- PRELIMINARY: input table below its milestone; outside the BH family
p is the cluster-robust t(G-1) p-value, replaced by the wild cluster bootstrap p when fewer than 30
FE groups carry the variation.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from analysis.level_data import OUT_TABLES  # noqa: E402
from analysis.targets import ROOT  # noqa: E402

REPORT = ROOT / "reports/level_findings.md"

NOTES = {
    "H1a": "Metro premiums are relative to the pooled smaller metros, net of artist and year. **Why the within-artist permutation is valid under metro-level dependence (review 2, P1):** under the null of no metro effects, an artist's shows are exchangeable across its metros given artist and year. A shock common to all artists in a metro *is* a metro effect, so it belongs to the alternative, not to the nuisance structure the null must preserve. The statistic is computed on artist + year-FE residuals, and permutation happens within artist, so the artist's career and calendar structure is kept. The FX test (reports/currency_test.md) finds no local-currency contamination of \"$\" figures, so non-US metro premiums aren't currency artifacts. Australia's premium does move with the AUD/USD rate, though (θ_AU < 0), so it's era-dependent. The Las Vegas premium likely reflects residency/casino shows and high-roller pricing, not the city alone.",
    "H1b": "Income is a 2024 ACS snapshot applied to all years. With metro size held fixed, this asks whether richer metros of a given size pay more for the same artist in the same year. **Two-way clustered by split_key × metro (review 2, P1):** with performer clustering only, SE 0.014 and q 0.03; metro-level dependence more than doubles the SE.",
    "H1c": "Bigger metros pay more for the same artist in the same year, with income held fixed. Big metros also get bigger venues and more nights; this is the total association, not a mechanism. Two-way clustered by split_key × metro.",
    "H2a": "Within the same tour unit (plus year FE), single-night shows only (aggregate figures are dated to their first night). Sunday is a separate dummy; Mon–Thu is the reference. Weekend dates aren't randomly assigned to cities, so a within-tour metro-size control is reported as a sensitivity (US only, where metro size exists).",
    "H2b": "National public-holiday calendars only (US federal, England for the UK); holiday eve or long weekend vs other days, holding day of week fixed.",
    "H3": "Legs are inferred for most tours (gap/continent rule), and continent is controlled, so this asks whether later legs in the same region are priced differently. Ex post: the leg structure is known only as the tour was played.",
    "H4": "A row covering ≥ 2 nights at one venue vs single-night rows of the same tour. Extra nights are added because demand is strong, so this is demand revealing itself (reverse causality), not an effect of adding nights. Ex post.",
    "H5": "**Association only.** Tickets available per show is configured in response to demand (OUTCOME), so this regressor can't test a venue-size effect. Shown because it's the best-measured size variable. Two-way clustered by split_key × venue.",
    "H5w": "**The primary venue-size test.** Wikidata capacity is today's capacity, often in a sports configuration, so it measures the room, not the night's configuration (venue table at its priced milestone). Two-way clustered by split_key × venue.",
    "H5o": "Indoor/outdoor comes from the Wikidata class (domed stadiums typed as plain 'stadium' are misread as outdoor). Controls Wikidata capacity, not the OUTCOME tickets per show. Two-way clustered by split_key × venue. Outdoor × weather is tested in F15 (H10).",
    "H5f": "**Association only** (it uses the OUTCOME tickets per show). Ratio of pageviews (365-d mean) to tickets per show, 2016+. The unrestricted model below shows which side carries it.",
    "H6a": "Within-artist changes in Wikipedia attention (365-d mean before the show), controlling for momentum. The window ends the day before the show, after most on-sales: POST_ONSALE.",
    "H6b": "The 'Dom Dolla effect': short-run attention growth (last 30 d vs 61–90 d before the show), controlling for level. Mostly after the on-sale, when prices are already set, so a null here doesn't rule out a momentum effect on the primary price-setting decision.",
    "H7a": "Within tour: nights with more opening acts vs fewer. Only rows whose opener cell is filled (a blank cell means unknown, not none). Opener *draw* (opener pageviews) is tested separately in F14 (H7c).",
    "H7b": "Within performer group (split_key FE + year): the same performers' co-headline package tours vs their solo tours (e.g. Elton John & Billy Joel vs Elton John). Few groups carry this contrast, so the wild bootstrap p and a leave-one-group-out range are reported.",
    "H7c": "Within tour unit: nights whose best-known opener had more Wikipedia attention in the 90 days before the show. Only linked openers with a usable pageview window (mostly 2016+), so n is small. The window ends the day before the show, after the on-sale (POST_ONSALE); a bigger opener is also typically booked for bigger markets, which the tour FE only partly absorbs.",
    "H10": "Within tour unit, single-night shows: evening rain (≥ 1 mm, 18–23 h local) at an outdoor venue, beyond any rain effect at indoor venues (rain and outdoor are controlled). Average price mostly reflects tickets sold before the weather is known, so a large effect isn't expected. Show-day weather is SHOWDAY context, never a predictor.",
    "H8a": "Within artist (+ year FE): farewell-labelled tours vs the same artist's other tours. Only 7 artists have both, so this is descriptive. Hindsight categories (Kiss, Cher and Elton John have several 'farewell' tours).",
    "H8b": "Within artist (+ year FE): reunion-labelled tours vs the same artist's other tours. 10 artists carry the contrast, led by long-gap returns (The Police 2007 vs 1982–83, Genesis 2007 vs 1992, RBD, Spice Girls). Year FE removes the market-wide real-price trend, but a reunion is also a 'legacy act after a long gap' effect; this is not a pure reunion premium.",
}


def verdict(h: pd.DataFrame, hid: str) -> str:
    b = h[(h.hid == hid) & (h.sens == "base")].iloc[0]
    if b.status != "ok":
        return f"NOT RUN ({b.status})"
    if isinstance(b.get("excluded_reason", None), str):
        return "OUTSIDE THE BH FAMILY (a priori): " + b.excluded_reason
    if not (b.q < 0.05):
        return "NOT SUPPORTED"
    sens = h[(h.hid == hid) & (h.sens != "base") & (h.status == "ok")]
    pu = sens.p_wild.where(sens.p_wild.notna(), sens.p)
    bad = sens[(np.sign(sens.coef) != np.sign(b.coef)) | (pu >= 0.05)]
    assoc = isinstance(b.label, str) and any(c in b.label for c in ("EXPOST", "OUTCOME", "POST_ONSALE", "SHOWDAY"))
    word = "SUPPORTED as an association" if assoc else "SUPPORTED"
    skipped = h[(h.hid == hid) & h.status.str.startswith("skipped")].sens.tolist()
    tail = f"; not runnable: {', '.join(skipped)}" if skipped else ""
    return f"{word} (robust{tail})" if bad.empty else f"{word} (fragile: {', '.join(bad.sens)}{tail})"


def fmt_eff(r) -> str:
    if r.kind == "sd":
        return f"SD of metro premiums {100 * r.coef:.1f} log points"
    unit = " per 1 SD" if r.kind == "continuous" else ""
    return f"{r.effect_pct:+.1f}%{unit} [{r.effect_pct_lo:+.1f}, {r.effect_pct_hi:+.1f}]"


def sens_table(h: pd.DataFrame, hid: str) -> str:
    t = h[h.hid == hid]
    wild = t.p_wild.notna().any()
    hdr = "| spec | effect (95% CI) | coef (SE), log pts | p | " + ("wild p | leave-one-group-out range | " if wild else "") + "n | G | G_eff |"
    lines = [hdr, "|" + "---|" * (hdr.count("|") - 1)]
    for _, r in t.iterrows():
        if r.status != "ok":
            lines.append(f"| {r.sens} | {r.status} | | | " + ("| | " if wild else "") + "| | |")
            continue
        coef = f"{r.coef:.4f} ({r.se:.4f})" if r.kind != "sd" else f"{r.coef:.4f}"
        extra = (f"{r.p_wild:.4f} | [{r.loo_min:+.3f}, {r.loo_max:+.3f}] | " if pd.notna(r.p_wild) else "— | — | ") if wild else ""
        geff = int(r.effective_clusters) if pd.notna(r.get("effective_clusters", np.nan)) else "—"
        lines.append(f"| {r.sens} | {fmt_eff(r)} | {coef} | {r.p:.4f} | {extra}{int(r.n):,} | {int(r.clusters)} | {geff} |")
    return "\n".join(lines)


def _md(t: pd.DataFrame) -> str:
    cols = list(t.columns)
    lines = ["| model | " + " | ".join(cols) + " |", "|---|" + "---|" * len(cols)]
    for i, r in t.iterrows():
        lines.append(f"| {i} | " + " | ".join(
            f"{v:,.3f}" if c.endswith("log") else (f"{int(v):,}" if c == "n" else f"{v:,.1f}") for c, v in r.items()) + " |")
    return "\n".join(lines)


def main() -> None:
    h = pd.read_csv(OUT_TABLES / "hypotheses.csv", keep_default_na=False, na_values=[""])
    h["status"] = h["status"].astype(str)
    extras = json.loads((OUT_TABLES / "extras.json").read_text())
    eff = pd.read_csv(OUT_TABLES / "metro_effects.csv")
    cov = json.loads((ROOT / "data/shows_join_coverage.json").read_text())
    sel = json.loads((OUT_TABLES / "selection.json").read_text())
    cur = json.loads((OUT_TABLES / "currency_test.json").read_text())
    fam = json.loads((OUT_TABLES / "bh_family.json").read_text())
    touch1 = json.loads((OUT_TABLES / "model_results_touch1.json").read_text()) \
        if (OUT_TABLES / "model_results_touch1.json").exists() else None
    frozen = json.loads((OUT_TABLES / "final_spec.json").read_text()) if (OUT_TABLES / "final_spec.json").exists() else None
    mval_path = OUT_TABLES / "model_results_valid.json"
    mval = json.loads(mval_path.read_text()) if mval_path.exists() else None
    sm = cov["_summary"]
    reunion_artists = pd.read_csv(OUT_TABLES / "reunion_artists.csv")
    reunion_checks = pd.read_csv(OUT_TABLES / "reunion_checks.csv")
    ablation = pd.read_csv(OUT_TABLES / "ablation.csv")
    power = pd.read_csv(OUT_TABLES / "power.csv")
    tx = extras["tour_units"]
    tu = {"keys_label": tx["keys_with_split_label"], "rows_label": tx["rows_with_split_label"],
          "keys_multi": tx["keys_with_2plus_units_in_sample"], "rows_multi": tx["rows_in_keys_with_2plus_units"],
          "max_span": tx["max_unit_span_years"]}
    moves = extras["split_moves"]
    mres = json.loads((OUT_TABLES / "model_results.json").read_text()) if (OUT_TABLES / "model_results.json").exists() else None
    if mres and "price_rel_tour" not in mres:
        mres = None  # an older (pre-review) results file

    order = list(dict.fromkeys(h.hid))
    findings, n = [], 0
    summary_rows = ["| # | hypothesis | effect (base, 95% CI) | p used | q (BH) | verdict | label |",
                    "|---|---|---|---|---|---|---|"]
    for hid in order:
        b = h[(h.hid == hid) & (h.sens == "base")].iloc[0]
        n += 1
        v = verdict(h, hid)
        if hid == "H2a":
            ws = h[(h.hid == "H2a") & (h.status == "ok")]
            us = ws[ws.sens == "US only"].iloc[0]
            mde = 100 * (np.exp(power.loc[power.hypothesis == "Weekend premium", "clustered MDE"].iloc[0]) - 1)
            v = (f"Not significant after BH (q = {b.q:.3f}). Small and positive in every sensitivity "
                 f"({ws.effect_pct.min():+.1f}% to {ws.effect_pct.max():+.1f}%; US {us.effect_pct:+.1f}%, p {us.p:.3f}). "
                 f"Consistent with a 1–2% weekend premium at the edge of detectability (MDE ≈ {mde:.1f}%)")
        q = "—" if pd.isna(b.q) else f"{b.q:.3f}"
        pu = "—" if b.status != "ok" else (f"{b.p_wild:.4f} (wild)" if pd.notna(b.p_wild) else f"{b.p:.4f}")
        eff_txt = fmt_eff(b) if b.status == "ok" else b.status
        label = b.label if isinstance(b.label, str) and b.label else "none"
        if hid == "H8b":
            trend = reunion_checks[reunion_checks.spec.str.contains(">= 3 tour units")].iloc[0]
            eff_txt = f"{eff_txt} ({trend.pct:+.1f}% with artist-specific trends)"
        summary_rows.append(f"| F{n} [L{n}] | {hid} {b['name']} | {eff_txt} | {pu} | {q} | {v} | {label} |")
        extra = ""
        if hid == "H1a":
            top, bot = eff.tail(5)[::-1], eff.head(5)
            us = h[(h.hid == "H1a") & (h.sens == "US only")]
            extra = (f"\n\n{int((eff.q_within_metros < 0.05).sum())} of {len(eff)} metros differ from the reference at q < 0.05 (BH within metros). "
                     f"Priciest: {', '.join(f'{m} {100 * (np.exp(c) - 1):+.0f}%' for m, c in zip(top.metro, top.coef))}. "
                     f"Cheapest: {', '.join(f'{m} {100 * (np.exp(c) - 1):+.0f}%' for m, c in zip(bot.metro, bot.coef))}. "
                     + (f"US-only: SD {100 * us.coef.iloc[0]:.1f} log points (p = {us.p.iloc[0]:.3f})." if len(us) else "")
                     + " Chart: charts/level_metros.png.")
        if hid == "H8b":
            alines = "\n".join(f"| {r.artist} | {r.reunion_years} ({r.reunion_shows}) | {r.comparison_years} ({r.comparison_shows}) |"
                                for r in reunion_artists.itertuples())
            clines = "\n".join(f"| {r.spec} | {r.pct:+.1f}% [{100 * (np.exp(r.ci_lo) - 1):+.1f}, {100 * (np.exp(r.ci_hi) - 1):+.1f}] | {r.coef:.3f} ({r.se:.3f}) | {r.p:.4f} | {int(r.n):,} |"
                                for r in reunion_checks.itertuples())
            extra = (f"\n\n**Who carries the contrast** (reunion-tour years (shows) vs the same artist's other sample years (shows)):\n\n"
                     f"| artist | reunion | comparison |\n|---|---|---|\n{alines}\n\n"
                     "Two of these are unusual reunions: Guns N' Roses 2016–19 is compared only with *later* tours, and Pink Floyd's "
                     "1987–88 'reunion' label sits on the post-Waters relaunch. The headline is an association between reunion-labelled "
                     "tours and price, not the effect of reuniting.\n\n"
                     f"**Robustness checks** (src/analysis/level_reunion.py; reports/level_tables/reunion_checks.csv):\n\n"
                     f"| spec | effect (95% CI) | coef (SE) | p | n |\n|---|---|---|---|---|\n{clines}\n\n"
                     "The gap control holds the time since the artist's previous show fixed. The artist-trend check gives each artist "
                     "with ≥ 3 tour units its own linear price trend; the variant that also gives two-period artists a trend absorbs most "
                     "of the contrast, because for them a line through two periods *is* the reunion contrast. The placebo flags each "
                     "non-reunion artist's last tour and finds nothing, so late-career tours in general don't carry the premium.")
        if hid == "H5f":
            e = extras["H5f_unrestricted"]
            extra = (f"\n\nUnrestricted (same sample and FE): log pageviews {e['b_log_pv365']:+.3f} (SE {e['se_log_pv365']:.3f}), "
                     f"log tickets per show {e['b_log_cap_sold']:+.3f} (SE {e['se_log_cap_sold']:.3f}); test that they are equal and opposite p = {e['p_equal_opposite']:.3f}. "
                     "**The ratio's effect comes from the capacity side.** Pageviews add nothing within artist, so this is H5 (venue size) restricted to 2016+, not separate evidence about fanbase.")
        fe = b.fe if isinstance(b.get("fe", None), str) else ""
        findings.append(f"""### F{n} [L{n}]. {hid}: {b['name']}

**Verdict: {v}.** Base effect {eff_txt}; p = {pu}, q = {q}; n = {int(b.n) if b.status == 'ok' else 0:,} shows, G = {int(b.clusters) if b.status == 'ok' else 0} clusters ({'two-way: split_key × ' + b.cluster2 if isinstance(b.get('cluster2', None), str) and b.cluster2 else 'split_key'}), G_eff = {int(b.effective_clusters) if b.status == 'ok' and pd.notna(b.get('effective_clusters', np.nan)) else '—'} clusters with variation (t df = G_eff − 1), {int(b.groups_with_variation) if b.status == 'ok' else 0} FE groups with variation. FE: {fe}. Leakage label: {label}. {b.note if isinstance(b.note, str) else ''}

{NOTES.get(hid, '')}{extra}

{sens_table(h, hid)}

Skeptic: [ ] approve  [ ] reject: ______
""")

    gpath = OUT_TABLES / "genre.csv"
    if gpath.exists():
        gt = pd.read_csv(gpath).sort_values("pct")
        n += 1
        glines = "\n".join(f"| {r.genre} | {r.artists} | {r.shows:,} | {r.pct:+.1f}% [{r.pct_lo:+.1f}, {r.pct_hi:+.1f}] | {r.p:.3f} |"
                            for r in gt.itertuples())
        findings.append(f"""### F{n} [L{n}]. H9: Genre (DESCRIPTIVE, outside the BH family)

**Verdict: OUTSIDE THE BH FAMILY (a priori): genre is fixed per artist, so these are between-artist contrasts with an effective n of artists, not shows.** Log price on genre dummies (reference: pop) with year FE, clustered by performer group. Only country is clearly below pop, and it is the only contrast that survives a Bonferroni correction across the 10; every other CI spans zero. Genres are current Wikidata/MusicBrainz labels for the whole career, and the comparison also carries every other way the artists differ (scale, era, venue mix). Chart: charts/level_genre.png; table: reports/level_tables/genre.csv.

| genre | artists | shows | vs pop (95% CI) | p (nominal, 10 unadjusted contrasts) |
|---|---|---|---|---|
{glines}

Skeptic: [ ] approve  [ ] reject: ______
""")
        summary_rows.append(f"| F{n} [L{n}] | H9 Genre (vs pop) | country {gt[gt.genre == 'country'].pct.iloc[0]:+.1f}%; others span 0 | — | — | OUTSIDE THE BH FAMILY (descriptive) | SNAPSHOT |")

    model_txt = ""
    if mval:
        t = pd.DataFrame(mval["y"]["valid"]).T.sort_values("mae_log")
        r = pd.DataFrame(mval["price_rel_tour"]["valid"]).T
        g = mval["valid_gbm_vs_best_baseline"]
        rz = mval["valid_rel_gbm_vs_zero"]
        ref = [i for i in t.index if i.startswith("reference")][0]
        if touch1:
            t1 = touch1["y"]["test"]
            touch1_txt = (f"**Touch #1** (2026-10-19 16:59 PDT, pre-review data and split, 48-combination grid, recorded in "
                          f"test_touch_log.jsonl after the fact): GBM test MAE {t1['GBM']['mae_log']:.3f} log points vs. year median "
                          f"{t1['year median']['mae_log']:.3f}, global median {t1['global median']['mae_log']:.3f} and genre × 5-yr "
                          f"{t1['genre × 5-yr median']['mae_log']:.3f}; the within-artist model lost to its zero baseline "
                          f"({touch1['price_rel_artist_median']['test']['GBM']['mae_log']:.3f} vs {touch1['price_rel_artist_median']['test']['zero (artist median)']['mae_log']:.3f}). "
                          "**After seeing it**, the grid was widened (to 108 combinations) because the chosen parameters sat at the grid edge. "
                          "That order of events means touch #1 informed a modelling choice, which is disclosed here. Since then the review-1 fixes "
                          f"changed the split for {moves['sample_rows_changed_split']:,} sample rows ({moves['artist_ids_changed_split']} artist_ids), so the final test set differs from the one touched.")
        else:
            touch1_txt = "No earlier touch."
        frozen_txt = (f"sha256 {frozen['sha256'][:16]}…, data build {frozen['spec']['data_built']}" if frozen
                      else "spec not frozen yet; it is frozen before the final run")
        n += 1
        if mres:
            tt = pd.DataFrame(mres["y"]["test"]).T.sort_values("mae_log")
            gt = mref = mres["gbm_vs_best_baseline"]
            reft = [i for i in tt.index if i.startswith("reference")][0]
            test_txt = f"""**Verdict on the TEST split (touched once):** the GBM's MAE is {tt.loc['GBM', 'mae_log']:.3f} log points (${tt.loc['GBM', 'mae_usd']:.0f} per ticket; median ${tt.loc['GBM', 'medae_usd']:.0f}). The best baseline, {gt['baseline']}, has {tt.loc[gt['baseline'], 'mae_log']:.3f}: a difference of {gt['mae_diff_log']:+.3f} log points, 95% cluster-bootstrap CI [{gt['ci95'][0]:+.3f}, {gt['ci95'][1]:+.3f}] (resampling performer groups). The artist's own leave-one-out median (not available for unseen artists) gives {tt.loc[reft, 'mae_log']:.3f}.

Test split ({mres['n']['test']:,} shows, {mres['artist_keys']['test']} artist_keys; model refit on train + valid):

{_md(tt)}

"""
        else:
            test_txt = "**Test split not yet evaluated.**\n\n"
        model_txt += f"""### F{n} [L{n}]. Predicting price for an unseen artist (artist held out)

**Scope.** "Unseen artist" means an artist with no price history in the training data, described by 2026 snapshot features (ListenBrainz listeners, Wikidata genre and career data, today's venue capacity) that postdate most past shows. This is a cross-sectional benchmark, not a forecast made at on-sale time.

{test_txt}**Ablation (VALID split only, frozen hyperparameters; src/analysis/level_ablation.py):** {'; '.join(f"{r.features} ({r.n_features} features) {r.valid_mae_log:.3f}" for r in ablation.itertuples())}. Removing the ListenBrainz snapshot costs about 0.01 log points of MAE, and removing the career variables as well costs about 0.03, so part of the accuracy rests on snapshot information. The test split was not used for this.

Valid split (used for tuning, so optimistic): GBM {t.loc['GBM', 'mae_log']:.3f} vs. {g['baseline']} {t.loc[g['baseline'], 'mae_log']:.3f}, difference {g['mae_diff_log']:+.3f} [{g['ci95'][0]:+.3f}, {g['ci95'][1]:+.3f}]. The leave-one-out artist median ignores career time (it is one number per artist across decades), so it is a weak reference for long-career artists; on valid it does worse than the GBM ({t.loc[ref, 'mae_log']:.3f}), on test better. It is a reference, not a ceiling.

{_md(t)}

Valid split: {mval['n']['valid']:,} shows, {mval['artist_keys']['valid']} artist_keys. Train: {mval['n']['train']:,} shows. Hyperparameters were tuned on valid (108-combination grid; best {mval['y']['best_params']}), so **valid MAE is optimistic by the tuning step**. Features: {len(mval['features_numeric']) + len(mval['features_categorical'])} columns, none coded EXPOST/OUTCOME/TARGET/SHOWDAY/POST_ONSALE/ID (asserted in code). Pageviews are excluded as POST_ONSALE, so for unseen artists popularity enters only through ListenBrainz (a current snapshot) and career variables.

**Test-set discipline (review 2, P2).** Every test touch is reported. {touch1_txt} The final evaluation uses the new split only, with a spec frozen before the touch ({frozen_txt}); `level_model.py --final` refuses to run unless the current features, grid, targets, seed, data build and split match the frozen hash, and refuses a second final touch.

Skeptic: [ ] approve  [ ] reject: ______

"""
        n += 1
        if mres:
            rt = pd.DataFrame(mres["price_rel_tour"]["test"]).T
            rzt = mres["rel_gbm_vs_zero"]
            rel_test = (f" **On the test split (touched once):** GBM {rt.loc['GBM', 'mae_log']:.3f} vs. zero {rt.loc['zero (tour median)', 'mae_log']:.3f}, "
                        f"difference {rzt['mae_diff_log']:+.3f}, CI [{rzt['ci95'][0]:+.3f}, {rzt['ci95'][1]:+.3f}].")
            skill = rzt["ci95"][1] < 0
        else:
            rel_test, skill = "", rz["ci95"][1] < 0
        model_txt += f"""### F{n} [L{n}]. Which nights of an unseen artist's tour are pricier? (price_rel_tour)

**Verdict: {'some skill' if skill else 'no skill'}.** The GBM on the tour-relative target has valid MAE {r.loc['GBM', 'mae_log']:.3f}, while predicting 0 (the tour median) gives {r.loc['zero (tour median)', 'mae_log']:.3f}. The difference is {rz['mae_diff_log']:+.3f}, CI [{rz['ci95'][0]:+.3f}, {rz['ci95'][1]:+.3f}].{rel_test} The within-tour SD is ~0.23, and the fixed-effects estimates put individual within-tour effects (weekday, metro, venue size, multi-night) at 1–5% each.

Skeptic: [ ] approve  [ ] reject: ______

"""
        top = mval["shap_top10"]
        inter = pd.DataFrame(mval["interactions_top10"])
        n += 1
        model_txt += f"""### F{n} [L{n}]. What the model uses (SHAP, PDP, interactions)

**Verdict: descriptive. These are associations the model exploits, not effects.** Top features by mean |SHAP| (log points; GBM refit on train + valid): {', '.join(f'{k} {v:.3f}' for k, v in top.items())}. Charts: charts/level_shap.png, charts/level_pdp.png (top 10 PDPs, % vs. average prediction).

The interaction screen (mean |SHAP interaction| on 600 rows) is led by {', '.join(f'{a} × {b_}' for a, b_ in zip(inter.a[:4], inter.b[:4]))}. Genre matters little once scale and career are known: its PDP spans a few percent, while the raw country-vs-pop gap in F20 is about 26%. This is consistent with genre mattering little once scale and career are known; a PDP span next to a raw gap is not a decomposition. Year × ListenBrainz interactions are expected as an **artifact**: a 2026 listener count describes recent shows better than 1990s ones. They should not be read as "popularity mattered more recently". Chart: charts/level_interactions.png.

Skeptic: [ ] approve  [ ] reject: ______

"""

    p = cur["pooled"]
    text = f"""# LEVEL findings (task 6): what explains a show's average ticket price?

Generated by `src/analysis/level_report.py` from `level_hypotheses.py`, `level_model.py`, `selection.py` and `currency_test.py` (rerun all with `src/analysis/level.py`). Data: data/shows.parquet built {sm['built']} **after the review-1 fixes**, with an analysis sample of {sm['analysis_sample']:,} shows, {sm['analysis_artist_keys']} artist_keys and {sum(sm['split_keys'].values())} performer groups. Final collection: venue table resolved for {cov.get('venue', {}).get('pct_analysis_filled')}% of the sample, weather `ok` for {cov.get('weather', {}).get('pct_analysis_filled')}%, bill table complete (flags and lookups).

## Method

- Outcome: log average ticket price in Sep-2026 dollars (`log_avg_price_real`; aggregates deflated at their midpoint month). Effects are reported as % = exp(b) − 1; continuous regressors per 1 SD of the regressor in the estimation sample.
- **Every spec includes year FE** plus the FE named (artist = `artist_key`, one per performer; tour = `tour_unit`; performer group = `split_key`), absorbed by alternating projections (`src/analysis/fe.py`, checked against statsmodels in tests/test_fe.py).
- **Tour units (amendment A1, approved):** tour_keys spanning more than 2 years (list articles, residencies, tours with long pauses: Phish concert tours, List of Yes tours, Billy Joel at MSG, Celine, No Filter's COVID break) are split at gaps over 90 days, then by calendar year if a piece still spans more than 2 years. In the analysis sample, {tu['keys_label']} tour_keys ({tu['rows_label']:,} rows) carry a split label, and {tu['keys_multi']} of them ({tu['rows_multi']:,} rows) have ≥ 2 units inside the sample; the max unit span is {tu['max_span']:.2f} years. Shorter tours stay whole, so breaks between legs stay within a tour.
- **Standard errors:** cluster-robust (CR1) by `split_key` (performer group, which nests artist and tour). Regressors that vary at metro or venue level (H1b/H1c, H5/H5w/H5o) are **two-way clustered**, split_key × metro or split_key × venue (Cameron–Gelbach–Miller). Inference uses t with **df = G_eff − 1**, where G_eff counts clusters in which the regressor varies within its FE group.
- **Few clusters:** when G_eff or the number of FE groups carrying the variation is below 30, p comes from a null-imposed wild cluster bootstrap (Webb weights, 1,999 draws), and a leave-one-group-out range is reported.
- Sensitivity specs for every headline: US only (`country_final`), excluding "$" outside the US, 2016+, excluding multi-night aggregates, weighted by nights, **inverse-probability weighted for selection** (data/selection_weights.parquet), **tours with ≥ 80% coverage**, and **excluding split pseudo-tours**. Weekend and holiday also get a within-tour metro-size control (US). "same as base" means the restriction is already part of the base spec.
- Multiple testing: Benjamini–Hochberg over a family fixed in advance (next section).
- Leakage labels: EXPOST, OUTCOME, POST_ONSALE and SNAPSHOT regressors appear only in these explanatory regressions, labeled. The predictive model excludes everything coded EXPOST/OUTCOME/TARGET/SHOWDAY/POST_ONSALE/ID.
- City premium (H1a) is a dispersion test: metros with ≥ 30 shows from ≥ 5 artists get dummies (artist + year FE). The effect size is the bias-corrected SD of their premiums, √(var(b) − mean(SE²)); p comes from 999 within-artist permutations on the reduced-model residuals, so 0.001 is the floor.

## Data caveats that bound every finding

- **Selection** (src/analysis/selection.py): {100 * sel['coverage_all']:.0f}% of played shows in documented tours are covered. Coverage falls over a tour (within-tour LPM: progress {sel['lpm']['tour_progress']['b']:+.3f}) and rises with metro size ({sel['lpm']['log_metro_pop_f']['b']:+.3f} per log point) and venue size. Better-documented tours price slightly higher within an artist's era ({sel['strong_nights']['price_rel_artist_era_on_tour_coverage']['b']:+.3f} per unit of tour coverage, SE {sel['strong_nights']['price_rel_artist_era_on_tour_coverage']['se']:.3f}). Coverage also varies within tours, so within-tour contrasts don't remove this by construction; the IPW and ≥ 80%-coverage specs test it.
- **Currency** (reports/currency_test.md): within-tour FX slopes show no local-currency contamination. Pooled θ = {p['theta']:+.3f}, 95% CI [{p['ci95_t'][0]:+.3f}, {p['ci95_t'][1]:+.3f}]; CA {cur['per_country']['CA']['theta']:+.3f}; AU {cur['per_country']['AU']['theta']:+.3f} (the opposite sign from contamination).
- **Superstar sample:** these results describe big Boxscore-reporting tours only.

## The multiple-testing family (fixed in advance; review 2, P3)

BH runs over these {len(fam['family'])} planned hypotheses: {', '.join(fam['family'])}. {('Members with no result yet enter with p = 1 (conservative) until they land: ' + '; '.join(f'{k}: {v}' for k, v in fam['pending_p1'].items()) + '.') if fam['pending_p1'] else 'Every member has a result on the final data (none is carried at p = 1).'} **Outside the family, with reasons set before their estimates were seen:** {'; '.join(f'{k}: {v}' for k, v in fam['excluded'].items())}. Disclosure: the family was fixed after round-1 provisional estimates existed, at the skeptic's request. It contains every hypothesis in the brief, and the exclusions follow rules stated in task 5 (OUTCOME regressors, < 10 groups, between-artist only, not testable).

## Summary

{chr(10).join(summary_rows)}

Charts: charts/level_forest.png (all base effects), charts/level_sensitivity.png (each hypothesis across specs).

## Findings (explanatory, fixed effects)

{chr(10).join(findings)}
## Findings (predictive, artist held out)

{model_txt}
## Not tested

- **Set-list popularity:** not testable (setlist.fm permission).
"""
    REPORT.write_text(text)
    print(f"wrote {REPORT.relative_to(ROOT)}: {n} findings")


if __name__ == "__main__":
    main()
