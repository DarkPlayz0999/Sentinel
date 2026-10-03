#!/usr/bin/env bash
# SENTINEL - start the API and the web console.
#
#   bash start_app.sh          # both, Ctrl-C stops both
#
# Web console: http://localhost:3000   API docs: http://localhost:8000/docs
set -euo pipefail
cd "$(dirname "$0")"

PY="${PY:-python}"
[ -x ".venv/Scripts/python.exe" ] && PY=".venv/Scripts/python.exe"
[ -x ".venv/bin/python" ] && PY=".venv/bin/python"

# The API and the console read data/; generate it if this is a clean checkout.
[ -f data/burnin_wide.csv ] || "$PY" src/generate_burnin_dataset.py

# ponytail: no PID files or health polling - trap+wait is enough for a demo box.
trap 'kill 0' EXIT
"$PY" -m uvicorn src.api:app --port 8000 &
if [ -d web/node_modules ]; then
  (cd web && npm run dev -- --port 3000) &
else
  echo "web console skipped: run 'cd web && npm install' once to enable it"
fi
wait
