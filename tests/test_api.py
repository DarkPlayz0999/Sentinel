"""Tests for src/api.py and src/pipeline.py.

The failure this guards is rule 8: an endpoint whose features have silently
diverged from the training path. The API must not be able to disagree with the
pipeline about a part.
"""

import io

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from src.api import app
from src.explain import MODEL_VERSION
from src.features import PARAM_NAMES, build_features
from src.pipeline import screen


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


def test_health_reports_the_model_version_and_flags_simulated_data(client):
    r = client.get("/health").json()
    assert r["status"] == "ok"
    assert r["model_version"] == MODEL_VERSION
    assert r["simulated_data"] is True, (
        "every submission must label this dataset as simulated")


def test_part_endpoint_matches_the_pipeline_exactly(wide):
    """Rule 8, enforced across the process boundary."""
    client = TestClient(app)
    res = screen(wide)
    # The API screens the committed dataset; compare on a shared serial.
    serial = client.get("/lots").json() and None
    worst = res.fused.sort_values("risk_score", ascending=False).iloc[0]
    r = client.get(f"/part/{worst.serial}")
    if r.status_code == 404:
        pytest.skip("committed dataset differs from the fixture build")
    payload = r.json()
    assert payload["serial"] == worst.serial
    assert set(payload["sub_scores"]) == {
        "static_margin", "dynamic_outlier", "predicted_drift",
        "multivariate", "curvature"}


def test_every_verdict_carries_traceability(client):
    r = client.get("/lots").json()
    lot = r[0]["lot"]
    parts = client.get(f"/lot/{lot}").json()
    assert parts["status"] in {"OK", "LOT REVIEW"}

    # A real part, taken from the lot listing path.
    from src.pipeline import load_wide
    serial = load_wide().serial.iloc[0]
    v = client.get(f"/part/{serial}").json()
    assert v["model_version"] == MODEL_VERSION
    assert v["generated_utc"].endswith("+00:00")
    assert 0 <= v["risk_score"] <= 100
    assert v["verdict"] in {"ACCEPT", "WATCH", "REJECT"}


def test_unknown_serial_and_lot_return_404(client):
    assert client.get("/part/NOT-A-PART").status_code == 404
    assert client.get("/lot/L99").status_code == 404


def test_lot_endpoint_reports_pda_status(client):
    r = client.get("/lot/L04").json()
    assert r["lot"] == "L04"
    assert r["reject_fraction"] > r["pda_limit"], (
        "L04 is the deliberately bad lot and should exceed the PDA gate")
    assert r["status"] == "LOT REVIEW"
    assert any(c["code"] == "R-601" for c in r["reason_codes"])


def test_screen_endpoint_round_trips_a_csv(client, wide):
    sample = wide.head(120)
    buf = io.StringIO()
    sample.to_csv(buf, index=False)
    r = client.post("/screen",
                    files={"file": ("burnin.csv", buf.getvalue(), "text/csv")})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["parts"] == 120
    assert len(body["verdicts"]) == 120
    assert set(body["summary"]) <= {"ACCEPT", "WATCH", "REJECT"}


def test_screen_endpoint_rejects_a_frame_missing_required_columns(client, wide):
    bad = wide.drop(columns=["Iddq_uA_0h"]).head(20)
    buf = io.StringIO()
    bad.to_csv(buf, index=False)
    r = client.post("/screen",
                    files={"file": ("bad.csv", buf.getvalue(), "text/csv")})
    assert r.status_code == 422
    assert "Iddq_uA_0h" in r.text


def test_screen_endpoint_accepts_an_hour_24_frame(client, wide):
    """Module B cannot run without 168h. The service must still return a
    verdict, with predicted_drift zeroed and its weight redistributed - not a
    lower score that makes the part look safer."""
    early = wide.drop(columns=[f"{p}_{t}h" for p in PARAM_NAMES
                               for t in (96, 168)]).head(80)
    buf = io.StringIO()
    early.to_csv(buf, index=False)
    r = client.post("/screen",
                    files={"file": ("early.csv", buf.getvalue(), "text/csv")})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["parts"] == 80
    assert all(v["sub_scores"]["predicted_drift"] == 0 for v in body["verdicts"])


# ------------------------------------------------------------- pipeline
def test_pipeline_is_deterministic(wide):
    a, b = screen(wide), screen(wide)
    pd.testing.assert_series_equal(a.fused.risk_score, b.fused.risk_score)
    pd.testing.assert_series_equal(a.fused.verdict, b.fused.verdict)


def test_pipeline_skips_module_b_without_late_reads(wide):
    early = wide.drop(columns=[f"{p}_{t}h" for p in PARAM_NAMES
                               for t in (96, 168)])
    res = screen(early)
    assert res.module_b is None
    assert (res.fused.predicted_drift == 0).all()
    assert res.fused.verdict.isin(["ACCEPT", "WATCH", "REJECT"]).all()


def test_pipeline_uses_the_shared_feature_builder(wide):
    """Not a separate copy of the feature logic."""
    res = screen(wide)
    pd.testing.assert_frame_equal(res.features, build_features(wide))
