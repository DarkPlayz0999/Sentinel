# The SIH demonstration

**Scenario.** A lot of 200 RB-1 boards soaks at 125 °C. On one board, chosen by
the seed, the bulk capacitor C001 develops ESR degradation during accelerated
burn-in (severity 0.8, onset 24 h, accelerating). The run is BLIND.

## Run it

```
uvicorn src.api:app --port 8000        # or: powershell -File start_app.ps1
cd web && npm run dev                  # http://localhost:3000/console/lab
```

Press **Run the demo, blind**, or `POST /v1/simulations?start=true` with
`{"scenario": "sih_demo"}`.

## What happens, beat by beat

| # | Beat | What is on screen |
|---|---|---|
| 1 | Show the board | 3D RB-1, every part labelled with its backend ID |
| 2 | Run the burn-in | time bar 0 → 168 h, ACCELERATED SIMULATION TIME |
| 3 | Thermal/electrical change | *Thermal → Against its lot*: C001 warms against its siblings; *Electrical*: the rail droops |
| 4 | Component becomes suspicious | monitor event `THRESHOLD_CROSSED` at 168 h (Tpd 4.5 σ) |
| 5 | Measurements to Sentinel | "Sent 200 boards to Sentinel: serial, lot and ATE reads only" |
| 6 | Anomaly result | board B094 ranked first: risk 53.1, **REJECT**, R-401 (Tpd 4.5 σ), still inside every datasheet limit |
| 7 | 3D highlight | *Fault* view: C001 ringed, neighbours marked |
| 8 | Explanation | C001 ESR increase, evidence score 97, next best 69; QA/safety review |
| 9 | Replacement | three candidates ranked on stated criteria; reel A first (ranking score 77.5) |
| 10 | Rerun | second soak of B094 with the new part |
| 11 | Improved result | risk 53.1 → 20.6, REJECT → ACCEPT; C001 IR 129.5 → 126.4 °C; removed part benches at 2.48 Ω ESR against 0.14 Ω new |
| 12 | Ground truth | C001 ESR_INCREASE on B094 confirmed; the replaced part was the faulty one |
| 13 | Audit trail | every event, prediction, replacement and the reveal, timestamped |

Numbers from a run at seed 42 through the live API. `tests/test_twin_service.py`
asserts the same outcomes: C001 found, rerun ACCEPT, top-1 localisation. The
bench readings carry 1 % instrument noise and the candidate ranking folds in the
reels' recorded rework history, so those two can move slightly between
databases; the screen, the diagnosis and the verdicts do not.

## What to say, and what not to

* Say: *the part never breached a datasheet limit; a static test ships it.
  Sentinel caught it because it drifted away from its own lot.*
* Say: *the answer was hidden from everyone until Sentinel committed.*
* Do not claim early detection for this board: it is flagged at 168 h (the
  monitor did not fire earlier at 4.5 σ). Use the campaign results for early
  detection statistics.
* Do not call the evidence score or the candidate ranking a probability.
* Nothing here is flight certified, space qualified or a validated burn-in.
  It is a research and decision-support simulator.
