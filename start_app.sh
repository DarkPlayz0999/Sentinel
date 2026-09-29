#!/usr/bin/env bash
# SENTINEL - start the dashboard and the API.
#
#   bash start_app.sh          # both, Ctrl-C stops both
#
# Dashboard: http://localhost:8501     API docs: http://localhost:8000/docs
set -euo pipefail
cd "$(dirname "$0")"

PY="${PY:-python}"
[ -x ".venv/Scripts/python.exe" ] && PY=".venv/Scripts/python.exe"
[ -x ".venv/bin/python" ] && PY=".venv/bin/python"

# The dashboard reads data/; generate it if this is a clean checkout.
[ -f data/burnin_wide.csv ] || "$PY" src/generate_burnin_dataset.py

# ponytail: no PID files or health polling - trap+wait is enough for a demo box.
trap 'kill 0' EXIT
"$PY" -m uvicorn src.api:app --port 8000 &
"$PY" -m streamlit run app/dashboard.py --server.port 8501 --server.headless true &
wait
