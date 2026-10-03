# Reproducibility

Every simulation is a pure function of its configuration and seed.

* `simulate(cfg)` draws from independent child streams of one
  `numpy.random.SeedSequence(seed)`: as-built values, aging, tester noise, IR
  noise, intermittent glitches, and a separate stream per rework. Adding a fault
  consumes no random numbers, so every other board's reads are identical with or
  without it (`tests/test_twin.py::test_fault_moves_only_its_own_board`).
* A rework extends the horizon for one board without changing any original read
  (`test_a_rework_never_changes_the_original_reads`).
* The service stores the config, seed and faults; on a cache miss or a restart
  it recomputes the lot and gets the same bytes
  (`test_a_restarted_service_rebuilds_the_same_lot`).
* Campaign run seeds come from `SeedSequence([seed, stream])`, so run *i* is the
  same lot whether you ask for 10 runs or 1000. Training lots for Module B use a
  different stream from every evaluated lot.

## Replaying a result

```
# a campaign
python -m src.twin.experiments --kind ood --seed 42 --runs 28 --boards 150

# one lot, in Python
from src.twin.engine import SimConfig, simulate
from src.twin.faults import FaultSpec
r = simulate(SimConfig(boards=200, seed=42,
                       faults=(FaultSpec("C001", "ESR_INCREASE", 0.8, 24, 0.015, board=93),)))
r.sentinel_frame().to_csv("lot.csv", index=False)   # screen it like any upload
```

Each screening run of a simulated lot records the dataset SHA-256, model
artifact, pipeline/feature/policy versions and configuration hash
(`GET /v1/screening/runs/{run_id}/reproducibility`), exactly as for an upload.

One deliberate exception: a replacement candidate's *ranking score* includes
each reel's recorded defect history, which grows with every rework outcome the
database has seen. The candidates themselves (their true values and latent
defects) are deterministic in (seed, board index, component).

The committed `data/` is never touched: the twin writes only to the database and
`var/experiments/`.
