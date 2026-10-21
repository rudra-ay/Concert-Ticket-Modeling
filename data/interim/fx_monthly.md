# fx_monthly.parquet

Monthly foreign-exchange rates, **units of foreign currency per 1 USD**, January 1971 to September 2026. Long format: one row per currency per month. Built by `src/build_fx.py`. Raw files are cached in `data/raw/fx/` and `data/raw/fx_ecb/`.

**Sources:**
- **A12, Federal Reserve Board G.5/H.10** (primary; public domain). Cite "Board of Governors of the Federal Reserve System, G.5/H.10 Foreign Exchange Rates."
- **A13, ECB euro foreign exchange reference rates**, used only for the 21 currencies the Fed does not publish, from 1999 on. **Source: European Central Bank. The ECB data are modified here:** each day's rate is crossed through that day's USD/EUR reference rate (`(X per EUR) / (USD per EUR)`), and the daily crosses are averaged by month. The ECB's terms require stating such modifications. These rows have `is_cross_rate = True`.

Key: (`currency`, `month_start`).

| column | type | unit | source / meaning | null meaning |
|---|---|---|---|---|
| currency | string | ISO 4217 | e.g. GBP, EUR, DEM | never null |
| month_start | datetime | first day of month | | never null |
| year / month | int | | from `month_start` | never null |
| units_per_usd | float | currency units per USD | monthly average of daily noon buying rates in New York | never null (months with no data are omitted) |
| source | string | | `FRB G.5 monthly average` or `FRB H.10 historical daily, monthly mean` | never null |
| series_id | string | | G.5 series name (e.g. `RXI_N.M.JA`, `RXI$US_N.M.UK`) or the historical files used (e.g. `dat89_ge,dat96_ge`) | never null |
| quoted_as | string | | how the Fed quotes it: `units per USD`, or `USD per unit (inverted)` for AUD, NZD, GBP, EUR (and IEP from its daily file) | never null |
| is_euro_legacy | bool | | pre-euro national currency (Fed historical files) | never null |
| is_cross_rate | bool | | the row is an ECB rate crossed via USD/EUR (A13) | never null |
| eur_fixed_rate | float | units per EUR | irrevocable euro conversion rate (Council Regulations 2866/98 and 1478/2000) | not a legacy currency |
| n_daily_obs | float | days | trading days averaged (Fed legacy and ECB rows) | G.5 rows (the Fed averages them itself) |

## Coverage (55 currencies)
- **From 1971:** AUD, CAD, CHF, DKK, GBP, JPY, MYR, NOK, NZD, SEK, ZAR, plus legacy DEM, FRF, ITL, NLG, BEF, ATS, FIM, IEP.
- **Later starts:** INR and LKR 1973-01; ESP and PTE 1973-01; CNY, HKD, SGD and THB 1981-01; GRD 1981-04; KRW 1981-04; TWD 1983-10; **MXN 1993-11**; **BRL 1995-01**; VEB 1995-01; **EUR 1999-01**.
- **From the ECB, crossed via USD (1999 on unless noted):** CZK, HUF, PLN, ISK (gap during the 2008–2018 suspension), BGN (2000-07 to 2025-12; Bulgaria joined the euro 2026-01), ROL to 2005-06 then **RON** from 2005-07 (1 RON = 10,000 ROL), **TRL** to 2004-12 then **TRY** from 2005-01 (1 TRY = 1,000,000 TRL), RUB 2005-04 to 2022-03 (the ECB suspended it), HRK 2005-04 to 2022-12 (Croatia joined the euro 2023-01), IDR and PHP from 2005-04, ILS from 2011-01. Plus pre-euro currencies of the later joiners: SIT to 2006, CYP and MTL to 2007, SKK to 2008, EEK to 2010, LVL to 2013, LTL to 2014.
- **Still not covered:** ARS, CLP, COP, PEN, UYU, PYG, CRC, DOP, GTQ, RSD, AED, MOP and others. **On the final spine, 94.1% of priced non-US shows** (7,365 of 7,827) have a rate for their country's currency in their show month, 288 of them through ECB crosses (89.9% with the Fed alone). The untestable shows are mostly in Argentina, Chile, Colombia and Peru, then Costa Rica, the UAE and the Dominican Republic. Ecuador (since 2000), El Salvador (2001) and Panama use the US dollar, so "$" there is USD by law. AED (3.6725 per USD since 1997) and MOP (pegged to HKD at about 1.03) have fixed pegs the analyst can apply by hand if needed.

