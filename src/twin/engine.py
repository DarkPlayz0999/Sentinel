"""The simulation engine: a lot of RB-1 boards through accelerated burn-in.

Why a LOT and not one board
---------------------------
Sentinel scores a part against its own production lot: per-lot median and
1.4826 * MAD. One board has no population, so Dynamic PAT is undefined at
n = 1. The engine therefore always simulates a lot of identical boards (200 by
default), each with its own manufacturing variation, healthy aging and - where
injected - faults. The 3D twin shows one board at a time; the statistics come
from the same socket position across the whole lot.

What happens per time step (default 3 simulated hours)
------------------------------------------------------
  1. Parameters now = as-built value x healthy aging x injected fault effects.
     Healthy aging is the dataset's power law, X0 * (1 + A (t_eff/168)^n),
     sub-linear n: parts settle.
  2. Thermal: T = T_chamber + P * theta + neighbour coupling. Power depends on
     the CURRENT parameters (ESR sets ripple heating, Rds(on) sets MOSFET
     loss), so degradation feeds back into temperature.
  3. Clocks advance by dt * AF_rel(T): Arrhenius acceleration of each part's
     own temperature relative to its nominal temperature. Hot parts age and
     fault faster; a hotter chamber accelerates the whole lot.
  4. At read points (0/24/96/168 h) the ATE tests run: three DC netlists
     solved by MNA (circuit.py) for Iddq, Ileak and Vol, and the timing model
     for Tpd. Each observable gets tester noise, bias, range limits and
     handler dropouts. The IR camera reads every tracked part every step.

Ground truth - the injected faults, every internal parameter, health and the
noise-free observables - is held separately from what a tester could observe.
`sentinel_frame()` builds the frame Sentinel receives from observed values
only: serial, lot and the sixteen ATE columns. Nothing else.

ACCELERATED SIMULATION TIME: 168 simulated hours run in well under a second.
This is a model of a burn-in, not an experimentally validated one.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field, replace

import numpy as np
import pandas as pd

from src.features import PARAM_NAMES, PARAMS as SENTINEL_PARAMS

from src.twin import TWIN_VERSION
from src.twin.board import ATE, Board, get_board
from src.twin.circuit import Netlist
from src.twin.faults import FaultSpec, apply_effects, get_model, profile

__all__ = ["NoiseConfig", "SimConfig", "Swap", "SimResult", "simulate",
           "thermal_state", "ate_read", "NETLISTS", "OBSERVABLES",
           "EOL", "read_frame"]

K_BOLTZ_EV = 8.617e-5
REF_CHAMBER_C = 125.0

OBSERVABLES = tuple(PARAM_NAMES)   # Iddq_uA, Ileak_nA, Tpd_ns, Vol_mV

# Which physics produced each observable in the lot run. The DC tests are
# netlist solves; Tpd is an analytic delay model over solved quantities.
ATE_PROVENANCE = {"Iddq_uA": "PHYSICS_MODEL", "Ileak_nA": "PHYSICS_MODEL",
                  "Tpd_ns": "PHYSICS_MODEL", "Vol_mV": "PHYSICS_MODEL"}
ATE_SOLVER = {"Iddq_uA": "mna", "Ileak_nA": "mna", "Tpd_ns": "delay-model",
              "Vol_mV": "mna"}

# Change from as-built that counts as end of life, per parameter. Health is
# 1 - (worst relative change / this). A simulator-internal index: it is ground
# truth, hidden in blind mode, and never shown as a prediction.
EOL = {"esr": 1.0, "capacitance": 0.2, "leakage": 9.0, "resistance": 0.05,
       "r_contact": 4.0, "vth": 0.2, "r_ch": 0.5, "i_off": 9.0, "iddq": 9.0,
       "t_int": 0.1, "vth_int": 0.2, "theta": 1.0, "ciss": 0.5}
EOL_ABS = {"ripple": 0.1, "sag": 0.1, "vsupply": 0.2}


# ---------------------------------------------------------------- configs
@dataclass(frozen=True)
class NoiseConfig:
    """Tester and sensor imperfection. Ground truth never includes any of it.

    The flat 1.5 % default matches the committed dataset's metrology
    assumption (CLAUDE.md rule 14), so twin results are comparable with it.
    """
    current_noise: float = 0.015
    voltage_noise: float = 0.015
    timing_noise: float = 0.015
    temperature_noise_c: float = 0.5
    rail_noise_v: float = 0.002
    dropout: float = 0.012
    dropout_hours: tuple[int, ...] = (96,)
    sensor_bias: dict = field(default_factory=dict)   # observable -> relative bias

    def rel(self, observable: str) -> float:
        return {"Iddq_uA": self.current_noise, "Ileak_nA": self.current_noise,
                "Tpd_ns": self.timing_noise, "Vol_mV": self.voltage_noise}[observable]


@dataclass(frozen=True)
class SimConfig:
    board_id: str = "RB-1"
    boards: int = 200
    seed: int = 42
    lot_id: str = "SIM-L01"
    stress_temp_c: float = 125.0
    # Reads are taken in-situ at this temperature. Kept separate from the
    # stress temperature so an out-of-distribution hotter soak still reads
    # against the datasheet's test condition.
    read_temp_c: float = 125.0
    checkpoints: tuple[int, ...] = (0, 24, 96, 168)
    dt_h: float = 3.0
    noise: NoiseConfig = field(default_factory=NoiseConfig)
    faults: tuple[FaultSpec, ...] = ()
    healthy_wide_rate: float = 0.10
    # Process centring per "CID.param" (multiplier), and spread multiplier.
    lot_shift: dict = field(default_factory=dict)
    spread_mult: float = 1.0
    # A different component variant: "CID.param" -> new nominal value.
    nominal_overrides: dict = field(default_factory=dict)
    ea_ev: float = 0.7

    def __post_init__(self):
        if self.boards < 2:
            raise ValueError("a lot needs at least 2 boards")
        if 0 not in self.checkpoints:
            raise ValueError("the 0 h read is required")
        if any(c % self.dt_h for c in self.checkpoints):
            raise ValueError("every checkpoint must fall on the time grid")
        board = get_board(self.board_id)
        for f in self.faults:
            if not board.has(f.component_id):
                raise ValueError(f"{self.board_id} has no component {f.component_id!r}")
            get_model(board.get(f.component_id).kind, f.fault_type)
            if f.board >= self.boards:
                raise ValueError(f"fault board index {f.board} outside a lot of {self.boards}")

    def as_dict(self) -> dict:
        d = asdict(self)
        d["faults"] = [f.as_dict() for f in self.faults]
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "SimConfig":
        d = dict(d)
        noise = d.pop("noise", None) or {}
        if "dropout_hours" in noise:
            noise["dropout_hours"] = tuple(noise["dropout_hours"])
        faults = tuple(FaultSpec(**f) for f in d.pop("faults", ()) or ())
        if "checkpoints" in d:
            d["checkpoints"] = tuple(int(c) for c in d["checkpoints"])
        return cls(noise=NoiseConfig(**noise), faults=faults, **d)


@dataclass(frozen=True)
class Swap:
    """Rework: pull a component at `at_h` and fit a replacement part.

    ``values`` is the new part's as-built parameters. ``fault`` is the new
    part's own latent defect, if it has one (hidden truth; its `board` field
    is ignored). The board then runs a second full burn-in.
    """
    board: int
    component_id: str
    values: dict
    fault: FaultSpec | None = None
    at_h: float = 168.0
    seed_key: int = 0


# --------------------------------------------------------------- netlists
def _netlists() -> dict[str, Netlist]:
    iddq = (Netlist("RB-1 IDDQ test (quiescent, IN low)")
            .add("VATE", "vdd_ate", "0", "vsup")
            .add("RJ1V", "vdd_ate", "vdd_j", "rc")
            .add("R001", "vdd_j", "rail", "r001")
            .add("IU001", "rail", "gnd_b", "iddq")
            .add("RLC001", "rail", "gnd_b", "rleak_c001")
            .add("RLC002", "rail", "gnd_b", "rleak_c002")
            .add("RJ1G", "gnd_b", "0", "rc"))
    ileak = (Netlist("RB-1 output leakage test (Q001 off, OUT forced to VDD)")
             .add("VFRC", "out_ate", "0", "vsup")
             .add("RJ1O", "out_ate", "out_j", "rc")
             .add("RTR", "out_j", "out", "rtrace")
             .add("RQOFF", "out", "gnd_b", "rleak_q001")
             .add("RLC003", "out", "gnd_b", "rleak_c003")
             .add("RJ1G", "gnd_b", "0", "rc"))
    gate = (Netlist("RB-1 gate drive (U001 output high)")
            .add("VDRV", "drv", "0", "vsup")
            .add("R002", "drv", "gate", "r002")
            .add("R004", "gate", "gnd_b", "r004")
            .add("RJ1G", "gnd_b", "0", "rc"))
    vol = (Netlist("RB-1 VOL test (Q001 on, 40 mA into OUT)")
           .add("IOL", "0", "out_ate", "i_ol")
           .add("RJ1O", "out_ate", "out_j", "rc")
           .add("RTR", "out_j", "out", "rtrace")
           .add("RDS", "out", "gnd_b", "rds")
           .add("RQOFF", "out", "gnd_b", "rleak_q001")
           .add("RJ1G", "gnd_b", "0", "rc"))
    return {"iddq": iddq, "ileak": ileak, "gate": gate, "vol": vol}


NETLISTS = _netlists()
_V_LEAK = 3.3   # leakage currents are specified at the nominal rail


def _p(params: dict, key: str) -> np.ndarray:
    return np.asarray(params[key], dtype=float)


def netlist_values(params: dict, read_temp_c: float, sag: np.ndarray | float = 0.0
                   ) -> dict[str, dict[str, np.ndarray]]:
    """Element values for every ATE netlist, from component parameters."""
    s_t = 2.0 ** ((read_temp_c - REF_CHAMBER_C) / 10.0)   # leakage doubles per 10 C
    vsup = _p(params, "PR001.vsupply") - 0.5 * np.abs(sag)
    rc = _p(params, "J001.r_contact")
    common = {"vsup": vsup, "rc": rc}
    iddq = {**common, "r001": _p(params, "R001.resistance"),
            "iddq": _p(params, "U001.iddq") * s_t,
            "rleak_c001": _V_LEAK / (_p(params, "C001.leakage") * s_t),
            "rleak_c002": _V_LEAK / (_p(params, "C002.leakage") * s_t)}
    ileak = {**common, "rtrace": np.full_like(rc, ATE["r_trace_ohm"]),
             "rleak_q001": _V_LEAK / (_p(params, "Q001.i_off") * s_t),
             "rleak_c003": _V_LEAK / (_p(params, "C003.leakage") * s_t)}
    gate = {**common, "r002": _p(params, "R002.resistance"),
            "r004": _p(params, "R004.resistance")}
    return {"iddq": iddq, "ileak": ileak, "gate": gate,
            "vol_base": {**common, "rtrace": ileak["rtrace"],
                         "rleak_q001": ileak["rleak_q001"],
                         "i_ol": np.full_like(rc, ATE["i_ol_a"])}}


def _pdn(params: dict) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Decoupling network impedance at the burn-in clock, and each branch."""
    w = 2 * math.pi * ATE["f_clk_hz"]
    z1 = _p(params, "C001.esr") + 1.0 / (1j * w * _p(params, "C001.capacitance"))
    z2 = _p(params, "C002.esr") + 1.0 / (1j * w * _p(params, "C002.capacitance"))
    zp = z1 * z2 / (z1 + z2)
    return zp, z1, z2


