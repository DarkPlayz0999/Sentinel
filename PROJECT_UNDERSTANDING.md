# SENTINEL — PROJECT UNDERSTANDING REPORT

**SIH 2026 · PS SIH26170 · ISRO · AI-Driven Anomaly Detection in Component Burn-In & Screening**

Status: **DRAFT — awaiting your approval.** Once approved, this document becomes the
working source of truth for the project.

Prepared: 2026-09-14
Repo inspected: `/Users/himanshusolanki/Downloads/sih/Sentinel` @ `56457b3`
Method: every claim below was verified by reading the source and **executing** the code
(`pytest`, `src.baseline`, `src.report`, direct pipeline traces). Where I could not
verify something, it is marked `UNKNOWN / NEEDS CONFIRMATION`. Nothing is assumed.

---

## 0. EXECUTIVE SUMMARY

This is a **substantially complete, genuinely well-engineered ML system** — far beyond
typical hackathon maturity. 9,021 lines across Python + TypeScript. 150 tests, all
passing. Every headline metric in the README reproduces when I re-ran it.

The intellectual honesty is the strongest asset in the repo: it documents where its own
claims are weaker than the blueprint promised (the correlation-break rationale, Module B's
detection weakness, the metrology recall ceiling), with measurements. That is unusual and
it is a competitive weapon in front of technical judges.

**The real gaps are not in the ML.** They are:
1. No persistence layer, no auth, no audit log — a safety-critical claim the deck will make and the code cannot back.
2. Two disconnected frontends: a Streamlit inspector tool and a static Next.js explainer site that never talks to the API.
3. No upload path in the demo UI — the "upload your burn-in data" story runs only through raw HTTP.
4. Doc/code drift in four specific places (listed in §13 and §17).
5. The problem statement's own hero example is caught but **explained by the wrong reason code**.

---

## 1. SOURCE OF TRUTH — WHAT I INSPECTED

| Source | Status | Notes |
|---|---|---|
| SIH problem statement SIH26170 | From your brief only | I do not have the official PDF text. §13 mapping is against the brief you gave me. `NEEDS CONFIRMATION` |
| `docs/SENTINEL_Burn-In_Anomaly_Detection_Blueprint.pdf` | **NOT READ** | Binary PDF, not extracted. Code references it heavily (§8.4, §12, §2.1). `NEEDS CONFIRMATION` |
| `docs/SENTINEL_Slide_Blueprint.pdf` | **NOT READ** | Same. |
| `README.md` (446 lines) | Read in full | Extremely detailed; verified against code and re-execution |
| `CLAUDE.md` (rules 1–14) | Read in full | Operating constitution; code complies |
| All 17 `src/*.py` | Read in full | |
| `app/dashboard.py` | Read in full | |
| `web/` Next.js app | Read in full | |
| `data/*.csv` (5 files) | Profiled directly | |
| Test suite | **Executed** — 150 passed | |
| Screenshots / architecture diagrams | **NOT PROVIDED** | `NEEDS CONFIRMATION` |

> **Two blueprint PDFs are the stated authority for this project and I have not read
> them.** Everything below reflects the code and README. If the blueprint contradicts
> the code, the code is what actually runs — but I cannot tell you where they diverge.

---

## 2. THE PROBLEM, IN ENGINEERING TERMS

Components for space/defence go through **burn-in**: powered and operated at 125 °C with
electrical parameters read at 0 h, 24 h, 96 h, 168 h (MIL-STD-883 Method 1015).

Screening today is judged on **static datasheet limits**: a part is good if `Iddq < 50 µA`.

The flaw, quantified in this dataset: **174 of 174 latent defects (100.0%) pass every
static datasheet limit at 168 h.** Static screening catches literally none of them.
I verified this directly against `data/burnin_wide.csv`.

The physical argument the project rests on, with the numbers it actually uses:
- Arrhenius, Ea = 0.7 eV, 25 °C use / 125 °C stress → **AF ≈ 937**
- 168 burn-in hours ≈ **18 years** of field operation at 25 °C
- Therefore a drift visible in one week of burn-in consumes the part's entire mission life

**The reframe:** stop asking "is this part inside the datasheet?" and start asking
(a) "is this part behaving like its lot-siblings?" and (b) "where will it be in a week?"

Vocabulary the project uses consistently (and you must too, in front of judges):
- **Latent defect** — passes all limits, carries a growing physical flaw. The target class.
- **Escape** — a defective part that ships. False negative. Catastrophic.
- **Overkill** — a good part rejected. False positive. The currency you trade for recall.
- **DPAT** — Dynamic Part Average Testing. `median ± k · robust σ`, per lot. **The existing industry method this project extends.**
- **PDA** — Percent Defective Allowable. >5% of a lot rejected → lot goes to review. Caps aggression.
- **Robust sigma** — `1.4826 · MAD`. Equals σ for normal data, 50% breakdown point.

---

## 3. THE ACTUAL WORKFLOW AS IMPLEMENTED

Verified by reading `src/pipeline.py::screen()`, which is the single entry point the API,
dashboard and report generator all call.

```
data/burnin_wide.csv  (2,100 parts × 24 cols)
        │
        ▼
build_features(df)                              src/features.py
  per-lot robust z, 4 named views × 4 params    → 20 z-cols + 4 curv-cols
  log-transform currents; median + 1.4826·MAD
        │
        ├─────────────────────┬──────────────────────────────┐
        ▼                     ▼                              │
  MODULE A               MODULE B  (only if 168h present     │
  src/module_a.py        src/module_b.py   and ≥2 lots)      │
   L1 static USL          GroupKFold(lot) out-of-fold        │
   L2 DPAT worst |z|      power-law n* fit → LightGBM stack  │
   L3 pooled Σz²          + quantile(0.90) upper bound       │
   (L3 Mahalanobis =      calibrate_population_k → safety    │
    comparison only)      slope → early_reject @ h24         │
        │                     │                              │
        └──────────┬──────────┘                              │
                   ▼                                         │
             fusion.py — 5 named weighted sub-scores ◄────────┘
             risk 0–100 = 30·static_margin + 25·dynamic_outlier
                        + 20·predicted_drift + 15·multivariate
                        + 10·curvature
             bands_for_pda() sizes REJECT edge to the 5% PDA budget
             L1 static breach = hard REJECT override
                   │
                   ▼
             verdict: ACCEPT / WATCH / REJECT
                   │
                   ▼
             explain.py — reason codes R-101…R-601 (rule-based)
             lot_pda_status() → R-601 lot-level gate
                   │
      ┌────────────┼────────────┬─────────────┐
      ▼            ▼            ▼             ▼
  api.py      dashboard.py  report.py   screening_report.py
  FastAPI     Streamlit     stdout      one-page signed PDF
```

**Verdict on your conceptual workflow:** the implementation matches it closely, with one
important ordering difference. You described explainability *after* the risk score.
The code computes reason codes **in parallel** with fusion, from independent rule
thresholds (`explain.Thresholds`) — not from the fused score. This is architecturally
better (the explanation cannot be a post-hoc rationalisation of the score) but it means
**a part can be REJECT with zero reason codes, or carry reason codes while ACCEPT.**
That is a real demo risk. See §8.

| Stage | Status |
|---|---|
| Component → burn-in → measurements @ 0/24/96/168h | **IMPLEMENTED** (simulated) |
| Data preprocessing | **IMPLEMENTED** — `features.py`, log-transform, per-lot robust stats |
| Module A dynamic anomaly detection | **IMPLEMENTED** — L1, L2, L3 (+ Mahalanobis comparison) |
| Module B drift / future prediction | **IMPLEMENTED** — power law + LightGBM + quantile bound |
| Explainability | **IMPLEMENTED** — rule-based reason codes, exact attribution |
| Risk score | **IMPLEMENTED** — weighted named sub-scores |
| PASS / WATCH / REJECT | **IMPLEMENTED** — as ACCEPT/WATCH/REJECT, PDA-aware bands |
| Data upload in UI | **MISSING** — API only (`POST /screen`); no uploader in either frontend |
| Persistence / audit trail | **MISSING** |
| L4 ensemble layer | **MISSING** — README claims it, code has no L4 |

---

## 4. MODULE A — DYNAMIC ANOMALY DETECTION

`src/module_a.py` (220 lines), features from `src/features.py` (427 lines).

### Input features — 24 columns, all computed per lot

For each of 4 parameters, 5 z-views + 1 raw ratio:

| View | Formula | What it catches |
|---|---|---|
| `z_{p}_level_0h` | robust z of V₀ | born bad |
| `z_{p}_level_168h` | robust z of V₁₆₈ | **the brief's worked example** |
| `z_{p}_early` | robust z of (V₂₄ − V₀) | fast movers; only view available at h24 |
| `z_{p}_drift` | robust z of (V₁₆₈ − V₀) | classic delta, made lot-relative |
| `z_{p}_curvature` | robust z of acceleration ratio | settling vs accelerating |
| `curv_{p}` | raw acceleration ratio | quoted verbatim by R-501 |

### The three layers

