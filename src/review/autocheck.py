"""Skeptic autocheck: mechanical review checks for the LEVEL (task 7) and PATH (task 9) analyses.

    .venv/bin/python src/review/autocheck.py --level
    .venv/bin/python src/review/autocheck.py --path

Prints one line per check: PASS / FAIL / WARN / INFO, followed by the evidence. Exits 1 if any
check FAILs. WARN items don't fail the run; the skeptic judges them. Runtime is well under 60 s
(no model fitting; it reads the outputs and recomputes cheap invariants).

Run it before sending the skeptic anything. A FAIL is a blocking review item.

Output contract (both modes; PATH uses reports/path_tables/ and reports/path_findings.md):
  <tables>/hypotheses.csv   one row per hypothesis x sensitivity, with columns
                            hid, sens, status, fe, coef, se, ci_lo, ci_hi, p, p_wild, p_used,
                            effective_clusters, clusters, cluster2, in_family, descriptive, q, label, loo_min
  <tables>/bh_family.json   {"family": [...], "excluded": {hid: reason}, "pending_p1": {...}, "q": {hid: q}}
  <tables>/final_spec.json  {"sha256": ..., "spec": {...}}   (required if any test touch is logged)
  <tables>/test_touch_log.jsonl  one JSON line per evaluation on the test split
  <findings>.md             every decimal / % / $ / >=100 number must trace to a table value,
                            or the line must carry <!-- notrace: reason --> (listed as INFO for judgment)
PATH only:
  <tables>/path_spec.json   {"panel": "<parquet>", "entity": "event_id", "artist": "<col or null>",
                             "split": "<col>", "snapshot_time": "<col>", "show_time": "<col>",
                             "feature_time_cols": [...], "target_time_col": "<col or null>",
                             "features": [...], "forbidden_features": [...]}
"""
from __future__ import annotations

import argparse
import ast
import bisect
import glob
import hashlib
import json
import math
import re
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
PINS = ROOT / "reviews/pins"

FORBIDDEN_PRED = {"EXPOST", "OUTCOME", "TARGET", "SHOWDAY", "POST_ONSALE", "ID", "DEPRECATED"}
FORBIDDEN_CONTROL = {"OUTCOME", "TARGET", "ID", "DEPRECATED"}
NONCAUSAL = {"EXPOST", "OUTCOME", "POST_ONSALE", "SHOWDAY"}
REQUIRED_SENS = ["base", "US only", "excl. $ outside US", "2016+", "excl. aggregates", "weighted by nights",
                 "IPW (selection)", "tours ≥ 80% covered", "excl. split pseudo-tours"]
TWO_WAY = {"H1b": "metro_key", "H1c": "metro_key", "H5": "venue_id", "H5w": "venue_id", "H5o": "venue_id"}
WILD_BELOW = 30
# hypothesis/derived variable -> source columns in shows.parquet (for leakage codes)
DERIVED = {
    "log_cap_sold": ["tickets_available_per_show"], "fan_per_seat": ["pv_mean_365d", "tickets_available_per_show"],
    "log_metro_income": ["metro_median_hh_income"], "log_metro_pop": ["metro_log_population"],
    "log_pv365": ["pv_mean_365d"], "later_leg": ["leg_number"], "multi_night": ["is_aggregate_unit"],
    "holiday": ["is_holiday_eve", "is_long_weekend"], "log_capacity_wd": ["capacity"], "outdoor": ["indoor_outdoor"],
    "venue_age": ["year", "opening_year"], "log_lb_listens": ["lb_total_listen_count"],
    "log_lb_users": ["lb_total_user_count"], "year": ["show_date"], "country_final": ["country_iso2"],
    "n_openers_f": ["n_openers"], "log_opener_pv": ["opener_pv_mean_90d_max"],
    "rain_eve": ["wx_eve_precip_mm"], "rain_outdoor": ["wx_eve_precip_mm", "indoor_outdoor"],
}
TIME_LIKE = {"year", "years_active_at_show", "career_start_year", "n_tours_started_before_show_year"}
CAUSAL = re.compile(r"\b(causes?|caused|causal(?:ly)?|drives?|driven by|leads? to|because of|raises? prices?|pushes? (?:up|down))\b", re.I)


class Report:
    def __init__(self) -> None:
        self.rows: list[tuple[str, str, str]] = []

    def add(self, status: str, name: str, evidence: str) -> None:
        self.rows.append((status, name, evidence))
        print(f"{status:4s}  {name}: {evidence}", flush=True)

    def ok(self, cond: bool, name: str, good: str, bad: str, soft: bool = False) -> None:
        self.add("PASS" if cond else ("WARN" if soft else "FAIL"), name, good if cond else bad)

    @property
    def failed(self) -> int:
        return sum(r[0] == "FAIL" for r in self.rows)


