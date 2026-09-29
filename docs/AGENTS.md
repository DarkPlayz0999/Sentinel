# Reliability Intelligence Agent Team

Phase 1 is implemented, tested and running. It adds no second application: the
agents live in `backend/app/agents/` inside the existing FastAPI service and call
the existing ML code.

## Flow

```
dataset ─► Data Quality ──valid──► Anomaly  (Module A) ─┐
                │                  Forecast (Module B) ─┴─► Combine ─► persisted run
                └──invalid──► Quarantine                      │
                                                   HUMAN-REVIEW-REQUIRED finding
```

| Agent | Calls (existing code) | Output contract |
|---|---|---|
| Data Quality | `validate_dataset`, SHA-256 re-check against upload, provenance | `DataQualityReport` |
| Anomaly | `build_features`, `module_a_scores`, `static_limit_flags` | `AnomalyReport` |
| Forecast | `src.pipeline.run_module_b` (active model artifact if registered) | `ForecastReport` |
| Combine | `src.pipeline.combine`, `ScreeningService.persist_result` | `CombineReport` |
| Quarantine | none: records why, and nothing downstream runs | findings |

`src.pipeline.screen()` was split into `run_module_b()` and `combine()` with no
behaviour change: `python -m src.report` produces byte-identical output before
and after the split. A test asserts that the agent run and a direct
`ScreeningService` run give the same verdict for every part.

## Guarantees and where they are enforced

- **Parallel A ∥ B.** LangGraph fans out after validation. Measured on 2,100
  parts, both agents start at 0.05 s; Module A takes 0.26 s and Module B takes
  24.5 s (fitted in-run, because no trained artifact is registered).
- **Idempotent.** The idempotency key is a hash of (dataset SHA, policy
  fingerprint, model artifact, pipeline/feature version). A duplicate returns
  the existing workflow. Only a FAILED workflow can be retried.
- **Checkpointed.** `SqliteSaver` writes to `var/agent_checkpoints.db`, with
  `thread_id = workflow_id`. `POST /v1/agents/workflows/{id}/resume` continues
  from the last completed agent. The test confirms Data Quality is not re-run.
- **Retries.** Transient I/O errors (`OSError`, `sqlite3.OperationalError`) get
  up to 3 attempts. Logic errors fail fast. Every attempt is an `agent_steps` row.
- **Timeouts.** Each agent has a time budget (`TIMEOUT_S` in `graph.py`). A
  timed-out thread cannot be killed in CPython, so it is abandoned and the
  workflow is marked FAILED.
- **Auth.** Mutating endpoints use the existing `X-API-Key` dependency, which
  applies when `SENTINEL_API_KEY` is set.
- **Audit.** Workflow submit, complete, quarantine and fail events go to the
  existing append-only `audit_events` table. Screening runs keep their own
  audit trail.
- **No LLM, no release.** No language model is used anywhere in phase 1.
  Combine persists ACCEPT/WATCH/REJECT and raises `HUMAN-REVIEW-REQUIRED`.
  Nothing certifies or releases a component.
- **Simulated vs experimental.** A dataset with `source=builtin` is marked
  `simulated`. An upload is marked `unknown`, never assumed `experimental`.

## API

| Method | Path | |
|---|---|---|
| POST | `/v1/agents/workflows?dataset_id=…[&sync=true]` | submit (202; `deduplicated` flag) |
| POST | `/v1/agents/workflows/{id}/resume` | resume a FAILED workflow |
| GET | `/v1/agents/workflows`, `/v1/agents/workflows/{id}` | list; detail with steps and findings |
| GET | `/v1/agents/status` | latest step of each agent, workflow counts |
| GET | `/v1/agents/events` | SSE stream; honours `Last-Event-ID`, `?since=`, `?follow=false` |

Tables: `agent_workflows`, `agent_steps`, `agent_findings`, and `agent_events`
(the SSE change feed, written in the same transaction as each state change).

## Run (no Docker)

```
uvicorn src.api:app --port 8000
cd web && npm run dev          # http://localhost:3000/console/agents
```

Upload a CSV at `/console/screen` or `POST /v1/datasets/upload`, then press
**Run workflow** on the Agent operations page. Tests:
`python -m pytest tests/test_agents.py`.

## Not built yet (next phases)

| Phase | Adds | Needs |
|---|---|---|
| 2 | Watchers for upload, new model version and failure events; Celery workers | Redis (`brew install redis`) |
| 3 | Diagnostic agent (NetworkX evidence graph), Safety/QA agent (deterministic hard-limit and evidence checks) | none |
| 4 | Report agent; an LLM that may only word existing findings | an API key |
| 5 | Postgres repositories, MLflow/DVC/Evidently drift, OpenTelemetry | Postgres is installed locally; the rest are pip installs |

ngspice circuit simulation has no code in this repo yet. Its watcher waits
until a simulator exists.
