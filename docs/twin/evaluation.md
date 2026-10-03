# Evaluation

The **blind benchmark** is the only method used to claim simulator-based
performance. The simulator knows the true component, fault, severity and onset;
Sentinel does not. The score is computed after the prediction.

All metrics come from `src/evaluate.py` (one scorer, one truth), called by
`src/twin/benchmark.score()`.

| Group | Reported |
|---|---|
| Classification | recall, precision, F1, F2, PR-AUC (on risk score), false-negative rate, false-positive rate, confusion matrix in counts |
| Reliability | recall at a 5 % overkill budget, detection read (earliest screen that flagged), localisation top-1 / top-3 |
| Forecasting | Module B MAE, RMSE, normalised MAE, upper-bound coverage, drift error; **only** from a forecaster that never saw the evaluated lots |
| Simulation | injected, detected, missed, incorrectly flagged, unobservable faults, recall per fault type |

**Plain accuracy is not reported** (CLAUDE.md rule 5): with ~6 % of boards faulty,
"all good" scores ~94 %. The brief listed accuracy; the rule wins.

Operating point, stated with every number: *flagged = WATCH or REJECT at 168 h;
REJECT band sized to the 5 % PDA budget per lot; overkill budget 5 % of healthy
boards.* REJECT-only figures are reported beside it.

## Campaigns

```
python -m src.twin.experiments --kind monte_carlo --seed 42 --runs 200
python -m src.twin.experiments --kind esr_sweep   --seed 42 --runs 36 --boards 150
python -m src.twin.experiments --kind ood         --seed 42 --runs 28 --boards 150
```

Each writes one CSV row per board (run seed, truth, prediction, diagnosis) and
a JSON summary to `var/experiments/`. The same campaigns run from
`/console/benchmark` or `POST /v1/experiments`.

* **Monte Carlo**: every catalogue fault; noise 1–2.5 %, chamber 115–135 °C,
  lot centring and spread drawn per lot; severity 0.2–1.2, onset 0–96 h.
* **ESR sweep**: C001 ESR target 0.2–2.0 Ω (the brief's lower bound of 0.05 Ω is
  below the 0.12 Ω nominal, so it is not a degradation) × soak 25/85/125 °C.
* **OOD suite**: in-distribution, higher temperature (150 °C), different lot
  distribution, higher tester noise (3.5 %), unseen fault severity (0.08–0.2,
  subtler than training), different component values, combined faults. Module B
  is trained on in-distribution lots only.

## Measured results

From the two commands above (seed 42, 150 boards per lot, 6 % faulty,
in `var/experiments/`):

| OOD scenario | Recall | Recall, observable faults | FPR | PR-AUC | Top-1 localisation |
|---|---|---|---|---|---|
| in distribution | 0.694 | 0.800 | 0.124 | 0.529 | 0.56 |
| higher temperature | 0.750 | 0.897 | 0.119 | 0.649 | 0.56 |
| different lot distribution | 0.667 | 0.733 | 0.121 | 0.622 | 0.54 |
| higher sensor noise | 0.444 | 0.519 | 0.137 | 0.432 | 0.56 |
| unseen fault severity | 0.278 | 0.320 | 0.151 | 0.115 | 0.30 |
| different component values | 0.528 | 0.731 | 0.129 | 0.460 | 0.68 |
| combined faults | 0.778 | 0.794 | 0.119 | 0.742 | 0.82 |

ESR sweep at 125 °C, recall by ESR target: 0.11 (0.2 Ω), 0.06 (0.4 Ω),
0.22 (0.8 Ω), 0.44 (1.2 Ω), 0.67 (1.6 Ω), 0.78 (2.0 Ω). At 25 °C recall stays at
the healthy-board flag rate (~0.15–0.22): the fault barely develops without heat.

What the numbers say, and what they do not:

* Recall is bounded by what the four observables can see. Subtle faults and a
  noisier tester are where it falls, consistent with rule 14: metrology, not
  the model, is the ceiling.
* The false-positive rate (~12–15 %) is the PDA-sized band policy, not noise in
  the detector. Precision reflects it.
* These are simulator results against the simulator's own physics. They do not
  demonstrate performance on flight hardware.
