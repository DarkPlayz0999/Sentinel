# Module A: Dynamic (Lot-Relative) Outlier Detection for Burn-in Parametric Data

Scope: parts measured at 0h / 24h / 96h / 168h of 125 °C burn-in (Iddq, leakage, propagation delay). Goal: flag parts extreme *relative to their lot* even when inside static datasheet limits; false negatives are the dominant cost; explainability to a QA inspector is scored.

Research note: ~16 tool calls. AEC-Q001 PDF could not be fetched (SSL error), so its details come from search-result excerpts of the official document plus a Pintail/SWTest presentation. Formulas marked "standard" are textbook definitions. They are listed so the writer has them, and should be cited to a textbook or to sklearn/NIST if needed.

---

## 1. Robust univariate statistics (modified z, IQR, Dynamic PAT, log transform, Grubbs/ESD)

### Takeaway
The industry-standard, explainable base layer is **Dynamic PAT**: per-lot limits = robust center ± k·robust sigma, with robust center = median and robust sigma = IQR/1.35 (AEC-Q001). It is essentially the same idea as the Iglewicz–Hoaglin modified z-score (0.6745·(x−med)/MAD, flag |M|>3.5). Apply it to log-transformed leakage/Iddq, and apply it to the **drift features** (Δ, ratio) as well as the raw readings. In the example (lot median 10 µA, part at 45 µA) the part is obviously caught even though it passes the 50 µA static limit.

