# SENTINEL — AI-Driven Anomaly Detection in Component Burn-In & Screening

Hackathon project. Detect **latent defects** in high-reliability electronic
components: parts that pass every static datasheet limit but drift abnormally
during burn-in and fail early in the field.

Full spec: `docs/SENTINEL_Blueprint.pdf`. Read it before proposing architecture
changes.

## The problem in five lines

- Components are burned in at 125 °C; parameters are read at 0h, 24h, 96h, 168h.
- Static pass/fail limits catch gross failures only. In our dataset, **100% of
  latent defects pass the datasheet at 168h**.
- **Module A** — dynamic outlier detection: flag parts abnormal *relative to
  their own lot*, not relative to the datasheet.
- **Module B** — drift prediction: forecast `Value_168h` from `Value_0h` and
  `Value_24h` only, then reject early if predicted slope exceeds a safety slope.
- Scored on: recall (false negatives are catastrophic), MAE on the 168h
  forecast, and **explainability to a QA inspector**.

## Non-negotiable rules

Domain:
1. Currents (`Iddq_uA`, `Ileak_nA`) are **lognormal**. Log-transform before any
   statistics. Timing/voltage (`Tpd_ns`, `Vol_mV`) are ~normal, use raw.
2. Never use mean/std for limits or outlier scores. Use `median` and
   `1.4826 * MAD`. Mean-based limits get masked by the outliers they hunt.
3. All statistics are computed **per lot**. Lot-to-lot offsets are real and are
   the entire reason dynamic limits beat static ones.
4. Higher is worse for every parameter in this dataset. One-sided logic is fine
   but say so in comments.

ML:
5. **Never report plain accuracy.** ~8% of parts are defective; predicting "all
   good" scores 92%. Report recall, precision, F-beta (beta>=2), PR-AUC, and
   recall at a stated overkill budget.
6. Validation splits are **grouped by lot** (`GroupKFold(groups=lot)`). A random
   part-level split leaks lot statistics and inflates every score.
7. Thresholds are chosen by minimising `C_FN * FN + C_FP * FP` with
   `C_FN/C_FP = 100` by default. The ratio is a parameter, never a magic number.
8. Feature logic lives **only** in `src/features.py`, imported by both training
   and inference. Never inline feature code in a notebook or an endpoint.
9. Baseline before sophistication. A new model ships only if it beats the
   current baseline on the grouped holdout, and the baseline stays in the repo.
10. Deep learning is not the default. On ~2000 tabular rows, robust statistics
    and gradient boosting win. Justify any neural net with a holdout number.

Explainability (a third of the marks):
11. The top-level verdict is a **weighted sum of named sub-scores**, never a raw
    model output. ML improves the sub-scores; it does not make the decision.
12. Every flag emits a reason code (R-101…R-601) with inspector-facing English
    containing the actual value and the lot reference value.

Measured facts about this dataset (settled — do not relitigate):
13. The delta-vector covariance in this dataset is diagonal (max |rho| ~ 0.1).
    Do not claim multivariate methods catch "correlation breaks". They work
    here by pooling marginal evidence across axes, which is a real but
    different gain. Verify before claiming otherwise.
14. Recall is bounded by measurement noise, not by the model. Defects carried
    by Tpd_ns/Vol_mV score 0.24-0.42 recall at L2 |z|>=4.5, and 0.65 under L3
    at a 10% overkill budget, against the dataset's flat 1.5% ATE noise. Drop
    timing/voltage noise to 0.4% and the same pipeline reaches 0.92. Always
    state the operating point with the number. Report the sensitivity analysis
    (`python -m src.sensitivity`); never regenerate data/ to improve a score.

## Repo layout

```
src/
  generate_burnin_dataset.py   synthetic data, fixed seed, DO NOT change the seed
  features.py                  the ONLY place features are defined
  module_a.py                  dynamic outlier detection (L1 static, L2 DPAT, L3 multivariate)
  module_b.py                  drift forecast (power law + GBM + quantile bound)
  fusion.py                    0-100 screening risk score, ACCEPT/WATCH/REJECT
  explain.py                   reason codes, SHAP, per-part plots
  evaluate.py                  THE scorer. One scorer, one truth.
  api.py                       FastAPI service
app/                           Streamlit dashboard
data/                          generated CSVs (gitignored)
tests/
docs/
```

## Commands

```
python src/generate_burnin_dataset.py    # regenerate data (seed 42, reproducible)
python -m pytest tests/ -q
streamlit run app/dashboard.py
uvicorn src.api:app --reload
```

Windows: use `python`, not `python3`. Paths use `pathlib.Path`, never
hardcoded separators — teammates are on mixed OSes.

## Definition of done for any change

- Runs end to end from a clean `data/` directory.
- Has a test if it touches `features.py` or `evaluate.py`.
- Reports its metric via `src/evaluate.py`, not an ad-hoc calculation.
- If it changes a number that appears in the slides, say so explicitly.

## How I want you to work

- Show me the code that produced any number you report. I verify every figure
  before it reaches a slide.
- When recall is stuck, diagnose the missed parts before proposing a new model.
  Show me the feature rows of 10 misses.
- Argue against your own design when asked. "What would a reliability engineer
  object to here?" is a real question.
- Small commits with real messages. This is a hackathon, but the repo gets read.

## Vocabulary

- **Latent defect** — passes all limits, carries a growing physical flaw. Target class.
- **Escape** — a defective part that ships. False negative. Catastrophic.
- **Overkill** — a good part rejected. False positive. Expensive but survivable.
- **Robust sigma** — `1.4826 * MAD`, or `IQR / 1.35`. Equals σ for normal data.
- **DPAT** — Dynamic Part Average Testing. Limits = robust median ± 6 robust sigma,
  computed per lot. The industry method we are extending.
- **PDA** — Percent Defective Allowable. If >5% of a lot fails, the lot is rejected.
  This caps how aggressive we can be.
- **Safety slope** — max drift rate a part may show and still be trusted.
  `min(mission-based, population-based)`.
