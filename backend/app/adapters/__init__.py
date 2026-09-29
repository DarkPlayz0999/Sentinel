"""Dataset adapters.

Implemented
-----------
* `sentinel-burnin-csv` - the native wide burn-in format. Working, tested, and
  the reference implementation of the `DatasetAdapter` contract.

NOT implemented, and deliberately not stubbed
---------------------------------------------
NASA's accelerated-ageing sets (MOSFET thermal-overstress, IGBT) are the
obvious external validation targets, and the adapter interface exists so they
can be added without touching `src/`. They are NOT included here because the
data is not in this repository, and an adapter written against a schema nobody
in this project has loaded would be scaffolding presented as a capability.

What an author of one has to supply, and why it is not a small job:

  parameter mapping   NASA MOSFET ageing records drain-source ON resistance,
                      package temperature and gate voltage. None of those is
                      Iddq, Ileak, Tpd or Vol. There is no honest rename - a
                      new parameter must be registered with its OWN unit and
                      its own limit, or the run must be treated as
                      parameter-agnostic drift detection.

  timepoint mapping   NASA data is a continuous time series under cycling
                      stress, not four discrete read points at a fixed soak.
                      `map_timepoints` must decide which elapsed hours are
                      comparable read points, and that decision is a modelling
                      choice that belongs in a reviewable method, not in an
                      import script.

  lot semantics       SENTINEL's entire method is lot-relative. NASA's sets are
                      small collections of individually-instrumented devices
                      with no production lot structure. Without a peer
                      population there is nothing to be relative TO, and the
                      lot-relative layers do not apply as written.

  provenance          `SourceProvenance.equivalent_to_burn_in` must stay False.

So: the seam is built and proven by a working adapter, and the external sets
are named as future validation work rather than claimed as supported. Any run
on adapted data records the adapter name on the dataset row, so a result from
one can never be mistaken for a result from the other.
"""

from backend.app.adapters.base import (  # noqa: F401
    AdapterResult, DatasetAdapter, MeasurementRecord, SourceProvenance,
    get_adapter, registry,
)
from backend.app.adapters.sentinel_csv import (  # noqa: F401
    SentinelCsvAdapter, wide_from_long,
)

__all__ = [
    "AdapterResult", "DatasetAdapter", "MeasurementRecord", "SourceProvenance",
    "SentinelCsvAdapter", "get_adapter", "registry", "wide_from_long",
]
