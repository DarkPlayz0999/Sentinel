"""SENTINEL digital twin: a board-level burn-in and fault-injection simulator.

The twin GENERATES measurements. It never screens them. Every verdict, risk
score and reason code still comes from src/pipeline.py via the existing
service layer; this package only produces the four ATE parameters that
pipeline already consumes (Iddq_uA, Ileak_nA, Tpd_ns, Vol_mV), plus the
IR-thermal readings the diagnostic agent uses for localisation.

    board.py        the reference board RB-1: identities, layout, nets, parts
    circuit.py      SPICE-syntax netlists, a batched MNA solver, ngspice runner
    faults.py       the fault catalogue and the degradation profile
    engine.py       thermal model, aging, fault growth, ATE reads, noise
    diagnose.py     fault-signature localisation (what the agents call)
    replace.py      replacement candidates and their explicit ranking
    benchmark.py    blind benchmark scoring through src/evaluate.py
    experiments.py  sweeps, Monte Carlo campaigns, out-of-distribution suite

Honesty rules this package keeps:
  * Ground truth lives in `SimResult.truth` and is never part of the frame
    handed to Sentinel (`SimResult.sentinel_frame`).
  * Every observable carries a provenance label: SPICE, PHYSICS_MODEL,
    SYNTHETIC or DATASET.
  * Simulated hours are ACCELERATED SIMULATION TIME. Nothing here claims to be
    an experimentally validated burn-in.
"""

TWIN_VERSION = "twin-1.0.0"
