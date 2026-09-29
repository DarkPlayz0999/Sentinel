# SENTINEL backend service

The service layer around the ML core. `src/` holds the science and its
non-negotiable rules; `backend/` adds ingestion, validation, persistence, jobs,
audit and the HTTP API.

```
backend/app  ──imports──▶  src/   (features, module_a, module_b,
                                   fusion, explain, evaluate, pipeline)
```

Never the other way round. `src/` stays runnable with no database, no config
and no web server, which is what the test suite and the reproducibility story
depend on.

---

## Run it

```bash
# once: create the database, train and register the forecaster
python -m backend.train

# serve
uvicorn src.api:app --port 8000        # http://127.0.0.1:8000/docs
```

`python -m backend.train` takes ~30 s. Everything after it is fast: a screening
request loads that artifact instead of refitting.

Without an artifact the service still works — it falls back to fitting the
forecaster inside the request, which is ~45× slower and not reproducible across
restarts. `GET /health/models` reports which mode you are in.

---

## Architecture

```
route ──▶ service ──▶ src/pipeline.py        (the science)
                 └──▶ repository ──▶ SQLite  (the record)
```

Routes parse and shape. They hold no business logic.

| Layer | Location | Responsibility |
|---|---|---|
| Routes | `app/api/routes/` | HTTP only |
| Services | `app/services/` | orchestration, ordering, audit |
| ML | `app/ml/inference.py` | artifact train / save / checksum / load |
| Validation | `app/validation/` | machine-readable findings |
| Repositories | `app/repositories/` | the only code that writes SQL |
| Adapters | `app/adapters/` | external datasets → normalized schema |
| Core | `app/core/` | config, errors, logging, security |

---

## Two API surfaces

**Legacy (unversioned)** — `/health`, `/part/{serial}`, `/part/{serial}/report`,
`/lot/{id}`, `/lots`, `POST /screen`.

Contracts unchanged. The Streamlit dashboard, the web console's Screen page and
`tests/test_api.py` consume these. They now call the service layer and use the
model artifact, but every response shape is the same.

**`/v1`** — the production path: async, persisted, audited.

| Endpoint | Purpose |
|---|---|
| `POST /v1/datasets/upload` | upload + validate; nothing stored unless it passes |
| `GET /v1/datasets/{id}` | dataset detail with its validation report |
| `POST /v1/screening/runs?dataset_id=…` | start a run → job (add `&sync=true` for small frames) |
| `GET /v1/jobs/{job_id}` | `QUEUED` / `RUNNING` / `COMPLETED` / `FAILED` |
| `GET /v1/screening/runs/{run_id}` | summary + per-lot disposition |
| `GET /v1/screening/runs/{run_id}/components` | results, highest risk first |
| `GET /v1/screening/runs/{run_id}/components/{serial}` | structured evidence + explanation |
| `…/components/{serial}/record` | full screening record as JSON |
| `…/components/{serial}/report.pdf` | signed one-page PDF |
| `GET /v1/screening/runs/{run_id}/audit` | append-only audit trail |
| `GET /v1/screening/runs/{run_id}/reproducibility` | everything needed to replay it |
| `GET /v1/models/performance` | MAE vs both baselines, **including where the model loses** |
| `POST /v1/models/train` | train and register an artifact |
| `GET /health/live` `…/ready` `…/models` | probes |
| `GET /v1/config` | effective policy + fingerprint (never the API key) |

---

## Guarantees

**Every non-ACCEPT component has a `primary_reason`.** The verdict is
`sum(sub_score × weight)`, so the explanation is derived from those same
weighted contributions, ranked. Reason codes are corroborating detail, not the
only source — they can no longer be silent on a rejected part. A reason names a
code only when that code actually fired; otherwise it carries `related_code`.

**A high-severity finding escalates the verdict to at least WATCH.** Mirrors the
existing hard `l1_static` override: the screen may add flags, never remove them.
Without it, 12 of 2,100 components carried a safety-slope breach (R-301) and
were still dispositioned ACCEPT. WATCH consumes no PDA budget, so this costs no
lot disposition. Disable with `SENTINEL_ESCALATE_ON_HIGH_SEVERITY=0` — which
changes the policy fingerprint, so such a run is identifiable.

