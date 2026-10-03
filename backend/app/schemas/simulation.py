"""Request contracts for the digital twin endpoints (/v1/simulations, /v1/experiments)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

Mode = Literal["VISIBLE", "BLIND"]
Solver = Literal["mna", "auto", "ngspice"]


class FaultIn(BaseModel):
    component_id: str = Field(..., examples=["C001"])
    fault_type: str = Field(..., examples=["ESR_INCREASE"])
    severity: float = Field(0.6, ge=0.0, le=3.0,
                            description="Fraction of the effect's full scale reached at 168 h")
    start_h: float = Field(24.0, ge=0.0, lt=168.0, description="Onset, simulated hours")
    growth_rate: float = Field(0.004, ge=0.0, le=0.2,
                               description="Acceleration of the profile, per hour")
    board: int | None = Field(None, ge=0, description=(
        "Board index in the lot. Omitted: chosen from the seed, so the target is "
        "not always the first board."))


class HiddenFaultsIn(BaseModel):
    """Faults the SIMULATOR draws, for blind evaluation. Nobody sees them until reveal."""
    count: int = Field(1, ge=1, le=100)
    severity: tuple[float, float] = (0.4, 1.0)
    start_h: tuple[float, float] = (0.0, 72.0)
    growth_rate: tuple[float, float] = (0.004, 0.02)
    component_ids: list[str] | None = Field(None, description="Restrict to these parts")
    observable_only: bool = Field(True, description=(
        "Draw only faults that move at least one channel on this board. An "
        "unobservable fault is a fair test of nothing."))


class NoiseIn(BaseModel):
    current_noise: float = Field(0.015, ge=0.0, le=0.2)
    voltage_noise: float = Field(0.015, ge=0.0, le=0.2)
    timing_noise: float = Field(0.015, ge=0.0, le=0.2)
    temperature_noise_c: float = Field(0.5, ge=0.0, le=10.0)
    rail_noise_v: float = Field(0.002, ge=0.0, le=0.1)
    dropout: float = Field(0.012, ge=0.0, le=0.2)
    sensor_bias: dict[str, float] = Field(default_factory=dict)


class SimulationCreate(BaseModel):
    mode: Mode = "VISIBLE"
    scenario: Literal["custom", "sih_demo"] = Field("custom", description=(
        "`sih_demo` preloads the primary demonstration: a capacitor on one board "
        "develops ESR degradation during accelerated burn-in, in BLIND mode."))
    board_id: str = "RB-1"
    boards: int = Field(200, ge=30, le=1000, description="Lot size (Sentinel needs >= 30)")
    seed: int = Field(42, ge=0, le=2**31 - 1)
    stress_temp_c: float = Field(125.0, ge=25.0, le=175.0)
    read_temp_c: float = Field(125.0, ge=25.0, le=175.0)
    noise: NoiseIn = Field(default_factory=NoiseIn)
    faults: list[FaultIn] = Field(default_factory=list)
    hidden_faults: HiddenFaultsIn | None = None
    solver: Solver = Field("auto", description=(
        "mna: built-in solver only. auto: built-in for the lot, plus an ngspice "
        "cross-check of the flagged board when ngspice is installed. ngspice: every "
        "DC read solved by ngspice (lots up to 60 boards); failure stops the run."))
    auto_screen: bool = Field(True, description="Send the measurements to Sentinel at 168 h")
    monitor_z: float = Field(4.5, ge=2.0, le=20.0, description=(
        "Continuous-monitoring trigger: robust z of any read against its lot"))
    label: str = Field("", max_length=120)

    @model_validator(mode="after")
    def _check(self):
        if self.solver == "ngspice" and self.boards > 60:
            raise ValueError("solver=ngspice runs one process per read; keep boards <= 60")
        if self.mode == "BLIND" and self.faults and self.scenario != "sih_demo":
            # Allowed, but the creator then knows the answer; the API still hides it.
            pass
        return self


class ReplaceIn(BaseModel):
    serial: str
    component_id: str
    candidate_id: str


class ExperimentCreate(BaseModel):
    kind: Literal["esr_sweep", "monte_carlo", "ood"] = "monte_carlo"
    runs: int = Field(20, ge=1, le=500)
    seed: int = Field(42, ge=0, le=2**31 - 1)
    boards: int = Field(200, ge=30, le=500)
    fault_rate: float = Field(0.06, gt=0.0, le=0.5)
    train_lots: int = Field(4, ge=2, le=12)
    scenarios: list[str] = Field(default_factory=list)