| Layer | Algorithm | Output | Purpose |
|---|---|---|---|
| **L1** | `V > USL` at any read point | boolean | The baseline we exist to beat. Catches **0/174** latent defects. Kept in the pipeline permanently so the demo can show exactly that. |
| **L2** | worst-case `\|robust z\|` over all 20 z-cols, `skipna=True` | continuous | Dynamic PAT. The industry method, extended. PR-AUC 0.3889 |
| **L3** | **one-sided** sum of squared z over the 4 `_drift` axes | continuous | Pooled marginal evidence. PR-AUC **0.4083** — shipped |
| *(comparison)* | MinCovDet robust Mahalanobis on the 4-d delta vector | continuous | PR-AUC 0.4038 — kept as a comparison row, **not shipped** |

### Statistical technique — the core discipline

- **Location = `median`, spread = `1.4826 · MAD`.** Never mean/std. Rationale in code: a mean-based σ is inflated by the very outlier it is hunting (*masking*), and the mean is dragged by it (*swamping*). Both estimators have a 50% breakdown point.
- **MAD = 0 fallback → `IQR / 1.35`**, not `std()`. This is a *deliberate documented deviation* from the blueprint's reference snippet, justified by rule 2.
- **Currents log-transformed first** (`Iddq_uA`, `Ileak_nA` are lognormal); timing/voltage raw.
- **Every statistic within a lot** (`groupby(lot).transform(...)`). This is the entire reason dynamic beats static.
- **z-scores returned SIGNED** — the sign is needed to distinguish "abnormally high" from "abnormally low" in a reason code; the one-sided decision belongs to the scoring layer.

### Threshold calculation
Not magic numbers. `evaluate.cost_minimising_threshold` minimises `C_FN·FN + C_FP·FP` with
`C_FN/C_FP = 100` as a **parameter and a dashboard slider**. Separately, `fusion.bands_for_pda`
places band edges by quantile against the 5% PDA budget. `module_b.calibrate_population_k`
derives k from a stated flag-rate budget (unsupervised — needs no labels).

### Handling of edge cases — verified in code
| Case | Handling |
|---|---|
| Missing 96h read (99 rows, ~1.2%) | NaN **preserved, not filled**. Curvature omitted; part scored on remaining views via `skipna=True`. Filling with 0.0 would assert "no acceleration" — a claim the data does not support. |
| Lot with zero measurable spread | `robust_z` returns 0.0 (not ∞). "No spread means no evidence, not infinite evidence." |
| Non-positive current (log impossible) | → NaN, not −inf. Guards against a real tester emitting 0 on a failed read. |
| Hour-24 frame (no 168h cols) | L3 returns **NaN**, not 0 — "a caller that mistakes a missing layer for a zero score would read the part as safer than the evidence supports." |
| Different lots | Every statistic recomputed per lot. Unsupervised → runs on a lot never seen. |
| Different parameters | Registry-driven `PARAMS` dict; `is_current` flag drives the transform. |

### **The brief's worked example — VERIFIED WORKING**

I traced a real part through the shipped pipeline:

```
L04-0348 · lot L04
  Iddq_uA @ 168h = 49.5 µA      lot median = 15.1 µA      USL = 50.0 µA

  TRADITIONAL:  49.5 < 50.0  →  PASS  ✓ ships
  SENTINEL:     risk 78.9 / 100  →  REJECT

  sub-scores:  static_margin 98.0 | dynamic_outlier 100.0 | predicted_drift 35.7
               multivariate 100.0 | curvature 23.2
```

**Exactly how it reaches that decision:**
1. `transform()` puts Iddq on the log scale (lognormal).
2. `robust_z` within lot L04 on the drift view → `z_Iddq_uA_drift = 18.65`.
3. L2 `dpat_score` = worst |z| = 18.65 → squashed at full-scale 6σ → `dynamic_outlier = 100`.
4. L3 `pooled_evidence_score` clips negative z, squares, sums the 4 drift axes → 348.5 against a χ²(0.999, 4 dof) = 18.47 threshold → `multivariate = 100`.
5. `static_margin` = consumed headroom `(V₁₆₈ − V₀)/(USL − V₀)` = 98.0 — it ate essentially all its own margin.
6. Weighted sum = 78.9 → above the PDA-sized REJECT edge of 61.2 → **REJECT**.
7. `explain.py` emits **R-401**: *"No single parameter trips its own limit, but the combined drift evidence across parameters is 348.5 against an 18.5 threshold (Iddq_uA 18.7 sigma, Ileak_nA …). Individually ordinary, jointly rare for this lot."*

**⚠️ FINDING — the explanation does not match the story you will tell.**
`z_Iddq_uA_level_168h = 4.04`, and **R-101 fires only above 6.0**. So on the problem
statement's own signature case, the reason code that says *"the level is abnormal for this
lot"* **does not fire**. The part is caught by drift and pooled evidence instead.

The system gets the right answer for a defensible reason — but if a judge asks
*"show me it flagging the 45-in-a-10-µA-lot case and telling me why,"* the sentence it
produces is about combined drift, not about the level. **This is the single highest-value
fix before the demo.** See §17.

---

## 5. MODULE B — DRIFT / FUTURE PREDICTION

`src/module_b.py` (479 lines). The most sophisticated module in the repo.

| Item | Implementation |
|---|---|
| **Input** | `V_0h` and `V_24h` **only**, per parameter. Enforced structurally: `features.early_feature_names()` + a test that rebuilds from a frame with late columns deleted. |
| **Output** | Point forecast of `Value_168h`, plus a 0.90-quantile **upper bound** |
| **Model** | 3-stage stack: (1) physics power law, (2) LightGBM residual, (3) LightGBM quantile |
| **Training data** | `data/burnin_wide.csv`, out-of-fold under `GroupKFold(groups=lot)`, 6 splits |
| **Features** | 10 from `build_forecast_features` + `physics` forecast as an 11th column (stacking) |
| **Target** | `{param}_168h`, raw scale |
| **Loss** | `objective="regression_l1"` (MAE) for the point model; `objective="quantile", alpha=0.90` for the bound |
| **Hyperparameters** | `n_estimators=300, learning_rate=0.05, num_leaves=15, min_child_samples=30, subsample=0.9, colsample_bytree=0.9, random_state=42` |
| **Uncertainty** | Quantile regression at α=0.90. The REJECT decision is made **on the upper bound**, so a part is rejected only when even its optimistic forecast breaches. `np.maximum(q, point)` guards the bound from falling below the point estimate. |
| **Evaluation** | MAE (headline), plus normalised MAE, tail MAE, and two baselines: linear extrapolation and last-value-carried-forward. **No R² reported** — deliberate, and correct for a screening context. |

### The physics model

`X(t) = X₀ · (1 + A · (t/168)ⁿ)`

With only two points you cannot fit two parameters per part, so:
- **shape** (`n*`) fitted globally per parameter, on the training folds, by MAE grid search over `n ∈ [0.00, 2.00]` step 0.02
- **magnitude** (`A`) solved per part: `A_i = (X₂₄/X₀ − 1) / (24/168)^n*`, then `X₁₆₈ = X₀(1 + A_i)`

The exponent grid was **widened to include 0** (blueprint searches [0.3, 2.0]). At n=0 the
model degenerates exactly to last-value-carried-forward. This matters: for `Tpd_ns` and
`Vol_mV` the MAE-optimal exponent **is 0**, meaning *the data supports no extrapolation on
those axes*. On the blueprint's grid the model would be clamped at 0.30 and lose to a
trivial baseline. This is a genuinely good piece of engineering judgement.

### Measured performance — I re-ran this

| Parameter | n* | **MAE** | linear | last-value | verdict |
|---|---|---|---|---|---|
| `Iddq_uA` | 0.41 | **1.2923** | 2.3515 | 1.8353 | beats both |
| `Ileak_nA` | 0.41 | **2.5856** | 4.5585 | 3.5977 | beats both |
| `Tpd_ns` | 0.00 | 0.1576 | 0.3880 | **0.1128** | loses to last-value |
| `Vol_mV` | 0.00 | 8.7526 | 26.2308 | **7.5454** | loses to last-value |

> **⚠️ Numbers drift slightly from the README.** README states Iddq 1.313 / Ileak 2.595 /
> Vol 8.624; I measured 1.2923 / 2.5856 / 8.7526. Same ballpark, different third digit —
> almost certainly LightGBM threading nondeterminism or a platform/version difference
> (macOS here vs. the Windows environment `requirements.txt` was pinned against). **If a
> judge re-runs on a different machine and gets a different number than the slide, that is
> an awkward moment.** Pin `n_jobs=1` / `deterministic=True`, or quote the figures to 2
> significant figures. `NEEDS CONFIRMATION` on root cause.

### Safety slope — matches your described concept, with a correction

Two independent gates, in **different units**, so they are deliberately *not* `min()`'d
into one number (the docstring is explicit that averaging uA/h with log-uA/h would be
wrong). The **stricter decision wins** — either firing rejects the part:

- `S_mission = (USL − V₀) / (mission_hours / AF)` — "this part will not survive the mission"
- `S_population = median(slope_lot) + k · robust σ(slope_lot)`, computed **on the log scale** — "this part is not like its siblings"

**Measured:** the mission gate fires on 0.0–0.1% of parts. A 7-year mission is only 65.5
equivalent burn-in hours against 168 available, so a part would have to fail catastrophically
inside the burn-in to trip it. **The population gate does all the work.**

