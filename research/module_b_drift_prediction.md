# Module B: Drift Predictor (Value_0h, Value_24h → Value_168h) and Safety-Slope Flagging

Notation used throughout: V0, V24, V96, V168 = parametric value at 0/24/96/168 h of 125°C burn-in. D24 = V24 − V0, D168 = V168 − V0. Scored by MAE on V168.

## 1. Physics-informed extrapolation (power law, log-time, linear) with only 2 points; hierarchical / random-effects / stochastic-process degradation models

### Takeaway
With one drift increment (D24) you can't fit both amplitude A and exponent n per part. Fix n per lot or mechanism using a prior from training data, and extrapolate with D168 = D24·7^n. That formula is exactly a linear model in (V0, V24), so a plain linear or ridge regression is the power law with a learned exponent. Random-effects (Lu & Meeker) or Wiener/Gamma-process models add shrinkage toward the lot's mean trajectory. That matters because D24 is noisy and extrapolation multiplies the noise.

### Cited Findings
- NBTI: ΔVth = A·exp(E/E_ref)·exp(−Ea/kBT)·t^n. A small error in n can put lifetime extrapolations off by several years. — [Entner thesis, TU Wien, §6.2](https://www.iue.tuwien.ac.at/phd/entner/node26.html)
- The NBTI time exponent depends on the technology. It is typically 0.15–0.3, and reports vary from ~0.16 or lower all the way to logarithmic time dependence. Some of this spread comes from measurement delay: adding an assumed initial shift (e.g., 40 mV) to the data changes the fitted slope a lot. — [Entner thesis §6.3](https://iue.tuwien.ac.at/phd/entner/node27.html)
- A 2025 paper on 4H-SiC MOSFETs argues that n is not fixed at the reaction-diffusion value and ties the variable n to time-to-failure. — [Micromachines 16(12):1351 / PMC12734578](https://pmc.ncbi.nlm.nih.gov/articles/PMC12734578/)
- Hot-carrier degradation also follows power laws. Interface-trap (N_it) generation gives n ≈ 0.5 (0.5–1), and oxide-charge (N_ot) injection gives n ≈ 0.1–0.3. n can change with stress time (two-stage behaviour), and Id,lin degradation with n ≈ 0.55 has been reported for 0.18 µm devices. — [search summary of HCD literature incl. ScienceDirect 18 V DEMOS paper](https://www.sciencedirect.com/science/article/abs/pii/S0026271408003727); [Tyaginov, physics-based HCD models](https://www.iue.tuwien.ac.at/pdf/ib_2010/BC2011_Tyaginov_1.pdf)
- Lu & Meeker (1993), "Using degradation measures to estimate a time-to-failure distribution", *Technometrics* 35:161–174, introduced the general path model for repeated-measures degradation data, with random effects and Monte Carlo inference. — [Semantic Scholar](https://www.semanticscholar.org/paper/Using-Degradation-Measures-to-Estimate-a-Lu-Meeker/db7292882143cfab059e97d5533a8544fea7234e); [Clark et al. 2025 review](https://arxiv.org/pdf/2507.14666)
- The mixed-effects general path model is y_ij = D_i(t_ij; α, β_i) + ε_ij, with β_i ~ MVN(μ_β, Σ_β) and ε_ij ~ N(0, σ_ε). Failure CDF: F(t) = Pr[D(t; α, β) ≥ D0]. — [Clark et al., "What Quality Engineers Need to Know about Degradation Models" (arXiv 2507.14666)](https://arxiv.org/pdf/2507.14666)
- Stochastic-process alternatives:
  - Wiener: y(t) = μ(t) + σ·W[μ(t)], with Gaussian independent increments. The first-passage time is inverse-Gaussian: T = μ⁻¹(T*), T* ~ IG(D0, D0²/σ²).
  - Gamma process: increments are Gamma with shape μ(t2) − μ(t1), which suits monotone degradation.
  - Inverse-Gaussian process: a third option.
  - Source: [Clark et al. 2025](https://arxiv.org/pdf/2507.14666)
- Per-unit future prediction comes from the posterior or BLUP of the unit's random effects given its measurements so far, E[D(t*) | y1..yn]. — [Clark et al. 2025](https://arxiv.org/pdf/2507.14666) (summarised via fetch)
- Bayesian hierarchical noisy Gamma processes with unit-to-unit variability have been fitted in Stan-style frameworks. — [arXiv 2406.11216](https://arxiv.org/pdf/2406.11216)
- R packages: ADDT and SPREDA (Hong et al.). — [Clark et al. 2025 references](https://arxiv.org/pdf/2507.14666)

### Inferences (derivations, not sourced)
- **Two-point power law.** Take D(t) = A·t^n with D(0) = 0. Then A = D24/24^n and
  **V168_hat = V0 + D24·(168/24)^n = V0 + D24·7^n**.
  - Multipliers 7^n: n = 0.16 → 1.365; n = 0.25 → 1.627; n = 0.5 → 2.646; n = 1 (linear) → 7.0.
  - Choosing between NBTI-like, HCI-like and linear behaviour moves the prediction by up to 5× of D24. Estimating n from data is the most important decision in the module.
- **Estimating n from training data.**
  - Per part: n_i = ln(D168_i / D24_i) / ln 7. This is only valid when D24 and D168 have the same sign and |D24| is well above measurement noise.
  - With 96 h: n_i = ln(D96/D24) / ln 4. Compare it with ln(D168/D96) / ln(1.75) to check the power law holds; a drifting n means the model form is wrong.
  - Use a robust lot-level prior: lot median of n_i, or a global median when lots are small.
  - For a mixed-effects version: log D_ij = log A_i + n_lot·log t_j + ε, fitted with statsmodels MixedLM or PyMC/NumPyro. The lot random effect on n gives partial pooling.
- **Log-time model.** D(t) = a + b·ln(1 + t/τ). With τ fixed (e.g. 1 h), D168/D24 = ln(169)/ln(25) = 5.13/3.22 ≈ 1.59, which is close to the n ≈ 0.24 power law. Log-time and a low-n power law are hard to tell apart using 24 h and 168 h alone. Fit both and let CV choose.
- **Linear regression is the power law.** V168 = V0 + 7^n·(V24 − V0) = (1 − 7^n)·V0 + 7^n·V24. So the regression V168 ~ a + b·V24 + c·V0 recovers b = 7^n, c = 1 − b. Constraining b + c = 1 by regressing (V168 − V0) on D24 enforces the "no drift if no early drift" physics.
- **Shrinkage.**
  - Measurement noise in D24 (errors-in-variables) biases the fitted OLS slope toward zero. That is roughly the correct BLUP-style shrinkage for prediction, which is another reason fitted regression beats plugging in a physics n.
  - A random-intercept/slope model per lot gives the Lu–Meeker BLUP: predicted slope_i = w·(observed slope_i) + (1 − w)·(lot mean slope), where w = var_between / (var_between + var_noise/Δt²).
- **Wiener process with random drift.** V(t) = V0 + θ_i·t + σB(t) with θ_i ~ N(μ_lot, τ²). The posterior mean of θ_i after 24 h is (μ_lot/τ² + D24·24/σ²·(1/24)) / (1/τ² + 24/σ²), i.e. precision-weighted shrinkage. This form gives a closed-form predictive distribution for V168 and a useful baseline for uncertainty.
- **Sign of drift.** Iddq and leakage usually rise, and propagation delay rises with NBTI/HCI. Some parts recover or anneal, giving a negative D24. The power law is undefined for n when signs differ, so fall back to additive or learned models for those parts.

### Gaps
- No burn-in-specific (125°C, 168 h) published values of n for Iddq, leakage or delay at the product level were found. The NBTI and HCI numbers are transistor-level, and product parameters mix several mechanisms. Estimate n from the competition's training data.
- The Lu & Meeker 1993 full text was not fetched. The model form is taken from the 2025 review.

## 2. Regression models, feature engineering, target choice

### Takeaway
Predict the residual target y = V168 − V24 (or the multiplier (V168 − V0)/D24, or a log ratio), not raw V168. Use features V0, V24, D24, D24/V0, log(V24/V0), lot-level statistics, and the physics prediction V0 + D24·7^n_lot. Then use an L1 objective: LightGBM `objective='l1'`, quantile/median regression, or Huber. Blend a constrained linear or physics model with GBM, because GBMs extrapolate poorly beyond the training range.

### Cited Findings
- LightGBM has an L1 (MAE) objective with aliases `l1`, `regression_l1`, `mean_absolute_error`, `mae`. It is not supported with `linear_tree`. — [LightGBM Parameters docs](https://lightgbm.readthedocs.io/en/latest/Parameters.html)
- `objective='mae'` finds splits that reduce absolute deviations, which gives different trees from L2. — [LightGBM docs/objective summary](https://lightgbm.readthedocs.io/en/latest/Parameters.html)
- NASA PCoE power-MOSFET prognostics used ΔR_DS(on) as the single precursor feature and compared Gaussian-process regression (data-driven) with an EKF and a particle filter on an empirical exponential degradation model, whose parameters α and β are tracked online per device. — [Celaya et al., PHM 2011 (NTRS 20140010628)](https://ntrs.nasa.gov/api/citations/20140010628/downloads/20140010628.pdf)
- In that study GPR could only predict late, near the "elbow" of the exponential, while the model-based EKF/PF gave usable RUL earlier. At t_p = 140 h (EOL 228 h) GPR gave N/A, EKF erred by 23.0 h and PF by 10.4 h. At t_p = 190 h the errors were GPR 4.6 h, EKF 7.65 h, PF 10.9 h. — [Celaya et al. 2011](https://ntrs.nasa.gov/api/citations/20140010628/downloads/20140010628.pdf)
- The NASA PCoE data repository hosts the MOSFET and IGBT accelerated-aging datasets, usable for pretraining or sanity checks. — [NASA PCoE Data Set Repository](https://www.nasa.gov/intelligent-systems-division/discovery-and-systems-health/pcoe/pcoe-data-set-repository/)
- Burn-in-reduction research at SRC/TI (Daasch, Portland State) built "meta-variables" from sort parametrics as burn-in predictors: delta-IDDQ, ratio-IDDQ, frequency deltas and min-VDD. These were selected with CART, CCA and PCA. **Delta and ratio features dominated the variable-importance chart.** — [SRC 1197 "Burn-in Reduction: Improving Outlier Screening"](https://www.researchgate.net/publication/4217624_Burn-in_reduction_using_principal_component_analysis) (poster text via fetched PDF; see also [MAD-based IDDQ burn-in reduction](https://www.researchgate.net/publication/3953892_Evaluation_of_effectiveness_of_median_of_absolute_deviations_outlier_rejection-based_IDDQ_testing_for_burn-in_reduction))

### Inferences (recommended recipe)
- **Why delta or ratio targets win.**
  - V168 is dominated by V0 and V24; part-to-part offset variance is far larger than drift variance. With a raw target, trees spend splits re-learning the identity V168 ≈ V24.
  - Predicting y = V168 − V24 removes that. So does the scale-free multiplier m = D168/D24 (clip it, and guard |D24| < noise). Reconstruct with V168_hat = V24 + ŷ.
  - For multiplicative parameters such as Iddq and leakage, which span decades, use log space: y = log(V168/V24).
  - **L1 and log targets are compatible.** The median is equivariant under monotone transforms, so exp(median of log y) is the median of y. With L2 you would need a retransformation (smearing) correction; with L1 you don't.
- **Feature list.**
  - Per part: V0, V24, D24, D24/|V0|, log(V24/V0), sign(D24), the rank of D24 within the lot, and the z-score of D24 within the lot (robust: (D24 − median)/(1.4826·MAD)).
  - Physics feature: V0 + D24·7^n̂_lot, plus the log-time variant.
  - Lot and wafer context: lot median and IQR of D24, V0 and V24, since tester/fixture offsets live here. Also the parameter-type ID and test-socket/board ID if present. Handle the parameter type either with one model per parameter or with a one-hot/categorical feature (CatBoost handles categoricals natively).
- **Model ladder (stop when CV MAE plateaus).**
  - (a) Physics baseline: V0 + D24·7^n_lot.
  - (b) Median regression of (V168 − V0) on D24 (sklearn `QuantileRegressor(quantile=0.5, alpha≈0)`), or `HuberRegressor`.
  - (c) Ridge or Huber on the full feature set.
  - (d) LightGBM, XGBoost (`reg:absoluteerror`) or CatBoost (`loss_function='MAE'`) on the delta target.
  - (e) Blend (b) and (d) by median-of-models or stacking with an L1 meta-learner.
  - For monotone physics, add LightGBM `monotone_constraints` (+1 on D24), which improves extrapolation on high-drift parts.
- **GAMs and EBMs.** pyGAM `ExpectileGAM(expectile=0.5)` is mean-like; for a median use `LinearGAM` on the delta target plus L1 calibration. InterpretML `ExplainableBoostingRegressor` gives shape functions per feature, which you can show judges (e.g. the multiplier vs. D24 curve).
- **Gaussian process.** sklearn `GaussianProcessRegressor` (RBF + WhiteKernel) on (log V0, D24) gives predictive variance, but it scales O(N³). Subsample, or use the Wiener closed form from §1. NASA's experience that GPR lags model-based methods early on supports keeping a physics prior in the model.

### Gaps
- sklearn `QuantileRegressor`, XGBoost `reg:absoluteerror`, CatBoost `MAE`, pyGAM and InterpretML EBM APIs are cited from general knowledge. Their documentation pages were not fetched in this session, so check the parameter names.
- The NASA paper's equation (1) was garbled in extraction. It is an exponential model in t with per-device parameters α and β; the exact form was not verified (commonly written α(e^{βt} − 1)).

## 3. MAE-optimal estimation and prediction intervals (quantile regression, conformal / MAPIE)

### Takeaway
MAE is minimised by the conditional median, so train with L1 / quantile 0.5 losses rather than MSE. For flagging, fit the 0.05 and 0.95 quantiles as well and conformalize them (CQR via MAPIE). That gives finite-sample-valid intervals, and the upper bound drives the safety decision.

### Cited Findings
- Conformalized Quantile Regression (Romano, Patterson, Candès, NeurIPS 2019) combines conformal prediction with quantile regression. It achieves finite-sample, distribution-free coverage while adapting interval width to heteroscedasticity, unlike constant-width conformal intervals. — [arXiv 1905.03222](https://arxiv.org/abs/1905.03222)
- MAPIE's `ConformalizedQuantileRegressor` fits a target model plus lower and upper quantile models. It uses a conformalization set to shift the quantile predictions by a constant (symmetric or asymmetric), and `predict_interval` returns points plus intervals. LGBMRegressor with the quantile objective is a supported base model. — [MAPIE docs (1.2/1.3)](https://mapie.readthedocs.io/en/latest/generated/mapie.regression.ConformalizedQuantileRegressor.html); [MAPIE CQR tutorial](https://mapie.readthedocs.io/en/stable/generated/regression/2-advanced-analysis/plot_cqr_tutorial/)
- A comparison of conformal quantile regression variants is available. — [Sesia & Candès 2020, arXiv 1909.05433](https://arxiv.org/pdf/1909.05433)

### Inferences
- The argmin over c of E|Y − c| is the median of Y, so a model trained on MSE targets the mean and loses MAE when drift residuals are skewed. Leakage and Iddq drift is typically right-skewed, with a few runaway parts.
- **Pipeline.**
  1. `LGBMRegressor(objective='quantile', alpha=q)` for q in {0.05, 0.5, 0.95}, on the delta target.
  2. Hold out a conformalization split grouped by lot.
  3. Run MAPIE CQR at confidence 0.9 (`confidence_level=0.9` in MAPIE ≥1.0; older versions used `alpha=0.1`).
  4. Submit the q = 0.5 prediction as the point estimate.
  5. Use the upper bound U168 for flagging.
- **Exchangeability.** Conformal coverage assumes exchangeability. Calibrate on held-out lots so coverage holds for new lots. Mondrian (per-parameter-type) calibration keeps coverage per parameter.
- **Stabilising the point estimate.** Averaging the quantile-0.5 LightGBM and the linear median model, then taking the median of 3–5 seeds or CV folds' models, usually reduces MAE further (standard ensembling).

### Gaps
- No published burn-in-specific benchmark of CQR vs. other interval methods was found.

## 4. Using 96 h readouts available only in training

### Takeaway
Treat 96 h as privileged information. Use it (a) to estimate or validate the time exponent n per lot, (b) as an auxiliary target in multi-task or chained training, and (c) to pick the model form (power law vs. log vs. linear) from 3-point trajectories. Never use it as an input feature at inference.

### Cited Findings
- ESCC generic spec 5000 requires drift to be computed against the 0 h (initial) measurement, at defined data points (0 h and T(+24/−0) h). Intermediate readouts are part of standard screening flows. — [ESCC Generic Specification 5000, §8.20–8.21](https://escies.org/download/specdraftapppub?id=153)
- MIL-STD-883 Method 1015 requires interim (post-burn-in) electrical measurements, with delta-limit acceptance based on them. If they can't be completed within 96 h, the parts must be re-burned-in. — [MIL-STD-883 Method 1015 (search summary)](https://www.scribd.com/document/324699946/Mil-Burn-in-Std883-1015)

### Inferences
- **Exponent estimation.** Three points (0, 24, 96) per part let you fit (A_i, n_i) per part in training and then build a lot/parameter prior for n. Also check whether n drifts (ln(D168/D96)/ln 1.75 vs. ln(D96/D24)/ln 4), which tells you whether log-time fits better.
- **Chained model.** Train f1: (V0, V24) → V96 and f2: (V0, V24, V96) → V168. At inference compute V168_hat = f2(V0, V24, f1(V0, V24)). To avoid train/test mismatch, train f2 on out-of-fold f1 predictions, not true V96.
- **Multi-task.** Use a shared-trunk MLP or multi-output GBM predicting [V96, V168] (sklearn `MultiOutputRegressor` doesn't share structure; a small PyTorch MLP with L1 loss on both heads does). Weight the 96 h head as a regulariser.
- **Knowledge distillation / learning using privileged information.** Train a teacher on (V0, V24, V96), then train the student on (V0, V24) to match the teacher's out-of-fold predictions blended with the truth. This helps mainly when V168 labels are noisy.
- **Sequence models.** LSTMs or Transformers are overkill for 2–3 time points. A parametric curve fit (power, log) with partial pooling captures the same structure.

### Gaps
- No published study specifically on privileged 96 h data for burn-in end-point prediction was found.

## 5. Defining the "safety slope" and flagging rule

### Takeaway
Define drift rate r = (V168_hat − V0)/168 h (or relative: /|V0|, or in log units). The safety slope S can come from:
- (a) a spec delta limit: S = Δ_max/168;
- (b) the datasheet limit reached before the Arrhenius-equivalent mission life: S = (Limit − V0)/t_eq, or its power-law equivalent;
- (c) lot statistics: S = lot median r + k·1.4826·MAD;
- (d) the minimum of these.

Flag on the conformal upper bound of V168, not on the point estimate, and tune k or the quantile level for near-zero false negatives.

### Cited Findings
- ESCC 5000: a part is a "parameter drift failure" if its change during HTRB or Power Burn-in exceeds the drift value Δ in the detail spec. Drift is related to the initial (0 h) measurement.
  - Power burn-in is 168 h minimum and 264 h maximum by default; HTRB is ≥48 h for MOSFETs and ≥12 h for other devices by default.
  - A lot fails if drift plus limit failures exceed 5% of parts submitted.
  - Source: [ESCC Generic Spec 5000 §6.2.2, §6.4.1, §8.20–8.21](https://escies.org/download/specdraftapppub?id=153)
- A concrete ESCC detail-spec example (ST STPS80A150C Schottky, ESCC 5106/023):
  - Drift limits: I_R Δ = ±5 µA or ±100%; V_F Δ = ±0.05 V. Absolute limits also apply (I_R max 14 µA; V_F1 max 0.78 V).
  - Power burn-in: Tj = 175°C for ≥168 h. HTRB: 80°C at VR = 120 V for ≥48 h.
  - Source: [ESCC Detail Spec 5106/023](https://escies.org/download/specdraftapppub?id=4857)
- MIL-STD-883 Method 1015: delta limits are specified in the device specification or SMD, and acceptance is based on post-burn-in interim measurements. — [MIL-STD-883 1015](https://www.scribd.com/document/324699946/Mil-Burn-in-Std883-1015)
- MIL-STD-883 Method 1015's time-temperature table gives Class B minimum 160 h at 125°C and 80 h at 150°C. — [search summary of MIL-STD-883H Method 1015.10](https://ai-hmi.com/wp-content/uploads/2015/03/std883_1015.pdf) (the PDF returned 404 when fetched; the value is from the search index)
- JEDEC JEP122 lists activation energies per failure mechanism. Industry commonly uses Ea = 0.7 eV as a conservative default for Arrhenius extrapolation. — [JEDEC Ea definition](https://www.jedec.org/standards-documents/dictionary/terms/activation-energy-ea); [nomtbf.com "Where does 0.7 eV come from"](https://nomtbf.com/2012/08/where-does-0-7ev-come-from/)
- NASA PCoE prognostics used a crisp failure threshold (a 0.05 increase in ΔR_DS(on)) and predicted time-to-threshold. This is the same "time for the extrapolated trajectory to hit a limit" logic. — [Celaya et al. 2011](https://ntrs.nasa.gov/api/citations/20140010628/downloads/20140010628.pdf)
- Median-of-absolute-deviations (MAD) outlier rejection on IDDQ was evaluated as a burn-in-reduction screen against delta-IDDQ. — [ResearchGate](https://www.researchgate.net/publication/3953892_Evaluation_of_effectiveness_of_median_of_absolute_deviations_outlier_rejection-based_IDDQ_testing_for_burn-in_reduction)

### Inferences (formulas)
- **(a) Spec delta.** Flag if |U168 − V0| > Δ_max, i.e. S_a = Δ_max/168 h. For percentage specs (e.g. ±100% I_R), use the relative slope r_rel = (V168_hat − V0)/(|V0|·168).
  - Note the ESCC "±5 µA or ±100%" form, which is typically whichever is greater. Implement it as Δ_max = max(abs_tol, pct·|V0|).
- **(b) Datasheet limit plus mission life.**
  - Acceleration factor: AF = exp[(Ea/k)(1/T_use − 1/T_stress)], with k = 8.617×10⁻⁵ eV/K.
  - Example: Ea = 0.7 eV, T_use = 55°C, T_stress = 125°C gives AF ≈ 77.7. A 10-year mission (87,600 h) is then t_eq ≈ 1,128 h at 125°C.
  - Linear safety slope: S_b = (Limit − V0)/t_eq, per part.
  - Power-law version (less conservative): flag if V0 + D168_hat·(t_eq/168)^n > Limit.
  - Consistency check: the MIL table's 160 h @125°C ≡ 80 h @150°C implies AF = 2, i.e. an implied Ea ≈ 0.40 eV (ln2·k / (1/398.15 − 1/423.15)).
  - Choice of Ea matters: 0.4 vs 0.7 eV changes t_eq by about 6×. State the assumption explicitly.
- **(c) Lot-statistical.**
  - S_c = median_lot(r) + k·1.4826·MAD_lot(r), with k ≈ 3–6. This is a PAT-style robust outlier cut on predicted drift rate, computed on the lot's own V0/V24-derived predictions, which is legitimate at inference.
  - Use the robust sigma so a few runaway parts don't inflate the threshold.
- **Recommended final rule.** Flag a part if r_upper = (U168 − V0)/168 > S = min(S_a, S_b, S_c) (use whichever limits are available), or if U168 crosses the absolute datasheet limit.
- **Cost-sensitive tuning.**
  - Choose the CQR level (e.g. 0.9 → 0.99) or k to minimise C_FN·FN + C_FP·FP on grouped-CV folds. Here FN = a part whose true D168 exceeds the limit but wasn't flagged, and C_FN ≫ C_FP (a field escape vs. scrapping one part).
  - Equivalently, pick the threshold on the precision-recall curve at recall ≥ 0.99 for true drift failures.
- **Keep the scored point prediction separate from the flag.** The MAE-scored submission is the median prediction, while flags use the upper bound. Biasing the point estimate upward for safety would raise MAE.

### Gaps
- MIL-STD-883 Method 1015 itself doesn't contain numeric delta limits; they live in device SMDs and detail specs. No Iddq, leakage or propagation-delay delta values were found for this competition's parts. Use competition-provided limits if any.
- The AEC-Q001 PAT (robust ±6σ) specifics were not verified in this session.

## 6. Literature: early prediction of burn-in outcomes, burn-in time reduction, electronics RUL

### Takeaway
Direct literature on predicting end-of-burn-in parametric values from early readouts is thin. The closest work falls into three groups:
- (i) ML early-failure prediction during burn-in (QCL lasers, SVM, >80% sensitivity after 8 h);
- (ii) burn-in reduction from sort and IDDQ meta-variables (delta and ratio features);
- (iii) prognostics on NASA MOSFET/IGBT aging, where model-based filters beat pure GPR early in life.

### Cited Findings
- **Quantum cascade lasers (Sci. Rep. 2022).**
  - 9 QCLs under accelerated burn-in, with 28 features auto-extracted from LIV sweeps every ~2.5 h and an RBF-SVM classifier.
  - It predicted premature failure up to 200 h before failure, with average sensitivity 93.65% and specificity 100%.
  - "Sensitivity > 80% after 8 h of burn-in." Planned burn-in was 100–150 h.
  - Source: [PMC9163159](https://pmc.ncbi.nlm.nih.gov/articles/PMC9163159/)
- A 2025 *Computers & Industrial Engineering* paper proposes a data-driven framework predicting device quality to support burn-in decisions, combining equipment signals, wafer maps (LSTM-CNN anomaly detection) and pre-burn-in electrical tests. — [ScienceDirect S036083522500261X](https://www.sciencedirect.com/science/article/pii/S036083522500261X) (abstract via search; full text 403)
- An AI-based burn-in reduction framework for semiconductor manufacturing has been published (Springer 2024 chapter). — [Springer](https://link.springer.com/chapter/10.1007/978-3-031-59361-1_5)
- Claims that ML reduces burn-in time by 30–50% come from a PatSnap "Eureka" report, an aggregator of unclear methodology, so treat them as unverified. — [PatSnap](https://eureka.patsnap.com/report-optimizing-semiconductor-burn-in-to-prevent-early-life-device-failures)
- Patents on "dynamic duration burn-in" and "burn-in optimization" use per-lot delta and hazard values at each read-point to predict the passing read-point, which is the same idea as terminating burn-in early from early readouts. — [US 6175812](https://image-ppubs.uspto.gov/dirsearch-public/print/downloadPdf/6175812); [US 7141998](https://image-ppubs.uspto.gov/dirsearch-public/print/downloadPdf/7141998)
- Burn-in reduction via PCA on sort data. — [ResearchGate 4217624](https://www.researchgate.net/publication/4217624_Burn-in_reduction_using_principal_component_analysis)
- NASA PCoE MOSFET thermal-overstress prognostics:
  - Setup: 5 training devices and 1 test device (#36), EOL 228 h, with GPR, EKF and PF compared.
  - Assumed die-attach degradation is the only active mechanism.
  - Noted that parameters differ per device, so they must be estimated online. This mirrors the random-effects argument.
  - Source: [Celaya et al. 2011](https://ntrs.nasa.gov/api/citations/20140010628/downloads/20140010628.pdf); [NASA DASHlink](https://c3.ndc.nasa.gov/dashlink/resources/806)

### Inferences
- The QCL result shows early (≤10% of burn-in time) readouts carry most of the signal for eventual outliers. That supports the premise of Module B.
- NASA's finding supports using a physics or parametric prior and shrinkage when only early points are available.

### Gaps
- No IRPS or IEEE TR paper found in this session specifically regresses Iddq/leakage/delay at 168 h on 0/24 h readouts. The idea exists in the patents and in industry practice, but no public benchmark MAE numbers were found.

## 7. Validation strategy

### Takeaway
Use GroupKFold (or StratifiedGroupKFold, stratified on a drift-failure flag) with lot as the group. Compute every lot-level feature and prior (n_lot, lot medians) inside each training fold only, and report MAE overall, per lot and per parameter type, plus the worst-lot MAE.

### Cited Findings
- sklearn GroupKFold and StratifiedGroupKFold put each group in the test set exactly once, with no overlap between train and test groups. StratifiedGroupKFold additionally tries to keep class proportions. — [scikit-learn docs](https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.StratifiedGroupKFold.html)
- Other valid holdouts: the NASA study held out a whole device (#36) for testing; the QCL study tuned on separate device sets to avoid overfitting. — [Celaya 2011](https://ntrs.nasa.gov/api/citations/20140010628/downloads/20140010628.pdf); [PMC9163159](https://pmc.ncbi.nlm.nih.gov/articles/PMC9163159/)

### Inferences
- **Leakage traps.**
  - (1) Lot-level target statistics (e.g. the lot median of D168 or of n_i) computed on all data.
  - (2) Scalers or quantile transforms fitted on the full data.
  - (3) Using V96 as a feature.
  - (4) Random KFold when the hidden test set holds unseen lots. Note that lot statistics derived from test V0/V24 at inference are fine.
- **Where the hidden test probably comes from.** If it's likely made of new lots, GroupKFold by lot is the right proxy. If it comes from the same lots, random KFold MAE will be closer but optimistic. Report both, and choose models on the grouped score.
- **Report.**
  - Global MAE, and MAE on the delta scale divided by mean |D168|, since raw MAE is dominated by high-magnitude parameters.
  - Per-parameter MAE and per-lot MAE distribution (median and max).
  - CQR empirical coverage per lot.
  - FN/FP counts of the safety flag at the chosen threshold.
- **Multiple parameter types in one MAE.** If one MAE covers several parameter types, parameters with large absolute scale dominate. Spend modelling effort on those parameters, e.g. per-parameter models and extra tuning where |V| is large.

### Gaps
- The hidden test's lot composition is unknown, so the choice of CV scheme must be confirmed from the competition data.