def _mna(name: str, netlist: Netlist, values: dict) -> dict:
    return netlist.solve(values)


def ate_read(params: dict, read_temp_c: float = REF_CHAMBER_C,
             sag: np.ndarray | float = 0.0, solve=None) -> tuple[dict, dict]:
    """True (noise-free) ATE observables and the solved node voltages.

    Returns ({observable: (N,)}, {node: (N,)}). Units are Sentinel's:
    uA, nA, ns, mV. Tester range limits and resolution floors are applied
    here because they are properties of the reading, not of the noise.

    ``solve(name, netlist, values)`` chooses the circuit solver. The default
    is the batched MNA solver; the service passes an ngspice-backed one for a
    SPICE run. Either way the observables are derived from the solution by
    this one function, so the two solvers cannot drift apart in definition.
    """
    solve = solve or _mna
    vals = netlist_values(params, read_temp_c, sag)
    s_iddq = solve("iddq", NETLISTS["iddq"], vals["iddq"])
    s_leak = solve("ileak", NETLISTS["ileak"], vals["ileak"])
    s_gate = solve("gate", NETLISTS["gate"], vals["gate"])

    vgs_dc = s_gate["gate"] - s_gate["gnd_b"]
    vth = _p(params, "Q001.vth")
    r_ch = _p(params, "Q001.r_ch")
    rds = r_ch / np.maximum(vgs_dc - vth, 0.05)
    s_vol = solve("vol", NETLISTS["vol"], {**vals["vol_base"], "rds": rds})

    # The ATE measures across R001 at TP001/TP002 and divides by the value it
    # believes R001 has. A drifting sense resistor is therefore read as a
    # current change, as it would be on a real tester.
    r001_nom = get_board().get("R001").params["resistance"].nominal
    iddq_ua = (s_iddq["vdd_j"] - s_iddq["rail"]) / r001_nom * 1e6
    ileak_na = -s_leak["i(vfrc)"] * 1e9
    vol_mv = s_vol["out_ate"] * 1e3

    # ---- propagation delay: analytic, over solved and derived quantities
    zp, _, _ = _pdn(params)
    droop = ATE["i_dyn_a"] * np.abs(zp) + _p(params, "PR001.ripple") + np.abs(sag)
    v_eff = (_p(params, "PR001.vsupply")
             - ATE["i_avg_a"] * (_p(params, "R001.resistance") + 2 * _p(params, "J001.r_contact"))
             - droop)
    v0 = ATE["v_nominal"]
    vthi = _p(params, "U001.vth_int")
    t_in = 0.69 * _p(params, "R003.resistance") * ATE["c_in_f"]
    t_u = (_p(params, "U001.t_int") * (v_eff / v0)
           * ((v0 - vthi) / np.maximum(v_eff - vthi, 0.05)) ** ATE["alpha"])
    r002 = _p(params, "R002.resistance")
    r004 = _p(params, "R004.resistance")
    vg_dyn = v_eff * r004 / (r002 + r004)
    over = vg_dyn - vth
    on = over > 0.05
    t_gate = (r002 * _p(params, "Q001.ciss")
              * np.log(np.maximum(vg_dyn, 1e-3) / np.maximum(over, 1e-3)))
    rds_dyn = r_ch / np.maximum(over, 0.05)
    t_out = 0.69 * (rds_dyn + ATE["r_trace_ohm"] + _p(params, "J001.r_contact")) * ATE["c_load_f"]
    tpd_ns = ((t_in + t_u + t_gate + t_out + ATE["t_fixed_s"]) * 1e9
              * (1.0 + 0.001 * (read_temp_c - REF_CHAMBER_C)))
    tpd_ns = np.where(on, tpd_ns, ATE["range_tpd_ns"])   # never switches: timeout

    obs = {
        "Iddq_uA": np.clip(iddq_ua, ATE["floor_iddq_ua"], ATE["range_iddq_ua"]),
        "Ileak_nA": np.clip(ileak_na, ATE["floor_ileak_na"], ATE["range_ileak_na"]),
        "Tpd_ns": np.minimum(tpd_ns, ATE["range_tpd_ns"]),
        "Vol_mV": np.minimum(vol_mv, ATE["range_vol_mv"]),
    }
    nodes = {"v_rail_dc": s_iddq["rail"], "v_gate_dc": s_gate["gate"],
             "v_out_low": s_vol["out_ate"], "rds_on": rds, "v_rail_dyn": v_eff,
             "droop": droop, "z_pdn": np.abs(zp), "vg_dyn": vg_dyn}
    return obs, nodes


