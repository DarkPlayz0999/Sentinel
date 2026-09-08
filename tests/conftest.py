"""Shared fixtures.

The dataset is gitignored, so tests build their own rather than depending on a
populated data/. That keeps the suite green on a clean clone and makes every
test independent of whatever is currently sitting in the working directory.
"""

from pathlib import Path

import pandas as pd
import pytest

from src.generate_burnin_dataset import build

REPO = Path(__file__).resolve().parent.parent
COMMITTED_WIDE = REPO / "data" / "burnin_wide.csv"


@pytest.fixture(scope="session")
def dataset_dir(tmp_path_factory) -> Path:
    """One default-parameter build, shared by every test that needs data."""
    out = tmp_path_factory.mktemp("sentinel_data")
    build(outdir=out, verbose=False)
    return out


@pytest.fixture(scope="session")
def wide(dataset_dir) -> pd.DataFrame:
    return pd.read_csv(dataset_dir / "burnin_wide.csv")
