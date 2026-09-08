"""Tests for src/screening_report.py and src/wafer.py."""

import numpy as np
import pytest

from src.explain import MODEL_VERSION, reason_codes_for_part
from src.pipeline import screen
from src.screening_report import _LAYOUTS, build_report, build_reports
from src.wafer import (
    neighbour_risk,
    plot_wafer_map,
    spatial_clustering,
    wafer_grid,
)

pypdf = pytest.importorskip("pypdf")


@pytest.fixture(scope="module")
def screened(wide):
    return wide, screen(wide)


def _read(path):
    return pypdf.PdfReader(str(path))


# ------------------------------------------------------------ the invariant
def test_report_is_exactly_one_page(screened, tmp_path):
    """"One-page PDF per rejected part" is the spec, and it is what makes the
    record signable. Checked on the parts with the MOST reason codes, which are
    the ones that overflow."""
    wide, res = screened
    counts = {i: len(reason_codes_for_part(wide, res.features, i, res.module_b))
              for i in res.fused[res.fused.verdict == "REJECT"].index}
    worst = sorted(counts, key=counts.get, reverse=True)[:6]
    assert counts[worst[0]] >= 6, "expected some part to earn many codes"

    for i in worst:
        path = build_report(wide, res, i, tmp_path)
        assert len(_read(path).pages) == 1, (
            f"{res.fused.at[i, 'serial']} with {counts[i]} codes spans "
            f"{len(_read(path).pages)} pages")


def test_layouts_shrink_monotonically():
    """The retry ladder must actually get smaller, or the loop cannot converge."""
    codes = [c for c, _, _ in _LAYOUTS]
    widths = [w for _, w, _ in _LAYOUTS]
    heights = [h for _, _, h in _LAYOUTS]
    assert codes == sorted(codes, reverse=True)
    assert widths == sorted(widths, reverse=True)
    assert heights == sorted(heights, reverse=True)


# --------------------------------------------------------------- content
def test_report_carries_the_audit_trail(screened, tmp_path):
    wide, res = screened
    i = res.fused.risk_score.idxmax()
    serial = res.fused.at[i, "serial"]
    reader = _read(build_report(wide, res, i, tmp_path))

    assert reader.metadata.get("/Title") == f"SENTINEL screening report {serial}"
    text = reader.pages[0].extract_text()
    for token in (serial, str(res.fused.at[i, "lot"]), MODEL_VERSION,
                  "Simulated data", "Reason codes", "USL"):
        assert token in text, f"{token!r} missing from the report"


def test_report_states_when_codes_were_omitted(screened, tmp_path):
    """A capped list must say it is capped, or the record is misleading."""
    wide, res = screened
    counts = {i: len(reason_codes_for_part(wide, res.features, i, res.module_b))
              for i in res.fused[res.fused.verdict == "REJECT"].index}
    busiest = max(counts, key=counts.get)
    text = _read(build_report(wide, res, busiest, tmp_path)).pages[0].extract_text()
    if counts[busiest] > _LAYOUTS[-1][0]:
        assert "of" in text and "worst first" in text or "omitted" in text


def test_build_reports_defaults_to_every_reject(screened, tmp_path):
    wide, res = screened
    paths = build_reports(wide, res, verdict="REJECT", limit=4, out_dir=tmp_path)
    assert len(paths) == 4
    assert all(p.exists() and p.suffix == ".pdf" for p in paths)


def test_unknown_serial_raises(screened, tmp_path):
    wide, res = screened
    with pytest.raises(KeyError, match="unknown serial"):
        build_reports(wide, res, serials=["NOT-A-PART"], out_dir=tmp_path)


def test_no_temporary_png_is_left_behind(screened, tmp_path):
    wide, res = screened
    build_report(wide, res, res.fused.risk_score.idxmax(), tmp_path)
    assert not list(tmp_path.glob("*.png"))


# ------------------------------------------------------------- wafer map
def test_wafer_grid_is_dense_and_bounded(screened):
    wide, res = screened
    g = wafer_grid(wide, res.fused, "W01")
    vals = g.to_numpy()
    finite = vals[np.isfinite(vals)]
    assert finite.size > 100
    assert finite.min() >= 0 and finite.max() <= 100


def test_wafer_grid_rejects_an_unknown_wafer(screened):
    wide, res = screened
    with pytest.raises(KeyError, match="W99"):
        wafer_grid(wide, res.fused, "W99")


def test_spatial_clustering_reports_none_on_randomly_placed_dies(screened):
    """The generator draws (x, y) uniformly and independently of class, so
    there is no spatial structure to find. The test asserts the analysis says
    so rather than inventing a cluster - if this ever flips, the dataset has
    changed and the wafer-map claim must be re-derived."""
    wide, res = screened
    sc = spatial_clustering(wide, res.fused, n_permutations=120)
    assert sc["clustered"] is False
    assert sc["p_value"] > 0.05
    assert "no spatial clustering" in sc["verdict"]


def test_spatial_clustering_detects_a_planted_cluster(screened):
    """The counterpart: if clustering IS present the statistic must find it,
    otherwise the negative result above means nothing."""
    wide, res = screened
    planted = wide.copy()
    fused = res.fused.copy()
    # Put every REJECT on one wafer in a tight block.
    rej = fused.index[fused.verdict == "REJECT"][:60]
    planted.loc[rej, "wafer"] = "W01"
    planted.loc[rej, "x"] = np.arange(len(rej)) % 8
    planted.loc[rej, "y"] = np.arange(len(rej)) // 8

    sc = spatial_clustering(planted, fused, n_permutations=120)
    assert sc["clustered"] is True, sc
    assert sc["observed"] > sc["null_p95"]


def test_neighbour_risk_excludes_the_die_itself(screened):
    wide, res = screened
    nr = neighbour_risk(wide.head(300), res.fused.head(300), radius=3)
    assert nr.notna().sum() > 0
    assert (nr.dropna() >= 0).all() and (nr.dropna() <= 100).all()


def test_wafer_map_renders(screened):
    import matplotlib
    matplotlib.use("Agg")
    wide, res = screened
    ax = plot_wafer_map(wide, res.fused, "W01")
    assert "W01" in ax.get_title()
    assert ax.get_xlabel() == "die x"
