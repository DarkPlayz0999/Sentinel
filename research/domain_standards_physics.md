# Burn-in / ESS of Hi-Rel Electronic Components: Standards, Delta Limits, Failure Physics, Statistical Screening

Research date: 2026-09-26. Primary documents actually read (full text extracted): ESCC 9000 Issue 10 (Feb 2018), ESCC 5000, ESCC Detail Specs 5106/023 and 9201/107, AEC-Q001 Rev D, AEC-Q002 Rev B, JPL Publication 08-5 (NASA "Microelectronics Reliability" handbook), ISRO URSC COTS presentation. MIL-STD-883 Method 1015/5004 were NOT directly readable (DLA/elsmar/navsea blocked or 404); values for those come from search snippets of the Method 1015.10 text and from secondary sources, and are flagged as such.

## 1. What burn-in / ESS are, typical conditions, and governing standards

### Takeaway
Burn-in is a 100% screen: parts are operated (biased) at elevated temperature, typically ~125 °C, for 160 h (MIL Class B / QML Q) or 240 h (Class S / QML V; ESCC power burn-in) to precipitate infant-mortality (latent) defects; electrical parameters are measured before and after, and parts are rejected both for exceeding absolute limits and for excessive drift (delta). Lots are rejected if the fraction of failures exceeds the PDA (typically 5%).