# --- helpers -----------------------------------------------------------------------------------

def leak_codes() -> dict[str, set[str]]:
    """column -> set of leakage code words, parsed from data/DATA_DICTIONARY.md."""
    out: dict[str, set[str]] = {}
    for line in (ROOT / "data/DATA_DICTIONARY.md").read_text().splitlines():
        if not line.startswith("| `"):
            continue
        p = [x.strip() for x in line.split("|")]
        if len(p) < 9:
            continue
        head = p[8].split(":")[0]
        out[p[1].strip("`")] = {w for w in re.findall(r"[A-Z_]{2,}", head)}
    return out


def sources(var: str) -> list[str]:
    return DERIVED.get(var, [var])


def codes_of(var: str, codes: dict[str, set[str]]) -> tuple[set[str], list[str]]:
    """Union of codes over a variable's sources, plus the sources missing from the dictionary."""
    got, missing = set(), []
    for s in sources(var):
        if s in codes:
            got |= codes[s]
        else:
            missing.append(s)
    return got, missing


def truthy(v) -> bool:
    return str(v).strip().lower() in {"true", "1", "1.0"}


def pin(name: str, obj) -> tuple[bool, str]:
    """First run records obj; later runs compare. Returns (matches, message)."""
    PINS.mkdir(parents=True, exist_ok=True)
    f = PINS / f"{name}.json"
    blob = json.dumps(obj, sort_keys=True, default=str)
    if not f.exists():
        f.write_text(blob)
        return True, f"pinned now ({hashlib.sha256(blob.encode()).hexdigest()[:12]}) at {f.relative_to(ROOT)}"
    same = f.read_text() == blob
    return same, "matches pin" if same else f"CHANGED since pinned at {f.relative_to(ROOT)}"


def bh(p: pd.Series) -> pd.Series:
    v = p.astype(float).sort_values()
    m = len(v)
    q = (v * m / np.arange(1, m + 1))[::-1].cummin()[::-1].clip(upper=1)
    return q.reindex(p.index)


# --- number traceability ----------------------------------------------------------------------

NUM = re.compile(r"(?<![\w.])([−\-+]?)(\$?)(\d{1,3}(?:,\d{3})+|\d+)(\.\d+)?(\s?%| ?pp\b)?")


def _collect(obj, out: list[float]) -> None:
    if isinstance(obj, dict):
        for v in obj.values():
            _collect(v, out)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            _collect(v, out)
    elif isinstance(obj, bool):
        return
    elif isinstance(obj, (int, float)) and math.isfinite(obj):
        out.append(float(obj))
    elif isinstance(obj, str):
        try:
            x = float(obj)
            if math.isfinite(x):
                out.append(x)
        except ValueError:
            pass


def value_pool(tables: Path, extra: list[float]) -> list[float]:
    raw: list[float] = list(extra)
    for f in glob.glob(str(tables / "*.csv")):
        df = pd.read_csv(f)
        raw += [float(x) for x in df.select_dtypes("number").to_numpy().ravel() if np.isfinite(x)]
    for f in glob.glob(str(tables / "*.json")):
        _collect(json.loads(Path(f).read_text()), raw)
    for f in glob.glob(str(tables / "*.jsonl")):
        for line in Path(f).read_text().splitlines():
            if line.strip():
                _collect(json.loads(line), raw)
    pool = set()
    for v in raw:
        cands = [v, 100 * v]
        if abs(v) < 5:  # log points -> percent
            cands.append(100 * (math.exp(v) - 1))
        for c in cands:
            pool.add(round(c, 6))
            pool.add(round(abs(c), 6))
    return sorted(pool)


def traceable(x: float, dec: int, pool: list[float]) -> bool:
    tol = 0.5 * 10 ** (-dec) + 1e-9
    i = bisect.bisect_left(pool, x - tol)
    return i < len(pool) and pool[i] <= x + tol