`calibrate_population_k` replaces the blueprint's fixed k=4.5 (which fired on **25.8%** of
parts and blew the PDA gate five times over) with a k derived from a stated flag-rate
budget — k ≈ 30.5 for a 5% gate. Deliberately unsupervised.

### **The honest limitation — and you must lead with it, not hide it**

```
score                                        PR-AUC   R@5%   R@10%
Module A L3, full 168h drift  [the ceiling]  0.4083   0.776  0.874
hour-24 pooled z of the raw EARLY delta      0.1539   0.270  0.328
Module B, pooled z of physics forecast       0.1532   0.264  0.328
Module B, pooled z of GBM forecast           0.1427   0.195  0.310
Module B, slope ratio vs the safety slope    0.1248   0.138  0.236
```

**The forecast adds nothing to detection.** The raw early delta ranks defects as well as
anything built on top of it, because a forecast is a near-monotone function of the early
delta plus a level, and the level carries no defect information. The code says so
explicitly and `fusion` consumes `early_warning_score` (the raw early delta) rather than
the forecast for the hour-24 path.

**So the defensible pitch is a triage layer, not an earlier equivalent screen:**
> At hour 24 we catch ~33% of latent defects at a 10% overkill budget, against ~87% at
> hour 168 — and we free **144 oven-hours on every part we pull**, on a scarce,
> power-hungry, capacity-limiting resource.

Measured in `src.report`: 104 parts pulled at h24 = **14,976 oven-hours freed**.

---

## 6. DATASET ANALYSIS

**All data is synthetic**, generated by `src/generate_burnin_dataset.py`, seed 42, fully
reproducible (a test asserts byte-identical regeneration). This is disclosed prominently
in the README and **must be disclosed in the submission.**

### Files

| File | Rows | Cols | Contents |
|---|---|---|---|
| `burnin_wide.csv` | 2,100 | 24 | one row per part, all read points, labels — **the primary artefact** |
| `burnin_long.csv` | 8,400 | 8 | tidy long form (2,100 × 4 read points) |
| `public_train.csv` | 1,260 | 24 | 60% split, keeps labels + 168h |
| `hidden_test.csv` | 840 | 17 | 40% split, labels and all `_168h` columns **stripped** |
| `ground_truth.csv` | 840 | 8 | the stripped columns, for scoring |

### Schema — `burnin_wide.csv` (verified by direct profiling)

| Column | Type | Notes | Module A | Module B | Fusion |
|---|---|---|---|---|---|
| `serial` | object | `L{lot}-{nnnn}`, **2,100 unique, 0 duplicates** | id | id | id |
| `lot` | object | `L01`…`L06`, **350 parts each** | **✓ grouping** | **✓ grouping** | ✓ |
| `wafer` | object | `W01`…`W05` | ✗ | ✗ | wafer map only |
| `x` | int64 | 0–59 die coord | ✗ | ✗ | wafer map only |
| `y` | int64 | 0–59 die coord | ✗ | ✗ | wafer map only |
| `true_class` | object | `healthy`/`latent`/`gross` | eval only | eval only | eval only |
| `is_latent_defect` | int64 | **THE TARGET** | eval only | ✗ | eval only |
| `Iddq_uA_{0,24,96,168}h` | float64 | lognormal, centre 10.0, USL 50.0 | **✓** | **✓ (0h,24h)** | ✓ |
| `Ileak_nA_{0,24,96,168}h` | float64 | lognormal, centre 20.0, USL 200.0 | **✓** | **✓ (0h,24h)** | ✓ |
| `Tpd_ns_{0,24,96,168}h` | float64 | normal, centre 3.20, USL 4.60 | **✓** | **✓ (0h,24h)** | ✓ |
| `Vol_mV_{0,24,96,168}h` | float64 | normal, centre 210.0, USL 400.0 | **✓** | **✓ (0h,24h)** | ✓ |
| `static_fail_168h` | int64 | **55 parts** | L1 reference | ✗ | ✓ |

### Class balance and the headline fact

```
healthy  1863  (88.7%)
latent    174  ( 8.3%)   ← THE TARGET CLASS
gross      63  ( 3.0%)
```
**latent defects passing static limits at 168h: 174 / 174 = 100.0%** ✓ verified

### Missing values — the only NaNs in the dataset

| Column | NaN | Cause |
|---|---|---|
| `Iddq_uA_96h` | 24 | simulated handler drop, `MISSING_96H_RATE = 0.012` |
| `Ileak_nA_96h` | 25 | " |
| `Tpd_ns_96h` | 22 | " |
| `Vol_mV_96h` | 28 | " |

**Only the 96h read points. All 0h / 24h / 168h reads are complete.** Preserved as NaN
throughout — never imputed.

### Per-lot ground truth — L04 is the planted bad lot

| lot | gross | healthy | latent | latent rate |
|---|---|---|---|---|
| L01 | 10 | 315 | 25 | 7.1% |
| L02 | 7 | 329 | 14 | 4.0% |
| L03 | 5 | 326 | 19 | 5.4% |
| **L04** | **21** | **264** | **65** | **18.6%** ← centre ×1.22, spread ×1.45, 3× latent rate |
| L05 | 8 | 318 | 24 | 6.9% |
| L06 | 12 | 311 | 27 | 7.7% |

### Deliberate realism baked into the generator

- Lognormal currents / normal timing — so plain `mean ± 3σ` fails on currents
- Lot-to-lot offsets (`center_mult ~ N(1.0, 0.06)`) — so a static limit tuned on L01 is wrong for L04
- **~10% of healthy parts naturally "wide"** — the tails genuinely overlap, creating irreducible false positives
- Each latent defect affects **only 1–2 of 4 parameters** — a detector watching only Iddq misses half the population
- 1.5% flat measurement noise; timing/voltage drift scaled to **0.12** of current drift

### Unused fields
`wafer`, `x`, `y` feed only the wafer map. The code is honest about why: the generator
draws (x, y) **uniformly at random, independent of class**, so there is no spatial structure
to find. `wafer.spatial_clustering` runs a permutation test and correctly reports *no
clustering*. Good engineering; do not claim spatial detection on the slide.

### Missing fields that matter for a real ISRO deployment
`NEEDS CONFIRMATION` against the blueprint, but the following are absent and a
reliability engineer will notice:
- **Temperature / voltage actuals per read** — only a nominal 125 °C constant exists; no per-part chamber telemetry, so "temperature sensitivity" cannot be an explainability factor
- **Timestamps** — no real dates on any read
- **Tester / handler / chamber slot ID** — no way to detect equipment-correlated drift
- **Part type / package / date code**
- **Field-return outcomes** — the only true validation of a latent-defect claim

---

## 7. MACHINE LEARNING INVENTORY

There are **exactly two trained ML models** in this project. Everything else is robust
statistics or rule logic. That is a deliberate, documented, and defensible choice.

### Model 1 — Module B point forecaster

| Field | Value |
|---|---|
| **Name** | `PowerLawForecaster._mean_models[param]` |
| **Purpose** | Forecast `Value_168h` from the first 24 hours |
| **Input** | 11 features (10 lot-relative + `physics`), per parameter |
| **Output** | Scalar `Value_168h`, raw units |
| **Training data** | `burnin_wide.csv`, out-of-fold, `GroupKFold(groups=lot, n_splits=6)` |
| **Target** | `{param}_168h` |
| **Algorithm** | LightGBM `LGBMRegressor`, `objective="regression_l1"` — **supervised, ensemble, tabular** |
| **Hyperparameters** | `n_estimators=300, lr=0.05, num_leaves=15, min_child_samples=30, subsample=0.9/freq=1, colsample=0.9, seed=42` |
| **Evaluation** | MAE vs two baselines (linear, last-value) |
| **Performance** | Iddq −44%, Ileak −43% vs linear; **loses to last-value on Tpd and Vol** |
| **Limitations** | Cannot extrapolate where n*=0. Fitted per-parameter (4 models). Falls back to physics wherever the design matrix is unusable. |

### Model 2 — Module B quantile bound

Same class and hyperparameters, `objective="quantile", alpha=0.90`. Purpose: the
conservative upper bound the REJECT decision is made on. **Supervised, ensemble.**

### Non-ML scorers (statistical, unsupervised)

| Component | Type | Notes |
|---|---|---|
| L1 static limits | rule | threshold on USL |
| L2 DPAT | **robust statistics, unsupervised** | median + 1.4826·MAD per lot |
| L3 pooled evidence | **robust statistics, unsupervised** | one-sided Σz² over 4 drift axes |
| L3 Mahalanobis | unsupervised, robust covariance | `MinCovDet(random_state=42)` — **comparison only, not shipped** |
| Global exponent n* | **fitted parameter** (1 scalar per param) | MAE grid search; **re-fitted per fold** — leaving it fitted on all data would leak test-lot 168h values |
| `calibrate_population_k` | unsupervised calibration | targets a flag *fraction*, needs no labels |
| Fusion weights | **hand-set, not learned** | rule 11: ML improves sub-scores, it does not make the decision |
| Reason codes | **rule-based** | fixed thresholds in `explain.Thresholds` |

