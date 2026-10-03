"""The fault catalogue and the degradation profile.

A fault is injected into ONE component on ONE board and grows over the soak:

    d(t) = severity * shape(tau),        tau = accumulated stress hours since onset

    shape(tau) = (exp(r * tau) - 1) / (exp(r * H) - 1)     r = growth_rate (1/h)
               = tau / H                                     as r -> 0

    H = 168 - start_h, so under nominal conditions d(168 h) == severity exactly.

`tau` is not wall-clock time: each simulated step advances it by
dt * AF_rel(T), the Arrhenius acceleration of the component's own temperature
relative to its nominal temperature. A fault that heats its own part (ESR
growth in a capacitor carrying ripple current) therefore accelerates itself,
and a hotter chamber develops every fault faster. A positive growth rate makes
the profile convex - accelerating - which is the physical signature of a
latent defect as opposed to healthy settling.

`severity` is a fraction of each effect's full scale. It is the knob a fault
injection sets; what it does physically is in `EFFECTS`, stated per effect so
an engineer can check it.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np

__all__ = ["Effect", "FaultModel", "FaultSpec", "CATALOGUE", "fault_models_for",
           "profile", "apply_effects", "catalogue_dict"]

HORIZON_H = 168.0


@dataclass(frozen=True)
class Effect:
    """How degradation d moves one parameter.

    mode  mul    x * (1 + full_scale * d)
          down   x * max(0.02, 1 - full_scale * d)
          add    x + full_scale * d
          open   x * 10 ** (full_scale * d**4)    crack growth: slow, then open
          short  x * 10 ** (-full_scale * d**4)
    """
    param: str
    mode: str
    full_scale: float


@dataclass(frozen=True)
class FaultModel:
    fault_type: str
    kind: str
    effects: tuple[Effect, ...]
    mechanism: str
    intermittent: bool = False

    def as_dict(self) -> dict:
        return {"fault_type": self.fault_type, "kind": self.kind,
                "mechanism": self.mechanism, "intermittent": self.intermittent,
                "effects": [asdict(e) for e in self.effects]}


def _m(kind, fault_type, mechanism, *effects, intermittent=False):
    return FaultModel(fault_type, kind, tuple(Effect(*e) for e in effects),
                      mechanism, intermittent)


CATALOGUE: tuple[FaultModel, ...] = (
    # -------------------------------------------------------- capacitor
    _m("capacitor", "ESR_INCREASE",
       "Electrolyte dry-out / cathode degradation raises equivalent series "
       "resistance; ripple current then heats the part.",
       ("esr", "mul", 19.0)),
    _m("capacitor", "CAPACITANCE_LOSS",
       "Dielectric aging or cracking removes effective capacitance.",
       ("capacitance", "down", 0.8)),
    _m("capacitor", "LEAKAGE_INCREASE",
       "Dielectric breakdown sites conduct: DC leakage current grows.",
       ("leakage", "mul", 40.0)),
    _m("capacitor", "THERMAL_DEGRADATION",
       "Degraded solder joint / delamination raises thermal resistance, so "
       "the part runs hotter and wears faster.",
       ("theta", "mul", 3.0), ("leakage", "mul", 4.0)),
    _m("capacitor", "INTERMITTENT",
       "Micro-crack that opens and closes with temperature: leakage spikes on "
       "some reads and not others.",
       ("leakage", "mul", 25.0), intermittent=True),
    # --------------------------------------------------------- resistor
    _m("resistor", "RESISTANCE_DRIFT",
       "Film damage or electromigration raises resistance.",
       ("resistance", "mul", 0.6)),
    _m("resistor", "OPEN_CIRCUIT",
       "A crack grows through the film until the resistor opens.",
       ("resistance", "open", 6.0)),
    _m("resistor", "SHORT_CIRCUIT",
       "Conductive contamination or arcing bridges the resistor.",
       ("resistance", "short", 3.0)),
    _m("resistor", "THERMAL_DRIFT",
       "Poor heat-sinking raises the resistor temperature; TCR drift follows.",
       ("resistance", "mul", 0.25), ("theta", "mul", 2.0)),
    # ----------------------------------------------------------- mosfet
    _m("mosfet", "RDS_ON_INCREASE",
       "Die-attach or bond-wire degradation raises on-resistance.",
       ("r_ch", "mul", 1.5)),
    _m("mosfet", "LEAKAGE_INCREASE",
       "Junction damage raises off-state drain leakage.",
       ("i_off", "mul", 60.0)),
    _m("mosfet", "VTH_DRIFT",
       "Charge trapping in the gate oxide (bias-temperature instability) "
       "raises the threshold voltage.",
       ("vth", "add", 0.8)),
    _m("mosfet", "THERMAL_OVERSTRESS",
       "Voided die attach: the junction runs hot, leakage and Rds(on) climb.",
       ("theta", "mul", 3.0), ("i_off", "mul", 10.0), ("r_ch", "mul", 0.3)),
    _m("mosfet", "PARTIAL_FAILURE",
       "Some cells of the power die have failed: on-resistance and leakage "
       "rise together.",
       ("r_ch", "mul", 3.0), ("i_off", "mul", 20.0)),
    # --------------------------------------------------------------- ic
    _m("ic", "DELAY_DRIFT",
       "Hot-carrier injection slows the internal transistors.",
       ("t_int", "mul", 0.35)),
    _m("ic", "LEAKAGE_INCREASE",
       "Gate-oxide defects conduct: quiescent supply current grows.",
       ("iddq", "mul", 30.0)),
    _m("ic", "SUPPLY_SENSITIVITY",
       "Threshold shift makes the delay far more sensitive to rail voltage.",
       ("vth_int", "add", 0.5)),
    _m("ic", "THERMAL_DEGRADATION",
       "Degraded package thermal path: the die runs hotter and leaks more.",
       ("theta", "mul", 2.5), ("iddq", "mul", 3.0)),
    # -------------------------------------------------------- connector
    _m("connector", "CONTACT_RESISTANCE_INCREASE",
       "Fretting corrosion of the contact finish raises contact resistance.",
       ("r_contact", "mul", 60.0)),
    _m("connector", "INTERMITTENT_CONNECTION",
       "A loose or cracked contact: resistance spikes on some reads.",
       ("r_contact", "mul", 120.0), intermittent=True),
    # ------------------------------------------------------- power rail
    _m("power_rail", "VOLTAGE_INSTABILITY",
       "Regulator or distribution fault: the rail sags randomly under load.",
       ("sag", "add", 0.30)),
    _m("power_rail", "RIPPLE_INCREASE",
       "Degraded regulation: switching ripple on the rail grows.",
       ("ripple", "add", 0.40)),
)

_BY_KEY = {(f.kind, f.fault_type): f for f in CATALOGUE}


def fault_models_for(kind: str) -> list[FaultModel]:
    return [f for f in CATALOGUE if f.kind == kind]


def get_model(kind: str, fault_type: str) -> FaultModel:
    try:
        return _BY_KEY[(kind, fault_type)]
    except KeyError:
        valid = [f.fault_type for f in fault_models_for(kind)]
        raise ValueError(f"fault {fault_type!r} does not apply to a {kind}; "
                         f"valid: {valid}") from None


def catalogue_dict() -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for f in CATALOGUE:
        out.setdefault(f.kind, []).append(f.as_dict())
    return out


@dataclass(frozen=True)
class FaultSpec:
    """One injected fault. `board` is an index into the lot."""
    component_id: str
    fault_type: str
    severity: float = 0.6
    start_h: float = 24.0
    growth_rate: float = 0.004
    board: int = 0

    def __post_init__(self):
        if not 0.0 <= self.severity <= 3.0:
            raise ValueError("severity must lie in [0, 3]")
        if not 0.0 <= self.start_h < HORIZON_H:
            raise ValueError(f"start_h must lie in [0, {HORIZON_H:.0f})")
        if not 0.0 <= self.growth_rate <= 0.2:
            raise ValueError("growth_rate must lie in [0, 0.2] per hour")
        if self.board < 0:
            raise ValueError("board index must be non-negative")

    def as_dict(self) -> dict:
        return asdict(self)


def profile(tau: np.ndarray, severity: float, start_h: float,
            growth_rate: float) -> np.ndarray:
    """d as a function of accumulated stress hours since onset (see module doc)."""
    tau = np.maximum(np.asarray(tau, dtype=float), 0.0)
    span = max(HORIZON_H - start_h, 1.0)
    r = float(growth_rate)
    if r * span < 1e-6:
        shape = tau / span
    else:
        shape = np.expm1(r * tau) / np.expm1(r * span)
    # A part driven far past nominal conditions can overshoot; cap the runaway
    # so a thermal feedback loop cannot produce an infinite parameter.
    return severity * np.minimum(shape, 4.0)


def apply_effects(value: np.ndarray, effects: list[Effect], d: np.ndarray) -> np.ndarray:
    """Apply every effect on one parameter, in order."""
    v = np.asarray(value, dtype=float)
    for e in effects:
        if e.mode == "mul":
            v = v * (1.0 + e.full_scale * d)
        elif e.mode == "down":
            v = v * np.maximum(0.02, 1.0 - e.full_scale * d)
        elif e.mode == "add":
            v = v + e.full_scale * d
        elif e.mode == "open":
            v = v * 10.0 ** (e.full_scale * np.minimum(d, 1.0) ** 4)
        elif e.mode == "short":
            v = v * 10.0 ** (-e.full_scale * np.minimum(d, 1.0) ** 4)
        else:
            raise ValueError(f"unknown effect mode {e.mode!r}")
    return v
