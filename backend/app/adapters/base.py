"""External dataset adapters and the normalized internal schema.

Why this exists
---------------
SENTINEL's pipeline is written against one wide burn-in schema. Validating the
method against an external ageing dataset - NASA's MOSFET or IGBT accelerated
ageing sets, a tester export, a partner's ATE log - must not mean editing
`src/features.py`. An adapter normalises the foreign data into the canonical
representation below, and the pipeline never learns that the data came from
somewhere else.

The normalized record
---------------------
`MeasurementRecord` is long-form, one row per (component, parameter, time):

    serial, lot, parameter, time_hours, value, unit,
    temperature_c, voltage_v, source, device_type, stress_condition

Long-form is deliberate. An external set will not have SENTINEL's four
parameters at SENTINEL's four read points, and forcing it into wide columns
would mean inventing readings. Long-form represents what was actually measured
and pivots to wide only where the coverage genuinely exists.

WHAT AN ADAPTER MUST NOT DO
---------------------------
* It must not fabricate a read point that was not measured.
* It must not rescale a foreign parameter into a SENTINEL datasheet limit.
  A NASA MOSFET's drain-source on-resistance is not `Iddq_uA`, and a USL of
  50 µA means nothing for it. `source_provenance` exists so a normalized frame
  always carries what it actually is.
* It must not drop the original values. `normalize()` adds columns; it does
  not overwrite measurements.

External datasets are for RESEARCH AND VALIDATION - "does lot-relative drift
detection generalise?" - not for claiming equivalence with the burn-in
screening problem. A run on adapted data records the adapter name, so no
result from one can be mistaken for a result from the other.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field

import pandas as pd

__all__ = [
    "MeasurementRecord", "SourceProvenance", "AdapterResult", "DatasetAdapter",
    "MEASUREMENT_COLUMNS", "to_long_frame", "registry", "get_adapter",
]

MEASUREMENT_COLUMNS = [
    "serial", "lot", "parameter", "time_hours", "value", "unit",
    "temperature_c", "voltage_v", "source", "device_type", "stress_condition",
]


@dataclass(frozen=True)
class SourceProvenance:
    """What this data actually is. Recorded on every normalized frame.

    Without this a normalized frame is indistinguishable from native burn-in
    data, and a reviewer cannot tell whether a reported number came from the
    problem this project addresses or from a different device under a different
    stress.
    """

    source_dataset: str                  # e.g. "nasa-mosfet-accelerated-ageing"
    source_device_type: str              # e.g. "power MOSFET", "CMOS ASIC"
    source_stress_condition: str         # e.g. "thermal overstress, 80-260 C"
    equivalent_to_burn_in: bool = False
    notes: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class MeasurementRecord:
    """One measurement of one parameter on one component at one time."""

    serial: str
    lot: str
    parameter: str
    time_hours: float
    value: float
    unit: str
    source: str
    device_type: str = ""
    stress_condition: str = ""
    temperature_c: float | None = None
    voltage_v: float | None = None

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class AdapterResult:
    """A normalized dataset plus everything needed to interpret it."""

    long: pd.DataFrame                   # MEASUREMENT_COLUMNS
    provenance: SourceProvenance
    parameter_map: dict = field(default_factory=dict)
    timepoint_map: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    @property
    def thermal_context_available(self) -> bool:
        """True only when a real temperature was supplied per measurement.

        Never assume 125 °C. The shipped synthetic dataset carries no
        per-component thermal telemetry, and inventing the nominal soak
        temperature would turn a missing field into a fabricated measurement.
        """
        # bool(...) is load-bearing: pandas returns numpy.bool_, which is not
        # JSON-serialisable and would fail at the API boundary rather than here.
        return bool("temperature_c" in self.long.columns
                    and self.long["temperature_c"].notna().any())

    def summary(self) -> dict:
        return {
            "rows": int(len(self.long)),
            "components": int(self.long["serial"].nunique()),
            "lots": int(self.long["lot"].nunique()),
            "parameters": sorted(self.long["parameter"].unique().tolist()),
            "time_points_hours": sorted(
                float(t) for t in self.long["time_hours"].unique()),
            "provenance": self.provenance.as_dict(),
            "parameter_map": self.parameter_map,
            "timepoint_map": self.timepoint_map,
            "thermal_context_available": self.thermal_context_available,
            "warnings": self.warnings,
        }


def to_long_frame(records: list[MeasurementRecord]) -> pd.DataFrame:
    df = pd.DataFrame([r.as_dict() for r in records])
    for c in MEASUREMENT_COLUMNS:
        if c not in df.columns:
            df[c] = None
    return df[MEASUREMENT_COLUMNS]


class DatasetAdapter(ABC):
    """Contract every external dataset adapter implements."""

    name: str = "abstract"
    provenance: SourceProvenance

    @abstractmethod
    def validate(self, raw: pd.DataFrame) -> list[str]:
        """Structural problems that stop normalisation. Empty means usable."""

    @abstractmethod
    def map_parameters(self) -> dict:
        """Source column -> (canonical parameter name, unit).

        Returned rather than applied so a reviewer can see the mapping without
        reading the implementation - this is where a dishonest equivalence
        would hide.
        """

    @abstractmethod
    def map_timepoints(self, raw: pd.DataFrame) -> dict:
        """Source time representation -> elapsed stress hours."""

    @abstractmethod
    def normalize(self, raw: pd.DataFrame) -> AdapterResult:
        """Produce the canonical long frame. Must not invent measurements."""

    def to_standard_schema(self, raw: pd.DataFrame) -> AdapterResult:
        """validate -> normalize, with the failure reported as a list."""
        problems = self.validate(raw)
        if problems:
            raise ValueError(
                f"{self.name}: source data cannot be normalised: "
                + "; ".join(problems))
        return self.normalize(raw)


# ------------------------------------------------------------- registry
registry: dict[str, type[DatasetAdapter]] = {}


def get_adapter(name: str) -> DatasetAdapter:
    if name not in registry:
        raise KeyError(
            f"No adapter named {name!r}. Registered: {sorted(registry)}")
    return registry[name]()
