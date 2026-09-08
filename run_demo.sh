#!/usr/bin/env bash
# SENTINEL - one-command demo. Judges will ask you to re-run this.
#
#   bash run_demo.sh
#
# Runs the whole pipeline from an empty data/ directory and prints every number
# that appears in the deck. Deterministic: seed 42, byte-identical output.
set -euo pipefail

PY="${PY:-python}"
[ -x ".venv/Scripts/python.exe" ] && PY=".venv/Scripts/python.exe"
[ -x ".venv/bin/python" ] && PY=".venv/bin/python"

banner() { printf '\n\033[1m=== %s ===\033[0m\n' "$1"; }

banner "1/6  Generate the dataset (seed 42, reproducible)"
"$PY" src/generate_burnin_dataset.py

banner "2/6  Tests"
"$PY" -m pytest tests/ -q

banner "3/6  Baseline - what Module A has to beat (reproduces blueprint S12)"
"$PY" -m src.baseline

banner "4/6  Diagnostics - is there joint structure? where is recall going?"
"$PY" -m src.diagnose_why

banner "5/6  Sensitivity - how much of the ceiling is metrology, not model?"
"$PY" -m src.sensitivity

banner "6/6  Full screen - fused verdict, PDA status, reason codes"
"$PY" -m src.report

printf '\n\033[1mDashboard:\033[0m  streamlit run app/dashboard.py\n'
printf '\033[1mAPI:\033[0m        uvicorn src.api:app --reload   (docs at /docs)\n'