def check_numbers(rep: Report, md: Path, tables: Path, extra: list[float]) -> None:
    if not md.exists():
        rep.add("FAIL", "findings exist", f"{md.relative_to(ROOT)} missing")
        return
    pool = value_pool(tables, extra)
    bad, notrace, n_checked = [], [], 0
    for ln, line in enumerate(md.read_text().splitlines(), 1):
        if "<!-- notrace" in line:
            notrace.append(f"L{ln}: {line.strip()[:110]}")
            continue
        t = re.sub(r"`[^`]*`|!\[[^\]]*\]\([^)]*\)|\]\([^)]*\)|https?://\S+", " ", line)
        t = re.sub(r"\b\d{4}-\d{2}(?:-\d{2})?(?:T[\d:+]+)?", " ", t)       # dates
        t = re.sub(r"\bH\d+[a-z]?\b|\bP\d+\b|\bA\d+\b|#\d+|\b\d+(?:st|nd|rd|th)\b", " ", t)  # ids, ordinals
        t = re.sub(r"\b\d+[-–]\d+\b(?=\s*(?:days?|years?|yrs?|months?|h|ms))", " ", t)
        # design constants, not results: window lengths and resampling counts
        t = re.sub(r"\b[\d,]+(?=(?:-d\b|\s?d\b|-day|\s?days?\b|\s(?:within-artist\s)?(?:permutations|draws|bootstrap|resamples|combinations)))", " ", t)
        for m in NUM.finditer(t):
            sign, dollar, intpart, frac, unit = m.groups()
            val = float(intpart.replace(",", "") + (frac or ""))
            is_year = not frac and not unit and not dollar and 1900 <= val <= 2100
            if is_year or not (frac or unit or dollar or val >= 100):
                continue
            n_checked += 1
            dec = len(frac) - 1 if frac else 0
            x = -val if sign in ("−", "-") else val
            if not (traceable(x, dec, pool) or traceable(val, dec, pool)):
                bad.append(f"L{ln} '{m.group(0).strip()}'")
    rep.ok(not bad, "findings numbers traceable to tables",
           f"{n_checked} numbers checked, all trace to {tables.relative_to(ROOT)}",
           f"{len(bad)} of {n_checked} untraceable: " + "; ".join(bad[:25]) + (" ..." if len(bad) > 25 else ""))
    if notrace:
        rep.add("INFO", "lines marked notrace (skeptic judges)", " | ".join(notrace[:15]))


# --- shared checks ----------------------------------------------------------------------------

def check_split(rep: Report, s: pd.DataFrame) -> None:
    for k in ["artist_id", "artist_key", "split_key"]:
        n = int(s.groupby(k).artist_split.nunique().gt(1).sum())
        rep.ok(n == 0, f"split grouped by {k}", f"every {k} in exactly one split", f"{n} {k}s in >1 split")
    if "artist_qid" in s:
        n = int(s.dropna(subset=["artist_qid"]).groupby("artist_qid").artist_split.nunique().gt(1).sum())
        rep.ok(n == 0, "split grouped by QID", "every QID in one split", f"{n} QIDs in >1 split")
    rel = ROOT / "data/manual/artist_relations.csv"
    if rel.exists():
        r = pd.read_csv(rel)
        a, b = r.columns[:2]
        sp = s.groupby("artist_id").artist_split.first()
        bad = [(x, y) for x, y in zip(r[a], r[b]) if x in sp and y in sp and sp[x] != sp[y]]
        rep.ok(not bad, "manual artist relations share a split", f"{len(r)} relations OK", f"cross-split: {bad[:10]}")
    npf = ROOT / "data/manual/non_performers.csv"
    if npf.exists():
        ids = set(pd.read_csv(npf).iloc[:, 0])
        n = int(s.artist_id.isin(ids).sum())
        rep.ok(n == 0, "non-performers excluded", "none in analysis sample", f"{n} sample rows from non-performer ids")


