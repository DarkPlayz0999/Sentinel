# Simulation model

Source: `src/twin/board.py`, `src/twin/circuit.py`, `src/twin/engine.py`.
All time is **ACCELERATED SIMULATION TIME**: 168 simulated hours run in under a
second. This is a model of a burn-in, not an experimentally validated one.

## Board RB-1

A burn-in test board for one CMOS buffer (U001), 70 × 45 mm, 11 physical
components plus 4 test points. Every component can move at least one ATE
parameter through a real electrical path:

| Observable | How it is measured on the board | Components that move it |
|---|---|---|
| **Iddq** | voltage across the 1 Ω sense resistor R001 ÷ its *nominal* value | U001 quiescent current, C001/C002 dielectric leakage, R001 drift (read as current) |
| **Ileak** | Q001 off, OUT forced to VDD, current delivered | Q001 drain leakage, C003 leakage |
| **Vol** | Q001 on, 40 mA forced into OUT | Q001 Rds(on) (set by gate voltage through R002/R004), J001 contact, trace |
| **Tpd** | input RC + U001 delay at the dynamic rail + gate charge to Vth + output RC | R003, U001, R002, Q001, C001 ESR (rail droop), PR001 ripple/sag |

Nominal board reads: Iddq ≈ 9.8 µA, Ileak ≈ 19 nA, Tpd ≈ 3.27 ns, Vol ≈ 204 mV,
chosen to sit on the committed dataset's centres (10 µA, 20 nA, 3.2 ns, 210 mV)
so Sentinel sees familiar magnitudes. Datasheet limits are Sentinel's
(50 µA, 200 nA, 4.6 ns, 400 mV).

## Electrical: one netlist, two solvers

Each DC test is a SPICE-syntax netlist (R, V, I). `Netlist.solve()` is a
batched modified-nodal-analysis solve across every board at once; it follows
SPICE sign conventions and raises `SimulationFailed` on a singular matrix.
`run_ngspice()` renders the same netlist to a `.cir` file and runs a local
ngspice in batch mode. Tpd is an analytic delay model (Sakurai alpha-power law
for U001, RC terms elsewhere) over solved and derived quantities; it is labelled
as such.

Provenance on every measurement: `SPICE`, `PHYSICS_MODEL` (MNA or the delay
and thermal models), `SYNTHETIC`, or `DATASET`.

## Thermal

Lumped and physically interpretable, no CFD:
`T = T_chamber + P·θ + Σ_neighbours P_j · 25 °C/W / (1 + (d/8 mm)²)`.
Dissipation comes from the current parameters: capacitor ripple heating
`½ I² · ESR` (current split by the decoupling network's impedance at 1 MHz),
MOSFET conduction loss `I_rms² · Rds(on)`, U001 dynamic power. Degradation
therefore feeds back into temperature.

## Aging

Healthy parameters follow the committed dataset's power law,
`X(t) = X0 · (1 + A · (t_eff/168)^n)`, `A ~ |N(0.03, 0.03)|` with a 10 %
heavy tail of naturally wide parts, `n ~ U(0.35, 0.75)`. `t_eff` advances by
`dt · AF_rel(T)`, the Arrhenius factor (Ea = 0.7 eV) of each part's temperature
against its own nominal temperature at 125 °C. Hot parts age faster; a hotter
chamber ages the whole lot faster.

## Measurement imperfection

Kept separate from truth, all configurable (`NoiseConfig`):
tester repeatability per observable (1.5 % default, matching the committed
dataset and CLAUDE.md rule 14), IR camera noise (0.5 °C), rail-monitor noise,
handler dropouts at 96 h (1.2 %), and a per-observable sensor bias. Tester range
limits and resolution floors are applied as a real tester would report them.

## What Sentinel receives

`SimResult.sentinel_frame()`: `serial, lot` and sixteen observed ATE columns.
No component ID, no fault, no severity, no health, no noise-free value. The
critical test in `tests/test_twin_service.py` asserts exactly this on the stored
dataset.