# ------------------------------------------------------------------ thermal
def _powers(board: Board, params: dict) -> dict[str, np.ndarray]:
    """Dissipation of every thermally tracked part during dynamic burn-in (W)."""
    vsup = _p(params, "PR001.vsupply")
    zp, z1, z2 = _pdn(params)
    i1 = ATE["i_dyn_a"] * np.abs(zp / z1)
    i2 = ATE["i_dyn_a"] * np.abs(zp / z2)
    vg = vsup * _p(params, "R004.resistance") / (
        _p(params, "R002.resistance") + _p(params, "R004.resistance"))
    rds = _p(params, "Q001.r_ch") / np.maximum(vg - _p(params, "Q001.vth"), 0.05)
    i_avg2 = ATE["i_avg_a"] ** 2
    z = np.zeros_like(vsup)
    return {
        "J001": 3 * i_avg2 * _p(params, "J001.r_contact"),
        "R001": i_avg2 * _p(params, "R001.resistance"),
        "C001": 0.5 * i1 ** 2 * _p(params, "C001.esr") + vsup * _p(params, "C001.leakage"),
        "C002": 0.5 * i2 ** 2 * _p(params, "C002.esr") + vsup * _p(params, "C002.leakage"),
        "U001": 0.20 * (vsup / ATE["v_nominal"]) ** 2 + vsup * _p(params, "U001.iddq"),
        "R003": z + 1e-5,
        "R002": _p(params, "Q001.ciss") * vsup ** 2 * ATE["f_clk_hz"],
        "R004": 0.5 * vg ** 2 / _p(params, "R004.resistance"),
        "Q001": ATE["i_load_rms2"] * np.minimum(rds, 400.0),
        "C003": z + 1e-6,
    }