def check_hypotheses(rep: Report, tables: Path, codes: dict[str, set[str]], specs: list | None) -> pd.DataFrame | None:
    f = tables / "hypotheses.csv"
    if not f.exists():
        rep.add("FAIL", "hypotheses table", f"{f.relative_to(ROOT)} missing")
        return None
    h = pd.read_csv(f)
    need = ["hid", "sens", "status", "fe", "coef", "se", "ci_lo", "ci_hi", "p", "p_used", "effective_clusters",
            "clusters", "in_family", "q"]
    miss = [c for c in need if c not in h]
    rep.ok(not miss, "hypotheses.csv schema", "all required columns present", f"missing columns {miss}")
    if miss:
        return None
    h["in_family_b"] = h.in_family.map(truthy)
    base = h[h.sens == "base"]

    # BH family
    fam_f = tables / "bh_family.json"
    if not fam_f.exists():
        rep.add("FAIL", "BH family declared", f"{fam_f.relative_to(ROOT)} missing")
    else:
        fam = json.loads(fam_f.read_text())
        declared = set(fam["family"])
        excluded = set(fam.get("excluded", {}))
        in_tab = set(base.loc[base.in_family_b, "hid"])
        rep.ok(declared == in_tab, "BH family == rows flagged in_family",
               f"{len(declared)} hypotheses", f"declared-only {sorted(declared - in_tab)}, table-only {sorted(in_tab - declared)}")
        rep.ok(not (declared & excluded), "family and exclusions disjoint", "disjoint", f"overlap {sorted(declared & excluded)}")
        same, msg = pin(f"{tables.name}_bh_family", {"family": sorted(declared), "excluded": sorted(excluded)})
        rep.ok(same, "BH family fixed (pinned)", msg, msg)
        # recompute q: pending members enter at p = 1
        pu = base.set_index("hid").p_used.reindex(sorted(declared)).astype(float)
        pend = set(fam.get("pending_p1", {}))
        pu[pu.index.isin(pend) | pu.isna()] = 1.0
        q = bh(pu)
        stored = pd.Series(fam.get("q", {})).reindex(q.index).astype(float)
        tab_q = base.set_index("hid").q.reindex(q.index).astype(float)
        dq = float(np.nanmax(np.abs(q - stored))) if len(q) else 0.0
        dt = float(np.nanmax(np.abs(q - tab_q))) if len(q) else 0.0
        rep.ok(dq < 1e-9 and dt < 1e-9, "BH q recomputes (family, p_used, pending=1)",
               f"max |diff| json {dq:.1e}, table {dt:.1e}", f"max |diff| json {dq:.3g}, table {dt:.3g}")
        bad_excl = [x for x in excluded if not str(fam["excluded"][x]).strip()]
        rep.ok(not bad_excl, "every exclusion has a stated reason", f"{len(excluded)} excluded with reasons", f"no reason: {bad_excl}")

    # inference: df = effective clusters - 1, CI, wild bootstrap, LOO
    ok = h[(h.status == "ok") & h.se.notna() & (h.se > 0)].copy()
    g = ok.effective_clusters.astype(float)
    bad_eff = ok[g.isna() | (g > ok.clusters.astype(float))]
    rep.ok(bad_eff.empty, "effective clusters recorded and <= clusters", f"{len(ok)} rows",
           f"{len(bad_eff)} rows bad: {list(zip(bad_eff.hid, bad_eff.sens))[:8]}")
    ok = ok[g.notna() & (g >= 2)]
    df = ok.effective_clusters.astype(float) - 1
    tstat = ok.coef / ok.se
    p_re = 2 * stats.t.sf(tstat.abs(), df)
    crit = stats.t.ppf(0.975, df)
    errp = (p_re - ok.p).abs() / np.maximum(ok.p, 1e-12)
    errc = np.maximum((ok.coef - crit * ok.se - ok.ci_lo).abs(), (ok.coef + crit * ok.se - ok.ci_hi).abs()) / ok.se
    bp = ok[(errp > 1e-3) & ((p_re - ok.p).abs() > 1e-8)]
    bc = ok[errc > 1e-3]
    rep.ok(bp.empty, "p uses t with df = effective_clusters - 1", f"{len(ok)} rows reproduce",
           f"{len(bp)} rows don't (e.g. {list(zip(bp.hid, bp.sens, bp.p.round(4), p_re[bp.index].round(4)))[:5]})")
    rep.ok(bc.empty, "95% CI uses t(effective_clusters - 1)", f"{len(ok)} rows reproduce",
           f"{len(bc)} rows don't (e.g. {list(zip(bc.hid, bc.sens))[:5]})")
    few = base[(base.status == "ok") & base.effective_clusters.notna() & (base.effective_clusters.astype(float) < WILD_BELOW)]
    if len(few):
        nowild = few[few.p_wild.isna()] if "p_wild" in few else few
        rep.ok(nowild.empty, f"wild bootstrap p where G_eff < {WILD_BELOW}", f"{len(few)} hypotheses: {list(few.hid)}",
               f"missing p_wild: {list(nowild.hid)}")
        if "p_wild" in few:
            notused = few[few.p_wild.notna() & ((few.p_used - few.p_wild).abs() > 1e-12)]
            rep.ok(notused.empty, "wild p enters BH (p_used = p_wild)", "yes", f"not used: {list(notused.hid)}")
        if "loo_min" in few:
            noloo = few[few.loo_min.isna()]
            rep.ok(noloo.empty, f"leave-one-group-out where G_eff < {WILD_BELOW}", "present", f"missing: {list(noloo.hid)}")

    # two-way clustering
    if "cluster2" in h:
        bad = [f"{k} (has '{base.set_index('hid').cluster2.get(k, '')}')" for k, v in TWO_WAY.items()
               if k in set(base.hid) and str(base.set_index("hid").cluster2.get(k, "")) != v]
        rep.ok(not bad, "two-way clustering where required", ", ".join(f"{k}×{v}" for k, v in TWO_WAY.items()), "wrong/missing: " + "; ".join(bad))
    else:
        rep.add("FAIL", "two-way clustering where required", "no cluster2 column")

    # year FE everywhere
    nofe = base[(base.status == "ok") & ~base.fe.fillna("").str.contains("year")]
    rep.ok(nofe.empty, "year FE in every base spec", f"{int((base.status == 'ok').sum())} specs", f"no year FE: {list(nofe.hid)}")

    # sensitivities present for every family member
    fam_ids = set(base.loc[base.in_family_b, "hid"])
    missing = {hid: [s for s in REQUIRED_SENS if s not in set(h.loc[h.hid == hid, "sens"])] for hid in sorted(fam_ids)}
    missing = {k: v for k, v in missing.items() if v}
    rep.ok(not missing, "required sensitivities present", f"{len(REQUIRED_SENS)} specs × {len(fam_ids)} hypotheses",
           "; ".join(f"{k}: {v}" for k, v in list(missing.items())[:6]))
    empty = h[h.status.isna() | (h.status.astype(str).str.strip() == "")]
    rep.ok(empty.empty, "every sensitivity row has a status", "yes", f"{len(empty)} blank")

    # headline labels and family membership vs leakage codes
    if specs is not None:
        bad_ctrl, bad_fam, unmapped, label_mismatch, expost_ctrl = [], [], set(), [], []
        for sp in specs:
            xc, xm = codes_of(sp.x, codes)
            unmapped |= set(xm)
            if sp.hid in fam_ids and xc & {"OUTCOME", "TARGET", "ID", "DEPRECATED"}:
                bad_fam.append(f"{sp.hid}:{sp.x}={sorted(xc)}")
            lab = set(re.findall(r"[A-Z_]{2,}", sp.label or ""))
            if (xc & FORBIDDEN_PRED) - lab:
                label_mismatch.append(f"{sp.hid}: label '{sp.label}' vs codes {sorted(xc & FORBIDDEN_PRED)}")
            for c in list(sp.controls) + list(getattr(sp, "cat_controls", [])):
                cc, cm = codes_of(c, codes)
                unmapped |= set(cm)
                if cc & FORBIDDEN_CONTROL:
                    bad_ctrl.append(f"{sp.hid}:{c}={sorted(cc)}")
                elif cc & {"EXPOST"}:
                    expost_ctrl.append(f"{sp.hid}:{c}")
        rep.ok(not bad_ctrl, "no OUTCOME/TARGET/ID controls", f"{len(specs)} specs checked", "; ".join(bad_ctrl))
        rep.ok(not bad_fam, "no OUTCOME/TARGET regressor in the BH family", "none", "; ".join(bad_fam))
        rep.ok(not label_mismatch, "headline labels carry the regressor's leakage codes", "consistent", "; ".join(label_mismatch))
        if expost_ctrl:
            rep.add("WARN", "EXPOST controls (judge: post-treatment?)", ", ".join(expost_ctrl))
        if unmapped:
            rep.add("FAIL", "regressors/controls traceable to dictionary columns",
                    f"unmapped {sorted(unmapped)}: add to the dictionary or to DERIVED in autocheck.py")
    return h