### Cited Findings
**MIL-STD-883 Method 1015 (burn-in test)**
- Method 1015 purpose: screen/eliminate marginal devices "with inherent defects or defects resulting from manufacturing aberrations which cause time and stress dependent failures"; performed for 160 h at a minimum of 125 °C. — [Tekmos MIL-STD-883 compliance](https://www.tekmos.com/mil-std-883-compliance)
- Burn-in per Method 1015 Condition D, 160 h at 125 °C case temperature (vendor /883 flow). — [Apex Analog M/883 Screening Program](https://apexanalog.com/resources/quality/M-8831.pdf)
- At 125 °C, minimum burn-in time is 240 h for Class level S and 160 h for Class level B; test conditions A–E apply; minimum re-burn-in time 24 h. — [MIL-STD-883H Method 1015.10 (search snippet)](https://ai-hmi.com/wp-content/uploads/2015/03/std883_1015.pdf)
- Method 1015.10 Table I (time–temperature regression): temperature may be increased and time reduced at the supplier's option; at 150 °C the minimum is 120 h (Class S) / 80 h (Class B); at 125 °C 240 h / 160 h. Table spans 100 °C to 250 °C. — [MIL-STD-883H Method 1015.10 (search snippet)](https://ai-hmi.com/wp-content/uploads/2015/03/std883_1015.pdf); [Scribd copy of Method 1015](https://www.scribd.com/document/324699946/Mil-Burn-in-Std883-1015)
- Test conditions referenced by ESCC: Method 1015 Condition A = steady-state reverse bias (used for HTRB); Conditions B, D or E = power burn-in (B = steady-state forward bias, D = parallel excitation, E = ring oscillator per the standard's naming). — [ESCC 9000 Issue 10, §8.15–8.16](https://escies.org/download/specdraftapppub?id=3659)

**MIL-PRF-38535 (QML) / MIL-STD-883 Method 5004 (screening flow)**
- JPL flight-part guidance: burn-in "160 hours for QML Class Q, 240 hours for QML Class V or QPL Class S"; burn-in applies "high voltage (usually the maximum rated operating voltage) and temperature (usually around 125 °C)"; three stages: Static I, Static II, and Dynamic burn-in (test vectors toggle circuit nodes). — [JPL Flight Part Verification, Sect. 4.3](https://parts.jpl.nasa.gov/asic/Sect.4.3.html)
- JPL defines PDA as "the percentage of the lot allowed to fail during burn-in without forcing the lot to be rejected", judged by failure-vs-time statistics that "should look something like the first half of the bathtub curve." — [JPL Sect. 4.3](https://parts.jpl.nasa.gov/asic/Sect.4.3.html)
- Method 5004: PDA of 5% based on failures from Group A Subgroup 1 tests after cooldown as the final electrical test. — [Apex Analog M/883 flow](https://apexanalog.com/resources/quality/M-8831.pdf); [eesemi Method 5004 summary](https://www.eesemi.com/milscreens.htm)
- Current MIL-STD-883 is published in parts (e.g., MIL-STD-883-5 w/ Change 1, 18 Nov 2021) by DLA Land & Maritime. — [DLA MIL-STD-883-5](https://landandmaritimeapps.dla.mil/Downloads/MilSpec/Docs/MIL-STD-883/std883-5.pdf)

**ESCC (ESA) 9000 – integrated circuits**
- Screening includes High Temperature Reverse Bias (HTRB) burn-in (MIL-STD-883 TM1015 Cond. A, duration per Detail Spec) with drift data points at 0 h and T(+24/−0) h; drift "shall be related to the initial measurement." — [ESCC 9000 Iss. 10 §8.15](https://escies.org/download/specdraftapppub?id=3659)
- Power burn-in: MIL-STD-883 TM1015 Cond. B, D or E; "Unless otherwise specified … a total Power Burn-in period of 240 (+24 −0) hours"; alternative time/temperature combinations per TM1015 permitted if max ratings not exceeded. — [ESCC 9000 §8.16](https://escies.org/download/specdraftapppub?id=3659)
- Operating life (qualification) tests: 2000 h (or 4000 h at Tamb = +125 °C in some cases) with end-points at 0, 1000 ±48, 2000 ±48 h, drift always related to 0 h. — [ESCC 9000](https://escies.org/download/specdraftapppub?id=3659)

**ESCC 5000 – discrete semiconductors**
- HTRB: bipolar transistors per MIL-STD-750 TM1039 Cond. A; unless otherwise specified duration: MOSFETs 48 h minimum, all other devices 12 h minimum; drift at 0 h and T(+24/−0) h. — [ESCC 5000](https://escies.org/download/specdraftapppub?id=153)
- Power burn-in: diodes/rectifiers MIL-STD-750 TM1038 Cond. B; bipolar TM1039 Cond. B; thyristors TM1040 Cond. B; duration 168 h minimum and 264 h maximum. — [ESCC 5000](https://escies.org/download/specdraftapppub?id=153)
- Lot rejection at 5% (see §2) and a separate rule: "If the cumulative defective devices exceed 25% of the lot, the lot shall be rejected" (in a specific test context of ESCC 5000). — [ESCC 5000](https://escies.org/download/specdraftapppub?id=153)

**NASA EEE-INST-002 / ISRO practice**
- ISRO (URSC, Dr. S.V. Sharma presentation on COTS): screening/qualification tests "are tailored based on NASA doc, EEE-INST-002 and its respective MIL documents"; screening (thermal cycling, burn-in etc.) on 100% of devices; qualification (radiation, life test, DPA, vibration) on samples; space-grade parts are "Hi-rel MIL/ESCC Qualified/Processed." — [ISRO URSC COTS EEE parts presentation](http://www.drsvsharma.com/wp-content/uploads/2023/09/USAGE-OF-COTS-EEE-PARTS-DrSVSharma-Deputy-Director-ISRO-URSC.pdf)
- ISRO active-part (IC) screening matrix: Visual Inspection → Temperature Cycling → Constant Acceleration → PIND → Seal Leak → Burn-in → "Pre/Post B.I. Electrical @ amb, High & Low" → "PDA < 5%"; PEMs additionally Radiography & C-SAM, stabilization bake; for advanced/RF parts burn-in is done at card level with PDA < 5%. Also references PEM-INST-001. Parts screened this way flew on Chandrayaan-1/2, GSAT-29, RISAT. — [ISRO URSC COTS presentation](http://www.drsvsharma.com/wp-content/uploads/2023/09/USAGE-OF-COTS-EEE-PARTS-DrSVSharma-Deputy-Director-ISRO-URSC.pdf)
- ISRO reliability standards (ISRO-PAX series, e.g., PAX-300 workmanship for electronic packages) are listed on the SAC industry portal. — [SAC ISRO Standards](https://www.sac.gov.in/SAC_Industry_Portal/rnqa_standards.html)
- The SIH problem appears to be ISRO SIH 26170 ("AI burn-in anomaly screening"); a public demo repo exists. — [GitHub mo0001/burnin-screening-site](https://github.com/mo0001/burnin-screening-site)

### Inferences
- Static burn-in (DC bias, inputs tied) mainly stresses junctions/oxides (good for ionic contamination, oxide defects, HTRB-type leakage); dynamic burn-in (clocked vectors) exercises logic nodes and interconnect currents, better for EM-, HCI- and bridging-related defects. The JPL three-stage (Static I, Static II, Dynamic) flow reflects this.
- For a synthetic dataset, a realistic record per part = serial number, lot/wafer ID, burn-in board/slot/oven position, readpoints at 0 h, intermediate (e.g., 48/96 h) and final (160/168/240 h), parameters measured at 25 °C and hot/cold.
- Implied activation energy of Method 1015 Table I: 125 °C→150 °C halves time (160→80 h), i.e. AF=2, giving an effective Ea ≈ 0.40 eV (my calculation: ln2 / [(1/398.15 − 1/423.15)/k]). The table is thus more conservative than a 0.7 eV Arrhenius (which would give AF≈3.3).

### Gaps
- Could not read primary MIL-STD-883 Method 1015/5004 text (download blocked); exact 96-hour post-burn-in test window, cool-down-under-bias rule, and full Table I rows are from memory/secondary sources and not cited here — verify from DLA copy.
- MIL-PRF-19500 (JANTX/JANTXV/JANS) HTRB/burn-in durations and JESD22-A108 (HTOL/HTRB/HTGB) text were not retrieved; HTGB (high-temperature gate bias, for MOSFET gate oxide) is covered in MIL-STD-750 / JESD22-A108 but no citation obtained.
- No public ISRO-specific burn-in duration/temperature or drift-limit document found beyond PDA < 5%.

## 2. Delta (drift) limits and PDA computation

### Takeaway
Delta limits compare each serialized part's post-burn-in reading with its own pre-burn-in reading (Δ = post − pre, "related to the initial measurement"). A part fails if |Δ| exceeds the Detail-Spec Δ **or** if the post value exceeds the absolute limit. Typical Δ values are absolute (e.g., ΔIDD ±30 nA, ΔVth ±0.3 V, ΔVF ±0.05 V) or "absolute or percent, whichever is greater" (e.g., ΔIR ±5 µA or ±100%). PDA = (drift failures + limit failures) / parts submitted to burn-in; lot fails if > 5% (rounded up).

### Cited Findings
- ESCC 9000 §6.2.2: "A component shall be counted as a parameter drift failure if the changes during High Temperature Reverse Bias Burn-in or during Power Burn-in are larger than the drift values (Δ) specified." §6.2.3: limit failure if parameters exceed Room-Temp or Hi/Lo-Temp limits. Parts failing limits before HTRB are rejected but not counted toward lot rejection. — [ESCC 9000 Iss. 10](https://escies.org/download/specdraftapppub?id=3659)
- ESCC 9000 §6.4.1.1 (PDA equivalent): lot of packaged components fails if failures (drift + limit) "exceeds 5% (rounded upwards to the nearest whole number) of the components submitted to High Temperature Reverse Bias Burn-in (or Power Burn-in if HTRB Burn-in is not being performed)". Groups separately identifiable within a lot are judged separately. After lot failure, 100% retest allowed but cumulative percent defective must not exceed 5%. — [ESCC 9000](https://escies.org/download/specdraftapppub?id=3659)
- ESCC 9000 §6.4.2 die-lot sample rules (packaged test sublot): n=11/18/25/38 allow 0/1/2/3 failures before HTRB; after HTRB 0/1/1/2 (and 0/1/2/3 at any time in Chart F3B). — [ESCC 9000](https://escies.org/download/specdraftapppub?id=3659)
- ESCC 8.14.1: all Parameter Drift Values "shall be recorded against serial numbers and the parameter drift calculated." — [ESCC 9000](https://escies.org/download/specdraftapppub?id=3659)
- ESCC 5000 uses the same 5%-of-submitted rule for discretes. — [ESCC 5000](https://escies.org/download/specdraftapppub?id=153)
- Example drift table, ESCC Detail Spec 5106/023 (Schottky rectifier, measured at 25 ±3 °C): Reverse current IR Δ = ±5 µA or ±100% "whichever is the greater referred to the initial value", absolute max 14 µA; Forward voltages VF1–VF5 Δ = ±0.05 V, absolute max 0.78–1.05 V. ΔVF limits for thermal resistance defined per lot per MIL-STD-750 TM3101. — [ESCC 5106/023](https://escies.org/download/specdraftapppub?id=4857)
- Example drift/end-point table, ESCC Detail Spec 9201/107 (CMOS IC, 22 ±3 °C, all inputs/outputs on all gates tested): IDD Δ ±30 nA (abs max 100 nA); IIL Δ ±20 nA (abs −50 nA); IIH Δ ±20 nA (abs 50 nA); VOL4 Δ ±26 mV (abs max 260 mV); VOH4 Δ ±0.2 V (abs min 3.98 V); VTHN Δ ±0.3 V (abs −0.45 to −1.45 V); VTHP Δ ±0.3 V (0.45 to 1.35 V). — [ESCC 9201/107](https://escies.org/download/specdraftapppub?id=1683)
- MIL-STD-883 5004: PDA 5% from Group A Subgroup 1 after cooldown. — [Apex Analog](https://apexanalog.com/resources/quality/M-8831.pdf)
- ISRO: "Pre/Post B.I. Electrical @ amb, High & Low … PDA < 5%". — [ISRO URSC](http://www.drsvsharma.com/wp-content/uploads/2023/09/USAGE-OF-COTS-EEE-PARTS-DrSVSharma-Deputy-Director-ISRO-URSC.pdf)

### Inferences
- Formulas for implementation:
  - Δp_i = p_i(T) − p_i(0); drift fail if |Δp_i| > Δ_spec, where for "whichever greater" rules Δ_spec = max(Δ_abs, k·|p_i(0)|) (e.g., max(5 µA, 1.00·IR0)).
  - Limit fail if p_i(T) ∉ [LSL, USL].
  - PDA = (N_drift_fail ∪ N_limit_fail) / N_submitted_to_BI; lot reject if failures > ceil(0.05·N_submitted).
- Delta limits are fixed spec numbers applied per part; they do not use population statistics, so a part with large-but-in-spec drift relative to its lot-mates passes. That gap is where ML/PAT-style relative anomaly detection (lot-normalized Δ, multivariate Δ, trajectory shape) adds value.
- Percent deltas (±10%, ±20%) are common in vendor/SMD drift tables, but I did not retrieve a primary citation for a specific ±10% rule — treat as illustrative.

### Gaps
- MIL-STD-883 Method 5004 exact class-S "3% functional PDA" rule and delta-parameter list (typically Table in the SMD) not verified from primary text.

## 3. Physics of latent defects and drift mechanisms

### Takeaway
Wear-out mechanisms (NBTI/PBTI, HCI, TDDB, EM) produce smooth, power-law drifts (t^n) of Vth/Idsat/delay/leakage; latent *defects* (weak oxide spots, near-shorts/bridges, contamination, voids) produce outlier behaviour: elevated or rising Iddq/leakage, sudden steps (soft→hard breakdown), or non-monotonic/unstable readings. Useful numeric anchors: NBTI n ≈ 0.16–0.3 (theory 0.25); HCI n ≈ 0.5–1; EM Black's n = 2 (nucleation) or 1 (growth), Ea 0.7–1.1 eV; TDDB Ea 0.6–0.9 eV, Weibull-distributed.

### Cited Findings
- NBTI: ΔVTH = A·t^n; "theoretical value of … n is 0.25 according to the solution of diffusion equations. Reported value of n is in the range from 0.2 to 0.3"; per Chakravarthi n ≈ 0.165, 0.25, 0.5 depending on reaction/diffusing species; Arrhenius Ea from 0.18 to 0.84 eV. — [JPL Publication 08-5, Microelectronics Reliability (NEPP)](https://nepp.nasa.gov/DocUploads/996E1F0E-3EB7-4309-9C9FB38BD53543FC/07-102%20White_JPL%20Microelectronics%20Reliability.pdf)
- NBTI n is technology dependent, typically 0.15–0.3; interface-state generation shows initial exponent ~0.5 decaying to steady 0.25 after ~1000 s; a small error in n shifts predicted lifetime by years. Hole trapping (recoverable) and interface-state (permanent) components are separable — recovery after stress removal matters for readout timing. — [TU Wien IuE: NBTI time exponent](https://www.iue.tuwien.ac.at/phd/entner/node26.html); [Effect of hole-trap distribution on NBTI exponent](https://www.researchgate.net/publication/224471942_Effect_of_Hole-Trap_Distribution_on_the_Power-Law_Time_Exponent_of_NBTI); [SiC MOSFET power-law exponent study, Micromachines 2025](https://pmc.ncbi.nlm.nih.gov/articles/PMC12734578/)
- NBTI in p-channel power U-MOSFETs shows degradation and recovery mechanisms (relevant to HTGB of power MOSFETs). — [ST: NBTI in p-channel power U-MOSFETs](https://www.st.com.cn/resource/en/conference_paper/2014_nbti_in_p-channel_power_u-mosfets_understanding_the_degradation_and_the_recovery_mechanisms.pdf)
- HCI: interface-trap generation ΔNit ∝ t^n; reaction-limited early stage n = 1, diffusion-limited later n = 0.5, overall n between 0.5 and 1 (default 0.65 in JPL FaRBS); HCI apparent Ea is *negative*, −0.1 to −0.2 eV (worse at low temperature). — [JPL Pub 08-5](https://nepp.nasa.gov/DocUploads/996E1F0E-3EB7-4309-9C9FB38BD53543FC/07-102%20White_JPL%20Microelectronics%20Reliability.pdf)
- Electromigration: Black's equation t50 = A·J^−n·exp(Ea/kT); generalized Black: n = 2 for nucleation-dominated failures (and wide lines), n = 1 for growth-dominated (narrow lines); EM Ea 0.7–1.1 eV; EM failure times fit lognormal (and Weibull comparably). — [JPL Pub 08-5](https://nepp.nasa.gov/DocUploads/996E1F0E-3EB7-4309-9C9FB38BD53543FC/07-102%20White_JPL%20Microelectronics%20Reliability.pdf)
- TDDB: E-model with field acceleration ~1.1 decade per MV/cm, Ea 0.6–0.9 eV; for ultrathin oxides a voltage power-law (tBD ∝ V^−n) fits better than exponential; breakdown statistics are Weibull, with Weibull slope β decreasing as oxide thins; area scaling via A = W×L. — [JPL Pub 08-5](https://nepp.nasa.gov/DocUploads/996E1F0E-3EB7-4309-9C9FB38BD53543FC/07-102%20White_JPL%20Microelectronics%20Reliability.pdf)
- Power-law degradation kinetics are the common empirical form across TDDB, HCI, BTI, EM. — [Thermodynamic Framework for Reliability Kinetics, Micromachines 2026](https://pmc.ncbi.nlm.nih.gov/articles/PMC13413635/)
- AEC-Q001 names the parametric tests most sensitive to latent defects: pin leakage, standby IDD/ICC, IDDQ, output leakage at 80% of breakdown, and over-voltage stress (which "forces failures in … MOS type devices … that have gate oxide and other related defects"). — [AEC-Q001 Rev D, App. 2](http://www.aecouncil.com/Documents/AEC_Q001_Rev_D.pdf)
- Delta-Iddq distinguishes early-fail from reliable chips at elevated temperature. — [Delta Iddq for testing reliability, IEEE VTS 2000](https://ieeexplore.ieee.org/abstract/document/843876/)

### Inferences (mechanism → signature map for feature engineering)
| Mechanism | Primary parameter | Expected drift shape |
|---|---|---|
| NBTI/PBTI | |Vth|↑ (PMOS/NMOS), Idsat↓, delay↑ | ΔV = A·t^n, n≈0.16–0.25; partial recovery after bias removal |
| HCI | Vth, gm, Idsat, delay | t^n, n≈0.5–1; worse at low T |
| Gate-oxide weak spot / TDDB | Iddq, gate leakage (IGSS) | flat then soft breakdown (noisy step up), then hard breakdown (large step) |
| Ionic/mobile-ion (Na+, K+) contamination | Vth, leakage, IR (HTRB) | saturating/logarithmic or exponential-approach drift with temperature/bias; can partially recover after unbiased bake |
| Bridging / resistive short | Iddq (vector-dependent), static IDD | elevated from t=0 (outlier), may step when bridge degrades |
| EM / voids | resistance, delay, sudden opens | slow resistance creep then abrupt jump (open) |
- Sudden jumps and non-monotonic trajectories should be treated as more suspicious than smooth power-law drift of the same magnitude.

### Gaps
- No primary citation retrieved for mobile-ion drift kinetics, PBTI exponents, or quantitative bridging-defect Iddq magnitudes; values above for those rows are qualitative.

## 4. Bathtub curve, Weibull β<1, burn-in time selection, Arrhenius

### Takeaway
Infant mortality is the decreasing-hazard region of the bathtub (Weibull β<1); burn-in consumes that region. Burn-in duration is chosen so that the acceleration factor × burn-in hours covers the infant-mortality period; with Ea=0.7 eV, 160 h at 125 °C ≈ 12,400 h (~1.4 years) at 55 °C.

### Cited Findings
- JPL: PDA should be judged against failure-vs-time data that "should look something like the first half of the bathtub curve". — [JPL Sect. 4.3](https://parts.jpl.nasa.gov/asic/Sect.4.3.html)
- The historical constant-failure-rate (exponential) model underestimated infant mortality and wear-out dominated failures; Weibull and similar distributions are recommended; Arrhenius AF = exp[(Ea/k)(1/T1 − 1/T2)]. — [JPL Pub 08-5](https://nepp.nasa.gov/DocUploads/996E1F0E-3EB7-4309-9C9FB38BD53543FC/07-102%20White_JPL%20Microelectronics%20Reliability.pdf)
- Weibull F(t) = 1 − exp[−(t/η)^β] used for oxide breakdown statistics, β = Weibull slope. — [JPL Pub 08-5](https://nepp.nasa.gov/DocUploads/996E1F0E-3EB7-4309-9C9FB38BD53543FC/07-102%20White_JPL%20Microelectronics%20Reliability.pdf)
- Telcordia SR-332 can incorporate burn-in and lab test data into failure-rate predictions. — [JPL Pub 08-5](https://nepp.nasa.gov/DocUploads/996E1F0E-3EB7-4309-9C9FB38BD53543FC/07-102%20White_JPL%20Microelectronics%20Reliability.pdf)
- MIL-STD-883 1015 Table I: 125 °C 160 h (B)/240 h (S); 150 °C 80 h/120 h. — [Method 1015.10](https://ai-hmi.com/wp-content/uploads/2015/03/std883_1015.pdf)

### Inferences (my calculations, k = 8.617×10⁻⁵ eV/K)
- Weibull hazard h(t) = (β/η)(t/η)^(β−1): β<1 → decreasing hazard (infant mortality), β=1 → constant, β>1 → wear-out.
- AF(125 °C vs 55 °C), T in K = 398.15 / 328.15:
  - Ea = 0.7 eV → AF ≈ 77.7 → 160 h ≈ 12,425 h (~1.4 yr); 240 h ≈ 18,640 h (~2.1 yr).
  - Ea = 1.0 eV → AF ≈ 501 → 160 h ≈ 80,000 h.
  - Ea = 0.45 eV → AF ≈ 16.4 → 160 h ≈ 2,630 h.
- Ea choice dominates the answer; mechanisms have different Ea (HCI negative), so a single Arrhenius AF is a simplification.
- Burn-in time selection logic: pick t_BI such that the fitted infant-mortality Weibull (β<1) cumulative fraction remaining after AF·t_BI is below target, while wear-out consumed (NBTI/EM) is negligible; practically standards fix 160/240 h and PDA monitors whether the lot is still in the steep infant region.

### Gaps
- No primary source retrieved giving a typical infant-mortality β value for ICs (commonly quoted 0.2–0.6 in literature, not verified here).

## 5. Industry statistical screening: PAT, SYL/SBL, Iddq, NNR, GDBN

### Takeaway
Automotive-grade outlier screening uses robust statistics: PAT limits = median ± 6·(IQR/1.35), static (≥6 lots × ≥30 parts) or dynamic (per lot/wafer); lot-level SYL/SBL = mean ∓ 3σ/4σ flag abnormal lots. Spatial methods (NNR, GDBN) and Iddq signatures reduce variance so latent-defect outliers stand out — directly transferable to per-lot burn-in delta data.

### Cited Findings
- AEC-Q001 Rev D: Robust Mean = Q2 (median); Robust Sigma = (Q3 − Q1)/1.35 (1.35 inexact for n<20); robust stats "exclude outliers by estimating the location and spread of only the main distribution of parts." — [AEC-Q001 Rev D §2.4](http://www.aecouncil.com/Documents/AEC_Q001_Rev_D.pdf)
- Static PAT: data from at least six lots that passed spec; at least 30 random parts per lot (wafer level: ≥5 die from different areas per wafer, ≥30 die per lot); Static PAT Limits = Robust Mean ± 6 Robust Sigma; for clearly non-normal data use other suitable means; review during first 6 months or 8 wafer lots (whichever first), then semi-annually; PAT limits must not exceed spec limits. — [AEC-Q001 Rev D §3.1.1](http://www.aecouncil.com/Documents/AEC_Q001_Rev_D.pdf)
- Dynamic PAT: same formula (Robust Mean ± 6 Robust Sigma) computed on the current lot/wafer's passing parts; preferred because reference population = parts under test, giving tighter limits without lot-to-lot variation; packaged-product variant uses first N units (e.g., N = 500 or 1000) to set lot-specific limits. — [AEC-Q001 Rev D §3.1.2](http://www.aecouncil.com/Documents/AEC_Q001_Rev_D.pdf)
- AEC-Q002 Rev B: from ≥6 lots (updated with at least last 8 lots, ~twice per year): SYL1 = Mean − 3σ, SBL1 = Mean + 3σ, SYL2 = Mean − 4σ, SBL2 = Mean + 4σ (on yield % and per-bin fail %); non-normal data → Weibull/Gamma/Poisson fit; lots beyond SYL1/SBL1 flagged for engineering review, beyond SYL2/SBL2 may be quarantined with root-cause records. — [AEC-Q002 Rev B](http://www.aecouncil.com/Documents/AEC_Q002_Rev_B1.pdf)
- PAT in practice / dynamic real-time PAT implementations. — [EDN: PAT finds and rejects outlier ICs](https://www.edn.com/part-average-testing-finds-and-rejects-outlier-ics/); [Pintail: Dynamic PAT in real time, SWTW 2005](https://www.swtest.org/swtw_library/2005proc/PDF/S08_03_Mickyray.pdf)
- NNR: data-driven neighbourhood around a die to estimate its expected measurement; outlier score is the residual; reduces variance of good/faulty IDDQ distributions. — [Daasch et al., Neighborhood selection for IDDQ outlier screening, IEEE D&T 2002](https://ieeexplore.ieee.org/document/1033795/); [Neighbor selection for variance reduction in IDDQ](https://www.researchgate.net/publication/3972528_Neighbor_selection_for_variance_reduction_in_IDDQ_and_other_parametric_data)
- NNR and nearest-current-ratio can miss absolute outliers in bad neighbourhoods; multiple IDDQ metrics (delta-IDDQ, current signature, ratios) combined improve identification. — [Use of Multiple IDDQ Test Metrics for Outlier Identification](https://www.researchgate.net/publication/4014272_Use_of_Multiple_IDDQ_Test_Metrics_for_Outlier_Identification); [IDDQ neighbor current ratios, J. Systems Architecture](https://www.sciencedirect.com/science/article/abs/pii/S1383762103001917)
- MAD-based outlier rejection on IDDQ evaluated for burn-in reduction. — [MAD outlier-rejection IDDQ for burn-in reduction](https://www.researchgate.net/publication/3953892_Evaluation_of_effectiveness_of_median_of_absolute_deviations_outlier_rejection-based_IDDQ_testing_for_burn-in_reduction)
- IDDQ current signature used for process-parameter estimation (Bayesian). — [Bayesian process parameter estimation via IDDQ signature](https://www.researchgate.net/publication/260730612_A_Bayesian-based_process_parameter_estimation_using_IDDQ_current_signature)

### Inferences (formulas to implement)
- PAT: L,U = median ± 6·(Q3−Q1)/1.35, clipped to [LSL, USL]. Apply to post-BI values AND to Δ values (Δ-PAT).
- MAD variant: σ̂ = 1.4826·median(|x − median|); robust z = (x − median)/σ̂.
- Delta-Iddq: ΔI_j = Iddq(v_j) − Iddq(v_{j−1}) across vectors, or ΔI = Iddq_post − Iddq_pre across burn-in; current signature = sorted Iddq across vectors, a defect shows a step.
- Current ratio: CR = max(Iddq)/min(Iddq) per die (scales out process variation).
- NNR: residual r_i = x_i − median(x_neighbors(i)); flag if |r_i| > median(r) + k·robust σ(r).
- GDBN: a passing die is flagged if ≥ m of its 8 (or 24) neighbours failed; on burn-in boards the analogous "neighbourhood" is lot/wafer/board/slot.
- For hackathon: lot-level PDA ≈ a SYL-type metric; per-part Δ-PAT + NNR on lot/wafer neighbourhood + trajectory-shape features (fitted n, jump size) cover both regulatory (Δ-limit/PDA) and statistical (outlier) layers.

### Gaps
- GDBN original paper not retrieved; formula above is standard practice, not sourced here.
- AEC-Q001 text extraction showed "Robust Mean – 6 Robust Sigma" (dash artifact); intended as ± per Figure 4 (two-sided limits).

## 6. Real-world escapes / lessons learned

### Takeaway
Public, well-documented latent-defect escape case studies with specific part numbers were not found in this session; NASA sources do record the general lesson that cutting burn-in/thermal-cycling increases infant-mortality risk on the pad or in flight.

### Cited Findings
- NASA lessons-learned: measures that reduce thermal cycling, burn-in, and thermal-vacuum testing for cost/schedule "may actually increase the risk of failure by allowing infant mortality failures to occur while on the launch pad"; unidentified latent failures undetected due to reduced testing may manifest in flight. — [NASA OSMA Lessons Learned](https://sma.nasa.gov/SignificantIncidents/lessons_learned.html); [NASA NESC Lessons Learned](https://www.nasa.gov/nesc/knowledge-products/lessons-learned/)
- Aerospace circuit failure data show an approximately exponential (constant-rate) system-level pattern once infant mortality is screened. — [JPL Pub 08-5](https://nepp.nasa.gov/DocUploads/996E1F0E-3EB7-4309-9C9FB38BD53543FC/07-102%20White_JPL%20Microelectronics%20Reliability.pdf)
- Pitfalls of predicted failure data (MIL-HDBK-217-type) for NASA programs. — [NASA NTRS 20160006974](https://ntrs.nasa.gov/api/citations/20160006974/downloads/20160006974.pdf)

### Inferences
- Well-known cases worth the team checking (not verified here): NASA/GSFC tin-whisker and ceramic-capacitor (BME/flex-crack) advisories, GIDEP alerts on counterfeit/remarked parts that failed burn-in, and MIL-PRF-38535 lots rejected for PDA. Use NASA Lessons Learned Information System (llis.nasa.gov) and NEPP presentations.

### Gaps
- No specific cited case (part, mission, drift signature) of a latent-defect escape found within budget; recommend searching NASA LLIS for "burn-in" and "PDA", and ESA Alert system (escies.org).
