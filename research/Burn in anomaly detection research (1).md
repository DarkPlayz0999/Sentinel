# Layered Robust Screens Win ISRO's Burn-In Challenge

The winning design for SIH26170 is not a clever deep model. It is a layered, recall-first OR-gate. Deterministic datasheet and delta limits come first. Lot-relative robust statistics (Dynamic PAT on log values and on drift features) come next, then a robust Mahalanobis plus Isolation Forest/ECOD ensemble. Last, a 24-hour-to-168-hour drift forecaster flags a part on the *conformal upper bound* of its predicted drift, not on the point estimate. Every flag carries deterministic reason codes that a QA inspector can audit. Three facts back this design. First, the problem mirrors 30 years of semiconductor burn-in-reduction practice: robust per-lot limits of median ± k·IQR/1.35 (AEC-Q001), delta-Iddq meta-variables, and multivariate outlier screens. Second, the largest anomaly-detection benchmark found no unsupervised method statistically better than the rest, and deep methods often lost to shallow ones. Third, MAE is minimised by the conditional median, and a two-point power law is algebraically just a linear regression on (V0, V24). No official dataset appears to ship with the problem. Every public team repo found (8+) uses synthetic data, sometimes with NASA degradation data as a proxy. So data realism, lot-grouped validation and honest escape-rate bounds are where a team can differentiate. The basic "DPAT + Isolation Forest + LightGBM + SHAP + Streamlit" stack is already public in at least two repos, which makes it table stakes rather than a winning edge.

## Burn-in consumes infant mortality, and delta limits leave a statistical gap