def check_touches(rep: Report, tables: Path, findings: Path, current_hash: str | None, split_counts: dict | None) -> None:
    log = tables / "test_touch_log.jsonl"
    touches = [json.loads(x) for x in log.read_text().splitlines() if x.strip()] if log.exists() else []
    rep.add("INFO", "test touches logged", f"{len(touches)}: " + "; ".join(f"#{i + 1} {t.get('at')} kind={t.get('kind', '-')}" for i, t in enumerate(touches)))
    if not touches and not (tables / "final_spec.json").exists():
        rep.add("INFO", "holdout", "no test touches and no frozen spec: no out-of-sample claim may be made in the findings")
        return
    finals = [t for t in touches if t.get("kind") == "final"]
    if touches:  # a spec may be frozen before its test date (PATH, review 4 F5); then no touch exists yet
        rep.ok(len(finals) == 1, "exactly one final test touch", "1 final touch", f"{len(finals)} final touches")
    else:
        rep.add("INFO", "final test touch", "spec frozen, no touch yet: no out-of-sample claim may be made")
    spec_f = tables / "final_spec.json"
    if not spec_f.exists():
        rep.add("FAIL" if touches else "INFO", "frozen spec", "final_spec.json missing")
        return
    frozen = json.loads(spec_f.read_text())
    h = hashlib.sha256(json.dumps(frozen["spec"], sort_keys=True, default=str).encode()).hexdigest()
    rep.ok(h == frozen["sha256"], "frozen spec self-hash", h[:12], f"file says {frozen['sha256'][:12]}, content hashes to {h[:12]}")
    if finals:
        f = finals[0]
        rep.ok(f.get("spec_sha256") == frozen["sha256"], "final touch used the frozen spec",
               frozen["sha256"][:12], f"touch {str(f.get('spec_sha256'))[:12]} != frozen {frozen['sha256'][:12]}")
        if split_counts:
            rep.ok(f.get("n") == split_counts, "final touch split sizes == current split", str(split_counts),
                   f"touch {f.get('n')} vs now {split_counts}")
        mr = tables / "model_results.json"
        if mr.exists():
            r = json.loads(mr.read_text())
            diffs = []
            for tgt, mods in f.get("test_mae_log", {}).items():
                for m, v in mods.items():
                    got = r.get(tgt, {}).get("test", {}).get(m, {}).get("mae_log")
                    if got is None or abs(got - v) > 1e-12:
                        diffs.append(f"{tgt}/{m}")
            rep.ok(not diffs, "model_results.json test numbers == logged final touch", "identical",
                   f"differ (unlogged re-evaluation?): {diffs[:6]}")
    if current_hash is not None:
        rep.ok(current_hash == frozen["sha256"], "current code+data reproduce the frozen spec", current_hash[:12],
               f"current {current_hash[:12]} != frozen {frozen['sha256'][:12]} (code or data changed after freezing)")
    if findings.exists() and touches:
        txt = findings.read_text()
        def disclosed(i: int, t: dict) -> bool:
            if re.search(rf"touch\s*#?\s*{i + 1}\b", txt, re.I):
                return True
            sha = str(t.get("spec_sha256") or "")
            return t.get("kind") == "final" and len(sha) >= 12 and sha[:12] in txt
        miss = [i + 1 for i, t in enumerate(touches) if not disclosed(i, t)]
        rep.ok(not miss, "every test touch disclosed in findings", f"touches 1..{len(touches)} mentioned", f"not mentioned: {miss}")


