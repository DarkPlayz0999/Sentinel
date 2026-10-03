"""Reference board RB-1: the burn-in test assembly for one CMOS logic buffer.

Why this board
--------------
Sentinel screens four ATE parameters: quiescent supply current, output
leakage, propagation delay and output-low voltage. A board is only a useful
twin if every component on it can move at least one of those four through a
real electrical path. RB-1 is drawn so that each one does:

    J001 --VDD_IN-- R001 --VDD-- U001 --DRV-- R002 --GATE-- Q001 --OUT-- J001
                     |           |  \                 |           |
                   TP001       C001 C002            R004        C003
    J001 --IN-- R003 --IN_U-- U001

    Iddq    read as the voltage across the sense resistor R001, divided by its
            NOMINAL value. U001's own quiescent current and the dielectric
            leakage of C001/C002 all flow through it, and a drifting R001
            reads as a current change - which is exactly how a real ATE
            would be fooled.
    Ileak   Q001 off, OUT forced to VDD: Q001 drain leakage plus C003 leakage.
    Vol     Q001 on, 40 mA forced into OUT: Rds(on), trace and contact
            resistance, with Rds(on) set by the gate voltage R002/R004 deliver.
    Tpd     input RC (R003), U001 delay at the dynamic rail voltage, gate
            charge through R002 to Q001's threshold, output RC through Rds(on).
            Rail droop comes from the decoupling network (C001/C002 ESR) and
            the rail's own ripple, so a capacitor fault reaches timing.

Identity
--------
Every component has a fixed ID (C001, R001, ...) and a `model` naming the
simulation model behind it. The 3D object, the backend record and the
simulation parameter set all key on the same string, and the order of
`RB1.components` never changes - that is what makes the mapping
deterministic.

Units are SI throughout (ohm, farad, ampere, second, volt, watt). Positions are
millimetres on a 70 x 45 mm board, origin at the bottom-left corner.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

__all__ = ["Param", "Component", "Board", "RB1", "BOARDS", "get_board",
           "ATE", "KEY_PARAMS", "REPLACEABLE_KINDS"]


@dataclass(frozen=True)
class Param:
    """One physical parameter of a component.

    ``dist`` and ``spread`` describe manufacturing variation: ``normal`` is a
    relative sigma, ``lognormal`` a log-sigma, ``fixed`` has none. ``aging``
    is the direction healthy wear moves the value ("up", "down" or None) and
    ``aging_scale`` how strongly, relative to the current-like parameters.
    """
    nominal: float
    unit: str
    dist: str = "normal"
    spread: float = 0.0
    aging: str | None = None
    aging_scale: float = 0.0
    label: str = ""


@dataclass(frozen=True)
class Component:
    component_id: str
    kind: str                 # capacitor resistor ic mosfet connector power_rail test_point
    model: str                # the simulation model behind the 3D object
    label: str
    part_number: str
    params: dict[str, Param]
    x_mm: float
    y_mm: float
    w_mm: float
    d_mm: float
    h_mm: float
    # Body-to-board thermal resistance. Zero means the part dissipates nothing
    # the thermal model tracks (test points, the rail itself).
    theta_c_per_w: float
    nets: tuple[str, ...]
    ratings: dict[str, float] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "component_id": self.component_id, "type": self.kind,
            "component_model": self.model, "label": self.label,
            "part_number": self.part_number,
            "nominal": {k: p.nominal for k, p in self.params.items()},
            "units": {k: p.unit for k, p in self.params.items()},
            "param_labels": {k: p.label or k for k, p in self.params.items()},
            "position_mm": [self.x_mm, self.y_mm],
            "size_mm": [self.w_mm, self.d_mm, self.h_mm],
            "theta_c_per_w": self.theta_c_per_w,
            "nets": list(self.nets), "ratings": dict(self.ratings),
        }


@dataclass(frozen=True)
class Board:
    board_id: str
    name: str
    size_mm: tuple[float, float]
    components: tuple[Component, ...]
    # Net -> ordered component IDs, for drawing copper and for the electrical
    # dependency graph the diagnostic agent walks.
    nets: dict[str, tuple[str, ...]]

    def __post_init__(self):
        ids = [c.component_id for c in self.components]
        if len(ids) != len(set(ids)):
            raise ValueError(f"duplicate component IDs on {self.board_id}")

    # ------------------------------------------------------------ lookup
    @property
    def ids(self) -> list[str]:
        return [c.component_id for c in self.components]

    def get(self, component_id: str) -> Component:
        for c in self.components:
            if c.component_id == component_id:
                return c
        raise KeyError(f"{self.board_id} has no component {component_id!r}")

    def has(self, component_id: str) -> bool:
        return any(c.component_id == component_id for c in self.components)

    @property
    def simulated(self) -> list[Component]:
        """Components with physical parameters (test points carry none)."""
        return [c for c in self.components if c.params]

    @property
    def thermal(self) -> list[Component]:
        """Components the thermal model tracks and the IR camera reads."""
        return [c for c in self.components if c.theta_c_per_w > 0]

    # --------------------------------------------------------- topology
    def distance_mm(self, a: str, b: str) -> float:
        ca, cb = self.get(a), self.get(b)
        return math.hypot(ca.x_mm - cb.x_mm, ca.y_mm - cb.y_mm)

    def neighbours(self, component_id: str, radius_mm: float = 12.0) -> list[str]:
        """Physically adjacent parts: the thermal-coupling neighbourhood."""
        return [c.component_id for c in self.components
                if c.component_id != component_id and c.params
                and self.distance_mm(component_id, c.component_id) <= radius_mm]

    def electrical_neighbours(self, component_id: str) -> list[str]:
        """Parts sharing a signal net (ground is shared by everything, so skipped)."""
        mine = set(self.get(component_id).nets) - {"GND"}
        return [c.component_id for c in self.components
                if c.component_id != component_id and c.params
                and mine & (set(c.nets) - {"GND"})]

    def as_dict(self) -> dict:
        return {"board_id": self.board_id, "name": self.name,
                "size_mm": list(self.size_mm),
                "components": [c.as_dict() for c in self.components],
                "nets": {k: list(v) for k, v in self.nets.items()},
                "ate": dict(ATE)}


# ATE and burn-in operating conditions. Changing one changes every simulated
# reading, so they are named here rather than scattered through the engine.
ATE: dict[str, float] = {
    "i_ol_a": 0.040,          # Vol test sink current
    "c_in_f": 5e-12,          # U001 input capacitance behind R003
    "c_load_f": 150e-12,      # ATE load on OUT during the Tpd test
    "t_fixed_s": 0.22e-9,     # fixture and interconnect delay
    "alpha": 1.3,             # Sakurai alpha-power law exponent
    "f_clk_hz": 1e6,          # dynamic burn-in clock
    "i_dyn_a": 0.25,          # rail current step drawn by the switching load
    "i_avg_a": 0.06,          # average rail current during dynamic burn-in
    "i_load_rms2": 0.005,     # Q001 load current squared, RMS (100 mA, 50 %)
    "r_trace_ohm": 0.05,      # OUT trace resistance
    "v_nominal": 3.3,         # reference supply for the delay law
    # Tester range limits. A reading beyond range is reported AT the limit, as
    # a real tester does - and it keeps a gross failure inside the validator's
    # plausibility window, so it is scored rather than rejected as a typo.
    "range_iddq_ua": 500.0,
    "range_ileak_na": 2000.0,
    "range_tpd_ns": 46.0,
    "range_vol_mv": 3300.0,
    # Tester resolution floor. A shorted sense resistor reads as (almost) no
    # current; the floor keeps the value positive so it can be logged.
    "floor_iddq_ua": 0.01,
    "floor_ileak_na": 0.01,
}


def _tp(cid: str, label: str, x: float, y: float, net: str) -> Component:
    return Component(cid, "test_point", "test_point", label, "Test pad, 1.5 mm",
                     {}, x, y, 1.5, 1.5, 0.4, 0.0, (net,))


RB1 = Board(
    board_id="RB-1",
    name="Reference burn-in board RB-1 (CMOS buffer DUT)",
    size_mm=(70.0, 45.0),
    components=(
        Component("J001", "connector", "connector", "Edge connector",
                  "4-pin header, 2.54 mm pitch",
                  {"r_contact": Param(0.020, "ohm", "lognormal", 0.10, "up", 0.5,
                                      "contact resistance per pin")},
                  6.0, 22.5, 5.0, 14.0, 8.5, 40.0,
                  ("VDD_IN", "IN", "OUT", "GND"), {"current_a": 3.0}),
        Component("R001", "resistor", "resistor", "Supply sense resistor",
                  "1.00 ohm 0.1 % 1206",
                  {"resistance": Param(1.0, "ohm", "normal", 0.001, "up", 0.02,
                                       "resistance")},
                  20.0, 37.0, 3.2, 1.6, 0.6, 180.0, ("VDD_IN", "VDD"),
                  {"power_w": 0.25}),
        Component("C001", "capacitor", "capacitor", "Bulk decoupling capacitor",
                  "10 uF 16 V tantalum, case D",
                  {"capacitance": Param(10e-6, "F", "normal", 0.05, "down", 0.1,
                                        "capacitance"),
                   "esr": Param(0.12, "ohm", "lognormal", 0.10, "up", 0.5, "ESR"),
                   "leakage": Param(0.8e-6, "A", "lognormal", 0.25, "up", 1.0,
                                    "dielectric leakage")},
                  28.0, 33.0, 7.3, 4.3, 2.8, 110.0, ("VDD", "GND"),
                  {"voltage_v": 16.0, "ripple_a": 0.8}),
        Component("C002", "capacitor", "capacitor", "Local decoupling capacitor",
                  "100 nF 50 V X7R 0805",
                  {"capacitance": Param(100e-9, "F", "normal", 0.05, "down", 0.1,
                                        "capacitance"),
                   "esr": Param(0.02, "ohm", "lognormal", 0.10, "up", 0.5, "ESR"),
                   "leakage": Param(0.05e-6, "A", "lognormal", 0.30, "up", 1.0,
                                    "dielectric leakage")},
                  37.0, 27.5, 2.0, 1.25, 1.25, 150.0, ("VDD", "GND"),
                  {"voltage_v": 50.0, "ripple_a": 1.0}),
        Component("U001", "ic", "ic", "Device under test: CMOS buffer",
                  "Single buffer, SOIC-8",
                  {"iddq": Param(9.0e-6, "A", "lognormal", 0.17, "up", 1.0,
                                 "quiescent current"),
                   "t_int": Param(1.90e-9, "s", "normal", 0.015, "up", 0.12,
                                  "intrinsic delay"),
                   "vth_int": Param(0.70, "V", "normal", 0.02, "up", 0.05,
                                    "internal threshold")},
                  36.0, 18.5, 4.9, 6.0, 1.6, 70.0, ("VDD", "IN_U", "DRV", "GND"),
                  {"power_w": 0.5, "tj_max_c": 150.0}),
        Component("R003", "resistor", "resistor", "Input series resistor",
                  "100 ohm 1 % 0603",
                  {"resistance": Param(100.0, "ohm", "normal", 0.01, "up", 0.02,
                                       "resistance")},
                  22.0, 15.0, 1.6, 0.8, 0.45, 250.0, ("IN", "IN_U"),
                  {"power_w": 0.1}),
        Component("R002", "resistor", "resistor", "Gate resistor",
                  "47 ohm 1 % 0603",
                  {"resistance": Param(47.0, "ohm", "normal", 0.01, "up", 0.02,
                                       "resistance")},
                  45.0, 22.5, 1.6, 0.8, 0.45, 250.0, ("DRV", "GATE"),
                  {"power_w": 0.1}),
        Component("R004", "resistor", "resistor", "Gate pull-down",
                  "100 kohm 1 % 0603",
                  {"resistance": Param(1e5, "ohm", "normal", 0.01, "up", 0.02,
                                       "resistance")},
                  47.0, 13.0, 1.6, 0.8, 0.45, 250.0, ("GATE", "GND"),
                  {"power_w": 0.1}),
        Component("Q001", "mosfet", "mosfet", "Output N-MOSFET",
                  "N-channel 30 V, SOT-23",
                  {"vth": Param(1.20, "V", "normal", 0.035, "up", 0.12,
                                "threshold voltage"),
                   # Rds(on) = r_ch / (Vgs - Vth): 5 ohm at the nominal 2.1 V overdrive.
                   "r_ch": Param(10.5, "ohm*V", "normal", 0.05, "up", 0.12,
                                 "channel resistance coefficient"),
                   "i_off": Param(16e-9, "A", "lognormal", 0.25, "up", 1.0,
                                  "off-state drain leakage"),
                   "ciss": Param(10e-12, "F", "normal", 0.05, None, 0.0,
                                 "input capacitance")},
                  54.0, 20.0, 2.9, 1.6, 1.1, 280.0, ("GATE", "OUT", "GND"),
                  {"vds_v": 30.0, "power_w": 0.35, "tj_max_c": 150.0}),
        Component("C003", "capacitor", "capacitor", "Output filter capacitor",
                  "1 nF 50 V C0G 0603",
                  {"capacitance": Param(1e-9, "F", "normal", 0.05, "down", 0.1,
                                        "capacitance"),
                   "esr": Param(0.05, "ohm", "lognormal", 0.10, "up", 0.5, "ESR"),
                   "leakage": Param(3e-9, "A", "lognormal", 0.30, "up", 1.0,
                                    "dielectric leakage")},
                  61.0, 13.0, 1.6, 0.8, 0.8, 250.0, ("OUT", "GND"),
                  {"voltage_v": 50.0}),
        Component("PR001", "power_rail", "power_rail", "VDD distribution rail",
                  "3.3 V rail, 1 oz copper",
                  {"vsupply": Param(3.3, "V", "normal", 0.002, None, 0.0,
                                    "supply voltage"),
                   "ripple": Param(0.005, "V", "fixed", 0.0, None, 0.0,
                                   "ripple amplitude"),
                   "sag": Param(0.0, "V", "fixed", 0.0, None, 0.0,
                                "instability (sag sigma)")},
                  27.0, 41.0, 30.0, 1.2, 0.035, 0.0, ("VDD_IN", "VDD"),
                  {"voltage_v": 3.6}),
        _tp("TP001", "Test point: VDD at connector", 14.0, 40.0, "VDD_IN"),
        _tp("TP002", "Test point: VDD rail", 33.0, 40.0, "VDD"),
        _tp("TP003", "Test point: MOSFET gate", 49.0, 29.0, "GATE"),
        _tp("TP004", "Test point: OUT", 62.0, 25.0, "OUT"),
    ),
    nets={
        "VDD_IN": ("J001", "TP001", "R001"),
        "VDD": ("R001", "PR001", "C001", "TP002", "C002", "U001"),
        "IN": ("J001", "R003"),
        "IN_U": ("R003", "U001"),
        "DRV": ("U001", "R002"),
        "GATE": ("R002", "TP003", "R004", "Q001"),
        "OUT": ("Q001", "C003", "TP004", "J001"),
        "GND": ("J001", "C001", "C002", "U001", "R004", "Q001", "C003"),
    },
)

BOARDS: dict[str, Board] = {RB1.board_id: RB1}


def get_board(board_id: str = "RB-1") -> Board:
    try:
        return BOARDS[board_id]
    except KeyError:
        raise KeyError(f"unknown board {board_id!r}; known: {sorted(BOARDS)}") from None


# The parameter a bench measurement reports first for each kind. Used for the
# before/after table and for incoming inspection of replacement candidates.
KEY_PARAMS: dict[str, tuple[str, ...]] = {
    "capacitor": ("esr", "capacitance", "leakage"),
    "resistor": ("resistance",),
    "mosfet": ("r_ch", "vth", "i_off"),
    "ic": ("iddq", "t_int"),
    "connector": ("r_contact",),
    "power_rail": ("vsupply", "ripple"),
}

# A rail or a test pad is not a part you pull from a reel.
REPLACEABLE_KINDS = ("capacitor", "resistor", "mosfet", "ic", "connector")
