# Datasets for AI-Driven Anomaly Detection in Component Burn-In & Screening

Research date: 2026-09-26. URLs were checked with curl (HTTP status and Content-Length) and/or WebFetch. Kaggle pages return 404 to plain curl HEAD requests (bot/JS gating), so they are marked "verified via search index" rather than "fetched".

## Q1: Does the problem statement ship an official dataset?

### Takeaway
The problem is **SIH26170 (Smart India Hackathon 2026, ISRO)**. None of the public mirrors of the problem statement say a dataset is provided. Every public team repo I found (8+) uses synthetic data or NASA proxy data, and several say outright that they have no ISRO data. Assume **no official dataset**. You will have to generate synthetic data and label it clearly as synthetic.

### Cited Findings
- SIH26170, organisation ISRO, title "AI-Driven Anomaly Detection in Component Burn-In & Screening", 34 ideas submitted, Smart Automation theme — [zaidsayyed.in SIH 2026 listing](https://zaidsayyed.in/tools/sih-problem-statements/theme/smart-automation)
- PS text: ML on time-series parametric data (standby current, leakage currents, propagation delays) at 0h/24h/96h/168h. **Module A, Dynamic Outlier Detection**, uses the example "If a lot has an average leakage current of 10µA, a part showing 45µA is a massive anomaly" even though the datasheet max is 50µA. **Module B, Drift Predictor**: "takes Value_0h and Value_24h as inputs and forecasts Value_168h". Metrics: an Anomaly Detection Score that penalises false negatives heavily, MAE on the 168h prediction, and explainability. The mirror "does not specify whether datasets are provided" — [zaidsayyed.in SIH26170](https://zaidsayyed.in/tools/sih-problem-statements/sih26170)
- Full PS compilation PDF (unofficial mirror, not fetched) — [SIH_2026_All_PS.pdf](https://sih-2026-problem-statements.shaikrohit187.workers.dev/public/pdfs/SIH_2026_All_PS.pdf)
- The official portal responds (HTTP 200), but its PS pages are JS-rendered and I could not read dataset attachments from them — [sih.gov.in](https://www.sih.gov.in/sih2025PS)
- Team repos. All synthetic, none with ISRO data:
  - SPAD: "Mock data ... does not represent actual test data"; 12 mock components; Iddq spec 4.00 mA, I_leak 1.50 µA, t_pd 11.00 ns — [mohith-reddy18/SIH26-SPAD](https://github.com/mohith-reddy18/SIH26-SPAD)
  - AI-ESS Guardian: NASA Capacitor Electrical Stress data used as a real-data proxy (10V, up to 194h, 11 checkpoints). Synthetic set of 90 parts, 3 lots, 0/24/96/168h, leakage µA / Iddq mA / t_pd ns / chamber temp. Archetypes: healthy, mild drift, latent lot outlier, accelerating degradation, step jump, absolute spec violation — [Jo120424/a-AI-ESS-GUARDIAN](https://github.com/Jo120424/a-AI-ESS-GUARDIAN)
  - Team-404Does: synthetic `DS-SYN-2026-0142`, 1,000 parts × 43 samples (0–168h every 4h). Scenarios: drift, step, thermal coupling, equipment transient on one channel, lot/wafer shift, static-pass/dynamic-fail, missing telemetry — [Team-404Does repo](https://github.com/Team-404Does/AI-Driven-Anomaly-Detection-in-Component-Burn-In-Screening)
  - AstraNova: `raw_burnin_data.csv`, 40,000 rows = 10,000 parts × 4 checkpoints. Generation parameters not documented — [neelkene/AstraNova-](https://github.com/neelkene/AstraNova-)
  - space-grade-burnin-ai: "Physics-Informed Burn-In Data Generator", 0/24/96/168h across wafer lots, 125°C. Parameters are in `data_generator.py` but not in the README — [aadityaexpress/space-grade-burnin-ai](https://github.com/aadityaexpress/space-grade-burnin-ai)
  - Others (existence confirmed via search/HTTP 200 only): [koliankit/Space-Guard-AI-2.0-](https://github.com/koliankit/Space-Guard-AI-2.0-), [mo0001/burnin-screening-site](https://github.com/mo0001/burnin-screening-site), [demontric/BurnQ-SIH-170](https://github.com/demontric/BurnQ-SIH-170), [DarshM6405/...Burn-in-Screening](https://github.com/DarshM6405/AI-Driven-Anomaly-Detection-in-Semiconductor-Component-Burn-in-Screening), [akshat-0080/...](https://github.com/akshat-0080/AI-Driven-Anomaly-Detection-in-Component-Burn-In-Screening), [Chandrika1908/BurnGuard_AI_Demo](https://github.com/Chandrika1908/BurnGuard_AI_Demo), [bhattacharyaanika21-design/burnin-qa-dashboard](https://github.com/bhattacharyaanika21-design/burnin-qa-dashboard)

### Inferences
- The PS numbers (lot mean 10 µA, anomaly 45 µA, datasheet max 50 µA, checkpoints 0/24/96/168h) are the de facto spec for any synthetic set. Base the generator on them.
- A hybrid of synthetic data (exact schema, labelled) plus one real degradation dataset (NASA MOSFET or capacitor) as a "real physics" sanity check is what competing teams do. It is also the most defensible story for judges.

### Gaps
- I could not confirm whether the official SIH portal PS page has an attached sample file, because the page is JS-rendered. Check it manually at sih.gov.in (log in and open the SIH26170 detail page), or ask the ISRO SPOC.
- I found no DRDO/BEL/other hackathon with the same title that ships data.

## Q2: Which real public datasets exist, and how well do they map to the 0/24/96/168h burn-in structure?

### Takeaway
No public dataset gives per-unit Iddq, leakage or delay at burn-in checkpoints across manufacturing lots. The closest real data is the **NASA PCoE power-device aging sets** (MOSFET, IGBT, capacitor). They are real time-series degradation of electronic components under thermal or electrical stress, but they cover only a few to a few dozen units, with continuous or irregular sampling rather than lots of thousands. SECOM, WM-811K and Bosch are production-test data. They are useful for outlier-detection method development only: they have no time axis at burn-in checkpoints.

### Cited Findings

| # | Dataset | Verified URL | Size / format | Units & fields | License | Fit to 0/24/96/168h |
|---|---|---|---|---|---|---|
| 1 | NASA PCoE **MOSFET Thermal Overstress Aging** (#13) | https://phm-datasets.s3.amazonaws.com/NASA/13.+MOSFET+Thermal+Overstress+Aging.zip (HTTP 200, 7.85 GB zip) | MATLAB .mat | IRF520Npbf TO-220 run-to-failure under thermal/power cycling. The failure precursor is a rise in ON-resistance from die-attach degradation. 7 aging runs are described in the related paper | NASA open data (public, cite Celaya et al.) | **Best real proxy for drift trajectories.** Resample ΔRds(on) at relative times to mimic 4 checkpoints and treat each device as a "part". Too few units to model lots |
| 2 | NASA PCoE **IGBT Accelerated Aging** (#8) | https://phm-datasets.s3.amazonaws.com/NASA/8.+IGBT+Accelerated+Aging.zip (HTTP 200, 240 MB); Kaggle mirror https://www.kaggle.com/datasets/vignesh9147/igbt-accelerated-aging-data-set (search-index only) | .mat | 6 devices (1 DC gate bias, 5 square-wave gate bias). Gate voltage, V_CE, I_C, some high-speed transients | NASA open data | Real degradation curves (V_CE(on), latch-up). Only 6 units, so use it only to validate drift-shape priors |
| 3 | NASA PCoE **Capacitor Electrical Stress** (#12) | https://phm-datasets.s3.amazonaws.com/NASA/12.+Capacitor+Electrical+Stress.zip (HTTP 200, 5.04 GB) | .mat | Capacitors at 10V/12V/14V, EIS plus charge/discharge signals. The AI-ESS Guardian repo reports 10V runs up to 194h over 11 inspection checkpoints | NASA open data | **Closest time scale (~0–194h, discrete checkpoints).** Interpolate capacitance/ESR to 0/24/96/168h. The three stress levels give "lots", and 10V vs 14V gives healthy vs accelerated drift |
| 4 | NASA Capacitor Electrical Stress-2 (#14) | listed on the NASA repo page as **currently unavailable** (contact christopher.a.teubert@nasa.gov) | — | 10V stress | — | Not usable |
| 5 | NASA PCoE repository index | https://www.nasa.gov/intelligent-systems-division/discovery-and-systems-health/pcoe/pcoe-data-set-repository/ ; mirror https://data.phmsociety.org/nasa/ (HTTP 200) | — | Also has battery, turbofan (C-MAPSS), etc. | — | Batteries and turbofans are not component burn-in, so they are out of scope |
| 6 | **UCI SECOM** | https://archive.ics.uci.edu/dataset/179/secom (HTTP 200); zip https://archive.ics.uci.edu/static/public/179/secom.zip (HTTP 200) | space-separated text, 5.1 MB | 1,567 runs × 591 anonymised sensor features, pass/fail label (104 fails), timestamps, NaNs | CC BY 4.0 | No checkpoints. Use to benchmark Module A detectors (Isolation Forest, robust z / MAD) on real, messy, imbalanced fab data |
| 7 | **WM-811K (LSWMD)** | https://www.kaggle.com/datasets/qingyi/wm811k-wafer-map (search-index only; free Kaggle login) | 157 MB zip → LSWMD.pkl (~2.1 GB, legacy py2 pickle) | 811,457 wafer maps, 172,950 labelled into 9 pattern classes, ~85% "none" | Kaggle page terms (originally MIR Lab, NTU) | Spatial, not temporal. Only relevant for adding wafer/lot spatial context (e.g. "part near a failing cluster") |
| 8 | **Bosch Production Line Performance** (Kaggle competition) | https://www.kaggle.com/c/bosch-production-line-performance (search-index only; needs competition-rules acceptance) | large CSVs (numeric/categorical/date) | Anonymised station measurements per part, extreme imbalance of failures | Competition rules (non-commercial) | Not electronic burn-in. Only useful as a rare-failure imbalance benchmark |
| 9 | Kaggle "Semiconductor Sensor Data for Predictive Quality" | https://www.kaggle.com/datasets/programmer3/semiconductor-sensor-data-for-predictive-quality (search-index only) | CSV | Not inspected | unknown | Likely synthetic. Low value |

- Source for the NASA dataset descriptions, download links and citations (Celaya, Wysocki, Goebel 2009 for IGBT; Celaya, Saxena, Saha, Goebel for MOSFET; Renwick, Kulkarni, Celaya for capacitors) — [NASA PCoE repository](https://www.nasa.gov/intelligent-systems-division/discovery-and-systems-health/pcoe/pcoe-data-set-repository/)
- MOSFET dataset physics (IRF520Npbf, die-attach degradation, Rds(on) as precursor, 7 aging runs) — [Celaya et al., RAMS 2012](https://c3.ndc.nasa.gov/dashlink/static/media/publication/RAMS-12_MOSFET_Final.pdf); [NTRS 20140010629](https://ntrs.nasa.gov/citations/20140010629)
- IGBT dataset catalogue entry — [data.nasa.gov](https://data.nasa.gov/dataset/igbt-accelerated-aging-data-set)
- SECOM facts and license — [UCI](https://archive.ics.uci.edu/dataset/179/secom)
- WM-811K facts — [Kaggle](https://www.kaggle.com/datasets/qingyi/wm811k-wafer-map); [pqtrng/wm811k-defect-detection](https://github.com/pqtrng/wm811k-defect-detection)
- Survey of public degradation datasets for PHM (Mauthe et al., rev. Feb 2026), useful for finding more candidates — [arXiv 2403.13694](https://arxiv.org/abs/2403.13694)
- SiC MOSFET HTGB/HTRB Vth-drift studies publish results in papers, not downloadable data. Example: 650V SiC planar MOSFET, HTGB ~15% variation in ΔVth vs ~4% for HTRB — [Materials 17(8):1908 / PMC11051854](https://pmc.ncbi.nlm.nih.gov/articles/PMC11051854/)
- IEEE DataPort "Degradation state instance" (Zebin Jiang, 2022) needs a subscription. Its content relevance is unverified — [IEEE DataPort](https://ieee-dataport.org/documents/degradation-state-instance)
- LED LM-80 data (4,831 samples × 10,000 h) is used in a 2025 ACM TIST paper. I found no public download — [ACM TIST 10.1145/3776556](https://dl.acm.org/doi/10.1145/3776556)

### Inferences
- **Recommended real-data usage:** use NASA Capacitor #12 (10V vs 14V) or MOSFET #13 to fit healthy and accelerating drift *shapes* (power-law exponent, onset time). Then plug those shapes into the synthetic generator below. That is how to justify the synthetic set as "physics-informed" to judges.
- To adapt NASA data to the schema, set `part_id` = device, `lot_id` = stress level or run, and take the parameter value (Rds(on), V_CE(on), capacitance or ESR) at the samples nearest to 0/24/96/168 h of aging time (or at normalised fractions of life 0, 1/7, 4/7, 1). The label is "anomalous" if the device fails early or deviates from its cohort.
- SECOM is the only large real multivariate pass/fail semiconductor set with a clean license (CC BY 4.0). It is good for stress-testing Module A under missing values and imbalance.

### Gaps
- No public dataset of Iddq, HTOL or burn-in parametric readouts at checkpoints exists that I could find. Such data is proprietary (fabs/OSATs).
- No public ring-oscillator aging (NBTI/HCI) raw dataset was found. Only figures inside papers.
- I did not fetch the actual contents of the NASA zips because they are 0.24–7.8 GB. The exact field names inside the .mat files are unverified.
- Kaggle URLs are confirmed only through the search index (curl gets 404 from bot gating).
- ResearchGate pages (MAD-based Iddq burn-in reduction paper) returned 403. Numbers from that paper are unverified.

## Q3: How to generate a realistic synthetic burn-in dataset

### Takeaway
Build it from the PS constants (lot mean ~10 µA, datasheet limit 50 µA, 0/24/96/168h, 125°C). Draw the baseline from a lognormal with lot-to-lot shifts, apply a small power-law drift to healthy parts, and inject 1–5% defects of four types. The defects that matter most are **in-spec but lot-relative outliers** and **accelerating latent drift**. Published industry work confirms statistical outlier screening (MAD, Delta-Iddq, NNR) is the established baseline to beat.

### Cited Findings
- Industrial precedent: LSI Logic, 0.18 µm, 24-hour burn-in on 14 lots (60,105 die). Statistical post-processing of wafer test data caught 168 of 171 burn-in failures (98.2%). Intel 90 nm cut burn-in time by >90% with adaptive bucketing. Delta-Iddq and Nearest Neighbor Residual (NNR) are the standard Iddq outlier modules — [SemiEngineering, "Using Analytics To Reduce Burn-in"](https://semiengineering.com/using-analytics-to-reduce-burn-in/)
- MAD-based Iddq outlier rejection has been evaluated for burn-in reduction against delta-Iddq and current signatures (IEEE paper, abstract only; full text 403) — [ResearchGate 3953892](https://www.researchgate.net/publication/3953892_Evaluation_of_effectiveness_of_median_of_absolute_deviations_outlier_rejection-based_IDDQ_testing_for_burn-in_reduction)
- SRC burn-in reduction / outlier screening poster (PCA on multiple analog measurements) — [SRC 2008 TEA poster](https://www.src.org/award/tech-excellence/2008/tea-poster.pdf)
- AI framework for burn-in reduction in semiconductor manufacturing (Springer 2024) — [Springer chapter](https://link.springer.com/chapter/10.1007/978-3-031-59361-1_5)
- Defect archetypes already used by peer SIH teams: healthy, mild drift, latent lot outlier, accelerating degradation, step jump, spec violation ([AI-ESS Guardian](https://github.com/Jo120424/a-AI-ESS-GUARDIAN)). Also thermal coupling, equipment/channel transient, lot/wafer shift, missing telemetry ([Team-404Does](https://github.com/Team-404Does/AI-Driven-Anomaly-Detection-in-Component-Burn-In-Screening))
- Real degradation physics to borrow drift shapes from: Rds(on) rise from die-attach degradation in power MOSFETs ([Celaya RAMS 2012](https://c3.ndc.nasa.gov/dashlink/static/media/publication/RAMS-12_MOSFET_Final.pdf)); ΔVth shift under HTGB in SiC MOSFETs ([PMC11051854](https://pmc.ncbi.nlm.nih.gov/articles/PMC11051854/))

### Inferences

The following recipe is a design proposal. The numbers are engineering choices anchored to the PS where noted, not values from a paper. No published paper that I found gives an open parameter set for simulated Iddq burn-in trajectories.

**Schema (long format, one row per part × checkpoint; also emit a wide table):**
`part_id, lot_id, wafer_id, x, y, board_id, channel_id, param (iddq_uA | ileak_uA | tpd_ns), t_h (0,24,96,168), temp_C (125), value, label (0/1), defect_type`
Wide format for Module B: `Iddq_0h, Iddq_24h, Iddq_96h, Iddq_168h, ...`

**Population**
- 6–10 lots × 500–5,000 parts per lot, for about 20k parts in total.
- Iddq baseline: `log(I0) ~ N(log(10 µA) + lot_shift, σ=0.25)`, with `lot_shift ~ N(0, 0.15)`. This means lot medians of about 8.6–11.6 µA (PS anchor: lot mean 10 µA). Optional wafer effect `N(0, 0.05)` plus a radial term.
- Leakage: similar lognormal, around 1 µA scale. t_pd: normal around 10 ns, σ=2%. Correlate the three through a shared latent "process corner" z (ρ≈0.5) so multivariate detectors have something to learn.
- Datasheet limit: Iddq 50 µA (from the PS). Choose limits for the others so that more than 99.9% of healthy parts pass.

**Healthy drift (power law, typical of BTI/diffusion aging)**
`I(t) = I0 · (1 + A · (t/168)^n)`, with `A ~ LogNormal(log 0.03, 0.5)` (about 3% median drift by 168h) and `n ~ U(0.2, 0.5)`.

**Measurement noise:** multiplicative `N(0, 1%)` per reading, plus an optional per-channel offset `N(0, 0.5%)`.

**Defects (total prevalence 1–5%, default 2%; make it configurable)**

| Type | Share of defects | Model | Why it matters |
|---|---|---|---|
| Latent accelerating drift | 40% | `I0 · (1 + A·(t/168)^n + B·exp(k·(t−t_on))⁺)`, `t_on ~ U(0,96)`, reaching 2–4× I0 at 168h but mostly **still < 50 µA** | Core target for Module B: 0h/24h look nearly normal, 168h diverges |
| Step jump | 20% | at `t_s ∈ {24,96,168}`, multiply by `U(1.5, 3)` | Sudden defect activation, e.g. gate-oxide soft breakdown |
| Early lot-relative outlier | 25% | `I0` drawn at lot median × `U(3, 4.5)` (e.g. 30–45 µA), **in-spec** | Exactly the PS example (45 µA in a 10 µA lot). Tests Module A |
| High-noise / intermittent | 10% | noise σ ×5–10, or random spikes | Contact/leak intermittents. Tests robustness |
| Hard fail | 5% | exceeds 50 µA by 168h | Sanity class: static limits catch these |

- Add confounders with no label change: one faulty test channel with an offset on every part it touches, plus one lot shifted +20%. These teach the model to use lot-relative features and not flag whole lots.
- Add about 1% missing readings.
- **Splits:** hold out whole lots for test, so no lot leaks into training. Keep the class imbalance, and report recall at a fixed false-positive rate, since the PS penalises false negatives.
- **Features the recipe supports:** robust z / MAD within lot at each checkpoint, ratios (I24/I0), fitted power-law exponent, and residual versus the lot-median trajectory. Module B target: `Iddq_168h` from `(Iddq_0h, Iddq_24h, lot stats)`.
- Minimal generator sketch (numpy only):
```python
import numpy as np
rng=np.random.default_rng(0); T=np.array([0,24,96,168])
def lot(n,lot_mu):
    I0=np.exp(rng.normal(np.log(10)+lot_mu,0.25,n))
    A=np.exp(rng.normal(np.log(.03),.5,n)); p=rng.uniform(.2,.5,n)
    X=I0[:,None]*(1+A[:,None]*(T/168)**p[:,None]); y=np.zeros(n,int)
    d=rng.random(n)<0.02; idx=np.where(d)[0]; y[idx]=1
    for i in idx:
        k=rng.choice(4,p=[.45,.2,.25,.1])
        if k==0: ton=rng.uniform(0,96); X[i]*=1+0.02*np.expm1(np.clip(T-ton,0,None)/40)
        elif k==1: ts=rng.choice([24,96,168]); X[i,T>=ts]*=rng.uniform(1.5,3)
        elif k==2: X[i]*=rng.uniform(3,4.5)
        else: X[i]*=1+rng.normal(0,.08,4)
    return X*(1+rng.normal(0,.01,X.shape)), y
```
  Tune the latent-drift rate (`/40`, `0.02`) so that most latent defects stay under 50 µA at 168h. Check the fraction in a unit test.

### Gaps
- I found no peer-reviewed paper that publishes a simulation parameter set specifically for Iddq trajectories at 0/24/96/168h. The parameters above are my proposal and should be presented as assumptions.
- Real Iddq values vary by orders of magnitude between technologies (nA for old CMOS, mA for advanced nodes; the SPAD repo uses mA). The µA scale here follows the PS example only.
- Real latent-defect prevalence after burn-in (DPPM) for space-grade parts was not found in a citable source. The 1–5% here is deliberately inflated for ML training and should be stated as such.