### Cited Findings
- AEC-Q001 defines "robust mean" = median of the lot data, and "robust sigma" = (Q3 − Q1)/1.35, where Q1 and Q3 are the values 1/4 and 3/4 of the way down the sorted list. Robust statistics are used because ordinary mean/σ are "very sensitive to outliers." — [AEC-Q001 Rev-D (via search excerpt)](http://www.aecouncil.com/Documents/AEC_Q001_Rev_D.pdf); [AEC-Q001 Rev-C](http://www.aecouncil.com/Documents/AEC_Q001_Rev_C.pdf)
- Dynamic PAT limits are "calculated on a wafer or lot basis… continuously changing based on the performance of the material for that wafer or lot," as Mean ± n·Sigma or Median ± N·Robust Sigma. — [AEC-Q001 (search excerpt)](http://www.aecouncil.com/Documents/AEC_Q001_Rev_D.pdf); [Pintail, Dynamic PAT in Real-time (SWTW 2005)](https://www.swtest.org/swtw_library/2005proc/PDF/S08_03_Mickyray.pdf)
- To set static PAT limits, AEC-Q001 says to collect data from at least 6 lots that passed spec limits, sampling a minimum of 30 parts per lot. — [AEC-Q001 (search excerpt)](http://www.aecouncil.com/Documents/AEC_Q001_Rev_D.pdf)
- Modified z-score: M_i = 0.6745·(x_i − x̃)/MAD, where MAD = median(|x_i − x̃|). Iglewicz & Hoaglin recommend flagging |M_i| > 3.5. The standard z-score is misleading in small samples because max|z| ≤ (n−1)/√n. — [NIST/SEMATECH e-Handbook §1.3.5.17](https://www.itl.nist.gov/div898/handbook/eda/section3/eda35h.htm)
- Grubbs' test is recommended when testing for a **single** outlier. Generalized ESD needs only an upper bound on the number of outliers and is recommended when that number is unknown. — [NIST e-Handbook](https://www.itl.nist.gov/div898/handbook/eda/section3/eda35h.htm)
- MAD-based outlier rejection on IDDQ has been evaluated specifically as a burn-in-reduction screen (LSI 0.18 µm). — [ResearchGate: Evaluation of MAD outlier rejection-based IDDQ testing for burn-in reduction](https://www.researchgate.net/publication/3953892_Evaluation_of_effectiveness_of_median_of_absolute_deviations_outlier_rejection-based_IDDQ_testing_for_burn-in_reduction)
- Spatial and neighbor-based variants such as Nearest-Neighbor Residual (NNR, Daasch et al., ITC 2001) estimate each die's defect-free value from its neighbors to reduce the variance of the IDDQ distribution before outlier screening. NNR's effectiveness depends on the smoothness of the wafer pattern. — [IEEE D&T: Neighborhood selection for IDDQ outlier screening](https://ieeexplore.ieee.org/document/1033795/); [Sabade & Walker, NNR vs NCR](https://people.engr.tamu.edu/d-walker/5yrPapers/DBT_NCR_042004.pdf)
- Industry evolution of screening methods (NXP/UCSB): yield-based SBL/BMY → univariate S-PAT/D-PAT, NNR, location averaging → multivariate → ML. — [Hu et al., ITC 2020](https://web.ece.ucsb.edu/~lip/publications/OutlierDectectionIEEE-ITC2020.pdf)

### Formulas (standard)
- IQR/Tukey fences: [Q1 − k·IQR, Q3 + k·IQR], with k = 1.5 ("outlier") or 3 ("far out"). With robust σ = IQR/1.35, the 1.5·IQR fence ≈ median ± 2.7σ for Gaussian data.
- Relationship: for Gaussian data, MAD·1.4826 ≈ σ and IQR/1.349 ≈ σ, so modified-z 3.5 ≈ 3.5 robust σ. PAT's customary 6σ is a much looser, yield-protecting limit (see gap on 6σ).
- Chauvenet: reject x if n·P(|Z| > |z|) < 0.5. It depends on non-robust mean/σ and is not recommended for production (inference).
- Log transform: leakage/Iddq are typically right-skewed and roughly lognormal, so compute robust z on y = log(x) (or log(x + c)). Otherwise the upper tail inflates spurious flags while masking low-side anomalies.

### Inferences
- Use a **one-sided upper** limit for leakage and Iddq, and two-sided limits for delay. Choose k lower than PAT's 6 (e.g., 3–4.5) because FN cost is dominant. Tune k on labeled or injected-defect data.
- Grubbs/ESD assume normality and small n, and PAT scales better to lots of hundreds of parts. ESD is useful as a secondary "how many outliers in this lot" check. Chauvenet is not recommended.
- Robust z is highly explainable: "Part 17: Iddq@168h = 45 µA; lot median 10 µA; robust σ 2 µA ⇒ 17.5σ above lot."

### Gaps
- I could not fetch the AEC-Q001 PDF itself (SSL failure), so the exact default multiplier (commonly quoted as 6 robust σ for static PAT and 6σ for dynamic PAT) and the lot-size minimums for dynamic PAT are unverified here. Check against the Rev-D PDF.
- I found no source on the minimum lot size at which robust statistics become unstable. Engineering practice suggests ≥ 30 parts, consistent with the AEC-Q001 sampling rule.

---

## 2. Multivariate methods (robust Mahalanobis/MCD, Hotelling T², PCA SPE/Q, multivariate PAT)

### Takeaway
Iddq, leakage and delay are correlated, and some defects only show as a broken correlation (e.g., normal Iddq but abnormally slow delay). A **robust Mahalanobis distance (MCD)** on per-lot standardized features is the strongest "no-learning" multivariate screen reported for automotive test data. PCA T²/SPE decomposition adds explainability.

### Cited Findings
- A JMP Discovery abstract on automotive semiconductor outlier screening reports that the Mahalanobis distance was the best multivariate method without learning, detecting returns at 0.36% yield loss. (Summary via search snippet; the page returned 403.) — [JMP Community abstract](https://community.jmp.com/t5/Abstracts/Outlier-Screening-in-Test-of-Automotive-Semiconductors-Use-of/ev-p/849742)
- Freescale/UCSB (Sumikawa et al., ITC 2012): 16 months of production data for an automotive SoC, with 62 customer returns from 52 lots. Multivariate models were built on parametric wafer-sort tests using a preemptive approach (correlated test subsets) and a reactive approach (a model per known return). Each approach caught returns the other missed. — [Sumikawa et al., ITC 2012 PDF](http://mtv.ece.ucsb.edu/licwang/PDF/2012-ITCa.pdf); [IEEE Xplore](https://ieeexplore.ieee.org/document/6401547/)
- O'Neill (ITC 2008), "Production multivariate outlier detection using principal components," is a production PCA-based outlier screen. — cited in [Hu et al., ITC 2020 refs](https://web.ece.ucsb.edu/~lip/publications/OutlierDectectionIEEE-ITC2020.pdf)
- Mahalanobis distance is affine-invariant. PCA is only orthogonally invariant but allows component selection and helps interpret flagged outliers. ICS (Invariant Coordinate Selection) is proposed for high-quality-control settings (automotive/avionics) where ≤ 2% outliers are plausible. — [Archimbaud et al., ICS for Multivariate Outlier Detection (arXiv 1612.06118)](https://arxiv.org/abs/1612.06118)
- In NXP's industrial data, a plain Gaussian model had the worst average AUROC (0.837) because it "mispredicts examples close to the center" as abnormal. — [Hu et al., ITC 2020](https://web.ece.ucsb.edu/~lip/publications/OutlierDectectionIEEE-ITC2020.pdf)

### Formulas (standard)
- Robust Mahalanobis: D²(x) = (x − μ̂_MCD)ᵀ Σ̂_MCD⁻¹ (x − μ̂_MCD). Under Gaussian data D² ~ χ²_p, so flag D² > χ²_{p,1−α} (e.g., α = 0.001). MCD takes the subset of h ≈ (n+p+1)/2 points with minimal covariance determinant. sklearn uses `MinCovDet(support_fraction=None)` (default h = (n+p+1)/2) and `EllipticEnvelope(contamination=…)`.
- Hotelling T² on PCA scores: T² = Σ_{k=1..K} t_k²/λ_k. SPE/Q-statistic: Q = ‖x − P_K P_Kᵀ x‖². T² flags extreme-but-consistent parts, while Q flags parts that break the correlation structure. Contribution plots decompose T² and Q per feature, which gives explainability.
- Multivariate PAT = the same approach per lot: fit robust μ and Σ per lot (or per lot × read-point), then threshold D².

### Inferences
- With p ≈ 3 raw parameters × 4 read-points plus drift features (≈ 15–25 dims) and lots of hundreds of parts, MCD is well-conditioned. Fit per lot when n ≥ ~5p. Otherwise use a pooled covariance with per-lot location.
- For explainability, report both the D² value and its per-feature contribution (e.g., (x−μ)ᵢ·[Σ⁻¹(x−μ)]ᵢ).

### Gaps
- I could not access the full JMP abstract for its exact dataset or recall numbers.

---

## 3. ML unsupervised detectors (IF, EIF, LOF, OCSVM, ECOD, COPOD, HBOS, AE, Deep SVDD) and benchmarks

### Takeaway
ADBench (NeurIPS 2022, 30 algorithms × 57 datasets) found **no unsupervised method statistically better than the others**. Deep methods (DeepSVDD, DAGMM) were often worse than shallow ones. The best method depends on the anomaly type: LOF for local anomalies, KNN for global and dependency anomalies. On real automotive test data with extremely rare returns (NXP ITC 2020), Isolation Forest and autoencoders were the best standard baselines, but no method was reliable alone. Recommendation: an ensemble of a few fast, parameter-light detectors (IForest + ECOD + KNN/LOF), not a single deep model.

### Cited Findings
- ADBench: "none of the benchmarked unsupervised algorithms is statistically better than others". "DL-based unsupervised methods like DeepSVDD and DAGMM are surprisingly worse than shallow methods" because they have more hyperparameters and are hard to tune without labels. — [Han et al., ADBench, NeurIPS 2022 (arXiv 2206.09426)](https://arxiv.org/abs/2206.09426)
- ADBench anomaly types: LOF is statistically best for **local** anomalies, KNN (k-th NN distance) is best for **global** anomalies and also top for **dependency** anomalies, and OCSVM is the best unsupervised method on **clustered** anomalies. "There is no algorithm performing well on all types of anomalies." — [ADBench](https://arxiv.org/abs/2206.09426)
- ADBench robustness: with anomalies duplicated 6×, the median ΔAUCROC is −16.43% for unsupervised methods, versus −0.05% for semi-supervised and +0.13% for supervised methods. — [ADBench](https://arxiv.org/abs/2206.09426)
- NXP/UCSB ITC 2020: six real customer failures out of several million automotive MCUs shipped, with 6–1377 parametric features per test insert and ~35–50k samples. Average AUROC on industrial data: Gaussian 0.837, OCSVM 0.860, **IsoForest 0.882**, AutoEncoder 0.867. The proposed self-labeling "RevTransC" scored 0.900. At a 93% yield goal, IsoForest caught 3 of 6 returns and RevTrans variants caught up to 5 of 6. The authors say standard methods "do not work well" for extremely rare customer failures. — [Hu, Nguyen, He, Li, ITC 2020](https://web.ece.ucsb.edu/~lip/publications/OutlierDectectionIEEE-ITC2020.pdf)
- ECOD (Li et al., IEEE TKDE 2022): computes empirical CDFs per dimension, estimates each point's tail probability, and aggregates across dimensions. It is **parameter-free** and interpretable per dimension. It was evaluated on 30 datasets against 11 baselines and is implemented in PyOD. — [ECOD, arXiv 2201.00382](https://arxiv.org/abs/2201.00382)
- PyOD (now v3) covers 61 detectors across modalities. The tabular set includes IForest, DIF, LOF, KDE, AutoEncoder, DeepSVDD, SUOD, and LSCP, and v3 adds ADEngine automated model selection plus benchmark-backed routing (ADBench, TSB-AD). — [PyOD docs](https://pyod.readthedocs.io/en/latest/)

### Method cheat-sheet (standard, with key hyperparameters)
| Method | Idea | Key hyperparams | Strength | Weakness |
|---|---|---|---|---|
| Isolation Forest | Avg path length to isolate; s(x)=2^(−E[h(x)]/c(n)) | n_estimators=100–500, max_samples=256, contamination | Fast, scales, good on global outliers | Axis-parallel bias, weaker on local/dependency anomalies |
| Extended IF | Random hyperplane splits | extension level | Removes axis artefacts | Less tooling (`isotree`, `eif`) |
| LOF | Local density ratio | n_neighbors=20–35 | Best on local anomalies | Sensitive to k, O(n²) |
| KNN | Distance to k-th neighbor | k=5–10, method=largest/mean | Best on global and dependency anomalies | Scaling-sensitive |
| OCSVM | Boundary around normal data | ν, γ (RBF) | Clustered anomalies | Tuning-heavy, poor explainability |
| ECOD | Per-dim ECDF tail probability | none | Parameter-free, per-feature explanation | Ignores feature correlation |
| COPOD | Empirical copula tails | none | Parameter-free, fast | Same limitation as ECOD |
| HBOS | Per-feature histograms | n_bins | Very fast, explainable | Independence assumption |
| AutoEncoder | Reconstruction error | architecture, epochs | Nonlinear dependencies | Needs data, tuning, low explainability |
| Deep SVDD | Minimum hypersphere in latent space | architecture, ν | Nonlinear | Underperforms shallow methods in ADBench |

### Inferences
- For a hackathon-scale tabular problem (≈ 20 features, hundreds to thousands of parts), deep methods add cost and hurt explainability without an evidenced gain. Prefer IForest + ECOD/COPOD + robust Mahalanobis.
- ADBench's duplication result matters for burn-in: if a whole sub-population drifts (e.g., a bad wafer within the lot), unsupervised "rare-ness" assumptions break. Lot-relative robust statistics also degrade, so add cross-lot reference limits (static PAT from golden lots) as a backstop.

### Gaps
- I did not retrieve ECOD's or COPOD's exact numeric rankings. Extended IF benchmark numbers were not checked.

---

## 4. Trajectory / time-series features across 0h → 24h → 96h → 168h

### Takeaway
Burn-in's real signal is **drift**: a latent defect often passes absolute limits at every read-point but degrades anomalously. Build per-part drift features and screen them lot-relatively. With only 4 time points, simple engineered features (Δ, ratio, slope, curvature, residual vs lot trend) beat functional-data or deep sequence models and stay explainable.

### Cited Findings
- Delta-IDDQ (the difference between IDDQ measurements, e.g., across vectors/conditions or pre/post stress) has been proposed as a reliability screen. A patent claims ΔIddq screening can replace burn-in because ΔIddq failure correlates with burn-in failure. — [Delta Iddq for testing reliability (ResearchGate)](https://www.researchgate.net/publication/3848848_Delta_Iddq_for_testing_reliability); [US Patent 6,230,293](https://image-ppubs.uspto.gov/dirsearch-public/print/downloadPdf/6230293)
- TI/Portland State (SRC task 1197, 2008 Technical Excellence Award): burn-in reduction via "meta-variables" from sort-test parametrics, e.g., **Delta IDDQ**, **Ratio IDDQ**, frequency deltas, and minVDD. These were combined with CART, CCA, and PCA. The pruned CART caught 80% of post-burn-in fails at 35% overkill on passes, versus 33% caught at 9% overkill for the original tree, which illustrates the recall/overkill trade-off. TI's K. Butler said TI "reaped a very large return on investment." — [SRC TEA 2008 poster](https://www.src.org/award/tech-excellence/2008/tea-poster.pdf)
- Related publications: "Burn-in Reduction using Principal Component Analysis" (Nahar, Daasch, Subramaniam, ITC 2005), and Butler et al., "Successful development and implementation of statistical outlier techniques on 90nm and 65nm process driver devices," IRPS 2006. — [SRC poster](https://www.src.org/award/tech-excellence/2008/tea-poster.pdf); [Hu et al. ITC 2020 references](https://web.ece.ucsb.edu/~lip/publications/OutlierDectectionIEEE-ITC2020.pdf)

### Feature set (standard; recommended)
For each parameter P ∈ {Iddq, leakage, t_pd} and read-points t ∈ {0, 24, 96, 168}:
- Absolute drift: ΔP_t = P_t − P_0, and max |ΔP|.
- Relative drift: P_t / P_0, or log(P_t/P_0), which is scale-free and suits leakage.
- Slope: least-squares slope of P vs t, or vs log(t), since many degradation mechanisms follow a power law P ∝ tⁿ.
- Curvature / acceleration: second difference, (P_168 − P_96)/72 − (P_24 − P_0)/24. A positive value means accelerating degradation, which is the most dangerous case.
- Residual vs lot trend: r_i,t = P_i,t − median_lot(P_t). Robust-z these per read-point and on the vector r_i, which removes common-mode drift from oven or ATE shifts.
- Non-monotonicity flag, i.e. sign changes in the Δs. This can signal intermittent or contact problems versus real degradation.
- Cross-parameter consistency: ΔIddq vs Δt_pd correlation, which feeds the Mahalanobis stage.

### Inferences
- Functional-data outlier methods (functional boxplots, MS-plot) and trajectory clustering (k-means/DTW on curves) are overkill for 4 points. Per-read-point robust z plus slope/curvature captures the same information. Trajectory clustering is useful only as a visual aid: showing the inspector the lot's median curve ± robust bands with the flagged part overlaid is highly explainable.
- Screen "residual vs lot trend" rather than raw values so that a whole-lot shift (oven temperature error) does not flag everyone.

### Gaps
- No public burn-in dataset with 0/24/96/168h read-points was found. Recommended thresholds for drift features (e.g., % ΔIddq) could not be sourced.

---

## 5. Supervised / semi-supervised learning when labels exist

### Takeaway
If even ~1% of anomalies are labeled (e.g., historic post-burn-in or field failures), semi-supervised or gradient-boosted models beat all unsupervised methods on average (ADBench). Keep them as an *additional* detector OR-ed with the unsupervised screens, because labels never cover novel defect types. Tune thresholds for recall (F2, or recall ≥ 99.x%) and do not optimize accuracy.

### Cited Findings
- ADBench: "with merely 1% labeled anomalies, most semi-supervised methods can outperform the best unsupervised method". With ≤ 5% labels, semi-supervised median AUCROC was 75.56% (1% labels) and 80.95% (5%), versus fully supervised 60.84% and 72.69%. Most supervised methods need ~10% labeled anomalies to beat the best unsupervised method. — [ADBench](https://arxiv.org/abs/2206.09426)
- ADBench: tree ensembles (XGBoost, CatBoost) and FTTransformer perform well among label-informed methods; at 1% labels the median AUCROC of ensembles was 76.47%. Supervised trees are robust to irrelevant features thanks to built-in feature selection. — [ADBench](https://arxiv.org/abs/2206.09426)
- ADBench caveat: for local, global and dependency anomalies, most label-informed methods did **worse** than the best unsupervised detector for that type, because partial labels do not capture all anomaly behaviors. Labels helped mainly for clustered anomalies. — [ADBench](https://arxiv.org/abs/2206.09426)
- ADBench: semi- and fully-supervised methods are resilient to minor annotation errors. — [ADBench](https://arxiv.org/abs/2206.09426)
- Real-world burn-in reduction frameworks combine machine signals, wafer maps and pre-burn-in electrical tests to predict lot quality. — [Springer 2024: AI-based framework for burn-in reduction](https://link.springer.com/chapter/10.1007/978-3-031-59361-1_5)

### Techniques (standard)
- XGBoost/LightGBM with `scale_pos_weight ≈ N_neg/N_pos` (or `class_weight`), shallow trees, early stopping on PR-AUC.
- Cost-sensitive threshold: flag if p(fail|x) > C_FP/(C_FP + C_FN). With C_FN ≫ C_FP the threshold goes toward 0, so choose it by recall-at-fixed-overkill on validation.
- F_β with β=2: F2 = 5·P·R/(4P + R), which weights recall 4× precision. Better still: report recall at a fixed overkill (e.g., ≤ 2% yield loss), as industry uses "yield loss" (see NXP's 93% yield goal).
- SMOTE caveat: synthetic interpolation in a ≈ 20-D parametric space can create unrealistic "defects" and inflate validation metrics. Apply it only inside CV folds, or prefer class weights. Physics-based defect injection (e.g., adding a leakage path that grows with t) is a more defensible augmentation (inference).
- XGBOD (in PyOD) augments supervised XGBoost with unsupervised outlier scores as features, a natural hybrid.

### Gaps
- No source found quantifying SMOTE harm specifically for semiconductor test data.

---

## 6. Ensembles, score combination, threshold calibration, conformal guarantees

### Takeaway
Combine a few detectors with **OR logic on calibrated per-detector alarms** (or a max of rank-normalized scores) to minimize FN. Calibrate each detector's threshold with **conformal p-values** on a clean reference set. This gives a finite-sample guarantee on the false-alarm rate (type-I). FN rate cannot be guaranteed without labeled defects; it can only be bounded empirically via recall on labeled or injected defects.

### Cited Findings
- Conformal outlier testing (Bates, Candès, Lei, Romano, Sesia, Annals of Statistics 2023) gives marginally valid p-values for "does this new sample come from the reference distribution?" The p-values are positively dependent, so Benjamini–Hochberg controls FDR. A calibration-conditional variant gives p-values valid conditional on the calibration data, with finite-sample guarantees via concentration inequalities. — [arXiv 2104.08279](https://arxiv.org/abs/2104.08279); [Annals of Statistics](https://projecteuclid.org/journals/annals-of-statistics/volume-51/issue-1/Testing-for-outliers-with-conformal-p-values/10.1214/22-AOS2244.full)
- A 2026 arXiv paper covers "Conformal Anomaly Detection in Python" (tooling for conformal wrappers around detectors). — [arXiv 2605.13642](https://arxiv.org/pdf/2605.13642)
- NXP ITC 2020 reports the operational framing: "estimated yield" = 1 − fraction of good parts rejected alongside the failure. A part counts as screened if *any* test insert's detector catches it, i.e., OR logic across inserts. — [Hu et al., ITC 2020](https://web.ece.ucsb.edu/~lip/publications/OutlierDectectionIEEE-ITC2020.pdf)
- Sumikawa et al. found that different model families catch different returns, which supports ensembles or OR-ing. — [ITC 2012](http://mtv.ece.ucsb.edu/licwang/PDF/2012-ITCa.pdf)
- PyOD provides SUOD/LSCP ensemble frameworks. — [PyOD docs](https://pyod.readthedocs.io/en/latest/)

### Formulas (standard)
- Split-conformal p-value for test score s(x), with calibration scores s_1..s_n from known-good parts: p(x) = (1 + #{i : s_i ≥ s(x)}) / (n + 1). Flag if p ≤ α, which guarantees P(flag | good part) ≤ α. With α = 0.01 and n ≥ 99, overkill ≤ 1% per detector.
- With m detectors OR-ed, overkill ≤ m·α (Bonferroni). Alternatively combine p-values (e.g., min-p × m, or Cauchy combination) and then threshold.
- Score normalization before combining: rank/ECDF-transform each detector's scores within the lot to [0,1]. Then take the max (FN-averse) or mean (overkill-averse). PyOD `pyod.models.combination` offers average, maximization, AOM, and MOA.
- FN control (empirical): choose thresholds so that recall on all labeled or injected defects is 100%, and report a Clopper–Pearson upper bound on the escape rate. With 0 misses in N defects, the 95% upper bound ≈ 3/N (the "rule of three").

### Inferences
- Conformal calibration fits the "lot-relative" framing naturally: the calibration set is the lot itself (exchangeability within a lot), or golden lots. If contamination in the lot is a concern, use the robust core, e.g., parts within the MCD support.
- "Guaranteed zero FN" is not achievable statistically. Present it as guaranteed overkill ≤ α plus empirically demonstrated 100% recall on N injected defects, with an escape-rate upper bound of 3/N at 95% confidence.

### Gaps
- I did not verify API details of specific conformal packages (e.g., `nonconform`, MAPIE's anomaly support).

---

## 7. Published industrial work (NXP, TI, Freescale, Intel, etc.)

### Takeaway
The semiconductor-test literature has progressed from PAT/NNR univariate screens (TI/PSU 2000–2006) to multivariate Mahalanobis/PCA (Freescale 2012, O'Neill 2008) to ML (NXP/UCSB 2020). A consistent finding is that no single method catches all escapes and that the trade-off is always recall versus yield loss.

### Cited Findings
- TI + Portland State (Daasch): NNR, location averaging, IDDQ delta/ratio meta-variables, CART/PCA burn-in reduction. Best paper awards at ITC 2002 and VTS 2003. — [SRC poster](https://www.src.org/award/tech-excellence/2008/tea-poster.pdf); [Daasch et al., ITC 2001](http://web.cecs.pdx.edu/~mcnames/Publications/ITC2001.pdf)
- Freescale (now NXP) / UCSB: multivariate customer-return screening, ITC 2012. — [PDF](http://mtv.ece.ucsb.edu/licwang/PDF/2012-ITCa.pdf)
- NXP / UCSB: self-labeling unsupervised learning over IsoForest/OCSVM/AE/Gaussian on 6 automotive MCU returns (ITC 2020, DOI 10.1109/ITC44778.2020.9325225). — [PDF](https://web.ece.ucsb.edu/~lip/publications/OutlierDectectionIEEE-ITC2020.pdf)
- Related: Tikkanen, Sumikawa et al., "Multivariate outlier modeling for capturing customer returns — How simple it can be." — [Semantic Scholar](https://www.semanticscholar.org/paper/Multivariate-outlier-modeling-for-capturing-returns-Tikkanen-Sumikawa/de9bae0521d2edfebd3a07eb753abc814957be60)
- Springer 2024 book chapter: AI framework for burn-in reduction using production machine signals, wafer maps, and pre-burn-in electrical tests. — [Springer](https://link.springer.com/chapter/10.1007/978-3-031-59361-1_5)
- Patent: identifying outliers following burn-in testing. — [US 8,010,310](https://image-ppubs.uspto.gov/dirsearch-public/print/downloadPdf/8010310)
- Several GitHub projects target this exact hackathon-style problem ("AI-driven anomaly detection in component burn-in screening"), which suggests it is a known problem statement. One (AI-ESS Guardian) describes lot-relative anomalies, 168h drift prediction, and PASS/REVIEW/REJECT output. — [GitHub DarshM6405](https://github.com/DarshM6405/AI-Driven-Anomaly-Detection-in-Semiconductor-Component-Burn-in-Screening); [GitHub Jo120424/AI-ESS-GUARDIAN](https://github.com/Jo120424/a-AI-ESS-GUARDIAN)

### Gaps
- I did not find openly accessible 2023–2026 Intel, Onsemi, or Infineon burn-in ML papers within the call budget. There are likely ITC/VTS papers behind the IEEE paywall.

---

## Recommended architecture (synthesis — inference, grounded in the above)

**Stage 0: Preprocess (per lot, per read-point).** Apply log transform to Iddq and leakage, and build drift features (Δ, log-ratio, slope, curvature, residual vs lot median trend). Apply static datasheet limits first as a hard fail.

**Stage 1: Univariate Dynamic PAT (explainable backbone).** For each raw and drift feature, compute robust z = (x − median_lot)/(IQR_lot/1.35) or 0.6745·(x−med)/MAD. Flag |z| > k with k ≈ 3.5–4.5, one-sided for leakage and Iddq. Output the per-feature z as the explanation.

**Stage 2: Multivariate robust Mahalanobis (MCD) per lot.** Catches correlation-breaking parts. Threshold is D² > χ²_{p,0.999} or a conformal threshold, and per-feature contribution is the explanation.

**Stage 3: ML ensemble.** IForest + ECOD (+ optional LOF/KNN) from PyOD, fit on the lot or on golden lots. Rank-normalize scores and take the max. Use SHAP/ECOD per-dimension tail probabilities for explanation.

**Stage 4 (if labels exist): LightGBM/XGBoost or XGBOD** with class weights, with threshold set for recall on validation data.

**Decision:** OR across stages (FN-averse). Each stage is threshold-calibrated with conformal p-values on known-good parts, so overkill is bounded (≤ Σα). Report recall on injected or labeled defects with a rule-of-three escape bound. Tiered output: REJECT (Stage 1 or 2 strong hit, or ≥ 2 stages hit), REVIEW (a single ML stage hit), PASS.

**Explainability report per flagged part:** which stage(s) fired, the top-3 features with robust z or contribution, a plot of the part's trajectory against the lot median ± 3 robust σ band, and the lot context (n, median, robust σ).

### Python library pointers
- `numpy`/`scipy.stats` (`median_abs_deviation(scale='normal')`, `iqr`, `chi2.ppf`) — robust z, fences, χ² thresholds.
- `sklearn.covariance.MinCovDet`, `EllipticEnvelope`. `sklearn.ensemble.IsolationForest`, `sklearn.neighbors.LocalOutlierFactor`, `sklearn.svm.OneClassSVM`, `sklearn.decomposition.PCA` (for T²/SPE).
- `pyod` (ECOD, COPOD, HBOS, IForest, LOF, KNN, AutoEncoder, DeepSVDD, XGBOD, SUOD, `pyod.models.combination`) — [PyOD docs](https://pyod.readthedocs.io/en/latest/).
- `isotree` or `eif` for Extended Isolation Forest.
- `lightgbm` / `xgboost` for supervised models; `shap` for explanations.
- ADBench code and datasets for benchmarking — [ADBench (arXiv 2206.09426)](https://arxiv.org/abs/2206.09426).
- Conformal p-values: a few lines of numpy (formula above); see also [arXiv 2605.13642](https://arxiv.org/pdf/2605.13642).