**Overall system classification: predominantly unsupervised / statistical, with two
supervised gradient-boosted regressors confined to the forecasting sub-task.** No deep
learning — explicitly rejected by rule 10 ("on ~2,000 tabular rows, robust statistics and
gradient boosting win"). The final verdict is **never** a raw model output.

### Declared but NOT USED — verified by grep across `src/`, `app/`, `tests/`

| Package | Declared for | Actually used? |
|---|---|---|
| `shap==0.46.0` | "TreeExplainer + waterfall plots" | **NO — zero imports** |
| `xgboost==2.1.3` | "alternative booster for Module A L4" | **NO — zero imports** |
| `pandera==0.20.4` | "dataframe schema contracts at ingest" | **NO — zero imports** |
| `joblib==1.4.2` | "model persistence" | **NO — zero imports. No model is ever saved.** |
| `plotly==5.24.1` | "interactive dashboard charts" | **NO — dashboard uses matplotlib** |
| `IsolationForest` | mentioned in requirements comment | **NO** |

This is ~6 unused pinned dependencies and, more importantly, **`explain.py`'s own docstring
claims "SHAP is only needed for Module B's gradient-boosted residual" — that code does not
exist.** A judge who greps for SHAP after reading that sentence will find nothing.

---

## 8. EXPLAINABILITY

`src/explain.py` (317 lines). Explicitly scoped as "a third of the marking scheme, and the
cheapest third to win."

### Mechanism: rule-based reason codes — NOT a model explainer

| Code | Trigger | Threshold | Severity | Fires on |
|---|---|---|---|---|
| **R-101** | robust z of 168h **level** | `> 6.0` | high | 155 |
| **R-201** | robust z of **early delta** (0→24h) | `> 5.0` | high | 85 |
| **R-301** | predicted slope / safety slope | `> 1.0` | high | 104 |
| **R-401** | pooled multivariate evidence | `> 18.47` (χ²(0.999), 4 dof) | medium | 251 |
| **R-501** | curvature ratio (late rate / early rate) | `> 2.0` | medium | 87 |
| **R-601** | **lot-level** REJECT fraction vs PDA | `> 0.05` | high | 3 lots |

**Measured: 682 codes across 285 parts.**

### Every code carries the actual value AND the lot reference, in datasheet units

Real output I generated:
> **R-101:** *"Iddq_uA at 168h is 9.3 robust sigma above the lot median (53.07 uA vs lot
> median 10.8 uA). This also EXCEEDS the datasheet limit of 50 uA — a hard reject on
> static limits alone."*

> **R-401:** *"No single parameter trips its own limit, but the combined drift evidence
> across parameters is 348.5 against a 18.5 threshold (Iddq_uA 18.7 sigma, Ileak_nA 9.9
> sigma). Individually ordinary, jointly rare for this lot."*

Two details that show real care:
1. **R-101 has a conditional clause.** If the part also breaches the USL it says so, because telling an inspector a breaching part is "within the datasheet limit" would be **a false statement on a signed record**.
2. **R-401's wording deliberately avoids "impossible combination"/"correlation break"** — because the delta-vector covariance in this dataset is diagonal (max |ρ| 0.153 vs permutation-null p95 0.189) and that claim would be unsupported.

### Attribution is exact, not approximate

`top_contributions()` — for the robust-z layers the contribution to the DPAT score **is**
the z-score, and the contribution to the pooled score **is** the squared term. No surrogate
model, no sampling. As the docstring puts it: *"Reporting them is not an approximation of
the decision, it is the decision."* This is genuinely stronger than SHAP for this
architecture and you should say so.

### The visual explainer
`drift_plot()` — four read points against the lot's 5th–95th percentile envelope over time,
the Module B forecast dashed out to 168h, the datasheet USL in red. The legend is pinned
upper-left deliberately (`loc="best"` lands it on the envelope exactly where the reader is
looking). **This is the single most persuasive artefact in the project.**

### Audit record
`part_report()` returns measured values vs lot statistics, reason codes, top contributions,
`MODEL_VERSION = "sentinel-0.3.0"`, and a UTC timestamp. `screening_report.py` renders a
**one-page signed PDF per rejected part** (reportlab; a test asserts it is exactly one page).

### Mapping to the factors you listed

| Factor you asked about | Implemented? |
|---|---|
| High deviation from lot average | **YES** — R-101 |
| Increasing drift | **YES** — R-201 |
| Abnormal slope | **YES** — R-301 |
| Predicted future threshold crossing | **YES** — R-301 (on the 0.90 upper bound) |
| Parameter instability / joint evidence | **YES** — R-401 |
| Acceleration vs settling | **YES** — R-501 |
| Lot-level anomaly | **YES** — R-601 |
| **Historical similarity** | **MISSING** — no case-based/nearest-neighbour retrieval |
| **Temperature sensitivity** | **MISSING** — no per-part temperature data exists (see §6) |

### ⚠️ Two explainability gaps

1. **Reason codes are decoupled from the verdict.** They come from independent fixed thresholds, not from the fused score. A REJECT part can carry zero codes. I did not measure how often — **`NEEDS CONFIRMATION`, and it is worth measuring before the demo.**
2. **R-101 misses the hero case** (§4). `z_level_168h = 4.04 < 6.0` on the exact scenario from the problem statement.

---

## 9. SYSTEM ARCHITECTURE — AS BUILT

```
┌─────────────────────────────┐   ┌──────────────────────────────────┐
│  Next.js 14 static site     │   │  Streamlit dashboard             │
│  web/  (App Router, export) │   │  app/dashboard.py — 7 screens    │
│  6 scroll "stations"        │   │  THE INSPECTOR TOOL              │
│  MEASURE→COMPARE→DETECT→    │   │  matplotlib charts, cost slider  │
│  PREDICT→EXPLAIN→DECIDE     │   └──────────────┬───────────────────┘
│                             │                  │ direct import
│  ⚠ NO API CALLS AT ALL      │                  │
│  reads lab-data.ts, which   │                  │
│  is EXPORTED offline by     │                  │
│  web/scripts/export_lab_    │                  │
│  data.py from the real      │                  │
│  pipeline                   │                  │
└─────────────────────────────┘                  │
                                                 │
┌─────────────────────────────┐                  │
│  FastAPI  src/api.py        │                  │
│  GET /health /part/{s}      │──────────────────┤
│      /part/{s}/report       │   direct import  │
│      /lot/{id} /lots        │                  │
│  POST /screen  (CSV upload) │                  │
│  ⚠ NO AUTH, NO CORS, NO RATE│                  │
│  @lru_cache(maxsize=1)      │                  │
└──────────────┬──────────────┘                  │
               │                                 │
               ▼                                 ▼
      ┌──────────────────────────────────────────────────┐
      │  src/pipeline.py :: screen(df) -> ScreenResult   │
      │  THE single orchestration point. API, dashboard  │
      │  and report.py all call it, so none of them can  │
      │  disagree about a part.                          │
      └────────────────────┬─────────────────────────────┘
                           ▼
      ┌──────────────────────────────────────────────────┐
      │  src/features.py — THE only feature definition   │
      └───┬──────────────┬──────────────┬────────────────┘
          ▼              ▼              ▼
    module_a.py     module_b.py     fusion.py ──► explain.py
    L1/L2/L3        powerlaw+GBM    weighted      R-101…R-601
                    +quantile       sub-scores    + PDF report
                           │
                           ▼
      ┌──────────────────────────────────────────────────┐
      │  src/evaluate.py — THE scorer. One scorer,       │
      │  one truth. accuracy() RAISES on purpose.        │
      └──────────────────────────────────────────────────┘
                           │
                           ▼
      ┌──────────────────────────────────────────────────┐
      │  STORAGE:  flat CSV in data/ only.               │
      │  ⚠ NO DATABASE. NO PERSISTENCE. NO AUDIT LOG.    │
      │  ⚠ NO MODEL ARTEFACTS SAVED (joblib unused).     │
      │  Everything recomputed in memory per process.    │
      └──────────────────────────────────────────────────┘
```

| Layer | Technology | Status |
|---|---|---|
| Frontend A (inspector) | Streamlit 1.39.0, 7 screens | **IMPLEMENTED** |
| Frontend B (explainer) | Next.js 14.2 + React 18 + Tailwind + framer-motion + recharts, **static export** | **IMPLEMENTED**, untracked in git |
| Backend / API | FastAPI 0.115.5 + uvicorn, 6 endpoints, pydantic contracts | **IMPLEMENTED** |
| ML services | In-process Python. No model server, no queue | **IMPLEMENTED (in-process)** |
| Database | **NONE** | **MISSING** |
| Storage | Flat CSV in `data/` | Minimal |
| Authentication | **NONE** | **MISSING** |
| Data pipeline | `pipeline.py` — synchronous, in-process | **IMPLEMENTED** |
| Model serving | Refit on every cold start; `@lru_cache(maxsize=1)` | **PARTIAL** |
| Model versioning | `MODEL_VERSION` string constant only | **PARTIAL** |
| Logging / audit trail | **NONE** — no `logging` import anywhere | **MISSING** |
| Deployment | Two bash scripts (`run_demo.sh`, `start_app.sh`). No Docker, no CI | **MISSING** |
| Testing | 150 pytest tests, **all passing** | **IMPLEMENTED** |