def check_predictive_features(rep: Report, tables: Path, codes: dict[str, set[str]], s: pd.DataFrame | None) -> None:
    spec_f = tables / "final_spec.json"
    if not spec_f.exists():
        return
    spec = json.loads(spec_f.read_text())["spec"]
    feats = spec.get("features_numeric", []) + spec.get("features_categorical", [])
    bad, uncoded = [], []
    for c in feats:
        cc, missing = codes_of(c, codes)
        uncoded += missing
        if cc & FORBIDDEN_PRED:
            bad.append(f"{c}={sorted(cc & FORBIDDEN_PRED)}")
    rep.ok(not bad, "predictive features carry no EXPOST/OUTCOME/TARGET/SHOWDAY/POST_ONSALE/ID code",
           f"{len(feats)} features clean", "; ".join(bad))
    rep.ok(not uncoded, "predictive features present in the dictionary", "all coded", f"not in dictionary: {sorted(set(uncoded))}")
    sus = [c for c in feats if re.search(r"price|gross|ticket|sellout|avg_|revenue|attendance|rel_|split", c)]
    rep.ok(not sus, "no outcome-like feature names", "none", f"suspicious: {sus}")
    tg = spec.get("targets", [])
    rep.ok("price_rel_artist_median" not in tg, "deprecated target not modelled", f"targets {tg}", "price_rel_artist_median used")
    if s is not None:
        y = s.log_avg_price_real
        yw = y - y.groupby(s.artist_key).transform("mean")
        hi = []
        for c in spec.get("features_numeric", []):
            if c in s and c not in TIME_LIKE:
                x = pd.to_numeric(s[c], errors="coerce").astype(float)
                xw = x - x.groupby(s.artist_key).transform("mean")
                m = xw.notna() & (xw.abs() > 0)
                if m.sum() > 100:
                    r = float(np.corrcoef(xw[m], yw[m])[0, 1])
                    if abs(r) > 0.4:
                        hi.append(f"{c} r_within={r:.2f}")
        rep.ok(not hi, "no feature with |within-artist r| > 0.4 vs price (leak screen)", "none", "; ".join(hi), soft=True)