Burn-in is a 100% screen. Parts are biased at about 125 °C to precipitate latent, "time and stress dependent" defects, then measured before and after. Under MIL-STD-883 Method 1015, the minimum is **160 h at 125 °C for Class B/QML Q and 240 h for Class S/QML V**. Its time–temperature table allows 80 h / 120 h at 150 °C ([Method 1015.10 snippet](https://ai-hmi.com/wp-content/uploads/2015/03/std883_1015.pdf); [JPL Flight Part Verification](https://parts.jpl.nasa.gov/asic/Sect.4.3.html)). ESCC 9000 defaults to **240 (+24/−0) h** of power burn-in for ICs, with HTRB drift measured at 0 h and at the end point, "related to the initial measurement" ([ESCC 9000](https://escies.org/download/specdraftapppub?id=3659)). ESCC 5000 sets discrete power burn-in at **168–264 h** ([ESCC 5000](https://escies.org/download/specdraftapppub?id=153)). That is the source of the problem statement's 168-hour horizon. MIL-PRF-38535 lets a manufacturer drop from 240 h to 160 h after three consecutive passing lots, and sets class S/V PDA at **5% (3% catastrophic)** ([MIL-PRF-38535M](https://landandmaritimeapps.dla.mil/Downloads/MilSpec/Docs/MIL-PRF-38535/prf38535.pdf)). ISRO's own practice follows NASA EEE-INST-002. Its active-part screening matrix runs from visual inspection through temperature cycling, PIND, seal, burn-in and "Pre/Post B.I. Electrical @ amb, High & Low" to **"PDA < 5%"**, and parts screened this way flew on Chandrayaan-1/2, GSAT-29 and RISAT ([ISRO URSC COTS presentation](http://www.drsvsharma.com/wp-content/uploads/2023/09/USAGE-OF-COTS-EEE-PARTS-DrSVSharma-Deputy-Director-ISRO-URSC.pdf)).

A part is rejected by two deterministic rules. It is a **limit failure** if a post-burn-in reading exits the spec window. It is a **drift failure** if |post − pre| exceeds a detail-spec Δ. The lot fails if drift plus limit failures exceed 5% of the parts submitted, rounded up ([ESCC 9000 §6.2, §6.4](https://escies.org/download/specdraftapppub?id=3659)). Real Δ values are small and specific. ESCC 9201/107, a CMOS IC, allows **ΔIDD ±30 nA** against a 100 nA absolute max, ΔIIL/IIH ±20 nA, and ΔVTH ±0.3 V ([ESCC 9201/107](https://escies.org/download/specdraftapppub?id=1683)). ESCC 5106/023, a Schottky rectifier, allows **ΔIR ±5 µA or ±100%, whichever is greater**, against a 14 µA max ([ESCC 5106/023](https://escies.org/download/specdraftapppub?id=4857)). The implementable rule is Δ_spec = max(Δ_abs, k·|p₀|).

These rules never consult the population. The PS example of a 45 µA part in a 10 µA-mean lot with a 50 µA datasheet max passes both of them if its 0-hour reading was also high. That gap is exactly what automotive **Part Average Testing** closes. AEC-Q001 defines robust mean = median and robust sigma = (Q3 − Q1)/1.35, with limits at **median ± 6 robust σ**. Static PAT is set from at least six lots × 30 parts, and Dynamic PAT is recomputed per lot from the parts under test. PAT limits may never loosen spec limits ([AEC-Q001 Rev D](http://www.aecouncil.com/Documents/AEC_Q001_Rev_D.pdf)). AEC-Q002 adds lot-level statistical yield and bin limits at mean ∓3σ/4σ for flagging whole anomalous lots ([AEC-Q002 Rev B](http://www.aecouncil.com/Documents/AEC_Q002_Rev_B1.pdf)). The problem statement's "Module A" is, in effect, Dynamic PAT applied to burn-in read-points.

The physics tells you which trajectory shapes to trust. Wear-out mechanisms produce **smooth power-law drift** ΔP = A·tⁿ:

- **NBTI:** n ≈ 0.2–0.3, with 0.25 theoretical.
- **HCI:** n ≈ 0.5–1, with a *negative* apparent Ea of −0.1 to −0.2 eV.
- **Electromigration:** follows Black's law with Ea 0.7–1.1 eV.
- **TDDB:** Weibull-distributed, with Ea 0.6–0.9 eV.

All four come from the same source ([JPL Publication 08-5](https://nepp.nasa.gov/DocUploads/996E1F0E-3EB7-4309-9C9FB38BD53543FC/07-102%20White_JPL%20Microelectronics%20Reliability.pdf)). Latent *defects* look different. They show up as elevated Iddq from time zero (bridges), noisy steps (gate-oxide soft breakdown) or abrupt jumps (voids and opens). AEC-Q001 names pin leakage, standby IDD and IDDQ as the tests most sensitive to latent defects ([AEC-Q001](http://www.aecouncil.com/Documents/AEC_Q001_Rev_D.pdf)), and delta-Iddq separates early-fail chips from reliable ones at elevated temperature ([IEEE VTS 2000](https://ieeexplore.ieee.org/abstract/document/843876/)). The design consequence is that a sudden jump or non-monotonic trajectory is more suspicious than smooth drift of the same magnitude.

| Mechanism | Parameter | Expected shape | Suggested reason-code label |
|---|---|---|---|
| NBTI/PBTI | Vth, delay ↑ | tⁿ, n ≈ 0.16–0.3, partial recovery | "BTI-like drift" |
| HCI | Vth, gm, delay | tⁿ, n ≈ 0.5–1 | "HCI-like drift" |
| Gate-oxide weak spot / TDDB | Iddq, gate leakage | flat → noisy step → large step | "Oxide breakdown precursor" |
| Bridging / resistive short | Iddq, static IDD | outlier from 0 h | "In-spec lot outlier" |
| EM / voids | resistance, delay | slow creep → abrupt jump | "Interconnect degradation" |

Arrhenius acceleration anchors the safety-slope logic. The calculations below are mine, using k = 8.617×10⁻⁵ eV/K. At **Ea = 0.7 eV**, 125 °C versus 55 °C gives **AF ≈ 78**, so 160 h of burn-in covers about 1.4 years of use. At Ea = 0.45 eV the AF is only about 16. The Method 1015 table's 125 °C → 150 °C halving implies an effective Ea of only about **0.40 eV**. The choice of Ea therefore changes any "mission-equivalent" limit by roughly 6×, and it has to be stated as an explicit assumption. JEDEC's JEP122 lists Ea by mechanism, and 0.7 eV is the conventional default ([JEDEC](https://www.jedec.org/standards-documents/dictionary/terms/activation-energy-ea); [nomtbf](https://nomtbf.com/2012/08/where-does-0-7ev-come-from/)).

## No official dataset exists, so physics-informed synthesis is the battleground

The PS is **SIH26170 (ISRO, Smart Automation theme, 34 ideas submitted)**. It specifies time-series standby current, leakage and propagation delay at **0/24/96/168 h**, the 10 µA / 45 µA / 50 µA Module A example, the Module B mapping Value_0h + Value_24h → Value_168h, and three metrics: an anomaly-detection score that heavily penalises false negatives, MAE on the 168-hour prediction, and explainability. No public mirror says whether a dataset is provided ([zaidsayyed.in SIH26170](https://zaidsayyed.in/tools/sih-problem-statements/sih26170)). The official portal is JS-rendered and its attachments could not be read, so teams should check sih.gov.in directly or ask the ISRO SPOC. Every competitor repo examined is synthetic:

- **SPAD** states its "mock data … does not represent actual test data" ([SIH26-SPAD](https://github.com/mohith-reddy18/SIH26-SPAD)).
- **Team-404Does** simulates 1,000 parts × 43 samples with thermal coupling, channel transients and missing telemetry ([repo](https://github.com/Team-404Does/AI-Driven-Anomaly-Detection-in-Component-Burn-In-Screening)).
- **AstraNova** ships 10,000 parts × 4 checkpoints with undocumented generation parameters ([repo](https://github.com/neelkene/AstraNova-)).
- **AI-ESS Guardian** pairs a 90-part synthetic set with NASA capacitor data as a real proxy ([repo](https://github.com/Jo120424/a-AI-ESS-GUARDIAN)).

No public dataset contains per-unit Iddq, leakage or delay at burn-in checkpoints across manufacturing lots. That data is proprietary to fabs and OSATs. The usable public data splits into real degradation physics with too few units, and large production-test sets with no time axis:

| Dataset | What it is | Use in this problem |
|---|---|---|
| [NASA PCoE MOSFET Thermal Overstress (#13)](https://phm-datasets.s3.amazonaws.com/NASA/13.+MOSFET+Thermal+Overstress+Aging.zip) | IRF520N run-to-failure; Rds(on) rise from die-attach degradation; 7.85 GB .mat | Fit healthy vs. accelerating drift-shape priors ([Celaya RAMS 2012](https://c3.ndc.nasa.gov/dashlink/static/media/publication/RAMS-12_MOSFET_Final.pdf)) |
| [NASA Capacitor Electrical Stress (#12)](https://phm-datasets.s3.amazonaws.com/NASA/12.+Capacitor+Electrical+Stress.zip) | 10/12/14 V stress, discrete checkpoints up to ~194 h | Closest time scale; stress levels act as "lots" |
| [NASA IGBT Accelerated Aging (#8)](https://phm-datasets.s3.amazonaws.com/NASA/8.+IGBT+Accelerated+Aging.zip) | 6 devices, V_CE(on) degradation | Shape validation only |
| [UCI SECOM](https://archive.ics.uci.edu/dataset/179/secom) | 1,567 fab runs × 591 features, 104 fails, NaNs, CC BY 4.0 | Stress-test Module A on real, messy, imbalanced data |
| [WM-811K](https://www.kaggle.com/datasets/qingyi/wm811k-wafer-map) | 811k wafer maps, 9 pattern classes | Only for spatial/neighbourhood context |
| [Bosch Production Line](https://www.kaggle.com/c/bosch-production-line-performance) | Extreme-imbalance station data | Rare-failure benchmark only |

The NASA sets come from the [PCoE repository](https://www.nasa.gov/intelligent-systems-division/discovery-and-systems-health/pcoe/pcoe-data-set-repository/). The Capacitor-2 set is listed there as currently unavailable. To adapt NASA data, map `part_id` to the device and `lot_id` to the stress level or run, then sample the degradation parameter at the times nearest 0/24/96/168 h, or at normalised life fractions.

The synthetic generator should use the PS constants as its spec. The parameters below are a design proposal, not published values, and should be presented to judges as stated assumptions:

- **Population and baseline.** Use 6–10 lots of 500–5,000 parts. Draw Iddq as log I₀ ~ N(log 10 µA + lot_shift, 0.25) with lot_shift ~ N(0, 0.15).
- **Correlated parameters.** Leakage and delay should share a latent process-corner variable, so that multivariate detectors have real structure to learn.
- **Healthy drift.** I(t) = I₀·(1 + A·(t/168)ⁿ), with A about 3% median and n ~ U(0.2, 0.5).
- **Noise.** Apply 1% multiplicative noise, plus per-channel offsets.
- **Defect mix.** Inject about 2% defects (configurable 1–5%):

  | Defect type | Share of defects | What it models |
  |---|---|---|
  | Latent accelerating drift, mostly still under 50 µA at 168 h | 40% | Module B's core target |
  | Step jump | 20% | Sudden defect activation |
  | In-spec lot-relative outlier at 3–4.5× the lot median | 25% | The literal 45 µA example |
  | Intermittent / high noise | 10% | Contact and leak intermittents |
  | Hard spec fail | 5% | Sanity class that static limits catch |

- **Unlabelled confounders.** Add one faulty test channel and one lot shifted +20%. These force the model to learn lot-relative behaviour instead of flagging whole lots.
- **Splits.** Hold out whole lots for testing.

Industrial precedent shows what statistical screening can achieve. At LSI Logic, 0.18 µm, statistical post-processing of wafer-test data caught **168 of 171 burn-in failures (98.2%)** across 60,105 die in 14 lots. Intel cut 90 nm burn-in time by more than 90% with adaptive bucketing ([SemiEngineering](https://semiengineering.com/using-analytics-to-reduce-burn-in/)).

## Module A: robust lot statistics beat deep detectors for FN-averse screening

The explainable backbone is **Dynamic PAT on log-transformed values and on drift features**. The robust z is (x − median_lot)/(IQR_lot/1.35). The equivalent Iglewicz–Hoaglin modified z is 0.6745·(x − x̃)/MAD, flagged at |M| > 3.5 ([NIST/SEMATECH e-Handbook](https://www.itl.nist.gov/div898/handbook/eda/section3/eda35h.htm)). MAD-based Iddq outlier rejection has been evaluated specifically as a burn-in-reduction screen ([ResearchGate 3953892](https://www.researchgate.net/publication/3953892_Evaluation_of_effectiveness_of_median_of_absolute_deviations_outlier_rejection-based_IDDQ_testing_for_burn-in_reduction)).

The multiplier matters for this problem. In my calculation, a lot with median 10 µA and a lognormal spread of σ_log = 0.25 has a linear robust σ of about 2.5 µA, so a 45 µA part sits about **14σ** above the median. In log space, where the defect-free distribution is actually Gaussian, the same part sits only about **6.0σ** above: ln 4.5 / 0.25. That is right on AEC's customary 6σ yield-protecting fence. Because a false negative is catastrophic here, k should be about **3.5–4.5**, one-sided upward for leakage and Iddq and two-sided for delay, and it should be tuned on injected defects rather than inherited from automotive PAT. Screening the **residual against the lot-median trajectory** at each read-point, rather than raw values, stops an oven-temperature shift from flagging the entire lot.

Drift is where burn-in carries its real signal. With only four read-points, simple engineered features beat functional-data or sequence models and stay explainable. For each parameter, the recommended features are:

- Δ_t = P_t − P₀
- log(P_t/P₀)
- Least-squares slope against t or log t
- Curvature: (P₁₆₈ − P₉₆)/72 − (P₂₄ − P₀)/24, where a positive value means accelerating degradation
- A non-monotonicity flag
- Cross-parameter consistency

The TI/Portland State burn-in-reduction programme built this kind of "meta-variable" from sort parametrics, including **Delta IDDQ, Ratio IDDQ**, frequency deltas and min-VDD. Delta and ratio features dominated variable importance. A pruned CART caught **80% of post-burn-in fails at 35% overkill**, against 33% at 9% for the original tree, which shows how recall trades against yield loss ([SRC TEA 2008 poster](https://www.src.org/award/tech-excellence/2008/tea-poster.pdf)).

Correlated parameters need a multivariate layer, because some defects only break the correlation (normal Iddq but abnormally slow delay). **Robust Mahalanobis distance on a Minimum Covariance Determinant fit**, thresholded at χ²_{p,0.999}, was reported as the best non-learning multivariate method on automotive test data, catching returns at 0.36% yield loss ([JMP abstract](https://community.jmp.com/t5/Abstracts/Outlier-Screening-in-Test-of-Automotive-Semiconductors-Use-of/ev-p/849742)). That figure comes from a search snippet because the page was blocked. Freescale/UCSB's multivariate screening of 62 customer returns found that preemptive and reactive models each caught returns the other missed ([Sumikawa et al., ITC 2012](http://mtv.ece.ucsb.edu/licwang/PDF/2012-ITCa.pdf)), which argues for OR-ing detectors. PCA T²/SPE contribution plots are an alternative that is more explainable.

For the ML layer, two results set the rules:

- **ADBench** tested 30 algorithms on 57 datasets. It found that "**none of the benchmarked unsupervised algorithms is statistically better than others**" and that DeepSVDD and DAGMM were "surprisingly worse than shallow methods". LOF won on local anomalies and KNN on global and dependency anomalies ([ADBench, NeurIPS 2022](https://arxiv.org/abs/2206.09426)).
- **NXP/UCSB** worked on several million automotive MCUs with six real customer returns. Average AUROC was Gaussian 0.837, OCSVM 0.860, AutoEncoder 0.867 and **Isolation Forest 0.882**. At a 93% yield goal, Isolation Forest caught 3 of 6 returns, and the authors' self-labelling method caught up to 5 ([Hu et al., ITC 2020](https://web.ece.ucsb.edu/~lip/publications/OutlierDectectionIEEE-ITC2020.pdf)).

The practical choice is a small ensemble: **Isolation Forest + ECOD** (parameter-free, with per-dimension tail probabilities that explain themselves; [ECOD](https://arxiv.org/abs/2201.00382)), plus optionally KNN/LOF, all available in [PyOD](https://pyod.readthedocs.io/en/latest/). There is one caveat. When anomalies cluster, for example a whole bad wafer inside a lot, unsupervised AUROC drops by a median of 16% in ADBench, and lot-relative statistics degrade too. Golden-lot static PAT limits are therefore a necessary backstop.

If labels exist, even 1% labelled anomalies lets semi-supervised methods beat the best unsupervised detector ([ADBench](https://arxiv.org/abs/2206.09426)). LightGBM or XGBoost with class weights, or XGBOD (supervised trees fed with unsupervised scores), should be *OR-ed with* the unsupervised screens rather than replace them, because labels never cover novel defect types. Physics-based defect injection is a more defensible augmentation than SMOTE interpolation in a 20-dimensional parametric space.

To combine detectors, OR together calibrated per-detector alarms, and set each threshold with **split-conformal p-values** on known-good parts: p(x) = (1 + #{sᵢ ≥ s(x)})/(n + 1). This guarantees P(flag | good) ≤ α per detector, and ≤ m·α across m detectors ([Bates, Candès et al., Annals of Statistics 2023](https://arxiv.org/abs/2104.08279)). The false-negative rate cannot be guaranteed without labelled defects. The honest claim is "overkill ≤ α, plus 100% recall on N injected defects, with a 95% escape-rate upper bound of about 3/N", using the rule of three.

## Module B: the power law is a linear model, so predict the median delta

With only V0 and V24, a per-part fit cannot identify both the amplitude A and the exponent n. The physics prediction is **V̂168 = V0 + D24·7ⁿ**, where D24 = V24 − V0 and n is fixed per lot or mechanism. The multiplier 7ⁿ is 1.37 at n = 0.16, 1.63 at n = 0.25, 2.65 at n = 0.5 and 7.0 for linear drift. Choosing between BTI-like and linear behaviour therefore moves the forecast by up to 5× D24, and estimating n is the module's key decision. The NBTI literature warns that small errors in n shift extrapolations by years ([TU Wien, Entner](https://www.iue.tuwien.ac.at/phd/entner/node26.html)).

The formula rearranges to V168 = (1 − 7ⁿ)·V0 + 7ⁿ·V24. **Linear regression on (V0, V24) is therefore the power law with a learned exponent**, and regressing (V168 − V0) on D24 enforces "no early drift, no late drift". This derivation is mine. Log-time drift, a + b·ln(1 + t/τ), gives a ratio of about 1.59, which cannot be told apart from n ≈ 0.24 using two points, so both should be fitted and chosen by cross-validation. Measurement noise in D24 attenuates the OLS slope. That is roughly the correct shrinkage for prediction, and the Lu–Meeker mixed-effects general path model formalises it: yᵢⱼ = D(tᵢⱼ; α, βᵢ) + ε with random effects βᵢ, and BLUP prediction pulls each part's slope toward the lot mean ([Clark et al. 2025 review](https://arxiv.org/pdf/2507.14666)). Wiener and Gamma process models give closed-form predictive distributions from the same idea. NASA's MOSFET prognostics offer an empirical warning. Pure Gaussian-process regression could not predict until near the degradation "elbow" (N/A at 140 h versus a particle-filter error of 10.4 h), while model-based filters with per-device parameters worked earlier ([Celaya et al., PHM 2011](https://ntrs.nasa.gov/api/citations/20140010628/downloads/20140010628.pdf)). A physics prior matters most when data is earliest.

Because **MAE is minimised by the conditional median**, the model should train with L1 or quantile-0.5 losses. Drift in leakage and Iddq is right-skewed with a few runaway parts, and an MSE model chasing the mean loses MAE. The recommended recipe is a model ladder, stopping when grouped-CV MAE plateaus:

1. The physics baseline.
2. Median regression of (V168 − V0) on D24.
3. Huber or ridge regression on the full feature set.
4. **LightGBM with `objective='l1'` on the delta target** (V168 − V24, or log(V168/V24) for multiplicative parameters), with a +1 monotone constraint on D24 ([LightGBM parameters](https://lightgbm.readthedocs.io/en/latest/Parameters.html)).
5. A median blend of the linear and GBM models.

The feature set should include:

- V0, V24, D24, D24/|V0| and log(V24/V0)
- The lot-robust z and rank of D24
- Lot medians and IQRs of V0, V24 and D24
- The physics feature V0 + D24·7^n̂_lot

The median is equivariant under monotone transforms, so an L1 fit in log space back-transforms correctly without the smearing correction that L2 would need. GBMs extrapolate poorly beyond the training range, which is why the linear component stays in the blend.

The 96-hour readout is **privileged information**: available in training, never at inference. Three uses are legitimate:

- **Estimate n** per part as ln(D96/D24)/ln 4, and pool it into a lot prior.
- **Validate the model form** by checking ln(D168/D96)/ln 1.75 against that estimate.
- **Chain models**: (V0, V24) → V96 → V168. The second stage must train on out-of-fold stage-1 predictions.

Validation must use **GroupKFold by lot** ([scikit-learn](https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.StratifiedGroupKFold.html)), with every lot-level statistic and prior computed inside the training fold. The report should give MAE per parameter and the worst-lot MAE. If one MAE pools parameters of different scale, the large-magnitude parameter dominates it, so modelling effort belongs there.

**Uncertainty: Conformalized Quantile Regression.** CQR fits the 0.05, 0.5 and 0.95 quantiles and shifts the band on a held-out, lot-grouped calibration split. This gives finite-sample, distribution-free coverage that adapts to heteroscedastic drift ([Romano, Patterson, Candès 2019](https://arxiv.org/abs/1905.03222)), and it is implemented as MAPIE's `ConformalizedQuantileRegressor` over LightGBM ([MAPIE](https://mapie.readthedocs.io/en/latest/generated/mapie.regression.ConformalizedQuantileRegressor.html)).

**Scored output vs. safety flag.** Submit the median as the MAE-scored prediction, and flag on the upper bound U168. Biasing the point estimate upward for safety would inflate MAE for no gain, so the two outputs must stay separate.

**The "safety slope".** The PS leaves it undefined. The notes support four candidates:

- **Spec-delta slope:** S_a = Δ_max/168, with Δ_max = max(Δ_abs, pct·|V0|) in the ESCC "whichever greater" form.
- **Mission-life slope:** S_b = (Limit − V0)/t_eq, where t_eq = mission hours / AF. At Ea = 0.7 eV and a 10-year mission, t_eq ≈ 1,128 h at 125 °C.
- **PAT-style lot slope:** S_c = median_lot(r) + k·1.4826·MAD_lot(r), computed on the lot's own predicted drift rates. This is legitimate at inference.
- **Rule of thumb:** use S = min of whichever of these are available.

The recommended rule flags a part if (U168 − V0)/168 > S, or if U168 crosses the datasheet limit. The CQR confidence level (0.9 → 0.99) or k is tuned on grouped folds to minimise C_FN·FN + C_FP·FP. Early-rejection precedent exists. On 9 quantum-cascade lasers, an SVM predicted premature failure up to 200 h ahead with **>80% sensitivity after only 8 h** of burn-in ([Sci. Rep. 2022](https://pmc.ncbi.nlm.nih.gov/articles/PMC9163159/)). Dynamic-duration burn-in patents use per-lot deltas at read-points to decide termination ([US 6175812](https://image-ppubs.uspto.gov/dirsearch-public/print/downloadPdf/6175812)). No public benchmark of 0/24 h → 168 h Iddq regression MAE was found.

## Explainability and metrics must speak MRB language, not ML language

Regulators frame current aerospace ML as assistance. EASA's Concept Paper Issue 2 defines **Level 1 (assistance) and Level 2 (human–AI teaming)** and splits explainability into operational and development views ([EASA](https://www.easa.europa.eu/en/newsroom-and-events/news/easa-publishes-artificial-intelligence-concept-paper-issue-2-guidance)). NPA 2025-07 (10 Nov 2025) turns this into draft "DS.AI" specifications ([EASA NPA 2025-07](https://www.easa.europa.eu/en/document-library/notices-of-proposed-amendment/npa-2025-07)). ESA published **ECSS-E-HB-40-02A**, a machine-learning qualification handbook, on 15 Nov 2024 ([ECSS](https://ecss.nl/wp-content/uploads/2024/12/ECSS-E-HB-40-02A(15November2024).pdf)). The defensible framing is: "the AI proposes dispositions with traceable reasons; the QA inspector/MRB decides". AI flags come **in addition to** spec and Δ-limit rejects, never in place of them, just as PAT never loosens spec limits.

The explanation hierarchy runs from most to least inspector-friendly:

1. **Deterministic reason codes.** Each code maps one-to-one to a rule and threshold. Examples: "R01: Iddq@24h = +6.2σ_robust above lot median (n = 48)"; "R07: predicted Iddq@168h = 41 µA [90% PI 37–45] > safety limit".
2. **Counterfactuals.** For threshold rules these are exact and cheap, e.g. "would pass if Iddq@24h ≤ 12.4 µA".
3. **ML attribution.** Use TreeSHAP on Isolation Forest or LightGBM, which SHAP now supports ([shap #237](https://github.com/slundberg/shap/issues/237)). DIFFI is the alternative: it reports Isolation Forest importance as effective as SHAP at much lower cost ([arXiv 2007.11117](https://arxiv.org/abs/2007.11117)).
4. **Visuals.** A lot histogram with the PAT fences; the part's trajectory over a lot P5–P95 fan chart with the forecast interval; an Iddq-vs-leakage scatter with the MCD ellipse.
5. **Optional LLM narrative.** It may only restate a JSON of computed facts, with an automated "no new numbers" check.

For Module B, EBMs give editable shape functions with near-boosting accuracy ([InterpretML](https://interpret.ml/docs/ebm.html)). Showing the physics baseline beside the ML forecast turns their disagreement into its own "model uncertainty" code. No user study on which formats semiconductor MRB inspectors prefer was found, so this hierarchy is reasoned, not measured.

The metric pack should follow the scoring asymmetry. Because anomalies are rare, report **recall and FN count first**, then F2, precision and FPR at the zero-FN operating point, and **PR-AUC rather than ROC-AUC**. Precision–recall plots better reflect performance under imbalance ([Saito & Rehmsmeier 2015](https://journals.plos.org/plosone/article?id=10.1371%2Fjournal.pone.0118432)), though a 2024 counterpoint argues AUPRC is not universally superior ([arXiv 2401.06091](https://arxiv.org/pdf/2401.06091)). Add three more views:

- A cost curve at FN:FP ratios of 10×, 100× and 1000×.
- The lot flag rate against the 5% PDA.
- A per-detector ablation showing each detector's *unique* catches.

sklearn's `TunedThresholdClassifierCV` post-tunes thresholds against a business cost ([scikit-learn](https://scikit-learn.org/stable/modules/classification_threshold.html)).

For regression, report MAE in physical units (the official metric), MedAE, per-parameter and worst-lot MAE, and conformal coverage and width. Avoid MAPE on near-zero leakage currents.

The zero-FN threshold procedure has four steps:

1. Split validation folds by lot.
2. In each fold, set the threshold just below the lowest true-defect score.
3. Take the most conservative threshold across folds.
4. Report the resulting overkill and the rule-of-three escape bound.

The official SIH scoring formula (β, cost ratio) was not found publicly.

## Competitors already ship the obvious stack, so differentiate on rigor

At least two public repos implement nearly the whole "obvious" solution:

- **space-grade-burnin-ai** has:
  - a physics-informed simulator with TDDB and EM modes;
  - robust DPAT (median, IQR/1.349) plus Isolation Forest on lot-relative z;
  - LightGBM drift prediction with a safety-slope check and "144 h saved" per early reject;
  - SHAP-waterfall QA certificates, a 10× FN cost weighting, and FastAPI plus Streamlit.

  ([GitHub](https://github.com/aadityaexpress/space-grade-burnin-ai))
- **ASTRA-IC** has:
  - MAD modified-z DPAT (>3.5);
  - Gaussian-process 24 h → 168 h forecasting with early abort on the upper 3σ bound;
  - KernelSHAP audit statements;
  - Streamlit with PDF export.

  It claims **100% recall, 0% escape, MAE 0.214 µA and R² 0.9966**, on its own synthetic data ([GitHub](https://github.com/jishasalariya/ASTRA-IC)).

Neither repo was verified to use lot-grouped validation. Their headline numbers are self-reported on self-generated data, which is exactly the weakness a stronger entry can expose.

The recommended end-to-end design follows from everything above:

| Stage | Method | Explanation emitted |
|---|---|---|
| Ingest | pandas schema check (lot, serial, param, unit, t, value, retest); SI unit normalisation; dedupe on (serial, t, param) | data-quality flags |
| Gate 0 | Datasheet limits + ESCC-style Δ = max(abs, pct·V0); lot PDA tally | hard reject codes |
| A1: Dynamic PAT | Robust z on log values, Δ, log-ratio, slope, curvature, residual-to-lot-median; k ≈ 3.5–4.5 one-sided; σ floor and "low-confidence" code when n < 30; MAD = 0 guard | "Nσ above lot" codes |
| A2: Multivariate | MinCovDet Mahalanobis, χ²₀.₉₉₉ or conformal threshold | per-feature contribution |
| A3: ML ensemble | IForest + ECOD (+KNN), rank-normalised max; golden-lot static PAT backstop | TreeSHAP/DIFFI, ECOD tails |
| B: Forecast | Physics baseline + L1 LightGBM on delta target, median-blended; 96 h as privileged prior; MAPIE CQR | forecast + interval, physics-vs-ML disagreement |
| B flag | (U168 − V0)/168 > min(S_a, S_b, S_c) or U168 > limit | "projected drift exceeds safety slope" |
| Decision | OR across stages, each conformal-calibrated; REJECT / REVIEW / CONTINUE / RELEASE | failure-mode hypothesis label |
| Governance | Streamlit lot overview, part inspector, MRB disposition buttons, append-only JSONL audit log (file hash, model hash, thresholds, inspector override) | per-part PDF certificate |

The differentiators judges have not yet seen together are five. First, a zero-escape operating point **proven on held-out lots**, with an explicit 3/N escape-rate bound in place of a bare "100% recall". Second, a three-way **reject / continue / release-candidate** decision at 24 h, driven by conformal bounds, with chamber-hours saved computed only for decisions that are statistically safe. Third, physics-labelled flags that map onto a failure-mode table. Fourth, a slide mapping the flow to MIL-PRF-38535 PDA, ESCC drift rules, EASA Level 1 and ECSS-E-HB-40-02A. Fifth, a static-versus-dynamic PAT baseline plus a detector ablation on SECOM and NASA-derived trajectories, which shows the method survives real, messy data rather than only its own simulator.

## Conclusion

The central insight is that this problem statement is a rediscovery of semiconductor test engineering, not a greenfield ML task. Robust lot-relative statistics, delta and ratio meta-variables, and multivariate outlier screens have 20 years of industrial evidence behind them, and benchmarks show that sophisticated unsupervised learners add little on top. The real open questions sit elsewhere:

- **The multiplier k.** AEC's 6σ is tuned for automotive yield, not space-grade escape aversion. The 45 µA example sits almost exactly on that fence once leakage is analysed in log space, as it should be.
- **Separating the scored median from the safety bound.** One prediction must optimise MAE while another carries the flag.
- **Being honest about what synthetic data can prove.** A zero-escape guarantee is statistically unattainable. A calibrated overkill bound plus an empirical escape-rate bound is attainable, and more credible to ISRO reliability engineers than any headline recall number.

Several things remain unknown and should be resolved early:

- Whether ISRO supplies data. If it does, lot composition in the hidden test set decides the CV scheme.
- The exact scoring formula.
- The real drift exponents for product-level Iddq, leakage and delay at 125 °C.
- The definition ISRO intends for the "safety slope". The spec-delta, mission-life and lot-statistical definitions can differ by several-fold, so the chosen definition and its Ea assumption should be displayed, not buried.