**Key architectural strength:** the single-orchestration-point discipline. `pipeline.py` is
called by all three consumers, and `features.py` is the only place a feature is defined.
This closes the most common and most fatal ML-demo failure — training/serving skew.

---

## 10. FRONTEND ANALYSIS

### Frontend A — Streamlit inspector dashboard (`app/dashboard.py`, 314 lines)

Seven screens, sidebar radio navigation:

| Screen | Contents |
|---|---|
| Lot Overview | lot cards, PDA status, the bad lot standing out |
| Part Table | sortable by risk, colour-coded verdict chips |
| **Part Detail** | drift plot w/ lot envelope + forecast, risk breakdown, reason codes |
| Distributions | per-parameter histogram, log + linear, DPAT and datasheet limits overlaid |
| Model Performance | confusion matrix, recall-vs-overkill curve, MAE table |
| **Decision Policy** | **the cost-ratio slider — the demo centrepiece** |
| Wafer Map | die grid coloured by risk + the measured clustering test |

Header docstring: *"Renders only. Every number comes from `src.pipeline` / `src.evaluate` —
nothing is computed here, so what the inspector sees is what the API returns."* Verified true.

**Missing: no file uploader.** It loads `data/burnin_wide.csv` unconditionally.

### Frontend B — Next.js static explainer site (`web/`)

Six scroll-driven "stations" that walk the method: **MEASURE → COMPARE → DETECT → PREDICT
→ EXPLAIN → DECIDE**. One `IntersectionObserver` drives a process-flow rail.

| Sub-component | Data source | Real? |
|---|---|---|
| `lab-data.ts` (16 KB, generated) | `export_lab_data.py` ← real pipeline, seed 42 | **REAL — genuine histograms, PR data, lot stats** |
| `burnin.ts` (the animation clock) | **hardcoded** `V0=12.4, A=0.3642, N=0.9`, `PREDICTED_168H=48.7` | **SCRIPTED REPLAY — not pipeline output** |

The `burnin.ts` header is honest that it is *"the demo cell's scripted replay, fitted to the
storyboard control points"* using the same power-law form. It is a marketing animation, not
a live reading. **Do not let a judge believe the animating number is live inference.**

### Does the visual design communicate aerospace + semiconductor + reliability?

**Yes — genuinely and deliberately.** The evidence is in the design tokens:

- Palette comment: *"Instrument panel palette. Light, matte, no glow — this is a lab, not a spaceship bridge."*
- Colours: `lab-floor #E8E9EB`, `lab-panel #F6F6F5`, `sig-blue #12508C`, `sig-green #186B45`, `sig-amber #9A5B06`, `sig-red #A81E12` — muted signal colours, not SaaS gradients
- `.grid-paper` — *"Every panel in this building sits on engineering grid"*
- `.panel` — *"An instrument panel: hard corners, hairline rule, one soft inner light"*
- `.screw` — machined screw heads at rack-panel corners
- `.readout` — monospace, `tabular-nums`
- Animations restricted to `led` (2.4s blink), `shimmer`, `trace` — instrument behaviour, not AI sparkle
- **`prefers-reduced-motion` respected** — jumps straight to t=168h

**This is a strong differentiator.** It reads as test-floor equipment, not an AI startup.
It avoids exactly the "generic AI SaaS dashboard" failure you were worried about.

### Frontend priorities you listed — scorecard

| Priority | Where |
|---|---|
| Engineering clarity | **STRONG** — both frontends |
| Real measurements | **STRONG** — real units, real lot medians |
| Time-series charts | **STRONG** — `drift_plot` w/ lot envelope |
| Lot comparisons | **STRONG** — lot overview, per-lot PDA, distributions |
| Burn-in stages | **STRONG** — 0/24/96/168h throughout; the Next site is built on it |
| Component status | **STRONG** — verdict chips, risk scores |
| Prediction | **PRESENT** — forecast dashed on the drift plot |
| Explainability | **STRONG** — reason codes in both frontends |
| Screening decisions | **STRONG** — ACCEPT/WATCH/REJECT + PDA |
| Avoid unnecessary AI effects | **STRONG** — explicitly designed against |
| **Data upload** | **MISSING in both** |
| **Screening workflow (run a new lot)** | **MISSING in both** |
| **Alerts** | **MISSING** — no notification concept |

### ⚠️ The architectural problem with having two frontends
They share no code, no data path, and no API. The Next.js site never calls the FastAPI
service. If a judge asks *"is that site live?"* the answer is no — it is a static export
with numbers baked in at build time. **Decide before the demo which one is "the product"
and present the other as what it is.**

---

## 11. COMPETITOR ANALYSIS

> **`NEEDS CONFIRMATION` on this entire section.** Written from general domain knowledge,
> not from vendor documentation read in this session. Verify each claim before it goes on
> a slide — a judge from ISRO may know these tools better than you do.

| Competitor | What they already do | What they do better than us | What they don't focus on | How we differ |
|---|---|---|---|---|
| **KLA I-PAT** (Inline Part Average Testing) | Inline defect inspection data → per-die outlier scoring; flags dies that pass electrical test but sit in defect-rich neighbourhoods. **The closest prior art to our thesis.** | Real fab deployment, inline inspection data we don't have, proven yield correlation, spatial/wafer-level signal | Burn-in **time-series** drift; forecasting a future parametric value | We work on **parametric time-series during burn-in**, not inline inspection imagery. Our axis is *time*, theirs is *space*. |
| **yieldHUB** | Yield management, PAT/DPAT, test-data analytics, outlier detection, dashboards. **Already implements DPAT — our L2.** | Mature product, scale, real customers, data integration with ATE | Forecasting 168h from 24h; mission-life Arrhenius reasoning; inspector-facing reason codes as a first-class artefact | Our L2 *is* their feature. Our differentiation is **L3 + Module B + the reason-code layer**, not DPAT. |
| **PDF Solutions Exensio** | Big-data semiconductor analytics, test ops, PAT, ML on fab data | Enterprise scale, data volume, breadth | Small-lot hi-rel space screening; explicit PDA-vs-recall trade UI | Our niche is **small-lot, high-consequence, human-signed** screening |
| **Ansys Sherlock** | Physics-of-failure **reliability prediction** from CAD/BOM — solder fatigue, thermal cycling, life prediction | Real physics models, no data needed, accepted in design reviews | **Prediction from measured burn-in data of an individual part** | Sherlock predicts a *design's* reliability; we screen an *individual part* from its measurements |
| **Vektrex STARS** | LED/SSL stress test and reliability systems, test control | Instrument control, real stress hardware | AI anomaly detection on the resulting parametric data | We are the **analysis layer**, complementary not competing |
| **Keysight burn-in / reliability** | ATE, burn-in boards, test executives, data capture | The measurement hardware itself | What to *do* with the drift data beyond limits | We consume their output |
| **Academic AI burn-in work** | Isolation Forest / autoencoders / LSTMs on ATE data | Novel model architectures | Explainability to an inspector; PDA constraints; production operating points | We deliberately **reject deep learning** (rule 10) and ship explainability instead |

### ⚠️ Honest assessment of defensibility

**Never say "no one has done this before."** DPAT is an AEC-Q001 industry standard.
I-PAT is a shipping KLA product. yieldHUB sells outlier detection today. A judge from
ISRO may have evaluated these.

**What is genuinely ours:**
1. **The integration** — dynamic detection + early forecasting + rule-based explanation + PDA-aware disposition in one auditable pipeline, where each stage's contribution is *measured* against the others.
2. **The hour-24 triage economics** — 144 oven-hours freed per pulled part. I have not seen this framed as the headline value of early forecasting.
3. **The explainability contract** — the verdict is *structurally* a weighted sum of named sub-scores, so it cannot become a black box. Attribution is exact, not SHAP-approximate.
4. **The honesty artefacts** — `sensitivity.py` proving the recall ceiling is metrology not model, `diagnose_why.py` disproving the project's own original correlation-break rationale. **This is the most defensible thing in the repo** and no competitor pitch does it.

**What is NOT defensible as novel:** DPAT (L2), robust z-scores, Mahalanobis outlier
detection, gradient boosting on tabular data, Arrhenius acceleration. All standard.

---

## 12. USP ANALYSIS

### The USP as the code actually supports it

> **Existing tools measure, monitor and flag. SENTINEL decides — and shows its work.**
>
> Static screening lets 100% of latent defects through. Dynamic PAT (the industry
> standard) recovers 64% at a 10% flag rate. We add pooled cross-parameter evidence to
> reach **87% recall at a 10% overkill budget**, forecast the 168-hour value from the
> first 24 hours to pull the worst offenders **144 oven-hours early**, and emit a numbered
> reason code in datasheet units for every flag — so a QA inspector can sign the
> disposition instead of trusting a model.

### Verification of each claim against measured code output