_COUPLING_C_PER_W = 25.0
_COUPLING_D0_MM = 8.0


def thermal_state(board: Board, params: dict, chamber_c: float
                  ) -> tuple[dict[str, np.ndarray], dict[str, np.ndarray]]:
    """Steady temperature of every tracked part: T_chamber + P*theta + coupling.

    A lumped, physically interpretable approximation - no CFD. Coupling decays
    with centre-to-centre distance as 1 / (1 + (d / 8 mm)^2) through the board
    copper. Returns (temperatures, powers).
    """
    power = _powers(board, params)
    temps = {}
    tracked = board.thermal
    for c in tracked:
        t = chamber_c + power[c.component_id] * _p(params, f"{c.component_id}.theta")
        for o in tracked:
            if o.component_id == c.component_id:
                continue
            d = board.distance_mm(c.component_id, o.component_id)
            t = t + power[o.component_id] * _COUPLING_C_PER_W / (1 + (d / _COUPLING_D0_MM) ** 2)
        temps[c.component_id] = t
    return temps, power


def _af(temp_c: np.ndarray, ref_c: float, ea_ev: float) -> np.ndarray:
    return np.exp(ea_ev / K_BOLTZ_EV * (1.0 / (ref_c + 273.15) - 1.0 / (temp_c + 273.15)))