def check_causal_language(rep: Report, findings: Path, h: pd.DataFrame | None) -> None:
    if h is None or not findings.exists() or "label" not in h:
        return
    lab = h[h.sens == "base"].set_index("hid").label.fillna("")
    noncausal = [k for k, v in lab.items() if set(re.findall(r"[A-Z_]{2,}", v)) & NONCAUSAL]
    hits = []
    for ln, line in enumerate(findings.read_text().splitlines(), 1):
        if CAUSAL.search(line) and any(re.search(rf"\b{k}\b", line) for k in noncausal):
            hits.append(f"L{ln}: {line.strip()[:100]}")
    rep.ok(not hits, "no causal wording on EXPOST/OUTCOME/POST_ONSALE/SHOWDAY hypotheses", f"{len(noncausal)} labelled hypotheses",
           " | ".join(hits[:6]), soft=True)


def check_deprecated_in_code(rep: Report, pattern: str) -> None:
    hits = []
    for f in glob.glob(str(ROOT / pattern)):
        for ln, line in enumerate(Path(f).read_text().splitlines(), 1):
            code = line.split("#", 1)[0]
            if "price_rel_artist_median" in code and "touch" not in code:  # reading the touch-1 log entry is allowed
                hits.append(f"{Path(f).name}:{ln}")
    rep.ok(not hits, "deprecated price_rel_artist_median not used in analysis code", "absent", ", ".join(hits[:8]))


def check_approved(rep: Report, prefix: str) -> None:
    """reviews/approved.json: {"L1": "reviews/<file>.md", ...}. Each entry must point to an existing review file
    whose text states '<tag> ... APPROVED' on one line, so the report builder can trust the file."""
    f = ROOT / "reviews/approved.json"
    if not f.exists():
        rep.add("FAIL", "reviews/approved.json", "missing")
        return
    try:
        a = json.loads(f.read_text())
    except json.JSONDecodeError as e:
        rep.add("FAIL", "reviews/approved.json", f"invalid JSON: {e}")
        return
    bad = []
    for tag, path in a.items():
        if not re.fullmatch(r"[LP]\d+[a-z]?", tag):
            bad.append(f"{tag}: bad tag")
            continue
        rf = ROOT / str(path)
        if not rf.exists():
            bad.append(f"{tag}: {path} missing")
        elif not re.search(rf"\b{re.escape(tag)}\b.*\bAPPROVED\b", rf.read_text()):
            bad.append(f"{tag}: no '{tag} ... APPROVED' line in {path}")
    mine = sorted(k for k in a if k.startswith(prefix))
    rep.ok(not bad, "approved.json entries backed by a review", f"{len(a)} entries ({prefix}: {mine})", "; ".join(bad))


# --- modes ------------------------------------------------------------------------------------

def level_current_hash(s_loaded) -> str | None:
    """Recompute level_model.current_spec() without importing level_model (avoids the shap import)."""
    try:
        src = (ROOT / "src/analysis/level_model.py").read_text()
        consts = {}
        for node in ast.parse(src).body:
            if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                n = node.targets[0].id
                if n in {"GRID", "SEED", "MIN_LEVEL", "TARGETS"}:
                    consts[n] = ast.literal_eval(node.value)
        from analysis.level_data import predictive_features
        s = s_loaded
        num, cat = predictive_features(s)
        cov = json.loads((ROOT / "data/shows_join_coverage.json").read_text())
        split_hash = hashlib.sha256(s.sort_values("show_id")[["show_id", "artist_split"]].to_csv(index=False).encode()).hexdigest()
        spec = {"features_numeric": num, "features_categorical": cat, "grid": consts["GRID"], "targets": consts["TARGETS"],
                "seed": consts["SEED"], "min_level": consts["MIN_LEVEL"], "data_built": cov["_summary"]["built"],
                "n_sample": int(len(s)), "split_rows_sha256": split_hash}
        return hashlib.sha256(json.dumps(spec, sort_keys=True, default=str).encode()).hexdigest()
    except Exception as e:  # noqa: BLE001
        print(f"WARN  current spec hash: could not recompute ({type(e).__name__}: {e})")
        return None