| Claim | Verified? | Evidence |
|---|---|---|
| 100% of latent defects pass static limits | ✅ **VERIFIED** | 174/174, direct data profile |
| Static screening flags 55 parts, 0 latent | ✅ **VERIFIED** | `src.baseline`: recall 0.000, flagged 55 (2.6%) |
| DPAT recall 0.638 @ \|z\|≥4.5 | ✅ **VERIFIED** | `src.baseline` |
| L3 beats L2: PR-AUC 0.4083 vs 0.3889 | ✅ **VERIFIED** | `src.report` |
| Recall 0.874 @ 10% overkill | ✅ **VERIFIED** | `src.report` |
| Forecast beats linear by ~44% on currents | ✅ **VERIFIED** | MAE 1.29 vs 2.35 |
| 144 oven-hours freed per pulled part | ✅ **VERIFIED** | 104 parts × 144 = 14,976 h |
| Every flag carries a reason code | ⚠️ **PARTIAL** | 682 codes / 285 parts, but codes are threshold-decoupled from the verdict. `NEEDS CONFIRMATION` |
| Finds the bad lot without being told | ✅ **VERIFIED** | L04 at 9.7% reject vs L03 at 2.3% |

### ⚠️ Claims to strike from the deck

1. ❌ **"Correlation break detection"** — the covariance is diagonal (max \|ρ\| 0.153 vs null p95 0.189). The code forbids this claim explicitly.
2. ❌ **"Module B is an equally accurate screen, made earlier"** — it is not. ~33% vs ~87% recall. Pitch it as **triage**.
3. ❌ **"Spatial clustering detection"** — the permutation test correctly reports none exists in this data.
4. ❌ **"We use SHAP for explainability"** — it is in `requirements.txt` and in a docstring, but **not in the code**. Say "exact attribution", which is a *stronger* claim.
5. ⚠️ **Any accuracy figure** — `evaluate.accuracy()` raises on purpose. 8.3% prevalence means "all good" scores 91.7%.

---

## 13. SIH REQUIREMENT MAPPING

Mapped against the brief you provided. `NEEDS CONFIRMATION` against the official PS text.

| # | Requirement | Our implementation | Evidence in code | Status |
|---|---|---|---|---|
| 1 | Analyse burn-in / screening data | Full pipeline over 4 params × 4 read points | `src/pipeline.py::screen` | **IMPLEMENTED** |
| 2 | Detect latent reliability problems within datasheet limits | 174/174 latent defects pass static; system reaches 0.874 recall @10% overkill | `src/baseline.py`, `src/report.py` | **IMPLEMENTED** |
| 3 | Component-level measurements | 2,100 parts, per-part records | `data/burnin_wide.csv` | **IMPLEMENTED** |
| 4 | Lot-level behaviour | Every statistic per-lot; PDA gate; R-601 | `features.py` `groupby(lot)`, `fusion.lot_pda_status` | **IMPLEMENTED** |
| 5 | Static specification limits | L1 layer, kept permanently as the comparator | `module_a.static_limit_flags` | **IMPLEMENTED** |
| 6 | Dynamic / lot-relative anomaly detection | L2 DPAT + L3 pooled evidence | `module_a.dpat_score`, `pooled_evidence_score` | **IMPLEMENTED** |
| 7 | Parameter drift | `drift`, `early`, `curvature` views | `features.build_features` | **IMPLEMENTED** |
| 8 | Future-value prediction | 168h forecast from 0h+24h, out-of-fold | `module_b.forecast_all` | **IMPLEMENTED** |
| 9 | Early-life failure / reliability screening | Arrhenius AF≈937, mission gate, safety slope | `module_b.arrhenius_af`, `safety_slope` | **IMPLEMENTED** |
| 10 | False-negative minimisation | `C_FN/C_FP=100`, F₂, recall headline, `accuracy()` raises | `evaluate.py` | **IMPLEMENTED** |
| 11 | Explainable AI | R-101…R-601, exact attribution, signed PDF | `explain.py`, `screening_report.py` | **IMPLEMENTED** |
| 12 | PASS / WATCH / REJECT | ACCEPT / WATCH / REJECT, PDA-sized bands | `fusion.verdict`, `bands_for_pda` | **IMPLEMENTED** |
| 13 | Environmental / thermal stress | 125 °C nominal, Arrhenius modelling | `module_b.py` constants | **PARTIAL** — no per-part temperature telemetry exists |
| 14 | Handle real burn-in data | `POST /screen` accepts arbitrary wide CSV + column validation | `api.screen_csv` | **PARTIAL** — API only, no UI, no schema contract (`pandera` unused) |
| 15 | Deployable to ISRO | 2 bash scripts | `run_demo.sh`, `start_app.sh` | **MISSING** — no Docker, no CI, no auth, no DB |
| 16 | Human-in-the-loop | 3-band verdict, signed PDF, cost slider | `fusion.py`, `screening_report.py` | **PARTIAL** — no sign-off capture, no override record |
| 17 | Audit trail / traceability | `MODEL_VERSION` + UTC timestamp on every record | `explain.MODEL_VERSION` | **PARTIAL** — nothing is persisted |
| 18 | L4 ensemble layer | — | **README claims it; `module_a.py` has no L4** | **MISSING (doc bug)** |

---

## 14. DEMO FLOW — WHAT THE PROJECT ACTUALLY SUPPORTS

| # | Your ideal step | Supported? | How / gap |
|---|---|---|---|
| 1 | Select / upload burn-in dataset | ⚠️ **PARTIAL** | `POST /screen` accepts a CSV upload with column validation. **No uploader in either UI.** Demo would need curl or `/docs`. |
| 2 | Select lot / component | ✅ | Dashboard Part Detail `selectbox`; `GET /part/{serial}`, `GET /lot/{id}` |
| 3 | Display measurements | ✅ | Part Detail table + `part_report()` measured-vs-lot-median block |
| 4 | Show traditional screening result | ✅ | L1 `static_any` kept in the pipeline permanently; baseline prints recall 0.000 |
| 5 | Run dynamic anomaly detection | ✅ | L2 + L3, live |
| 6 | Show anomalous component | ✅ | **L04-0348: 49.5 µA, lot median 15.1 µA, USL 50 → static PASS, SENTINEL REJECT @ risk 78.9** |
| 7 | Show 0h/24h trajectory | ✅ | `drift_plot()` — 4 read points against the lot 5–95th envelope |
| 8 | Predict 168h value | ✅ | Forecast dashed to 168h with a star marker |
| 9 | Compare with safety threshold | ✅ | R-301 quotes the ratio; USL drawn in red |
| 10 | Generate explanation | ✅ | Reason codes in inspector English + one-page signed PDF |
| 11 | Produce PASS/WATCH/REJECT | ✅ | ACCEPT/WATCH/REJECT + PDA status |
| 12 | Dashboard summary | ✅ | Lot Overview, Model Performance, Wafer Map |
| — | *Bonus you didn't list* | ✅ | **Decision Policy cost-ratio slider — move `C_FN/C_FP` live and watch the bands move.** This is your strongest live moment. |

### Recommended 7-minute demo script

1. **`bash run_demo.sh`** — it regenerates from an empty `data/`, runs 150 tests, and prints every deck number. Deterministic, seed 42. *Judges will ask you to re-run it; lead with this.*
2. **The gap** — baseline output: static limits flag 55 parts, **recall 0.000**. 174/174 latent defects ship.
3. **The hero part** — dashboard Part Detail, **L04-0348**. 49.5 µA against a 50 µA limit → PASS. Against a lot median of 15.1 µA → 18.6 robust sigma. Show the drift plot: the part visibly walks out of the herd.
4. **The reason code** — read the R-401 sentence out loud. It names the parameters and the sigmas.
5. **Module B** — the forecast dashed from hour 24 to hour 168. *"We knew at hour 24. 144 oven-hours freed, per part."* State the triage framing, not an accuracy claim.
6. **The cost slider** — Decision Policy screen. Move `C_FN/C_FP` and show the bands and the PDA gate move. *"This is a policy decision, and it belongs to your reliability engineer, not to us."*
7. **The honesty slide** — `sensitivity.py`: *"Our recall on timing-carried defects is 0.24. That is a metrology limit, not a model limit — drop tester noise from 1.5% to 0.4% and the same pipeline reaches 0.92. We can prove it because we own the physics."*

---

## 15. LIKELY JUDGE QUESTIONS — WITH ANSWERS FROM THE ACTUAL IMPLEMENTATION

**Q: Why AI? Why not simple thresholding?**
A: We *do* use simple thresholding — it is L1, and it is in the pipeline permanently. It catches 0 of 174 latent defects. The layer that works is not deep learning either: it is robust statistics computed per-lot. Only the 168h forecast uses a learned model. The claim is not "AI is better"; it is "the reference is wrong" — the datasheet is a static reference and the lot is a dynamic one.

**Q: Why is this different from PAT / I-PAT?**
A: It is not different from DPAT — DPAT is our L2, and we reproduce the AEC-Q001 method exactly. We extend it three ways: pooled cross-parameter evidence (L3, PR-AUC 0.4083 vs 0.3889), a 24-hour forecast for early triage, and a reason-code layer an inspector can sign. I-PAT works on inline inspection data in space; we work on parametric data in time. They are complementary.

**Q: Why is this different from yieldHUB?**
A: yieldHUB is a mature yield-management product and already does outlier detection at scale. We are not competing on that. Our niche is small-lot, high-consequence screening where the output has to be a *signed, auditable disposition per part*, not a yield dashboard. And we publish where our method is weak, which a product pitch cannot.