# ------------------------------------------------------------------- result
@dataclass
class SimResult:
    config: SimConfig
    board: Board
    serials: list[str]
    grid: np.ndarray                      # (K,) simulated hours
    read_hours: list[float]               # absolute hours of every ATE read
    # ---- ground truth (never sent to Sentinel, hidden in blind mode)
    as_built: dict[str, np.ndarray]       # "CID.param" -> (N,)
    values: dict[str, np.ndarray]         # "CID.param" -> (N, K)
    temps: dict[str, np.ndarray]          # CID -> (N, K)
    power: dict[str, np.ndarray]          # CID -> (N, K)
    health: dict[str, np.ndarray]         # CID -> (N, K)
    stress: dict[str, np.ndarray]         # CID -> (N, K)
    ate_true: dict[str, np.ndarray]       # observable -> (N, K)
    nodes: dict[str, np.ndarray]          # node -> (N, K)
    faults: list[dict]                    # resolved injections
    glitches: list[dict]                  # intermittent events at reads
    # ---- observed
    ate_obs: dict[str, np.ndarray]        # observable -> (N, R) at read_hours
    ir_obs: dict[str, np.ndarray]         # CID -> (N, K) IR camera
    rail_obs: np.ndarray                  # (N, K) rail monitor, volts
    provenance: dict[str, dict] = field(default_factory=dict)
    board_index: np.ndarray | None = None  # original lot index of each row
    software_version: str = TWIN_VERSION

    # ------------------------------------------------------------ views
    @property
    def n(self) -> int:
        return len(self.serials)

    def grid_index(self, hour: float) -> int:
        i = int(np.argmin(np.abs(self.grid - hour)))
        if abs(self.grid[i] - hour) > 1e-6:
            raise ValueError(f"{hour} h is not on the simulation grid")
        return i

    def faulty_boards(self) -> set[int]:
        return {f["board"] for f in self.faults}

    def sentinel_frame(self, upto_h: float | None = None, *, offset_h: float = 0.0,
                       rows: list[int] | None = None) -> pd.DataFrame:
        """The ONLY frame Sentinel receives: serial, lot, observed ATE reads.

        No component ID, no fault, no severity, no health, no noise-free value.
        ``offset_h`` selects a later burn-in (168 for the rework soak), whose
        reads are relabelled 0/24/96/168 h relative to its own start.
        """
        rows = list(range(self.n)) if rows is None else rows
        out = {"serial": [self.serials[i] for i in rows],
               "lot": [self.config.lot_id] * len(rows)}
        for h in self.config.checkpoints:
            if upto_h is not None and h > upto_h:
                continue
            j = self.read_hours.index(offset_h + h)
            for p in OBSERVABLES:
                out[f"{p}_{h}h"] = np.round(self.ate_obs[p][rows, j], 4)
        df = pd.DataFrame(out)
        # Column order the committed dataset uses: parameter-major.
        cols = ["serial", "lot"] + [f"{p}_{h}h" for p in OBSERVABLES
                                    for h in self.config.checkpoints
                                    if f"{p}_{h}h" in df.columns]
        return df[cols]

    def ir_rise(self, upto_h: float = 168.0, *, offset_h: float = 0.0,
                rows: list[int] | None = None) -> pd.DataFrame:
        """Observed IR temperature rise of every tracked part over a soak.

        OBSERVED data: the camera frames, noise included. Mean of the first
        two and the last three frames of the window, to take the edge off
        camera noise. This is the thermal evidence the diagnostic agent uses.
        """
        rows = list(range(self.n)) if rows is None else rows
        a = self.grid_index(offset_h)
        b = self.grid_index(offset_h + upto_h)
        return pd.DataFrame({
            c: (self.ir_obs[c][rows, max(b - 2, a):b + 1].mean(axis=1)
                - self.ir_obs[c][rows, a:a + 2].mean(axis=1))
            for c in self.ir_obs}, index=range(len(rows)))

    def truth_frame(self) -> pd.DataFrame:
        """Ground truth per board. Used only AFTER a prediction exists."""
        from src.twin.diagnose import detectability   # local: diagnose imports engine
        det = detectability(self.config.board_id)
        faulty = {}
        for f in self.faults:
            faulty.setdefault(f["board"], []).append(f)
        j168 = self.read_hours.index(168.0)
        rows = []
        for i, s in enumerate(self.serials):
            b = int(self.board_index[i]) if self.board_index is not None else i
            fs = faulty.get(b, [])
            row = {"serial": s, "board": b, "is_faulty": int(bool(fs)),
                   "fault_components": ",".join(sorted({f["component_id"] for f in fs})),
                   "fault_types": ",".join(f["fault_type"] for f in fs),
                   "max_severity": max((f["severity"] for f in fs), default=0.0),
                   # From the model's fault dictionary, not from any result:
                   # does this fault move any channel at all on this board?
                   "detectable": int(any(det[f["component_id"]][f["fault_type"]]
                                         for f in fs))}
            for p in OBSERVABLES:
                row[f"true_{p}_168h"] = float(self.ate_true[p][i, self.grid_index(168.0)])
                row[f"obs_{p}_0h"] = float(self.ate_obs[p][i, 0])
                row[f"obs_{p}_168h"] = float(self.ate_obs[p][i, j168])
            rows.append(row)
        return pd.DataFrame(rows)

    def board_row(self, serial: str) -> int:
        return self.serials.index(serial)


# ------------------------------------------------------------------ engine
def _draw_as_built(board: Board, cfg: SimConfig, rng: np.random.Generator,
                   n: int) -> dict[str, np.ndarray]:
    """Manufacturing variation. One standard-normal draw per (part, param)
    in a fixed order, so adding a noise-free param never shifts the stream."""
    out = {}
    for c in board.simulated:
        for name, p in c.params.items():
            key = f"{c.component_id}.{name}"
            nominal = float(cfg.nominal_overrides.get(key, p.nominal))
            nominal *= float(cfg.lot_shift.get(key, 1.0))
            z = rng.standard_normal(n)
            s = p.spread * cfg.spread_mult
            if p.dist == "normal":
                out[key] = nominal * (1.0 + s * z)
            elif p.dist == "lognormal":
                out[key] = nominal * np.exp(s * z)
            else:
                out[key] = np.full(n, nominal)
        if c.theta_c_per_w > 0:
            out[f"{c.component_id}.theta"] = c.theta_c_per_w * (1.0 + 0.05 * rng.standard_normal(n))
    return out


def _draw_aging(board: Board, cfg: SimConfig, rng: np.random.Generator,
                n: int) -> dict[str, tuple[np.ndarray, np.ndarray, int]]:
    """Healthy power-law aging (A, n, direction) per (part, param).

    Same shape as the committed dataset's healthy class: A ~ |N(0.03, 0.03)|
    with a ~10 % heavy tail of naturally 'wide' parts, sub-linear exponent.
    """
    out = {}
    for c in board.simulated:
        for name, p in c.params.items():
            a = np.abs(rng.normal(0.03, 0.03, n))
            wide = rng.random(n) < cfg.healthy_wide_rate
            a = a + wide * rng.uniform(0.05, 0.20, n)
            expo = rng.uniform(0.35, 0.75, n)
            if p.aging:
                out[f"{c.component_id}.{name}"] = (
                    a * p.aging_scale, expo, 1 if p.aging == "up" else -1)
    return out