**Out-of-fold is a claim about parts, not file hashes.** The artifact records
the serials it was fitted on. A 60-row subset of the training frame hashes
differently but every component in it was seen, and it is reported as in-fold.

**Errors share one envelope.** No traceback ever reaches a client:

```json
{"error": {"code": "DATASET_SCHEMA_INVALID",
           "message": "…", "details": [...], "request_id": "9f2c1ab4de77"}}
```

**Reports are verified before they are issued.** The PDF path replays the run
under the exact recorded artifact and compares every regenerated verdict against
the persisted one. A run that does not reproduce is refused with
`RUN_NOT_REPRODUCIBLE` rather than producing a document that disagrees with the
record it cites.

---

## Configuration

Policy fields change verdicts and are hashed into `config_hash`, recorded on
every run. Operational fields are not.

| Variable | Default | Kind |
|---|---|---|
| `SENTINEL_C_FN` / `SENTINEL_C_FP` | `100` / `1` | policy |
| `SENTINEL_PDA_LIMIT` | `0.05` | policy |
| `SENTINEL_TARGET_REJECT_RATE` | `0.05` | policy |
| `SENTINEL_MODULE_B_QUANTILE` | `0.90` | policy |
| `SENTINEL_MISSION_YEARS` | `7.0` | policy |
| `SENTINEL_ESCALATE_ON_HIGH_SEVERITY` | `1` | policy |
| `SENTINEL_DATABASE_URL` | `sqlite:///var/sentinel.db` | operational |
| `SENTINEL_ARTIFACT_DIR` / `_UPLOAD_DIR` / `_REPORT_DIR` | `var/…` | operational |
| `SENTINEL_MAX_UPLOAD_BYTES` | `67108864` | operational |
| `SENTINEL_API_KEY` | *(unset — auth disabled)* | operational |
| `SENTINEL_CORS_ORIGIN_REGEX` | loopback only | operational |
| `SENTINEL_DEBUG` | `0` | operational |

Datasheet limits and units are **not** here: they live in `src/features.py`,
which rule 8 makes the single definition.

---

## Database

SQLite via stdlib `sqlite3`, WAL enabled. Six tables: `datasets`,
`screening_runs`, `component_results`, `audit_events`, `jobs`,
`model_artifacts`. `audit_events` is append-only by construction — the
repository exposes no update or delete.

Postgres is not implemented. The repository classes are the seam where it would
go, and `Settings.sqlite_path` raises on any other URL rather than pretending.

---

## Security scope, stated plainly

Implemented: loopback-only CORS, upload size and row limits, safe filenames
(no client string reaches a path), content-addressed storage, structured errors
with no traceback, an optional single-key `X-API-Key` gate on mutating
endpoints, and secrets excluded from every payload.

**Not** implemented: users, roles, sessions, per-actor permissions. The audit
trail's `actor` is *asserted by the caller, not authenticated* — it is traceable
in a cooperative environment, not evidence. A flight-lot deployment terminates
this behind a real authenticating gateway.

---

## Honesty notes

- All shipped data is **simulated** (seed 42). Ground truth makes recall
  measurable; it is never an input to a verdict.
- No SHAP, no deep learning, no L4 ensemble, no neural nets. `shap`, `xgboost`,
  `pandera` and `plotly` were pinned and never imported — they are gone.
- Module B **loses** to last-value-carried-forward on `Tpd_ns` and `Vol_mV`
  (fitted exponent 0 — the data supports no extrapolation there).
  `GET /v1/models/performance` reports this per parameter.
- NASA MOSFET/IGBT adapters are **not** implemented. The interface and the
  normalized schema exist and are proven by a working native adapter; the
  external sets are named as future validation work, with the reasons they are
  not drop-in documented in `app/adapters/__init__.py`.
- Thermal context is reported as absent rather than assumed. This dataset has
  no per-component telemetry, and defaulting to 125 °C would fabricate one.
