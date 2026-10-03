# Sentinel integration

The twin feeds Sentinel exactly what a test floor would: an ATE data log.

1. `SimResult.sentinel_frame()` builds `serial, lot, Iddq_uA_0h … Vol_mV_168h`
   from **observed** values.
2. `DatasetService.register_local_frame(frame, source="simulation")` registers it
   like any upload: validated, SHA-256 hashed, stored, audited.
3. The existing agent workflow runs on that dataset:
   `data_quality → (anomaly ∥ forecast) → combine`. Data Quality marks it
   `simulated`. Combine persists a normal screening run through
   `ScreeningService`, so verdicts, risk scores, reason codes (R-101…R-601),
   explanations and the audit trail are the standard ones.
4. The simulation stores Sentinel's per-board prediction in
   `simulation_predictions` and picks the **first-ranked flagged board** as the
   focus for the investigation and the 3D highlight.

Nothing in Module A, Module B, fusion or explain was changed. The existing
response schema is used, not an invented one: read any simulated run through
`GET /v1/screening/runs/{run_id}/components/{serial}`.

## Continuous monitoring

At each read point the simulator computes, on observed data, the lot-relative
robust z (via `src.features.transform` and `robust_z`) of every board's drift so
far, and of every part's IR temperature rise. Crossing `monitor_z` (4.5 by
default) emits `THRESHOLD_CROSSED` and triggers an **interim** Sentinel screen of
the reads available at that hour; the final screen always runs at 168 h. The
monitor triggers; it never decides.

## The PDA-sized REJECT band

Sentinel's policy places the REJECT edge so that about 5 % of every lot is
rejected (the PDA budget) and WATCH absorbs another ~10 %. On a lot with a single
defect that policy still flags roughly 15 % of boards. The ranking is what finds
the defect; the reveal reports the overkill this policy costs. This is the
existing policy, reported honestly, not tuned for the demo.

## ngspice

`solver = auto` (default): MNA for the lot; if ngspice is installed, the focus
board's 168 h DC reads are re-solved by ngspice and the difference recorded
(`SPICE_CROSSCHECK`). If ngspice is absent the run records `SPICE_UNAVAILABLE`.
`solver = ngspice`: every DC read of every board through ngspice (lots ≤ 60);
a failure stops the run as `SIMULATION_FAILED` with stderr, exit code, netlist
and simulation id. Point `SENTINEL_NGSPICE` at the executable to enable it.