## Country → currency mapping rule (use the show month)
- **Euro area:** the national currency before the join date, EUR from it. 1999-01-01: DE→DEM, FR→FRF, IT→ITL, ES→ESP, NL→NLG, BE→BEF, LU→BEF (the Luxembourg franc was at par with BEF), AT→ATS, PT→PTE, FI→FIM, IE→IEP. **2001-01-01: GR→GRD.** 2007-01-01: SI→SIT. 2008-01-01: CY→CYP, MT→MTL. 2009-01-01: SK→SKK. 2011-01-01: EE→EEK. 2014-01-01: LV→LVL. 2015-01-01: LT→LTL. 2023-01-01: HR→HRK. 2026-01-01: BG→BGN.
- **Redenominations:** RO→ROL before 2005-07-01, RON from it (1 RON = 10,000 ROL). TR→TRL before 2005-01-01, TRY from it (1 TRY = 1,000,000 TRL). VE→VEB is the Fed's series as published; it doesn't follow Venezuela's later redenominations, so treat it with care.
- **Everyone else:** a fixed code, e.g. GB→GBP, CA→CAD, AU→AUD, NZ→NZD, MX→MXN, JP→JPY, CH→CHF (also LI), SE→SEK, NO→NOK, DK→DKK, BR→BRL, KR→KRW, CN→CNY, HK→HKD, TW→TWD, SG→SGD, TH→THB, MY→MYR, IN→INR, ZA→ZAR, CZ→CZK, HU→HUF, PL→PLN, IL→ILS, PH→PHP, ID→IDR, RU→RUB, IS→ISK.
- **Dollarized** (no conversion; "$" is USD): EC (from 2000), SV (from 2001), PA, PR.
- The 89.9% / 94.1% coverage figures in this file use exactly this mapping.

## Which mislabels are self-revealing (skeptic review, src/review/r1b_fx_probe.py)
A local-currency figure mislabeled as "$" is inflated by `units_per_usd`. Where that ratio is far from 1, the error is visible without this table: pesos (CLP ~400–950, COP ~2,000–4,000, ARS after 2010, MXN ~10–20), **HKD (~7.8, pegged)** and **TWD (~30)**. The risky cases are ratios near 1–3: CAD, AUD, NZD, SGD, and **ARS 2002–2010 (~3 per USD, the one genuine blind spot without a rate here)**. That's where this table matters, with GBP, EUR and JPY as controls. ARS 1991–2001 is **harmless, not risky**: at the 1:1 peg a mislabel changes the number by 0%.

**Why the remaining untestable 5.9% doesn't bias the test (skeptic review, 2026-10-19; settled, please don't re-open without new evidence):**
1. Most untestable countries don't print prices in "$" at all: Peru (S/), Costa Rica (₡), Paraguay (₲), Guatemala (Q). Their rows can't be "$" mislabels.
2. Where "$" is used (AR, CL, CO, DO, UY), a mislabeled peso would inflate prices 3× to 4,000× (+1.1 to +8 log points vs the artist's norm). Observed sample medians are AR −0.10, CL −0.13, CO −0.01, DO −0.12, UY −0.12, with maxima of +0.99 to +1.20, far below a CLP (≈ +6.5) or COP (≈ +7.8) unit error. The ~10 extreme rows in AR/CL/CO/VE are already flagged (implausible / tour_outlier) and excluded. The analyst checks the individual rows above +0.7 by hand.
3. So conclusions from the testable 94.1% don't rest on a selected subset in any way that matters. Within the untestable set, the only residual risk is ARS 2002–2010 (10 rows, median −0.34, so no sign of inflation).

## Euro-legacy currencies (read before joining pre-1999 European shows)
- EUR exists only from **1999-01**. For eurozone shows before then, use the national currency: DEM, FRF, ITL, ESP, NLG, BEF (also used for Luxembourg), ATS, PTE, FIM, IEP. These run to 1998-12. **Greece (GRD) runs to 2000-12**, since it joined on 2001-01-01. No EUR row is synthesized before 1999.
- A legacy figure reported **after** 1999 (rare: national-currency prices circulated until early 2002) converts as `units_per_usd(EUR, month) × eur_fixed_rate`.
- Consistency check: each legacy rate in Dec 1998 is within 1.0–1.1% of EUR in Jan 1999 × its fixed rate, identical across all ten, which is the euro's move that month.
- Later euro joiners (Slovenia 2007, Cyprus and Malta 2008, Slovakia 2009, Estonia 2011, Latvia 2014, Lithuania 2015, Croatia 2023) have no pre-euro series here.

## Method and validation
- **ECB crosses vs the Fed**, for 8 currencies both publish (JPY, GBP, CAD, AUD, CHF, SEK, KRW, MXN; 225–333 months each): median relative gap **0.05–0.07%**, max 0.4–1.2% (KRW). The gap reflects the different fixing times (ECB about 14:15 CET, Fed noon New York). The current partial month is dropped from ECB rows.
- G.5 rows are the Fed's published monthly averages. Legacy rows are our monthly means of the Fed's daily noon buying rates, which is the same method G.5 uses. Recomputing **JPY** that way reproduces published G.5 to within **0.00005%** across all 348 overlapping months (1971–1998).
- Observations flagged ND (no data) are dropped. Months with no observations are omitted, not zero.
- `UNIT_MULT` on the GBP series in the Fed file is ignored: the values are dollars per pound (about 1.27 in 2024), inverted here to pounds per dollar.

## How to use it for the "$ means USD?" test
Join a show to (`currency` of its country, `month_start` of its date), then compare the reported "$" figure against `figure / units_per_usd` (if it was really local currency, converted to USD). For CAD, AUD, NZD and MXN, a local-currency "$" sits at a stable ratio to USD-reported figures for the same tour. Fixed-format checks (e.g. tour-level ratio ≈ units_per_usd) are the analyst's call.
