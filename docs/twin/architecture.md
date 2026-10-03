# Digital twin: architecture

The twin is a **measurement generator and a visualisation client** wrapped around
the existing Sentinel system. Sentinel stays the source of truth for screening,
ML inference, risk scoring, explainability, audit and agent decisions. Nothing in
the twin computes a verdict.

```
 web/src/app/console/lab        3D board (react-three-fiber), time controls, panels
 web/src/app/console/benchmark  campaigns, blind benchmark results
          │  HTTP + Server-Sent Events (one local API, documented at /docs)
          ▼
 backend/app/api/routes/simulation.py      /v1/simulations, /v1/experiments, /v1/twin
 backend/app/services/simulation_service.py   the closed loop, blind-mode gatekeeping
 backend/app/agents/investigation.py        diagnostic → root_cause → qa_safety → report
          │                   │
          │                   └── existing: agents/graph.py (data_quality → anomaly ∥ forecast → combine)
          │                                 ScreeningService → src/pipeline.py (Module A, Module B, fusion)
          ▼
 src/twin/   board · circuit (MNA + ngspice) · faults · engine (thermal, aging, ATE)
             diagnose · replace · benchmark · experiments
```

## Why the engine is where it is

| Choice | Reason |
|---|---|
| three.js in the existing Next.js app, not Unity or Unreal | Neither is installed; no second frontend, no inter-process bridge, WebGL already uses the GPU. The brief ranks engineering visualisation over cinematics. |
| A **lot** of boards, not one board | Sentinel scores a part against its own lot (median and 1.4826·MAD). At n = 1 Dynamic PAT is undefined. The 3D view shows one board; the statistics come from the same position across the lot. |
| Built-in MNA solver for the lot, ngspice as a cross-check | A 200-board lot at four read points is thousands of solves; ngspice is one process each. The same SPICE-syntax netlist feeds both solvers. |
| Measurements map to Sentinel's four parameters | Sentinel's contract is `Iddq_uA, Ileak_nA, Tpd_ns, Vol_mV` at 0/24/96/168 h. Every component fault reaches those four through a real circuit path (board.py docstring). |

## Endpoints

Reused, not duplicated: a simulated lot becomes an ordinary dataset
(`source = simulation`) and an ordinary screening run, so `/v1/screening/...`,
`/v1/agents/...` and the audit trail work on it unchanged.

| Method | Path | |
|---|---|---|
| GET | `/v1/twin/board` | board, fault catalogue, detectability, ngspice availability |
| POST | `/v1/simulations` | create (VISIBLE/BLIND, `scenario=sih_demo`, `?start=true`) |
| POST | `/v1/simulations/{id}/faults` | inject a fault before start |
| POST | `/v1/simulations/{id}/start` | burn-in as a background job (202 + `job_id`) |
| POST | `/v1/simulations/{id}/step` | advance one read point |
| POST | `/v1/simulations/{id}/screen` | measurements → Sentinel → agents |
| GET | `/v1/simulations/{id}` · `/boards` · `/components` · `/timeline` | state (truth withheld in BLIND) |
| GET | `/v1/simulations/{id}/events` | SSE progress stream |
| GET | `/v1/simulations/{id}/candidates` · POST `/replace` · GET `/comparison` | replacement loop |
| POST | `/v1/simulations/{id}/boards/{serial}/decision` | human disposition |
| POST | `/v1/simulations/{id}/reveal` | ground truth + benchmark, only after a prediction |
| GET | `/v1/simulations/{id}/audit` | complete trail |
| POST/GET | `/v1/experiments` | sweeps, Monte Carlo, OOD suite |

## Data model

Nine tables in `backend/app/models/database_models.py`, additive to the existing
schema: `simulation_runs, simulation_components, simulation_measurements,
simulation_faults, simulation_ground_truth, simulation_events,
simulation_predictions, simulation_replacements, simulation_experiments`. Every
row carries the simulation id, a timestamp, the twin software version and the
random seed; model version where a model was involved.

`simulation_measurements` holds **observed** values only. Truth lives in
`simulation_components` and `simulation_ground_truth`, and the service opens the
ground-truth repository only in `reveal()`.

## Performance

The engine is vectorised across boards: a 200-board lot through 168 h at a 3 h
step takes well under a second. The API never blocks on it: `start`, `screen`
and experiments run as background jobs, the browser follows `/events` over SSE
and polls as a fallback.