def _nominal_temps(board: Board) -> dict[str, float]:
    """Temperature of every tracked part on a nominal board at 125 C: the
    Arrhenius reference, so AF_rel = 1 under nominal conditions."""
    params = {}
    for c in board.simulated:
        for name, p in c.params.items():
            params[f"{c.component_id}.{name}"] = np.array([p.nominal])
        if c.theta_c_per_w > 0:
            params[f"{c.component_id}.theta"] = np.array([c.theta_c_per_w])
    temps, _ = thermal_state(board, params, REF_CHAMBER_C)
    return {k: float(v[0]) for k, v in temps.items()}


def _health(key_values: dict[str, np.ndarray], as_built: dict[str, np.ndarray],
            cid: str) -> np.ndarray:
    worst = None
    for key, v in key_values.items():
        c, name = key.split(".", 1)
        if c != cid:
            continue
        x0 = as_built[key][:, None]
        if name in EOL_ABS:
            dev = np.abs(v - x0) / EOL_ABS[name]
        elif name in EOL:
            dev = np.abs(v / np.where(x0 == 0, 1, x0) - 1.0) / EOL[name]
            if name in ("resistance",):
                # an open or short is end of life whichever way it went
                dev = np.maximum(dev, np.abs(np.log10(np.maximum(v, 1e-12) / x0)) / 1.0)
        else:
            continue
        worst = dev if worst is None else np.maximum(worst, dev)
    if worst is None:
        return None
    return 1.0 - np.clip(worst, 0.0, 1.0)


