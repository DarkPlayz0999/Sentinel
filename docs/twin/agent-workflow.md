# Agent workflow

Two LangGraph teams, both recorded in the existing `agent_workflows`,
`agent_steps`, `agent_findings` and `agent_events` tables and visible on the
Agent operations page.

```
phase 1 (existing)   data_quality ─► anomaly  ─┐
                                    forecast ─┴─► combine        (every screen)

investigation (new)  diagnostic ─► root_cause ─► qa_safety ─► report
                     trigger = sentinel_alert, runs ONLY when Sentinel flagged a board
```

| Agent | Calls | Output |
|---|---|---|
| Data Quality | `validate_dataset`, hash re-check | missing/invalid values, unit plausibility, duplicates, simulated/experimental |
| Anomaly | Module A (`src/module_a.py`) | L1/L2/L3 counts |
| Forecast | Module B (`src/pipeline.run_module_b`) | forecasts, R-301 early rejects |
| Diagnostic | `src/twin/diagnose.py` | per flagged board: fault-dictionary match, neighbours, electrical dependencies, IR hot spots, ambiguity group |
| Root cause | diagnostic output | ranked hypotheses with **evidence scores** |
| QA / Safety | Sentinel's persisted result, the frame, the run record | data sufficiency, engineering limits, model uncertainty, conflicting evidence, simulation validity |
| Report | all of the above | structured investigation report, `HUMAN-REVIEW-REQUIRED` |

## How the diagnostic agent localises

Sentinel says which **board** is abnormal and which **parameters** carried it.
The diagnostic agent builds a fault dictionary from the board model: for every
(component, fault) it simulates a nominal board through the soak with and
without the fault and records how each ATE drift and each part's temperature
rise change. It then compares that signature with the flagged board's observed
evidence, Sentinel's own lot-relative drift z-scores plus the IR camera's
lot-relative temperature rise, by cosine similarity.

`evidence score = 100 · max(0, cos)`. It is a similarity, **not a probability**,
and no field anywhere is labelled as one. Two faults with the same signature get
the same score. That is an **ambiguity group** (e.g. C001 leakage, C002 leakage,
U001 leakage and R001 drift all move only Iddq), and the agent says so and names
the bench test that would separate them.

## Isolation from ground truth

The investigation reads only the dataset Sentinel screened, Sentinel's
persisted results and the IR camera. `tests/test_twin_service.py` makes every
ground-truth accessor raise for the whole screen-and-investigate path.

No language model is used. Every sentence is assembled from computed numbers.
No agent releases or certifies a board; dispositions are recorded through
`POST /v1/simulations/{id}/boards/{serial}/decision` by a person.