def run_level(rep: Report) -> None:
    tables, findings = ROOT / "reports/level_tables", ROOT / "reports/level_findings.md"
    codes = leak_codes()
    from analysis.level_data import load_sample
    s = load_sample()
    rep.add("INFO", "analysis sample", f"{len(s)} rows, {s.artist_id.nunique()} artist_ids, {s.split_key.nunique()} split_keys")
    check_split(rep, s)
    try:
        from analysis.level_hypotheses import SPECS
    except Exception as e:  # noqa: BLE001
        SPECS = None
        rep.add("FAIL", "import level_hypotheses.SPECS", f"{type(e).__name__}: {e}")
    h = check_hypotheses(rep, tables, codes, SPECS)
    split_counts = {k: int(v) for k, v in s.artist_split.value_counts().items()}
    split_counts = {k: split_counts.get(k, 0) for k in ("train", "valid", "test")}
    check_touches(rep, tables, findings, level_current_hash(s), split_counts)
    check_predictive_features(rep, tables, codes, s)
    check_deprecated_in_code(rep, "src/analysis/level_*.py")
    check_causal_language(rep, findings, h)
    extra = [len(s), s.artist_id.nunique(), s.artist_key.nunique(), s.split_key.nunique(), *split_counts.values(),
             s.tour_unit.nunique() if "tour_unit" in s else 0]
    check_numbers(rep, findings, tables, extra)
    check_approved(rep, "L")


def run_path(rep: Report) -> None:
    tables, findings = ROOT / "reports/path_tables", ROOT / "reports/path_findings.md"
    if not tables.exists():
        rep.add("FAIL", "PATH outputs", f"{tables.relative_to(ROOT)} missing (see the contract in this file's docstring)")
        return
    codes = leak_codes()
    h = check_hypotheses(rep, tables, codes, None)
    spec_f = tables / "path_spec.json"
    if not spec_f.exists():
        rep.add("FAIL", "path_spec.json", "missing: needed for the as-of leakage checks")
    else:
        ps = json.loads(spec_f.read_text())
        p = pd.read_parquet(ROOT / ps["panel"])
        rep.add("INFO", "PATH panel", f"{ps['panel']}: {len(p)} rows, {p[ps['entity']].nunique()} entities")
        snap = pd.to_datetime(p[ps["snapshot_time"]], utc=True)
        show = pd.to_datetime(p[ps["show_time"]], utc=True)
        n = int((snap > show).sum())
        rep.ok(n == 0, "no snapshot after the show", "all snapshots precede the show", f"{n} rows snapshotted after show time")
        for c in ps.get("feature_time_cols", []):
            ft = pd.to_datetime(p[c], utc=True)
            n = int((ft > snap).sum())
            rep.ok(n == 0, f"as-of: {c} <= snapshot", "no future-dated feature input", f"{n} rows where {c} is after the snapshot")
        if ps.get("target_time_col"):
            tt = pd.to_datetime(p[ps["target_time_col"]], utc=True)
            n = int((tt <= snap).sum())
            rep.ok(n == 0, "target observed strictly after the snapshot", "yes", f"{n} rows with target time <= snapshot")
        if ps.get("split"):
            for k in [ps["entity"]] + ([ps["artist"]] if ps.get("artist") else []):
                n = int(p.groupby(k)[ps["split"]].nunique().gt(1).sum())
                rep.ok(n == 0, f"split grouped by {k}", f"every {k} in one split", f"{n} {k}s in >1 split")
        forb = set(ps.get("forbidden_features", []))
        used = set(ps.get("features", []))
        rep.ok(not (forb & used), "declared-forbidden features unused", f"{len(used)} features", f"used: {sorted(forb & used)}")
        sus = [c for c in used if re.search(r"final|last_price|future|lead_|next_|_after|outcome|resid", c, re.I)]
        rep.ok(not sus, "no future-looking feature names", "none", f"suspicious: {sus}", soft=True)
    check_touches(rep, tables, findings, None, None)
    fs = tables / "final_spec.json"
    if fs.exists():  # review 4 round 2: the frozen test code must still be the code on disk
        want = json.loads(fs.read_text())["spec"].get("test_code_sha256")
        got = hashlib.sha256((ROOT / "src/analysis/path_hypotheses.py").read_bytes()).hexdigest()
        rep.ok(got == want, "path_hypotheses.py matches frozen test_code_sha256", got[:12],
               f"current {got[:12]} != frozen {str(want)[:12]} (test code changed after freezing)")
    check_predictive_features(rep, tables, codes, None)
    check_causal_language(rep, findings, h)
    check_numbers(rep, findings, tables, [])
    check_approved(rep, "P")


def main() -> int:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--level", action="store_true")
    g.add_argument("--path", action="store_true")
    a = ap.parse_args()
    t0 = time.time()
    rep = Report()
    (run_level if a.level else run_path)(rep)
    n = {k: sum(r[0] == k for r in rep.rows) for k in ("PASS", "FAIL", "WARN", "INFO")}
    print(f"\nautocheck {'--level' if a.level else '--path'}: {n['PASS']} PASS, {n['FAIL']} FAIL, {n['WARN']} WARN "
          f"({time.time() - t0:.1f}s)")
    return 1 if rep.failed else 0


if __name__ == "__main__":
    sys.exit(main())
