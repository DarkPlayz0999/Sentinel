# Fault models

Source: `src/twin/faults.py`. A fault targets **one component on one board**:

```
fault_type   = "ESR_INCREASE"
target       = "C001" on board index b
severity     = 0.8      fraction of each effect's full scale reached at 168 h
start_h      = 24       onset
growth_rate  = 0.015    per hour; > 0 makes the profile convex (accelerating)
```

`d(t) = severity · (exp(r·τ) − 1) / (exp(r·(168 − start)) − 1)`, linear as
`r → 0`. `τ` is accumulated *stress* hours since onset, advanced at the part's
own Arrhenius rate, so an ESR fault that heats its capacitor accelerates itself.
Under nominal conditions `d(168 h) = severity` exactly.

## Catalogue

| Kind | Fault | Effect at full scale |
|---|---|---|
| capacitor | ESR_INCREASE | ESR × 20 |
| | CAPACITANCE_LOSS | C × 0.2 |
| | LEAKAGE_INCREASE | leakage × 41 |
| | THERMAL_DEGRADATION | θ × 4, leakage × 5 |
| | INTERMITTENT | leakage spikes on some reads only |
| resistor | RESISTANCE_DRIFT | R × 1.6 |
| | OPEN_CIRCUIT / SHORT_CIRCUIT | R × 10^±(k·d⁴): slow, then catastrophic |
| | THERMAL_DRIFT | R × 1.25, θ × 3 |
| mosfet | RDS_ON_INCREASE | r_ch × 2.5 |
| | LEAKAGE_INCREASE | I_off × 61 |
| | VTH_DRIFT | Vth + 0.8 V |
| | THERMAL_OVERSTRESS | θ × 4, I_off × 11, r_ch × 1.3 |
| | PARTIAL_FAILURE | r_ch × 4, I_off × 21 |
| ic | DELAY_DRIFT · LEAKAGE_INCREASE · SUPPLY_SENSITIVITY · THERMAL_DEGRADATION | see file |
| connector | CONTACT_RESISTANCE_INCREASE · INTERMITTENT_CONNECTION | contact R × 61 / spikes |
| power_rail | VOLTAGE_INSTABILITY · RIPPLE_INCREASE | random sag / ripple + 0.4 V |

## Detectability is declared, not discovered

`src/twin/diagnose.detectability()` runs every fault through the board model
and lists the channels it moves. Some faults move **nothing** Sentinel measures:
C002 ESR is masked by C001 at the 1 MHz burn-in clock; capacitance loss on a
decoupling capacitor barely changes a DC read. The injection form says so before
the run, and the benchmark reports "recall on observable faults" beside plain
recall. Shorts pull Iddq or Tpd *down*; Sentinel's one-sided logic (higher is
worse, rule 4) correctly does not flag them, and the benchmark shows that too.

## Visible vs blind

* **VISIBLE (debug)**: the API returns the fault, and every internal value.
* **BLIND (evaluation)**: `hidden_faults` lets the simulator draw the board,
  part, fault and severity (observable faults only by default). The API
  withholds them, and all internal values, until `reveal`, which is refused
  before Sentinel's 168 h prediction exists.