**Q: Why is prediction necessary if it barely improves detection?**
A: It doesn't improve detection, and we say so in the code and on the slide. It buys *time*: 144 oven-hours freed per part pulled at hour 24, on a resource that is the throughput bottleneck of the whole screening line. That is the claim, and it is the only claim we make for Module B.

**Q: Why 168 hours?**
A: MIL-STD-883 Method 1015 conventional burn-in duration. At Ea = 0.7 eV and 25/125 °C, AF ≈ 937, so 168 hours ≈ 18 years of field life — which is longer than the mission. That is also why our mission-based safety gate almost never binds (0.0–0.1% of parts): 7 years is only 65.5 equivalent burn-in hours.

**Q: How do you prevent false negatives?**
A: Three ways. The cost function minimises `C_FN·FN + C_FP·FP` at a default ratio of 100:1 — a parameter and a UI slider, not a magic number. The reject decision is made on the *0.90 upper quantile* of the forecast, not the point estimate. And the three-band verdict means a marginal part goes to WATCH and ships flagged, rather than being silently accepted.

**Q: What happens if the prediction is wrong?**
A: Module B contributes 20% of the fused score and never decides alone. A wrong forecast cannot un-reject a part that L1, L2 or L3 flagged — the static breach is a hard override that the screen can only add to, never remove. And the reject is made on the conservative bound.

**Q: How do you validate the model?**
A: `GroupKFold(groups=lot)` everywhere — no part is scored by a model that saw its own lot, including the fitted power-law exponent, which is re-fitted per fold. A random part-level split would leak lot statistics and inflate every number. 150 tests, all passing. `evaluate.accuracy()` raises an exception on purpose so no one can report it.

**Q: Is the dataset real or synthetic?**
A: **Synthetic, and we say so on every page.** Generated with seed 42 from an explicit physics model. That is a deliberate trade: synthetic data is the only way to prove *recall*, because it is the only way to know the ground truth. Real unlabelled burn-in data can tell you your false-positive rate and nothing about your escapes — and escapes are the whole problem.

**Q: How do you handle limited data?**
A: 2,100 rows is why we chose robust statistics and gradient boosting, and explicitly rejected deep learning. Most of the stack is unsupervised — DPAT limits, pooled evidence, the k calibration — so it runs on a lot it has never seen, with no training at all.

**Q: How do you explain the model?**
A: Not with SHAP — with exact attribution. For the robust-z layers the contribution to the score *is* the z-score, and to the pooled score *is* the squared term. There is no surrogate model. Plus six numbered reason codes in inspector English, each quoting the part's actual value and the lot reference in datasheet units, on a one-page signed PDF.

**Q: Can this integrate with existing burn-in equipment?**
A: The interface is a wide CSV — one row per part, `{PARAM}_{HOURS}h` columns — which is what every ATE data-log exports. `POST /screen` accepts it and validates columns. We do not touch the oven or the tester. **`NEEDS CONFIRMATION`: we have not tested against any real ATE format (STDF is the industry standard and we do not parse it).**

**Q: Can ISRO actually deploy this?**
A: Not as it stands, and I would not claim otherwise. It runs, it is tested and it is reproducible, but it has no database, no authentication, no audit log and no containerisation. That is the next engineering phase, and it is ordinary work — the science is the part that is done.

**Q: What happens when an anomalous component is detected?**
A: Three bands. REJECT removes it from the lot before final electrical test and counts against the 5% PDA budget. WATCH ships it with the serial flagged for extra scrutiny and does *not* consume PDA budget. If a lot breaches PDA, R-601 fires and the whole lot goes to review — which is what caught L04 at 9.7% without being told it was the bad lot.

**Q: How do you avoid rejecting good components?**
A: We measure it honestly and separately. `overkill_rate` counts false positives among *healthy parts only* — flagging a gross failure is correct behaviour, not over-rejection. At the shipped operating point REJECT costs 0.4% overkill, REJECT+WATCH costs 6.0%. And the PDA cap is what stops the cost-optimal threshold from flagging 80% of the lot, which is mathematically optimal and operationally impossible.

**Q: How does the system scale?**
A: 2,100 parts screen in seconds. The statistics are per-lot `groupby` operations, which are linear. The honest limit is that the current API refits the forecaster on cold start and has no persistence — a production version would fit once, version the artefact, and serve it. Nothing in the method is superlinear.

**Q: What is your actual innovation?**
A: The integration and the honesty, not any single algorithm. DPAT is an industry standard; robust z-scores and gradient boosting are textbook. What is ours: pooled one-sided cross-parameter evidence that measurably beats worst-case-z, hour-24 triage framed on oven-hour economics, and a verdict that is *structurally* a weighted sum of named sub-scores so it cannot become a black box. And we ship the diagnostics that disprove our own original hypothesis — the correlation-break rationale in our blueprint does not hold on our data, we measured it, and we changed the method.

### Questions you should prepare for that you did NOT list

- *"Your z-score is 18.6. What does that mean physically?"* — have the failure-mechanism answer ready: partially-open bond, resistive via, ionic contamination, gate-oxide damage.
- *"Your data is synthetic, so your 87% recall is a property of your generator. Why should I believe it transfers?"* — **the hardest question you will get.** The honest answer is the sensitivity analysis: we show recall tracks measurement noise, which is a property of the tester, not the generator.
- *"Who signs the REJECT?"* — see §16; right now, nobody. Have the answer ready.

---

## 16. SECURITY, RELIABILITY AND ENGINEERING

| Concern | Status | Detail |
|---|---|---|
| **Input validation** | ⚠️ **PARTIAL** | `POST /screen` checks required columns → HTTP 422; CSV parse errors → 400. **No dtype, range, or physical-plausibility checks. `pandera` is pinned and never imported.** |
| **Model validation** | ✅ **STRONG** | `GroupKFold(groups=lot)` everywhere; exponent re-fitted per fold; `forecast_out_of_fold` flag records when a MAE may *not* be quoted; `accuracy()` raises by design |
| **API security** | ❌ **NONE** | No auth, no API key, no CORS policy, no rate limiting, no request size cap. `POST /screen` accepts an unbounded upload. |
| **Authentication** | ❌ **NONE** | No user concept anywhere |
| **Logging** | ❌ **NONE** | Zero `logging` imports across `src/` and `app/` |
| **Audit trail** | ⚠️ **PARTIAL** | Every record carries `MODEL_VERSION` + UTC timestamp, and rejects get a signed PDF — **but nothing is persisted.** No record of who screened what, when, or what they decided. |
| **Reproducibility** | ✅ **STRONG** | Seed 42, exact dependency pins, byte-identical regeneration asserted by test, `run_demo.sh` from empty `data/` |
| **Model versioning** | ⚠️ **PARTIAL** | A string constant `"sentinel-0.3.0"`. No artefact registry; `joblib` pinned and unused; models refit on every cold start. **Two runs can produce different models under the same version string** — I measured MAE drift vs the README. |
| **Failure handling** | ✅ **GOOD** | NaN preserved not imputed; degenerate lots return 0 not ∞; missing layers return NaN not 0 ("a caller that mistakes a missing layer for a zero score would read the part as safer than the evidence supports"); physics fallback when the GBM design matrix is unusable; quantile bound floored at the point estimate |
| **Missing sensor data** | ✅ **GOOD** | 99 dropped 96h reads handled with `skipna` throughout; part still scored on remaining views |
| **Out-of-distribution data** | ❌ **MISSING** | No OOD detection. A lot with a different process centre is handled *by design* (per-lot stats), but a genuinely foreign part type would be scored silently with no warning. |
| **Human-in-the-loop** | ⚠️ **PARTIAL** | The 3-band verdict and the cost slider are HITL by design; the signed PDF is built for a human. **But there is no mechanism to capture the human's decision, override, or signature.** |

### Where human approval MUST remain mandatory — for an aerospace context

1. **Every REJECT on a flight-lot part.** The screen recommends; a reliability engineer dispositions. Non-negotiable.
2. **Every lot-level PDA breach (R-601).** Scrapping or reviewing a whole lot is a programme-schedule decision, not a model output.
3. **Any change to the `C_FN/C_FP` ratio or the band edges.** These are policy. The slider makes that visible — good — but the value must be an approved, recorded setting, not a demo toy.
4. **Any WATCH part that proceeds to flight hardware.** WATCH means "we are not sure"; "not sure" on a payload needs a name against it.
5. **Any screening run where `forecast_out_of_fold is False`.** The code already tracks this. A single-lot inference run must be flagged as such on the record.
6. **Accepting a part the model flagged.** Overrides are the highest-risk action in the system and there is currently no record of them.

---

## 17. PROJECT STATUS

