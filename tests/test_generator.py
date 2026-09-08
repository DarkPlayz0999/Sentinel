"""Tests for src/generate_burnin_dataset.py.

The generator gained a per-parameter noise argument so that src/sensitivity.py
can quantify how much of the recall ceiling is metrology. That argument is only
safe if the default path still produces the committed dataset exactly - every
number in the repo and every figure on a slide is built on it.

These tests exist to make that guarantee mechanical rather than a promise.
"""

import hashlib
from pathlib import Path

import pandas as pd
import pytest

from src.features import PARAM_NAMES
from src.generate_burnin_dataset import MEAS_NOISE, build, default_noise

REPO = Path(__file__).resolve().parent.parent
COMMITTED_WIDE = REPO / "data" / "burnin_wide.csv"

FILES = ("burnin_wide.csv", "burnin_long.csv", "public_train.csv",
         "hidden_test.csv", "ground_truth.csv")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_default_build_is_bit_for_bit_reproducible(tmp_path):
    """Seed 42, twice, into two directories. Judges re-run the repo."""
    a, b = tmp_path / "a", tmp_path / "b"
    build(outdir=a, verbose=False)
    build(outdir=b, verbose=False)
    for f in FILES:
        assert sha(a / f) == sha(b / f), f"{f} is not reproducible"


@pytest.mark.skipif(not COMMITTED_WIDE.exists(),
                    reason="data/ not generated in this working tree")
def test_default_build_still_matches_the_committed_dataset(tmp_path):
    """The guarantee the noise argument had to preserve.

    If this fails, every metric in the README and every slide figure is stale -
    do not 'fix' it by regenerating data/.
    """
    build(outdir=tmp_path, verbose=False)
    assert sha(tmp_path / "burnin_wide.csv") == sha(COMMITTED_WIDE)


def test_default_noise_is_flat_across_parameters():
    assert default_noise() == {p: MEAS_NOISE for p in PARAM_NAMES}


def test_changing_one_parameters_noise_leaves_the_others_untouched(tmp_path):
    """The claim in build()'s docstring, made testable.

    ``RNG.normal(0, scale)`` consumes the same draws whatever the scale, so
    lowering the noise on Tpd must not shift the random stream for Iddq. If it
    did, the sensitivity analysis would be comparing two different populations
    and its conclusion would be worthless.
    """
    base, quiet = tmp_path / "base", tmp_path / "quiet"
    build(outdir=base, verbose=False)
    build(outdir=quiet, noise={"Tpd_ns": 0.001}, verbose=False)

    a = pd.read_csv(base / "burnin_wide.csv")
    b = pd.read_csv(quiet / "burnin_wide.csv")

    # Labels and identity are untouched.
    pd.testing.assert_series_equal(a.serial, b.serial)
    pd.testing.assert_series_equal(a.true_class, b.true_class)

    # Every column of every other parameter is bit-identical.
    for p in PARAM_NAMES:
        for t in (0, 24, 96, 168):
            col = f"{p}_{t}h"
            if p == "Tpd_ns":
                continue
            pd.testing.assert_series_equal(a[col], b[col], check_exact=True,
                                           obj=f"{col} moved when only Tpd noise changed")

    # And Tpd itself did change.
    assert not a["Tpd_ns_168h"].equals(b["Tpd_ns_168h"])


def test_lower_noise_reduces_measurement_scatter(tmp_path):
    """Sanity: the knob does what it says.

    Measured on healthy parts' 0h->24h movement, which is almost pure noise
    over such a short window.
    """
    loud, quiet = tmp_path / "loud", tmp_path / "quiet"
    build(outdir=loud, noise={"Tpd_ns": 0.030}, verbose=False)
    build(outdir=quiet, noise={"Tpd_ns": 0.002}, verbose=False)

    def scatter(d):
        df = pd.read_csv(d / "burnin_wide.csv")
        h = df[df.true_class == "healthy"]
        return (h.Tpd_ns_24h - h.Tpd_ns_0h).std()

    assert scatter(quiet) < 0.3 * scatter(loud)


def test_headline_dataset_facts_hold(wide):
    """The three numbers the pitch rests on."""
    assert len(wide) == 2100
    assert wide.lot.nunique() == 6
    assert int(wide.is_latent_defect.sum()) == 174

    latent = wide[wide.is_latent_defect == 1]
    assert int(latent.static_fail_168h.sum()) == 0, (
        "the headline claim is that 100% of latent defects pass static limits"
    )


def test_gross_failures_are_not_all_caught_by_static_limits(wide):
    """Corrects blueprint section 12, which records 63.

    Eight of the 63 gross parts never breach a datasheet limit at 168h, so
    static screening flags 55. Locked down because it is a slide number.
    """
    assert int((wide.true_class == "gross").sum()) == 63
    assert int(wide.static_fail_168h.sum()) == 55
    assert int(wide[wide.true_class != "gross"].static_fail_168h.sum()) == 0
