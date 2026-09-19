# SENTINEL backend upgrade — what changed

Full service documentation: [`backend/README.md`](backend/README.md).

## A. Files changed

**Modified (7)**

| File | Change |
|---|---|
| `src/pipeline.py` | `screen()` accepts a pre-fitted `forecaster`. `forecaster=None` reproduces the previous behaviour exactly. |
| `src/explain.py` | Added **R-102** (lot-relative drift anomaly). Corrected the docstring that claimed SHAP. |
| `src/api.py` | Now a shim re-exporting `backend.app.main:app`, so `uvicorn src.api:app` and `tests/test_api.py` keep working. |
| `tests/test_explain.py` | One test updated: it enumerates every threshold, so a new code must be listed. |
| `requirements.txt` | Removed `shap`, `xgboost`, `pandera`, `plotly` — pinned and never imported. |
| `README.md` | Removed the "L4 ensemble" claim; `module_a.py` has no L4. |
| `.gitignore` | `var/`, `reports/` — runtime state. |

**Added:** `backend/` (4,827 lines, 26 modules), `tests/test_backend.py` (543 lines), `backend/README.md`, `backend/train.py`.

`src/` keeps the science. `backend/` imports it, never the reverse.

## B. What was implemented

**Architecture** — route → service → pipeline/repository → SQLite. No business logic in routes.

**Train/inference split** — `python -m backend.train` fits once, writes a checksummed joblib artifact, records out-of-fold metrics. Screening loads it. **Measured: 24.18s → 0.54s, 44.8× faster**, identical verdict counts, deterministic.

**Explanation matches the verdict** — the verdict is `sum(sub_score × weight)`, so the explanation is derived from those same ranked contributions. Every non-ACCEPT component has a `primary_reason`. A reason names a code only when that code actually fired.

**The hero case** — L04-0348 now emits R-102: *"Iddq_uA drifted 27.51 uA between 0h and 168h (21.94 → 49.45 uA), which is 18.7 robust sigma beyond this lot's median drift of 0.5403 uA. It remains within the datasheet limit of 50 uA, so a static screen passes it."* No data was altered; the explanation architecture was fixed.

**Also**: dataset upload + validation (14 error codes), screening jobs, SQLite persistence, append-only audit trail, model registry, structured Module A/B evidence, reproducibility endpoint, adapter interface, health probes, error envelope, structured logging, config fingerprinting.

## C. Tests added

40 new tests in `tests/test_backend.py`: validation (8), upload (5), persistence/audit/reproducibility (5), **explanation↔verdict invariants (6)**, Module A/B structure (2), **leakage regression (3)**, model registry + out-of-fold honesty (5), health/security (2), adapters (4).

## D. Existing tests

**All 150 pass.** Total suite: **190 passed**.

## E. API changes

Legacy endpoints (`/health`, `/part/{serial}`, `/part/{serial}/report`, `/lot/{id}`, `/lots`, `POST /screen`) — **contracts unchanged**. `POST /screen` gained additive integrity fields the web console already reads.

New `/v1` surface: datasets, screening runs, jobs, components, reports, models, reproducibility, health probes, config. 32 routes total.

## F. Database

SQLite, six tables: `datasets`, `screening_runs`, `component_results`, `audit_events`, `jobs`, `model_artifacts`. `audit_events` is append-only by construction. Postgres is not implemented; the repositories are the seam.

## G. Security

Loopback CORS, upload size/row limits, safe filenames, content-addressed storage, structured errors with no traceback, optional `X-API-Key` on mutating endpoints, secrets never in payloads.

**Not** implemented: users, roles, sessions. The audit `actor` is *asserted, not authenticated*.

## H. Remaining limitations

1. **No authentication system.** Single shared key at best.
2. **SQLite only.**
3. **Jobs are in-process.** A restart mid-run leaves it `RUNNING`; no reaper.
4. **NASA adapters not implemented** — interface only, with reasons documented.
5. **No thermal telemetry** in this dataset; reported absent, never assumed.
6. **Module B loses to last-value on `Tpd_ns`/`Vol_mV`** — reported per parameter.
7. **The blueprint PDFs remain unread.**
8. **Legacy `/screen` stays synchronous** to avoid breaking the web console.

## I. Run the backend

```bash
cd /Users/himanshusolanki/Downloads/sih/Sentinel
python -m backend.train                 # once, ~30s
uvicorn src.api:app --port 8000         # http://127.0.0.1:8000/docs
python -m pytest tests/ -q
```

## J. Full screening demo

```bash
python -m backend.train
uvicorn src.api:app --port 8000 &

DS=$(curl -s -F "file=@web/public/samples/burnin_two_lots_168h.csv" \
     http://localhost:8000/v1/datasets/upload | python -c "import sys,json;print(json.load(sys.stdin)['dataset_id'])")

RUN=$(curl -s -X POST "http://localhost:8000/v1/screening/runs?dataset_id=$DS&sync=true" \
      | python -c "import sys,json;print(json.load(sys.stdin)['run_id'])")

curl -s "http://localhost:8000/v1/screening/runs/$RUN" | python -m json.tool
curl -s "http://localhost:8000/v1/screening/runs/$RUN/components/L04-0348" | python -m json.tool
curl -s "http://localhost:8000/v1/screening/runs/$RUN/reproducibility" | python -m json.tool
curl -s "http://localhost:8000/v1/models/performance" | python -m json.tool
curl -s -o report.pdf "http://localhost:8000/v1/screening/runs/$RUN/components/L04-0348/report.pdf"

# frontend
cd web && npx next dev -p 3111
```

The existing demo still works: `bash run_demo.sh`, `streamlit run app/dashboard.py`.