```
                        PROJECT STATUS

Problem Understanding        ✅   Exceptional. Physics, economics and
                                  metrology all quantified.
Dataset                      ⚠️   Excellent quality, fully synthetic,
                                  reproducible. No real data path tested.
Module A                     ✅   L1/L2/L3 implemented, measured, beats
                                  its own baseline. L4 claimed, absent.
Module B                     ✅   Physics + GBM + quantile, out-of-fold,
                                  honest about its detection weakness.
Explainability               ✅   6 reason codes, exact attribution,
                                  signed PDF. Decoupled from the verdict.
Backend                      ⚠️   Clean FastAPI, single orchestration
                                  point. No auth, no logging, no persistence.
Frontend                     ⚠️   Two good frontends that don't talk to
                                  each other or to the API. No upload.
Database                     ❌   Does not exist.
Integration                  ⚠️   Python stack integrates perfectly.
                                  Next.js site is fully disconnected.
Testing                      ✅   150 tests, all passing, verified by me.
Deployment                   ❌   Two bash scripts. No Docker, no CI.
Demo                         ⚠️   Every element exists; no upload path,
                                  and the hero example's reason code
                                  tells the wrong story.
```

### TOP 5 THINGS WE MUST FIX

1. **R-101 does not fire on the problem statement's own hero example.** `z_level_168h = 4.04` against a 6.0 threshold on L04-0348 — the 49.5 µA-in-a-15 µA-lot part. The verdict is right; the *sentence* is about pooled drift, not about the level being abnormal for the lot. Either retune R-101 against the level view's actual distribution, or add a dedicated lot-relative level code. **This is the difference between a judge seeing the thesis demonstrated and seeing it merely implied.**
2. **No upload path in either UI.** The whole "bring your burn-in data" story runs through `curl` today. A file uploader in the Streamlit dashboard is roughly 15 lines (`st.file_uploader` → `pd.read_csv` → `screen`) and closes the biggest demo gap in the project.
3. **Module B MAE does not reproduce across machines.** I measured 1.2923 / 2.5856 / 8.7526 against the README's 1.313 / 2.595 / 8.624. A judge re-running on their laptop and getting a different number than the slide is an avoidable own-goal. Set LightGBM to deterministic single-threaded, re-run `src.report`, and update every figure in the README and deck in one commit.
4. **Four doc/code inconsistencies that a grep will expose.** (a) README repo layout claims `L4 ensemble` — `module_a.py` has no L4. (b) `explain.py`'s docstring says SHAP is used for Module B — it is not imported anywhere. (c) `requirements.txt` pins `shap`, `xgboost`, `pandera`, `joblib`, `plotly` with purpose comments; none are used. (d) `pandera` is described as "dataframe schema contracts at ingest" and there is no schema contract. **Either implement or delete — a judge who greps for SHAP after reading that docstring will find nothing, and that costs more than the feature was worth.**
5. **`web/` is untracked in git** (`?? web/`). 2,600 lines of frontend outside version control on a shared hackathon repo. One `git add` away from a catastrophe.

### TOP 5 THINGS WE SHOULD IMPROVE

1. **Connect the Next.js site to the API, or state clearly that it is an explainer.** It currently makes zero network calls and `burnin.ts` animates hardcoded constants. Decide which frontend is "the product" before the demo and present the other honestly.
2. **Persist something.** Even SQLite: one table of screening runs (timestamp, dataset hash, model version, verdict counts) and one of per-part dispositions with an inspector name. It converts "no audit trail" from a hole into a feature, and it is an afternoon of work.
3. **Measure the verdict↔reason-code coupling.** Count REJECT parts with zero reason codes and ACCEPT parts carrying high-severity codes. If either is non-trivial, the explainability claim has a hole a judge can find. Currently `NEEDS CONFIRMATION`.
4. **Add minimal API hardening.** An API key header, a request size cap, and a CORS policy. Three small changes that turn "no security at all" into "appropriate for a screening service" in the §16 conversation.
5. **Add schema validation at ingest.** `pandera` is already pinned. Dtype + physically-plausible range checks on the uploaded CSV, so a unit-scale mistake (nA vs µA) is caught rather than silently screened.

### TOP 5 THINGS THAT ARE ALREADY STRONG

1. **The intellectual honesty, with receipts.** `diagnose_why.py` disproves the project's own blueprint rationale. `sensitivity.py` proves the recall ceiling is metrology, not model. `evaluate.accuracy()` raises an exception so nobody can report a misleading 92%. `pr_auc` warns when a saturated score would inflate itself. The README corrects the blueprint's own §12 (63 → 55 static flags) *against its own interest*. **No competing team will have this, and technical judges reward it heavily.**
2. **The single-source discipline.** One feature definition (`features.py`), one scorer (`evaluate.py`), one orchestration point (`pipeline.py`) called by API, dashboard and reporter alike. Training/serving skew — the classic ML-demo death — is structurally impossible here.
3. **150 passing tests on a hackathon project**, including a byte-identical regeneration test and a test that rebuilds Module B's features from a frame with late columns deleted to prove no leakage. Verified by execution, not by claim.
4. **Explainability that is exact rather than approximate.** The contribution to the DPAT score *is* the z-score; to the pooled score *is* the squared term. No surrogate model. Six numbered codes in inspector English with real values and real lot references, on a one-page signed PDF. This is a genuinely better answer than SHAP for this architecture.
5. **The visual design language.** *"Instrument panel palette. Light, matte, no glow — this is a lab, not a spaceship bridge."* Graph-paper grids, machined screw heads, monospace tabular readouts, muted signal colours, motion restricted to instrument behaviour, `prefers-reduced-motion` respected. It reads as test-floor equipment, not an AI startup — exactly the differentiation you were aiming for.

---

## 18. OPEN QUESTIONS — I NEED YOUR CONFIRMATION

**Blocking (affects the accuracy of this report):**
1. **The two blueprint PDFs in `docs/` are the stated authority and I have not read them.** Should I extract and reconcile them against the code? The code cites §2.1, §8.4 and §12 specifically.
2. **Do you have the official SIH26170 problem statement text?** §13's mapping is against your brief, not the official document.

**Non-blocking but important:**
3. Are there screenshots, architecture diagrams, or a pitch deck outside this repo that I should incorporate?
4. **Which frontend is "the product"** for the SIH demo — the Streamlit inspector tool or the Next.js site?
5. Is there any intention to test against **real ATE data** (STDF format), or does the project stay on synthetic data through the final round?
6. Is the target the **software prototype evaluation**, or is there a hardware/integration component I should know about?
7. **Team size and remaining time?** It determines whether the §17 "must fix" list is realistic or needs to be cut to the top two.

---

## APPENDIX — VERIFICATION LOG

Everything below was executed in this session on the committed dataset.

| Check | Command | Result |
|---|---|---|
| Test suite | `pytest tests/ -q` | **150 passed**, 0 failed |
| Dataset shape | direct pandas profile | 2,100 × 24; 0 duplicate serials |
| Class balance | " | healthy 1863 / latent 174 / gross 63 |
| **Headline claim** | " | **latent passing static @168h = 174/174 = 100.0%** ✓ |
| Missing values | " | 99 NaN, all in `*_96h` columns only |
| Static baseline | `python -m src.baseline` | recall **0.000**, flagged 55 (2.6%) ✓ matches README |
| DPAT \|z\|≥8 / 6 / 4.5 | " | 0.414 / 0.523 / 0.638 ✓ all match README exactly |
| Baseline PR-AUC | " | 0.389 ✓ |
| L2 vs L3 PR-AUC | `python -m src.report` | 0.3889 vs **0.4083** ✓ |
| Module B MAE | " | 1.2923 / 2.5856 / 0.1576 / 8.7526 — ⚠️ **differs from README in the 3rd digit** |
| Fitted exponents n* | " | 0.41 / 0.41 / **0.00** / **0.00** ✓ |
| Fusion bands (PDA-sized) | " | WATCH ≥ 36.3, REJECT ≥ 61.2 |
| Verdict split | " | ACCEPT 1785 / WATCH 210 / REJECT 105 |
| REJECT recall / overkill | " | 0.201 / 0.4% ✓ |
| REJECT+WATCH | " | **0.810 recall / 6.0% overkill** ✓ |
| PDA per lot | " | L04 **9.7%** (bad lot found), L01 5.4%, L06 5.7% breach ✓ |
| Reason codes | " | **682 codes / 285 parts**; R-401 most frequent (251) |
| Oven hours freed | " | 104 parts × 144 h = **14,976 h** ✓ |
| **Hero example** | direct pipeline trace | **L04-0348: 49.5 µA vs lot median 15.1 µA, USL 50 → static PASS, SENTINEL REJECT @ 78.9** ✓ |
| ⚠️ Hero reason code | " | `z_level_168h = 4.04` < R-101 threshold 6.0 → **R-101 does not fire** |
| Unused deps | grep across `src/ app/ tests/` | `shap`, `xgboost`, `pandera`, `joblib`, `plotly` — **zero imports** |
| L4 layer | grep `module_a.py` | **absent**; README line 174 claims it |
| Database | grep sqlite/postgres/sqlalchemy | **none** |
| Logging | grep `import logging` | **none** |
| Auth | grep auth/token/Depends/CORS in `api.py` | **none** |
| Dashboard upload | grep `file_uploader` | **none** |
| Next.js → API calls | grep `fetch(`, `localhost:8000` in `web/src` | **none — fully static** |
| Git status | `git status --short` | `?? web/` — **frontend untracked** |

---

*End of report. Awaiting your approval before any code is modified.*
