# Explainability, Evaluation Metrics, and End-to-End Solution Design for AI-Driven Burn-In Anomaly Detection

Scope: XAI suited to QA inspectors, regulatory expectations, metric design (FN-catastrophic detection + MAE regression), demo architecture/stack, pitfalls, and judge differentiators. Research date: 2026-09-26.

Source-quality note: EASA/ECSS/MIL/ESCC sources are primary. The AEC-Q001 PDF could not be fetched (SSL error); PAT details below come from the search snippet of the aecouncil.com PDF and from secondary sources (Keysight, yieldWerx, GitHub repos). Items marked "(background knowledge)" are standard, widely documented facts I did not re-verify in this session; the report writer should treat them as lower confidence.

---

## 1. XAI methods suited to QA inspectors

### Takeaway
For a QA inspector, the most defensible explanation is a glass-box one: per-parameter robust z-scores relative to the lot (PAT-style "N sigma from the lot median"), plus drift-slope ratios, turned into deterministic reason codes. SHAP (TreeSHAP for Isolation Forest/LightGBM) and DIFFI should be the second layer ("which features drove the ML score"). Plots (lot distribution with the part highlighted, trajectory vs. lot envelope, SHAP waterfall) and an optional LLM narrative that only restates computed facts sit on top.

### Cited Findings
**Statistical / reason-code layer (glass-box by construction)**
- AEC-Q001 PAT defines the "robust mean" as the median of the test data. "Robust" means the statistic is insensitive to outliers. PAT is a statistical method for removing parts with abnormal characteristics (outliers). — [AEC-Q001 Rev D (search snippet)](http://www.aecouncil.com/Documents/AEC_Q001_Rev_D.pdf)
- Dynamic PAT limits are set from the current lot's own data. They can be tighter than static limits without rejecting good parts because they don't have to absorb lot-to-lot variation. PAT limits shall not exceed device specification limits. Static PAT needs data from at least 6 lots, with at least 30 parts sampled per lot. — [AEC-Q001 Rev D (search snippet)](http://www.aecouncil.com/Documents/AEC_Q001_Rev_D.pdf); [Keysight: Static to Dynamic PAT](https://www.keysight.com/us/en/assets/3121-1257/case-studies/Moving-from-Static-Limits-to-Dynamic-Part-Average-Test-PAT-Limits.pdf)
- Robust sigma = (Q3 − Q1)/1.349 (normalized IQR). An existing burn-in AI repo uses median + normalized IQR as its "Robust DPAT (AEC-Q001)" layer. — [space-grade-burnin-ai (GitHub)](https://github.com/aadityaexpress/space-grade-burnin-ai)
- An alternative lot-relative score is the modified z-score from MAD (Iglewicz–Hoaglin), with |Mz| > 3.5 as the outlier rule. A burn-in/aerospace IC repo uses it for Dynamic PAT "maverick" flagging. — [ASTRA-IC (GitHub)](https://github.com/jishasalariya/ASTRA-IC); rule origin: [NIST/SEMATECH e-Handbook, outliers](https://www.itl.nist.gov/div898/handbook/eda/section3/eda35h.htm) (background knowledge)
- Some classic (non-robust) PAT implementations reject parts outside [µ−4σ, µ+4σ], computed per wafer. The reported yield impact was ≤ 2%. — [EDN: PAT finds and rejects outlier ICs](https://www.edn.com/part-average-testing-finds-and-rejects-outlier-ics/)

**ML-attribution layer**
- DIFFI (Depth-based Isolation Forest Feature Importance) gives global and local feature importance for Isolation Forest from the depths at which features isolate anomalies. The authors report it is as effective as SHAP at much lower compute cost, fast enough for real-time use. It also supports unsupervised feature selection. Code: official repo plus an unofficial sklearn-compatible implementation. — [arXiv 2007.11117](https://arxiv.org/abs/2007.11117); [official repo](https://github.com/mattiacarletti/DIFFI); [britojr/diffi](https://github.com/britojr/diffi)
- SHAP's TreeExplainer now supports sklearn IsolationForest (`shap.TreeExplainer(iforest)`). Early versions did not. — [shap issue #237](https://github.com/slundberg/shap/issues/237); [shap issue #1917 (local SHAP on IF)](https://github.com/slundberg/shap/issues/1917)
- EBM (InterpretML's Explainable Boosting Machine) is a cyclic gradient-boosted GAM with automatic pairwise-interaction detection. Its accuracy is comparable to random forests and boosted trees, it gives exact explanations, and domain experts can edit it. — [InterpretML EBM docs](https://interpret.ml/docs/ebm.html); [interpretml/interpret](https://github.com/interpretml/interpret); [InterpretML whitepaper](https://www.microsoft.com/en-us/research/uploads/prod/2020/05/InterpretML-Whitepaper.pdf)
- Recent work continues to extend EBMs for interpretability. — [arXiv 2512.00528](https://arxiv.org/pdf/2512.00528)
- Existing burn-in repos present SHAP waterfall or force plots per component inside a "QA audit certificate". Content: verdict, failure-mode diagnosis (TDDB / in-spec lot outlier / gross defect), recommended action, and plain-English audit statements. — [space-grade-burnin-ai](https://github.com/aadityaexpress/space-grade-burnin-ai); [ASTRA-IC](https://github.com/jishasalariya/ASTRA-IC)
- Foundational references (background knowledge): SHAP [Lundberg & Lee 2017, arXiv 1705.07874](https://arxiv.org/abs/1705.07874); TreeSHAP [arXiv 1802.03888](https://arxiv.org/abs/1802.03888); LIME [arXiv 1602.04938](https://arxiv.org/abs/1602.04938); counterfactuals via DiCE [arXiv 1905.07697](https://arxiv.org/abs/1905.07697), [interpretml/DiCE](https://github.com/interpretml/DiCE); PyOD [yzhao062/pyod](https://github.com/yzhao062/pyod).

### Inferences
- Recommended explanation hierarchy, most to least inspector-friendly:
  1. **Reason codes (deterministic).** Examples: "R01: Iddq@24h = +6.2σ_robust above lot median (lot n=48)"; "R04: drift slope 0→24h = 3.1× lot P95"; "R07: predicted Iddq@168h = 41 µA [90% PI 37–45] > safety limit 30 µA". Each code maps 1:1 to a rule and a threshold. That is auditable and reproducible, which matches the traceability culture of MIL/ESCC delta-limit screening.
  2. **ML attribution.** TreeSHAP on IF/LightGBM, or DIFFI for IF, answers "which parameter/time-point drove the score". Always show it in the same units and space as the reason codes, so features should be lot-relative robust z's rather than raw values.
  3. **Counterfactual.** Example: "part would pass if Iddq@24h were ≤ 12.4 µA (lot median + kσ)". For threshold rules this is trivial to compute exactly, so DiCE isn't needed. Only use DiCE for the ML model.
  4. **Visuals.** (a) Lot histogram/strip plot per parameter with the part highlighted and the ±kσ_robust PAT fences. (b) Trajectory plot of the part (0/24/96/168h) over a lot fan chart (P5–P95 band, median), with the predicted 168h point and conformal interval. (c) SHAP waterfall. (d) Parameter-vs-parameter scatter (Iddq vs. leakage) with a robust Mahalanobis ellipse, which shows multivariate outliers that pass univariate checks.
  5. **LLM narrative (optional).** Generate text only from a JSON of computed facts (template or LLM constrained to those facts). Add a "no new numbers" check that verifies every number in the text appears in the facts JSON, to avoid hallucinated QA statements.
- LIME and KernelSHAP are unnecessary when models are tree-based (TreeSHAP is exact and fast). KernelSHAP only makes sense for a non-tree regressor (e.g., the GP used by ASTRA-IC).
- For Module B, a strong interpretability story: use a physics-shaped glass-box baseline, e.g. value(t) = a + b·t^n or a + b·log(t) fitted from 0h/24h, next to an EBM or LightGBM residual model. Show both. If they disagree, that disagreement is itself a reason code ("model uncertainty").

### Gaps
- No peer-reviewed user study found on which explanation format QA/MRB inspectors in semiconductor screening prefer. The recommendation above is inference.
- Exact AEC-Q001 static-PAT multiplier (commonly cited as ±6σ robust) and the IQR/1.35 constant could not be verified from the primary PDF (fetch failed).

---

## 2. Regulatory and industry expectations (aerospace/space) for explainability and human-in-the-loop

### Takeaway
Aerospace and space regulators treat current ML as assistance or human-AI teaming (EASA Level 1/2), which keeps a human in the decision. ESA's ECSS now has an ML qualification handbook (Nov 2024), and EASA's first binding-track proposal (NPA 2025-07, Nov 2025) turns trustworthiness, including explainability, into detailed specifications. Burn-in screening itself is governed by deterministic delta limits and lot PDA rules (MIL-PRF-38535, ESCC). The AI should therefore be framed as an assistant that proposes dispositions with traceable reasons for an MRB/QA sign-off.

### Cited Findings
- EASA AI Concept Paper Issue 2 was published 6 March 2024 ("Guidance for Level 1 & 2 machine learning applications"). Level 1 is human augmentation/assistance. Level 2 is human-AI teaming, where AI makes automatic decisions under human oversight. The paper deepens "learning assurance", "AI explainability" and "ethics-based assessment". — [EASA news](https://www.easa.europa.eu/en/newsroom-and-events/news/easa-publishes-artificial-intelligence-concept-paper-issue-2-guidance); [Concept Paper PDF](https://www.easa.europa.eu/sites/default/files/dfu/easa_concept_paper_guidance_for_level_1and2_machine_learning_applications_proposed_issue_02_feb2023.pdf); [document library](https://www.easa.europa.eu/en/document-library/general-publications/easa-artificial-intelligence-concept-paper-issue-2)
- EASA splits explainability into operational explainability (for end users) and development explainability (for stakeholders during development and post-operation). — [Unmanned Airspace summary of EASA concept paper](https://www.unmannedairspace.info/emerging-regulations/easa-issues-concept-paper-to-address-challenges-of-deploying-ai-in-aviation/)
- EASA NPA 2025-07 was published 10 Nov 2025 with a 3-month consultation. It proposes Detailed Specifications "DS.AI" on AI trustworthiness, aligned with the EU AI Act (Reg. 2024/1689) high-risk requirements. It covers Level 1 (assistance) and Level 2 (human-AI teaming) for supervised and unsupervised ML. It is Step 1 of RMT.0742, with a second NPA planned for 2026 for domain-specific deployment. — [EASA news](https://www.easa.europa.eu/en/newsroom-and-events/news/easas-first-regulatory-proposal-artificial-intelligence-aviation-now-open); [NPA 2025-07 page](https://www.easa.europa.eu/en/document-library/notices-of-proposed-amendment/npa-2025-07); [NPA 2025-07 (B) DS.AI PDF](https://www.easa.europa.eu/sites/default/files/dfu/NPA_2025-07__B__-_Proposed_detailed_specifications_and_AMC___GM_for_AI_trustworthiness__DS.AI__0.pdf)
- ESA/ECSS published ECSS-E-HB-40-02A "Space engineering – Machine learning handbook" on 15 Nov 2024. It covers data selection and qualification, training, and V&V of ML functions, initially for software criticality categories B, C, D. — [ECSS PDF](https://ecss.nl/wp-content/uploads/2024/12/ECSS-E-HB-40-02A(15November2024).pdf); [ESA AI STAR intro](https://www.aistar.esa.int/advancing-the-european-space-industry-with-ai-introduction-to-the-ecss-e-hb-40-02a-machine-learning-qualification-handbook)
- NASA: the Sept 2024 OMB M-24-10 compliance plan says NASA will use existing quality control and risk management processes to assure responsible AI use. NASA-HDBK-2203 (Software Engineering & Assurance Handbook) is the general assurance reference. NASA also has published "trusted AI framework" lessons for space applications. — [NASA compliance plan](https://www.nasa.gov/wp-content/uploads/2024/09/nasa-omb-compliance-plan-20240923.pdf); [NTRS 20230005782](https://ntrs.nasa.gov/citations/20230005782); [NESC: AI and software quality](https://www.nasa.gov/centers-and-facilities/nesc/understanding-risk-artificial-intelligence-and-improving-software-quality/)
- MIL-PRF-38535 (QML) rules:
  - Burn-in is minimum 160 h at 125 °C. It can be reduced from 240 h to 160 h after three consecutive lots from different wafer lots pass PDA.
  - PDA for class S/V is 5% (3% catastrophic).
  - For class-S-level devices, pre- and post-burn-in interim electricals are recorded, and delta calculations are done on 100% of devices.
  - Class V specifies delta parameters.
  — [MIL-PRF-38535M PDF](https://landandmaritimeapps.dla.mil/Downloads/MilSpec/Docs/MIL-PRF-38535/prf38535.pdf); [DLA EP study tables](https://landandmaritimeapps.dla.mil/Downloads/MilSpec/Docs/5962EPStudies/prf38535EPStudytables.pdf); [TI: QML flow](https://www.ti.com/lit/sboa143)
- ESCC Generic Specs:
  - A component is a parameter-drift failure if its change during HTRB/power burn-in exceeds the specified Δ values.
  - The lot fails if failures exceed 5% (rounded up) of the parts submitted to burn-in.
  - Parts that fail limits before burn-in are rejected and not counted toward PDA.
  — [ESCC 5000](https://escies.org/download/specdraftapppub?id=153); [ESCC 9000](https://escies.org/download/specdraftapppub?id=3659)

### Inferences
- Map the demo to EASA Level 1 (assistance). The AI flags parts and explains why, and a QA inspector/MRB dispositions them (accept / reject / retest / downgrade). Log every override with the inspector ID and a free-text reason. This gives the "human oversight" and "development explainability" (audit trail) that EASA and ECSS describe.
- Traceability expectations from MIL/ESCC practice translate to:
  - storing lot ID, serial number, test program/limits version, model version and hash, thresholds, and data hash per decision;
  - reproducible explanations (deterministic reason codes, fixed random seeds);
  - reporting the lot-level PDA alongside individual flags, e.g. "lot flagged rate 3.8% vs 5% PDA". A high AI-flag rate could itself trigger lot-level MRB review.
- Frame AI outlier flags as **in addition to** spec and delta-limit rejects, never replacing them. Hard spec limits and Δ-limits stay as a first-pass deterministic gate. This mirrors AEC-Q001's rule that PAT limits never loosen spec limits.

### Gaps
- No ISRO-specific public guidance on ML in component screening found. ISRO parts-screening documents appear to be non-public.
- Did not retrieve the exact explainability objective IDs (e.g., EXP-xx) from the EASA Concept Paper/NPA text.

---

## 3. Evaluation metric design (FN-catastrophic detection + 168h regression)

### Takeaway
Optimize and report recall first: FNR = 0 on validation, recall with bootstrap CI, and F2 or a cost-weighted loss (FN ≫ FP). Report PR-AUC rather than ROC-AUC because anomalies are rare. Choose thresholds on held-out lots so that every known defective part is caught, then report precision/FPR at that operating point. For Module B, report MAE (the official metric) plus MedAE and a per-parameter MAE. Avoid MAPE for near-zero leakage currents. Report conformal interval coverage.

### Cited Findings
- On imbalanced data, ROC plots can mislead because of an intuitive but wrong reading of specificity. Precision-recall plots evaluate the fraction of true positives among positive predictions and better predict future performance. — [Saito & Rehmsmeier 2015, PLoS ONE](https://journals.plos.org/plosone/article?id=10.1371%2Fjournal.pone.0118432)
- A counterpoint that re-examines AUROC vs. AUPRC under class imbalance argues AUPRC is not universally preferable. — [arXiv 2401.06091](https://arxiv.org/pdf/2401.06091)
- scikit-learn's `TunedThresholdClassifierCV` post-tunes the decision threshold via CV to minimize a user-defined business cost (unequal FP/FN costs) or maximize any scorer, e.g. `make_scorer(fbeta_score, beta=2)` or recall. The documented cost-sensitive example trades precision for much higher recall. — [sklearn threshold tuning guide](https://scikit-learn.org/stable/modules/classification_threshold.html); [TunedThresholdClassifierCV API](https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.TunedThresholdClassifierCV.html); [cost-sensitive example](https://scikit-learn.org/stable/auto_examples/model_selection/plot_cost_sensitive_learning.html)
- Existing burn-in repos: one uses a cost-sensitive threshold weighting FN 10× over FP and reports recall, a cost-penalized score, MAE, and chamber-hours saved. Another claims 100% latent-defect recall, 0% escape rate, MAE 0.214 µA, R² 0.9966 (on synthetic data). — [space-grade-burnin-ai](https://github.com/aadityaexpress/space-grade-burnin-ai); [ASTRA-IC](https://github.com/jishasalariya/ASTRA-IC)
- MAPIE gives model-agnostic conformal prediction intervals for any sklearn-compatible regressor, with marginal coverage guarantees. At 90% confidence the true value falls inside the interval for ≥90% of future observations. v1 changed the API. — [MAPIE docs](https://mapie.readthedocs.io/en/stable/content/conformal-prediction/); [MAPIE GitHub](https://github.com/scikit-learn-contrib/MAPIE)
- ASTRA-IC triggers an "early abort" if the upper 3σ bound of the 168h forecast exceeds a limit (30 µA). That is an uncertainty-aware decision rule. — [ASTRA-IC](https://github.com/jishasalariya/ASTRA-IC)

### Inferences
- **Detection metric pack:**
  - Primary: recall/sensitivity and FNR (= 1 − recall), with FN count reported explicitly.
  - Secondary: F2 (β=2 weights recall 4× in the harmonic mean) or F3, precision at the zero-FN threshold, FPR, and PR-AUC. Put ROC-AUC in a footnote.
  - Cost: C = 100·FN + 1·FP (state the ratio and show a sensitivity table for 10×/50×/100×/1000×).
  - Also report recall@FPR ≤ 1%/5%, and lot-level flag rate vs. the 5% PDA.
- **Zero-FN threshold procedure:**
  1. Split by lot (GroupKFold on lot_id).
  2. On each held-out fold, set the threshold at the minimum anomaly score among true defectives, minus a safety margin (e.g., the lowest positive score minus a fraction of the robust spread).
  3. Take the most conservative (lowest) threshold across folds.
  4. Report the resulting FP cost.
  
  With few positives, "0 FN on validation" is weak evidence. Report a one-sided 95% upper bound on FNR (rule of three: ≈ 3/n_pos when 0 of n_pos are missed) so judges see honest uncertainty. The rule of three is standard statistics (background knowledge), not taken from a cited source here.
- A union (OR) ensemble raises recall at an FP cost: flag if ANY of robust-z PAT, multivariate robust Mahalanobis, Isolation Forest, or Module B predicted-slope rule fires. Report the per-detector contribution: how many true defects each alone catches, and how many only it catches.
- **Regression metric pack:**
  - MAE (official), MedAE, per-parameter MAE in physical units. Use MAE normalized by lot robust σ if parameters mix units.
  - Conformal PI coverage and mean width.
  - MAPE only if values are well away from zero. Leakage/Iddq in nA/µA can be near zero, which blows up MAPE, so prefer sMAPE or MAE.
  - Train on log(Iddq) when the distribution is log-normal, but compute MAE in original units since that's how scoring works.
- **Module B flag metric:** treat "predicted slope > safety slope" as a classifier. Use the upper conformal bound of the predicted slope (not the point estimate) for the rejection rule to keep FNs low. Evaluate it against the true 168h slope (recall/precision), and report "burn-in hours saved" = 144 h × parts correctly rejected at 24h.
- Typical hackathon scoring (inferred from the problem statement): hidden test set → detection score (likely recall- or cost-weighted), MAE leaderboard, and a subjective explainability score from judges. Optimizing the recall-first operating point and presenting MAE honestly with intervals covers both.

### Gaps
- The official SIH/ISRO scoring formula (exact Fβ, cost ratio, or recall threshold) was not found publicly.
- No public dataset matching the exact 0/24/96/168h Iddq/leakage/delay schema was found. The repos use physics-informed synthetic simulators.

---

## 4. End-to-end architecture and tech stack for the demo

### Takeaway
A lean Python stack wins on time: pandas → robust lot statistics (NumPy/SciPy) → PyOD/sklearn Isolation Forest → LightGBM or EBM regressor with MAPIE conformal intervals → SHAP/DIFFI → Streamlit dashboard with a per-part PDF QA certificate and a CSV/JSONL audit log. Two public repos already implement close variants of this design with Streamlit. A differentiated entry needs lot-grouped validation, uncertainty-aware early rejection, and MRB workflow/audit features, not just the same stack.

### Cited Findings
- **space-grade-burnin-ai** implements:
  - a physics-informed simulator (0/24/96/168h; I_leak, I_ddq, t_pd; TDDB and electromigration modes);
  - Module A: robust DPAT (median, IQR/1.349) plus Isolation Forest on lot-relative z-scores;
  - Module B: LightGBM using Δ24−0, % drift, and lot-relative drift velocity, with a safety-slope check and 144 h saved per early reject;
  - Module C: QA certificates with SHAP waterfall and failure-mode diagnosis;
  - FastAPI (Vercel) plus Streamlit dashboards, and `evaluate.py` benchmarking static vs. dynamic screening.
  — [GitHub](https://github.com/aadityaexpress/space-grade-burnin-ai)
- **ASTRA-IC** implements:
  - MAD modified-z DPAT (>3.5);
  - Gaussian Process regression (24h→168h) with early abort on the upper 3σ bound;
  - SHAP KernelExplainer with plain-English audit statements;
  - a Streamlit dashboard with a KPI summary, scatter plots, component inspector, and PDF/CSV export;
  - MIL-STD-883 Method 1015 framing (claims ~85.7% chamber-time reduction).
  — [GitHub](https://github.com/jishasalariya/ASTRA-IC)
- Other reference dashboards:
  - semiconductor-test-analytics: Python/SQL, Streamlit, leakage-drift exploration — [GitHub](https://github.com/MeetG7823/semiconductor-test-analytics)
  - semiconductor-quality-intelligence: SPC, root-cause, drift-aware fail prediction on UCI SECOM, Streamlit — [GitHub](https://github.com/TheMobasshirRahman/semiconductor-quality-intelligence)
  - Commercial PAT/outlier tools: [yieldHUB outlier detection](https://www.yieldhub.com/outlier-detection), [yieldWerx PAT guide](https://yieldwerx.com/blog/ultimate-guide-to-outlier-detection-using-part-average-testing/)
- Libraries: MAPIE for conformal intervals ([docs](https://mapie.readthedocs.io/)); InterpretML EBM ([docs](https://interpret.ml/docs/ebm.html)); SHAP TreeExplainer supports IsolationForest ([issue #237](https://github.com/slundberg/shap/issues/237)); DIFFI ([repo](https://github.com/mattiacarletti/DIFFI)); sklearn TunedThresholdClassifierCV ([docs](https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.TunedThresholdClassifierCV.html)).

### Inferences
- **Pipeline:**
  1. **Ingest.** One CSV per lot. Validate schema with pandas: lot_id, serial, param, unit, t ∈ {0, 24, 96, 168}, value, retest flag. Normalize units (nA/µA/mA, ps/ns) to canonical SI. Reject rows with missing or negative physical values, or log them as data-quality flags.
  2. **Gate 0 (deterministic).** Datasheet spec limits and MIL/ESCC-style Δ-limits give hard rejects.
  3. **Module A.**
     - Per lot, per parameter, per time point: compute the robust z = (x − median)/(1.4826·MAD) or the IQR/1.349 version. Also compute drift Δ and slope z-scores.
     - Multivariate: robust Mahalanobis (sklearn MinCovDet) and an Isolation Forest on the robust-z feature vector.
     - Flag = OR of detectors, with the threshold tuned for 0 FN on grouped validation.
  4. **Module B.**
     - Features: v0, v24, Δ, log-ratio, lot median/σ of v24, lot-relative z of the slope.
     - Model: LightGBM or EBM. Use quantile or MAPIE CQR/split-conformal intervals.
     - Flag if the upper bound of the predicted slope (v168_hat − v0)/168 > safety slope, or if the predicted v168 upper bound exceeds the spec limit.
  5. **Explain.** Reason codes, TreeSHAP/DIFFI, counterfactual thresholds.
  6. **Report.** Per-part PDF QA certificate (reportlab or WeasyPrint, or matplotlib → PDF). Lot summary: flag rate vs. PDA, distribution plots, early-reject hours saved.
  7. **Audit log.** Append-only JSONL/SQLite with timestamp, input file hash, model version, thresholds, decision, reason codes, inspector disposition and override reason.
- **UI:** Streamlit is enough for a hackathon, with Plotly for interactive lot/trajectory plots. Suggested pages:
  - Upload lot
  - Lot overview: KPIs, flag table, PDA gauge
  - Part inspector: distribution, fan chart, SHAP waterfall, reason codes, MRB buttons
  - Model card / metrics: PR curve, confusion matrix at the chosen threshold, MAE, conformal coverage
  
  FastAPI+React only if the team already has it. Skipped for time.
- Keep models tiny and deterministic (fixed seeds) so a live demo reproduces the same numbers as the slides.

### Gaps
- Didn't verify whether either public repo reports lot-grouped validation or uses real rather than simulated data. Both appear to be synthetic.
- Didn't verify performance claims (e.g., ASTRA-IC 100% recall / R² 0.9966). They are self-reported on synthetic data.

---

## 5. Pitfalls

### Takeaway
The main technical traps:
- leakage across lots (random row splits);
- mean/std masking by the outliers themselves;
- unstable statistics in small lots;
- correlated parameters (Iddq and leakage) double-counting or hiding multivariate outliers;
- retest/duplicate rows;
- unit inconsistencies.

### Cited Findings
- PAT uses the median as the robust mean specifically because it resists outliers. Dynamic PAT uses only passing parts of the current lot to set limits. — [AEC-Q001 Rev D (snippet)](http://www.aecouncil.com/Documents/AEC_Q001_Rev_D.pdf); [Keysight](https://www.keysight.com/us/en/assets/3121-1257/case-studies/Moving-from-Static-Limits-to-Dynamic-Part-Average-Test-PAT-Limits.pdf)
- Static PAT requires ≥6 lots and ≥30 parts per lot to set robust baselines, which points to sample-size sensitivity. — [AEC-Q001 Rev D (snippet)](http://www.aecouncil.com/Documents/AEC_Q001_Rev_D.pdf)
- ESCC excludes parts that fail pre-burn-in limits from the PDA count, which is a precedent for treating pre-screen rejects separately. — [ESCC 5000](https://escies.org/download/specdraftapppub?id=153)
- The basic PAT variant uses non-robust µ±4σ per wafer. — [EDN](https://www.edn.com/part-average-testing-finds-and-rejects-outlier-ics/)

### Inferences
- **Lot leakage.** Always split with GroupKFold/GroupShuffleSplit by lot_id. Compute lot statistics only from the lot being scored (dynamic PAT), never from pooled train and test data. Also never use 96h/168h values as Module B features at inference, since only 0h/24h are available then.
- **Masking.** Mean and std are inflated by the defects themselves, so a 10σ part can look like 3σ. Use median/MAD or IQR, or iterate: fit, drop flagged parts, refit (AEC "passing parts only").
- **Small lots (n < ~30).** Robust σ is noisy. Options:
  - floor σ with a historical or pooled-lot prior (shrinkage, e.g. σ_used = max(σ_lot, σ_min) or an empirical-Bayes blend);
  - widen k using a t- or bootstrap-based correction;
  - fall back to static PAT limits;
  - show "low-confidence: lot n=12" in the reason code.
- **Correlated parameters.** Iddq and leakage move together. Univariate z's double-count, and some parts are outliers only jointly. Add robust Mahalanobis (MCD) or Isolation Forest, and explain with SHAP so the correlation structure is visible.
- **Zero MAD.** Quantized or identical readings give MAD = 0, so guard against division by zero.
- **Retests/duplicates.** Deduplicate on (serial, t, param). Keep the last valid reading, or the median if repeated, and log retests. Retests can hide intermittent defects, so treat a large retest delta as its own reason code.
- **Units.** Check µA vs. nA, ns vs. ps, and temperature-condition mismatches. Convert to SI at ingest, and verify with per-lot median sanity ranges.
- **Scale/distribution.** Leakage is often log-normal, so compute z-scores on log values (background knowledge).
- **Direction.** Most degradation is one-sided (Iddq/leakage up, delay up). Consider one-sided tests for the drift slope, but keep two-sided checks for level outliers, since an abnormally low Iddq can also indicate a defect such as an open circuit.

### Gaps
- No quantitative study found on the minimum lot size for reliable dynamic-PAT MAD estimates in burn-in data.

---

## 6. What differentiates a winning solution for judges (ISRO/SIH)

### Takeaway
Two public repos already ship the "robust DPAT + IF + LightGBM + SHAP + Streamlit" stack, so the pattern is table stakes. A winning entry should add:
- a demonstrably zero-escape operating point with honest uncertainty (lot-grouped validation, FNR upper bound);
- uncertainty-aware early rejection at 24h (conformal intervals) with quantified chamber-hours saved;
- physics-grounded features and failure-mode labels;
- inspector-grade reason codes, an MRB workflow, and an audit trail aligned to MIL-PRF-38535/ESCC and EASA Level-1 "AI assists, human decides".

### Cited Findings
- MIL-PRF-38535 burn-in baseline is ≥160 h at 125 °C, with 240 h reducible to 160 h after 3 passing lots. PDA is 5% for class S/V. — [MIL-PRF-38535M](https://landandmaritimeapps.dla.mil/Downloads/MilSpec/Docs/MIL-PRF-38535/prf38535.pdf); [DLA EP study tables](https://landandmaritimeapps.dla.mil/Downloads/MilSpec/Docs/5962EPStudies/prf38535EPStudytables.pdf)
- Existing entries already claim 144 h saved per early reject and ~85.7% chamber-time reduction (24h of 168h). — [space-grade-burnin-ai](https://github.com/aadityaexpress/space-grade-burnin-ai); [ASTRA-IC](https://github.com/jishasalariya/ASTRA-IC)
- EASA frames trustworthy ML as Level 1/2 with human oversight, with explainability split into operational and development views. — [EASA Concept Paper Issue 2](https://www.easa.europa.eu/en/newsroom-and-events/news/easa-publishes-artificial-intelligence-concept-paper-issue-2-guidance); [Unmanned Airspace summary](https://www.unmannedairspace.info/emerging-regulations/easa-issues-concept-paper-to-address-challenges-of-deploying-ai-in-aviation/)
- ECSS-E-HB-40-02A (Nov 2024) sets expectations for data qualification and V&V of ML in space software. — [ECSS PDF](https://ecss.nl/wp-content/uploads/2024/12/ECSS-E-HB-40-02A(15November2024).pdf)
- Conformal intervals (MAPIE) carry finite-sample coverage guarantees. — [MAPIE docs](https://mapie.readthedocs.io/en/stable/content/conformal-prediction/)

### Inferences
Candidate differentiators for the slides:
1. **"Zero-escape by construction."**
   - Layered OR-gate: spec and Δ-limits → robust PAT → multivariate → ML → forecast-upper-bound.
   - Threshold set on lot-held-out validation at 0 FN.
   - Show the FNR 95% upper bound and the cost curve (FN 100×).
2. **"Early rejection with guarantees."**
   - Reject at 24h only when the conformal upper bound of the 168h slope exceeds the safety slope.
   - Otherwise continue burn-in: a three-way decision of reject / continue / release-candidate.
   - Report hours saved and the fraction of parts that can be decided early.
3. **Physics grounding.**
   - Features and priors from degradation physics: power-law/log-time drift, TDDB → leakage/Iddq rise, and hot-carrier/NBTI → delay increase (background knowledge).
   - Label each flag with a hypothesized failure mode.
   - Fit a monotone or physics-shaped baseline and use ML only on residuals. This gives monotone constraints in LightGBM and inspectable shape functions in EBM.
4. **Inspector-grade explanation.** Reason codes with numbers, a one-page PDF certificate per part, lot fan chart, SHAP waterfall, and a counterfactual ("would pass if…").
5. **Governance.**
   - MRB disposition buttons and override logging.
   - Model card with versioning and hashes.
   - Mapping slide to MIL-PRF-38535 PDA/Δ practice, ESCC drift rules, EASA Level 1 and ECSS-E-HB-40-02A.
6. **Honesty on data.** Show lot-grouped CV, a static-vs-dynamic PAT baseline comparison, and an ablation (each detector's unique catches).
7. **Speed.** Sub-second scoring of a whole lot and a live CSV upload in the demo.

### Gaps
- No public record found of SIH/ISRO judging rubrics for this specific problem statement, or of past winners.
- Physics-of-failure mappings (TDDB/NBTI/HCI → parameter signatures) were not re-sourced in this session. A companion physics research note should provide citations.