def simulate(cfg: SimConfig, *, swap: Swap | None = None,
             only_board: int | None = None) -> SimResult:
    """Run the lot. Deterministic in (config, swap): same inputs, same bytes.

    Randomness comes from independent child streams of one SeedSequence -
    as-built, aging, tester noise, IR noise, glitches, rework - so extending
    the horizon for a rework never changes the original reads.
    """
    board = get_board(cfg.board_id)
    n_all = cfg.boards
    ss = np.random.SeedSequence(cfg.seed)
    r_build, r_age, r_noise, r_ir, r_glitch, _r_spare = (
        np.random.default_rng(s) for s in ss.spawn(6))

    as_built = _draw_as_built(board, cfg, r_build, n_all)
    aging = _draw_aging(board, cfg, r_age, n_all)

    horizon = 168.0 + (swap.at_h if swap else 0.0)
    grid = np.round(np.arange(0.0, horizon + cfg.dt_h / 2, cfg.dt_h), 6)
    k_total = len(grid)
    reads = [float(h) for h in cfg.checkpoints]
    if swap:
        reads += [float(swap.at_h + h) for h in cfg.checkpoints]

    # Tester noise for the FIRST burn-in is drawn for the full lot in a fixed
    # shape regardless of rework, so a rework never perturbs original reads.
    n_base = len(cfg.checkpoints)
    noise_z = {p: r_noise.standard_normal((n_all, n_base)) for p in OBSERVABLES}
    drop_u = {p: r_noise.random((n_all, n_base)) for p in OBSERVABLES}
    sag_z = r_noise.standard_normal((n_all, n_base))
    k_base = int(round(168.0 / cfg.dt_h)) + 1
    ir_z = r_ir.standard_normal((len(board.thermal), n_all, k_base))
    rail_z = r_ir.standard_normal((n_all, k_base))
    glitch_u = r_glitch.random((n_all, n_base, 4))

    rows = list(range(n_all)) if only_board is None else [only_board]
    sel = np.asarray(rows)
    n = len(rows)

    def take(a):
        return a[sel]

    base = {k: take(v).copy() for k, v in as_built.items()}
    age = {k: (take(a), take(e), s) for k, (a, e, s) in aging.items()}
    noise_z = {k: take(v) for k, v in noise_z.items()}
    drop_u = {k: take(v) for k, v in drop_u.items()}
    sag_z = take(sag_z)
    ir_z = ir_z[:, sel]
    rail_z = rail_z[sel]
    glitch_u = glitch_u[sel]

    if swap:
        rr = np.random.default_rng([cfg.seed, 7919, swap.board, swap.seed_key])
        noise_z = {k: np.concatenate([v, rr.standard_normal((n, n_base))], axis=1)
                   for k, v in noise_z.items()}
        drop_u = {k: np.concatenate([v, rr.random((n, n_base))], axis=1)
                  for k, v in drop_u.items()}
        sag_z = np.concatenate([sag_z, rr.standard_normal((n, n_base))], axis=1)
        ir_z = np.concatenate([ir_z, rr.standard_normal(ir_z.shape)], axis=2)
        rail_z = np.concatenate([rail_z, rr.standard_normal(rail_z.shape)], axis=1)
        glitch_u = np.concatenate([glitch_u, rr.random((n, n_base, 4))], axis=1)
        swap_rng = np.random.default_rng([cfg.seed, 104729, swap.board, swap.seed_key])

    # ---------------------------------------------------------- faults
    # Each active fault: (row, component, model, spec, start_abs, span, tau)
    active: list[dict] = []
    resolved: list[dict] = []
    for f in cfg.faults:
        comp = board.get(f.component_id)
        model = get_model(comp.kind, f.fault_type)
        resolved.append({**f.as_dict(), "kind": comp.kind,
                         "serial": f"{cfg.lot_id}-B{f.board + 1:03d}",
                         "mechanism": model.mechanism, "source": "injected"})
        if f.board in rows:
            active.append({"row": rows.index(f.board), "board": f.board,
                           "cid": f.component_id, "model": model, "spec": f,
                           "start": f.start_h, "tau": 0.0, "removed": False})

    t_ref = _nominal_temps(board)
    t_eff = {c.component_id: np.zeros(n) for c in board.simulated}
    tracked = [c.component_id for c in board.thermal]

    keys = list(base)
    values = {k: np.zeros((n, k_total)) for k in keys}
    temps = {c: np.zeros((n, k_total)) for c in tracked}
    power = {c: np.zeros((n, k_total)) for c in tracked}
    ate_true = {p: np.zeros((n, k_total)) for p in OBSERVABLES}
    nodes: dict[str, np.ndarray] = {}
    ate_obs = {p: np.full((n, len(reads)), np.nan) for p in OBSERVABLES}
    glitches: list[dict] = []

    def fault_d(fa) -> float:
        start = fa["spec"].start_h
        return float(profile(fa["tau"], fa["spec"].severity, start, fa["spec"].growth_rate))

    def params_now() -> dict[str, np.ndarray]:
        """As-built x healthy aging x (non-intermittent) fault effects, now."""
        cur = {}
        for key in keys:
            v = base[key].copy()
            if key in age:
                a, e, sgn = age[key]
                cid = key.split(".", 1)[0]
                mult = 1.0 + sgn * a * (np.maximum(t_eff[cid], 0.0) / 168.0) ** e
                v = v * np.maximum(mult, 0.05)
            cur[key] = v
        for fa in active:
            if fa["removed"] or fa["model"].intermittent:
                continue
            d = fault_d(fa)
            by_param: dict[str, list] = {}
            for eff in fa["model"].effects:
                by_param.setdefault(eff.param, []).append(eff)
            for pname, effs in by_param.items():
                key = f"{fa['cid']}.{pname}"
                if key in cur:
                    rr_ = fa["row"]
                    cur[key][rr_] = apply_effects(cur[key][rr_:rr_ + 1], effs,
                                                  np.asarray(d))[0]
        return cur

    def apply_swap() -> None:
        """Rework: pull the part, fit the new one, reset its aging clock."""
        r = rows.index(swap.board)
        comp = board.get(swap.component_id)
        for name in comp.params:
            key = f"{swap.component_id}.{name}"
            if name in swap.values:
                base[key][r] = float(swap.values[name])
            if key in age:
                a, e, sgn = age[key]
                a[r] = abs(swap_rng.normal(0.03, 0.03)) * comp.params[name].aging_scale
                e[r] = swap_rng.uniform(0.35, 0.75)
        if f"{swap.component_id}.theta" in base:
            base[f"{swap.component_id}.theta"][r] = comp.theta_c_per_w   # fresh joint
        t_eff[swap.component_id][r] = 0.0
        for fa in active:
            if fa["row"] == r and fa["cid"] == swap.component_id:
                fa["removed"] = True
        if swap.fault is not None:
            comp_model = get_model(comp.kind, swap.fault.fault_type)
            spec = replace(swap.fault, board=swap.board)
            active.append({"row": r, "board": swap.board, "cid": swap.component_id,
                           "model": comp_model, "spec": spec,
                           "start": spec.start_h, "tau": 0.0, "removed": False,
                           "offset": swap.at_h})
            resolved.append({**spec.as_dict(), "kind": comp.kind,
                             "serial": f"{cfg.lot_id}-B{swap.board + 1:03d}",
                             "mechanism": comp_model.mechanism,
                             "source": "replacement part", "at_h": swap.at_h})

    def do_read(j: int, t: float, cur: dict) -> None:
        """One ATE read: intermittent glitches, rail sag, noise, bias, dropout."""
        read_params = {kk: vv.copy() for kk, vv in cur.items()}
        for fa in active:
            if fa["removed"]:
                continue
            d = fault_d(fa)
            r = fa["row"]
            if fa["model"].intermittent and d > 0:
                p_glitch = min(0.9, 1.2 * d)
                if glitch_u[r, j, 0] < p_glitch:
                    dg = d * (0.5 + glitch_u[r, j, 1])
                    for eff in fa["model"].effects:
                        key = f"{fa['cid']}.{eff.param}"
                        read_params[key][r] = apply_effects(
                            read_params[key][r:r + 1], [eff], np.asarray(dg))[0]
                    glitches.append({"board": fa["board"], "component_id": fa["cid"],
                                     "fault_type": fa["spec"].fault_type,
                                     "read_h": float(t), "magnitude": round(float(dg), 4)})
        sag = np.abs(sag_z[:, j]) * read_params["PR001.sag"]
        obs_read, _ = ate_read(read_params, cfg.read_temp_c, sag)
        nz = cfg.noise
        rel_h = t - (swap.at_h if (swap and j >= n_base) else 0.0)
        for p in OBSERVABLES:
            bias = float(nz.sensor_bias.get(p, 0.0))
            v = obs_read[p] * (1.0 + bias) * (1.0 + nz.rel(p) * noise_z[p][:, j])
            if int(round(rel_h)) in nz.dropout_hours:
                v = np.where(drop_u[p][:, j] < nz.dropout, np.nan, v)
            if p == "Iddq_uA":
                v = np.clip(v, ATE["floor_iddq_ua"], ATE["range_iddq_ua"])
            elif p == "Ileak_nA":
                v = np.clip(v, ATE["floor_ileak_na"], ATE["range_ileak_na"])
            elif p == "Tpd_ns":
                v = np.minimum(v, ATE["range_tpd_ns"])
            else:
                v = np.minimum(v, ATE["range_vol_mv"])
            ate_obs[p][:, j] = v

    read_idx = 0
    for k, t in enumerate(grid):
        cur = params_now()
        if swap and abs(t - swap.at_h) < 1e-9 and swap.board in rows:
            # The first soak's last read is taken BEFORE the part is pulled.
            while read_idx < n_base and abs(t - reads[read_idx]) < 1e-9:
                do_read(read_idx, t, cur)
                read_idx += 1
            apply_swap()
            cur = params_now()

        tmp, pw = thermal_state(board, cur, cfg.stress_temp_c)
        obs_true, nd = ate_read(cur, cfg.read_temp_c)
        for key in keys:
            values[key][:, k] = cur[key]
        for c in tracked:
            temps[c][:, k] = tmp[c]
            power[c][:, k] = pw[c]
        for p in OBSERVABLES:
            ate_true[p][:, k] = obs_true[p]
        for name, v in nd.items():
            nodes.setdefault(name, np.zeros((n, k_total)))[:, k] = v

        while read_idx < len(reads) and abs(t - reads[read_idx]) < 1e-9:
            do_read(read_idx, t, cur)
            read_idx += 1

        # ---- advance every clock to the next step
        if k < k_total - 1:
            dt = grid[k + 1] - t
            for c in board.simulated:
                cid = c.component_id
                if cid in tmp:
                    # relative to this part's own nominal temperature at 125 C
                    af = _af(tmp[cid], t_ref[cid], cfg.ea_ev)
                else:
                    af = _af(np.full(n, cfg.stress_temp_c), REF_CHAMBER_C, cfg.ea_ev)
                t_eff[cid] = t_eff[cid] + dt * af
            for fa in active:
                if fa["removed"]:
                    continue
                start_abs = fa["spec"].start_h + fa.get("offset", 0.0)
                if t + dt > start_abs:
                    cid = fa["cid"]
                    if cid in tmp:
                        af = float(_af(tmp[cid][fa["row"]:fa["row"] + 1], t_ref[cid], cfg.ea_ev)[0])
                    else:
                        af = float(_af(np.array([cfg.stress_temp_c]), REF_CHAMBER_C, cfg.ea_ev)[0])
                    fa["tau"] += (t + dt - max(t, start_abs)) * af

    # ---- IR camera and rail monitor: every step, observed with noise
    ir_obs = {}
    for ci, c in enumerate(tracked):
        z = ir_z[ci][:, :k_total] if ir_z.shape[2] >= k_total else np.pad(
            ir_z[ci], ((0, 0), (0, k_total - ir_z.shape[2])))
        ir_obs[c] = temps[c] + cfg.noise.temperature_noise_c * z
    rz = rail_z[:, :k_total] if rail_z.shape[1] >= k_total else np.pad(
        rail_z, ((0, 0), (0, k_total - rail_z.shape[1])))
    rail_obs = nodes["v_rail_dyn"] + cfg.noise.rail_noise_v * rz

    # ---- health and stress: simulator truth
    health, stress = {}, {}
    for c in board.simulated:
        # Reference is the fitted part's as-built value (after a rework, the new one).
        h = _health(values, base, c.component_id)
        if h is not None:
            health[c.component_id] = h
        if c.component_id in temps:
            tmax = c.ratings.get("tj_max_c", 150.0)
            s = (temps[c.component_id] - 25.0) / (tmax - 25.0)
            if "power_w" in c.ratings:
                s = np.maximum(s, power[c.component_id] / c.ratings["power_w"])
            stress[c.component_id] = s

    serials = [f"{cfg.lot_id}-B{i + 1:03d}" for i in rows]
    prov = {p: {"measurement_source": ATE_PROVENANCE[p], "solver": ATE_SOLVER[p],
                "noise_relative": cfg.noise.rel(p),
                "bias_relative": float(cfg.noise.sensor_bias.get(p, 0.0))}
            for p in OBSERVABLES}
    prov["ir"] = {"measurement_source": "PHYSICS_MODEL", "solver": "lumped-thermal",
                  "noise_c": cfg.noise.temperature_noise_c}
    return SimResult(
        config=cfg, board=board, serials=serials, grid=grid, read_hours=reads,
        as_built={k: take(v) for k, v in as_built.items()}, values=values,
        temps=temps, power=power, health=health, stress=stress,
        ate_true=ate_true, nodes=nodes, faults=resolved, glitches=glitches,
        ate_obs=ate_obs, ir_obs=ir_obs, rail_obs=rail_obs, provenance=prov,
        board_index=np.asarray(rows))


def read_frame(result: SimResult) -> pd.DataFrame:
    """Every observed read as a long table - the measurement records."""
    rows = []
    for i, s in enumerate(result.serials):
        for j, h in enumerate(result.read_hours):
            for p in OBSERVABLES:
                v = result.ate_obs[p][i, j]
                rows.append({"serial": s, "time_h": h, "parameter": p,
                             "value": None if not np.isfinite(v) else round(float(v), 6),
                             "unit": SENTINEL_PARAMS[p]["unit"],
                             "measurement_source": result.provenance[p]["measurement_source"]})
    return pd.DataFrame(rows)
