"""Tests for the backend service layer.

Kept separate from the existing suite so `src/` remains testable with no
database, no config and no web server - which is what the reproducibility story
and the 150 existing tests depend on.

Every test here runs against a temporary database and artifact directory, so a
run never touches the developer's `var/`.
"""

from __future__ import annotations

import io
import json

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from src.features import PARAM_NAMES
from src.fusion import RiskWeights

from backend.app.adapters import get_adapter, wide_from_long
from backend.app.core.config import Settings, get_settings
from backend.app.core.exceptions import DatasetValidationError
from backend.app.ml.inference import dataframe_sha256
from backend.app.models.database_models import init_db
from backend.app.services.dataset_service import DatasetService
from backend.app.services.screening_service import ScreeningService
from backend.app.validation.dataset_validator import validate_dataset


# ---------------------------------------------------------------- fixtures
@pytest.fixture()
def settings(tmp_path, monkeypatch) -> Settings:
    """An isolated service instance per test."""
    monkeypatch.setenv("SENTINEL_DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setenv("SENTINEL_ARTIFACT_DIR", str(tmp_path / "artifacts"))
    monkeypatch.setenv("SENTINEL_UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setenv("SENTINEL_REPORT_DIR", str(tmp_path / "reports"))
    s = get_settings(refresh=True)
    s.ensure_dirs()
    init_db(s.sqlite_path)
    yield s
    get_settings(refresh=True)


@pytest.fixture()
def client(settings) -> TestClient:
    from src.api import app
    return TestClient(app)


@pytest.fixture()
def two_lots(wide) -> pd.DataFrame:
    """A screenable frame with two lots, labels stripped as an upload would be."""
    return (wide[wide.lot.isin(["L03", "L04"])]
            .drop(columns=["true_class", "is_latent_defect", "static_fail_168h"])
            .reset_index(drop=True))


def _csv(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode()


# ================================================================ validation
def test_the_shipped_dataset_validates_cleanly(wide):
    rep = validate_dataset(wide)
    assert rep.ok, [f.as_dict() for f in rep.errors]
    assert rep.read_points == [0, 24, 96, 168]
    assert rep.module_b_available


def test_missing_required_columns_is_a_blocking_error(two_lots):
    rep = validate_dataset(two_lots.drop(columns=["Iddq_uA_0h"]))
    assert not rep.ok
    assert any(f.error_code == "MISSING_REQUIRED_COLUMNS" for f in rep.errors)


def test_duplicate_serials_block(two_lots):
    bad = two_lots.copy()
    bad.loc[1, "serial"] = bad.loc[0, "serial"]
    rep = validate_dataset(bad)
    assert not rep.ok
    assert any(f.error_code == "DUPLICATE_SERIAL" for f in rep.errors)


def test_negative_current_blocks_and_is_never_silently_repaired(two_lots):
    bad = two_lots.copy()
    bad.loc[0, "Ileak_nA_0h"] = -12.5
    rep = validate_dataset(bad)
    assert not rep.ok
    assert any(f.error_code == "NEGATIVE_CURRENT" for f in rep.errors)
    # The frame itself is untouched: validation reports, it does not coerce.
    assert bad.loc[0, "Ileak_nA_0h"] == -12.5


def test_non_numeric_measurement_blocks(two_lots):
    bad = two_lots.copy()
    bad["Iddq_uA_24h"] = bad["Iddq_uA_24h"].astype(object)
    bad.loc[0, "Iddq_uA_24h"] = "not-a-number"
    rep = validate_dataset(bad)
    assert any(f.error_code == "INVALID_NUMERIC" for f in rep.errors)


def test_a_missing_96h_read_is_a_warning_not_an_error(two_lots):
    """The generator drops ~1.2% of 96h reads; that must not block a screen."""
    rep = validate_dataset(two_lots.drop(
        columns=[f"{p}_96h" for p in PARAM_NAMES]))
    assert rep.ok
    assert any(f.error_code == "NO_MID_READ" for f in rep.warnings)


def test_an_hour_24_frame_is_valid_with_a_warning(two_lots):
    rep = validate_dataset(two_lots.drop(
        columns=[f"{p}_{t}h" for p in PARAM_NAMES for t in (96, 168)]))
    assert rep.ok, "an hour-24 triage frame is a legitimate submission"
    assert not rep.module_b_available
    assert any(f.error_code == "NO_FINAL_READ" for f in rep.warnings)


def test_small_lots_warn_because_robust_statistics_need_a_population(two_lots):
    rep = validate_dataset(two_lots.head(10))
    assert any(f.error_code == "INSUFFICIENT_LOT_POPULATION" for f in rep.warnings)


# ================================================================== upload
def test_upload_registers_and_hashes(client, two_lots):
    r = client.post("/v1/datasets/upload",
                    files={"file": ("lot.csv", _csv(two_lots), "text/csv")})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["rows"] == len(two_lots)
    assert body["lots"] == 2
    assert body["sha256"] == dataframe_sha256(two_lots)
    assert body["deduplicated"] is False


def test_identical_content_is_deduplicated(client, two_lots):
    a = client.post("/v1/datasets/upload",
                    files={"file": ("a.csv", _csv(two_lots), "text/csv")}).json()
    b = client.post("/v1/datasets/upload",
                    files={"file": ("b.csv", _csv(two_lots), "text/csv")}).json()
    assert b["dataset_id"] == a["dataset_id"]
    assert b["deduplicated"] is True


def test_malformed_csv_returns_a_structured_error(client):
    r = client.post("/v1/datasets/upload",
                    files={"file": ("x.csv", b"\x00\x01\x02 not a csv", "text/csv")})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "DATASET_SCHEMA_INVALID"


def test_invalid_upload_is_not_stored(client, settings, two_lots):
    before = len(DatasetService(settings).list())
    client.post("/v1/datasets/upload",
                files={"file": ("bad.csv",
                                _csv(two_lots.drop(columns=["Iddq_uA_0h"])),
                                "text/csv")})
    assert len(DatasetService(settings).list()) == before, (
        "a dataset that failed validation must leave no row behind")


def test_error_responses_share_one_envelope(client):
    r = client.get("/v1/screening/runs/run_nope")
    assert r.status_code == 404
    err = r.json()["error"]
    assert set(err) >= {"code", "message", "details"}
    assert err["code"] == "NOT_FOUND"
    assert "X-Request-ID" in r.headers


# ================================================= runs, persistence, audit
@pytest.fixture()
def completed_run(client, settings, two_lots):
    ds = client.post("/v1/datasets/upload",
                     files={"file": ("lot.csv", _csv(two_lots), "text/csv")}).json()
    job = client.post(
        f"/v1/screening/runs?dataset_id={ds['dataset_id']}&sync=true").json()
    return ds, job["run_id"]


def test_a_run_persists_every_component(client, completed_run, two_lots):
    _, run_id = completed_run
    run = client.get(f"/v1/screening/runs/{run_id}").json()
    assert run["status"] == "COMPLETED"
    assert sum(run["summary"].values()) == len(two_lots)
    rows = client.get(
        f"/v1/screening/runs/{run_id}/components?limit=2000").json()
    assert len(rows) == len(two_lots)


def test_a_run_records_everything_needed_to_reproduce_it(client, completed_run):
    ds, run_id = completed_run
    rp = client.get(f"/v1/screening/runs/{run_id}/reproducibility").json()
    assert rp["dataset"]["sha256"] == ds["sha256"]
    assert rp["configuration"]["config_hash"].startswith("cfg-")
    assert rp["versions"]["pipeline_version"]
    assert rp["versions"]["feature_version"]
    assert rp["versions"]["policy_version"]


def test_the_audit_trail_records_the_run_and_every_rejection(client, completed_run):
    _, run_id = completed_run
    events = client.get(
        f"/v1/screening/runs/{run_id}/audit?limit=2000").json()
    kinds = {e["event_type"] for e in events}
    assert "RUN_CREATED" in kinds and "RUN_COMPLETED" in kinds

    rejected = {r["serial"] for r in client.get(
        f"/v1/screening/runs/{run_id}/components?verdict=REJECT&limit=2000").json()}
    audited = {e["serial"] for e in events
               if e["event_type"] == "COMPONENT_REJECTED"}
    assert rejected == audited, "every rejection must have an audit event"


def test_lot_disposition_applies_the_pda_gate(client, completed_run, settings):
    _, run_id = completed_run
    run = client.get(f"/v1/screening/runs/{run_id}").json()
    for lot in run["lot_summary"]:
        expected = "LOT REVIEW" if lot["reject_fraction"] > settings.pda_limit else "OK"
        assert lot["status"] == expected


def test_screening_is_reproducible_across_runs(client, completed_run, two_lots):
    """Same dataset, same config, same model -> identical decisions."""
    ds, first = completed_run
    second = client.post(
        f"/v1/screening/runs?dataset_id={ds['dataset_id']}&sync=true").json()["run_id"]

    def by_serial(run_id):
        return {r["serial"]: (r["verdict"], round(r["risk_score"], 6))
                for r in client.get(
                    f"/v1/screening/runs/{run_id}/components?limit=2000").json()}

    assert by_serial(first) == by_serial(second)


# ============================================ explanation / verdict coupling
def test_every_non_accept_component_has_a_primary_reason(client, completed_run):
    """THE invariant. A REJECT with no explanation is the failure this
    architecture exists to prevent."""
    _, run_id = completed_run
    rows = client.get(
        f"/v1/screening/runs/{run_id}/components?limit=2000").json()
    offenders = [r["serial"] for r in rows
                 if r["verdict"] != "ACCEPT"
                 and not (r["explanation"] or {}).get("primary_reason")]
    assert not offenders, f"non-ACCEPT with no primary reason: {offenders[:5]}"


def test_no_component_reports_an_integrity_warning(client, completed_run):
    _, run_id = completed_run
    rows = client.get(
        f"/v1/screening/runs/{run_id}/components?limit=2000").json()
    flagged = [r["serial"] for r in rows
               if (r["explanation"] or {}).get("primary_reason", {})
               .get("integrity_warning")]
    assert not flagged, f"unattributed risk on {flagged[:5]}"


def test_the_decision_path_sums_to_the_risk_score(client, completed_run):
    _, run_id = completed_run
    for r in client.get(
            f"/v1/screening/runs/{run_id}/components?limit=200").json():
        total = sum(e["contribution"] for e in r["explanation"]["decision_path"])
        assert total == pytest.approx(r["risk_score"], abs=0.05), (
            f"{r['serial']}: decision path sums to {total}, "
            f"risk score is {r['risk_score']}")


def test_a_claimed_reason_code_actually_fired(client, completed_run):
    """A reason may name a code only when that code really triggered."""
    _, run_id = completed_run
    for r in client.get(
            f"/v1/screening/runs/{run_id}/components?limit=300").json():
        ex = r["explanation"]
        fired = {c["code"] for c in ex["reason_codes"]}
        for reason in [ex["primary_reason"], *ex["supporting_reasons"]]:
            if reason and reason.get("code"):
                assert reason["code"] in fired, (
                    f"{r['serial']} claims {reason['code']} which did not fire")


def test_accepted_components_carry_no_high_severity_code(client, completed_run):
    _, run_id = completed_run
    for r in client.get(
            f"/v1/screening/runs/{run_id}/components?verdict=ACCEPT&limit=2000").json():
        high = [c["code"] for c in r["reason_codes"] if c["severity"] == "high"]
        assert not high, f"ACCEPT {r['serial']} carries high-severity {high}"


def test_the_hero_case_is_rejected_and_explained_lot_relatively(client, completed_run):
    """L04-0348 passes every static limit and must still be rejected, with an
    explanation that names the lot-relative abnormality rather than something
    else. This is the project's own worked example."""
    _, run_id = completed_run
    r = client.get(
        f"/v1/screening/runs/{run_id}/components/L04-0348").json()

    assert r["verdict"] == "REJECT"
    assert r["static_breach"] is False, "the point is that static limits pass it"

    codes = {c["code"] for c in r["reason_codes"]}
    assert "R-102" in codes, (
        "R-102 states the lot-relative drift anomaly the verdict turns on")

    r102 = next(c for c in r["reason_codes"] if c["code"] == "R-102")
    assert r102["feature_value"] > 6.0
    assert "robust sigma" in r102["message"]
    assert "lot" in r102["message"].lower()

    reasons = [r["explanation"]["primary_reason"],
               *r["explanation"]["supporting_reasons"]]
    assert any((x or {}).get("code") == "R-102" for x in reasons), (
        "the lot-relative finding must appear in the explanation, not only "
        "in the raw code list")


# ================================================= module A / B structure
def test_module_a_evidence_is_layered_and_carries_its_thresholds(client, completed_run):
    _, run_id = completed_run
    ev = client.get(
        f"/v1/screening/runs/{run_id}/components/L04-0348").json()["evidence"]
    assert set(ev) >= {"static", "lot_relative", "multivariate", "curvature"}
    assert ev["static"]["verdict"] in {"PASS", "BREACH"}
    assert ev["lot_relative"]["dpat_limit_sigma"] == 6.0
    assert ev["lot_relative"]["worst"]["parameter"] in PARAM_NAMES
    assert ev["multivariate"]["threshold"] > 0
    assert len(ev["multivariate"]["contributions"]) == len(PARAM_NAMES)


def test_module_b_separates_observed_from_forecast(client, completed_run):
    _, run_id = completed_run
    mb = client.get(
        f"/v1/screening/runs/{run_id}/components/L04-0348"
    ).json()["evidence"]["module_b"]

    assert mb["available"] is True
    assert mb["inputs_used"] == ["0h", "24h"]
    assert mb["forecast"]["is_prediction"] is True
    assert mb["forecast"]["target"] == "168h"
    assert mb["forecast"]["upper_bound_quantile"] == 0.90
    # The measured 168h value must never appear inside the forecast block.
    assert "168h" in mb["observed"]
    assert mb["observed"]["168h"] != mb["forecast"]["point_estimate"]


# ======================================================== data leakage
def test_module_b_features_use_no_late_reads_or_labels(wide):
    """Regression guard for the single most dangerous bug in this project.

    Rebuilds the forecast features from a frame with every 96h/168h column and
    every label deleted, and requires an identical result.
    """
    from src.features import build_forecast_features

    stripped = wide.drop(columns=(
        [f"{p}_{t}h" for p in PARAM_NAMES for t in (96, 168)]
        + ["true_class", "is_latent_defect", "static_fail_168h"]))

    for p in PARAM_NAMES:
        full = build_forecast_features(wide, p)
        early = build_forecast_features(stripped, p)
        pd.testing.assert_frame_equal(full, early)


def test_early_feature_names_contain_no_late_view():
    from src.features import early_feature_names
    for name in early_feature_names():
        assert "168h" not in name and "drift" not in name and "curvature" not in name


def test_a_trained_forecaster_never_sees_a_label(wide):
    """The design matrix Module B trains on must contain no outcome column."""
    from src.module_b import PowerLawForecaster

    m = PowerLawForecaster(use_gbm=False)
    m.exponents = {p: 0.4 for p in PARAM_NAMES}
    for p in PARAM_NAMES:
        X, _ = m._design(wide, p, 0.4)
        cols = set(X.columns)
        assert not cols & {"true_class", "is_latent_defect", "static_fail_168h"}
        assert not any("168" in c or "96" in c for c in cols)


# ========================================================== model registry
def test_performance_reports_baselines_and_names_where_it_loses(client, settings, wide):
    """The honesty requirement: a parameter the model loses on is reported."""
    from backend.app.services.model_service import ModelService

    small = wide[wide.lot.isin(["L01", "L02"])]
    ModelService(settings).train(small, seed=42, actor="test")

    perf = client.get("/v1/models/performance").json()
    assert perf["available"] is True
    assert perf["validation"] == "GroupKFold(groups=lot)"
    for row in perf["parameters"]:
        assert {"model_mae", "linear_baseline_mae",
                "last_value_baseline_mae", "beats_last_value"} <= set(row)
    # Tpd_ns and Vol_mV fit an exponent of 0 and lose to last-value. The
    # endpoint must say so rather than average it away.
    assert any(not r["beats_last_value"] for r in perf["parameters"])
    assert "LOSES" in perf["honest_summary"] or "does NOT beat" in perf["honest_summary"]


def test_a_tampered_artifact_is_refused(settings, wide, tmp_path):
    """Serving predictions from bytes that are not the recorded bytes would
    destroy the reproducibility claim, so the load must fail."""
    from backend.app.core.exceptions import ModelInferenceError
    from backend.app.ml.inference import (
        load_forecaster_file, save_forecaster, train_forecaster,
    )

    model, _ = train_forecaster(wide[wide.lot.isin(["L01", "L02"])],
                                with_metrics=False)
    path = tmp_path / "fc.joblib"
    sha = save_forecaster(model, path)

    assert load_forecaster_file(path, sha) is not None
    path.write_bytes(path.read_bytes() + b"tampered")
    with pytest.raises(ModelInferenceError, match="checksum"):
        load_forecaster_file(path, sha)


def test_inference_does_not_refit_the_model(settings, wide):
    """A screen given an artifact must produce identical output twice and must
    not call the training path."""
    from src.pipeline import screen
    from backend.app.ml.inference import train_forecaster

    frame = wide[wide.lot.isin(["L01", "L02"])]
    model, _ = train_forecaster(frame, with_metrics=False)

    a = screen(frame, forecaster=model, forecaster_is_out_of_fold=False)
    b = screen(frame, forecaster=model, forecaster_is_out_of_fold=False)
    pd.testing.assert_series_equal(a.fused.risk_score, b.fused.risk_score)
    pd.testing.assert_series_equal(a.fused.verdict, b.fused.verdict)


# =============================================================== health
def test_health_probes_answer_different_questions(client):
    assert client.get("/health/live").json()["status"] == "alive"
    ready = client.get("/health/ready").json()
    assert "database" in ready["checks"]
    models = client.get("/health/models").json()
    assert "inference_mode" in models


def test_config_endpoint_never_exposes_the_api_key(client, monkeypatch):
    monkeypatch.setenv("SENTINEL_API_KEY", "super-secret-value")
    get_settings(refresh=True)
    body = client.get("/v1/config").json()
    assert "super-secret-value" not in json.dumps(body)
    assert body["auth_required"] is True
    get_settings(refresh=True)


# ============================================================== adapters
def test_the_native_adapter_round_trips_without_loss(wide):
    df = wide.head(50)
    res = get_adapter("sentinel-burnin-csv").to_standard_schema(df)
    back = wide_from_long(res.long)

    cols = ["serial", "Iddq_uA_0h", "Iddq_uA_168h", "Vol_mV_24h"]
    pd.testing.assert_frame_equal(
        df[cols].set_index("serial").sort_index(),
        back[cols].set_index("serial").sort_index(),
        check_dtype=False)


def test_normalisation_never_invents_a_missing_measurement(wide):
    """A dropped 96h handler read must stay absent, not become a value."""
    df = wide.head(300)
    res = get_adapter("sentinel-burnin-csv").to_standard_schema(df)
    emitted = len(res.long)
    measured = int(sum(df[f"{p}_{t}h"].notna().sum()
                       for p in PARAM_NAMES for t in (0, 24, 96, 168)))
    assert emitted == measured


def test_thermal_context_is_reported_absent_rather_than_assumed(wide):
    """This dataset has no per-component telemetry. Assuming 125 C would
    fabricate a measurement."""
    res = get_adapter("sentinel-burnin-csv").to_standard_schema(wide.head(20))
    assert res.thermal_context_available is False
    assert res.long["temperature_c"].isna().all()


def test_an_adapter_declares_its_provenance(wide):
    res = get_adapter("sentinel-burnin-csv").to_standard_schema(wide.head(5))
    p = res.provenance
    assert p.source_dataset and p.source_device_type and p.source_stress_condition
    # Only the native format may claim equivalence with the burn-in problem.
    assert p.equivalent_to_burn_in is True


# ================================================== out-of-fold honesty
def test_out_of_fold_is_false_for_parts_the_model_was_trained_on(settings, wide):
    """Out-of-fold is a claim about PARTS, not about file hashes.

    A subset of the training frame hashes differently while every component in
    it was in the fit. Reporting that as out-of-fold would overstate the
    forecast's validity, which is the kind of quiet inflation this project
    exists to avoid.
    """
    from backend.app.ml.inference import dataframe_sha256
    from backend.app.services.model_service import ModelService

    train = wide[wide.lot.isin(["L01", "L02"])]
    svc = ModelService(settings)
    svc.train(train, seed=42, actor="test")
    loaded = svc.loaded()
    assert loaded is not None and loaded.training_serials

    seen = train.head(30)
    assert loaded.is_out_of_fold_for(
        dataframe_sha256(seen), set(seen["serial"])) is False

    unseen = seen.copy()
    unseen["serial"] = "UNSEEN-" + unseen["serial"].astype(str)
    assert loaded.is_out_of_fold_for(
        dataframe_sha256(unseen), set(unseen["serial"])) is True


def test_the_artifact_records_which_parts_it_was_fitted_on(settings, wide, tmp_path):
    from backend.app.ml.inference import (
        load_forecaster_file, save_forecaster, train_forecaster,
    )

    frame = wide[wide.lot.isin(["L01", "L02"])]
    model, _ = train_forecaster(frame, with_metrics=False)
    path = tmp_path / "fc.joblib"
    sha = save_forecaster(model, path,
                          training_serials=set(frame["serial"].astype(str)))

    payload = load_forecaster_file(path, sha, return_payload=True)
    assert payload["training_serials"] == set(frame["serial"].astype(str))
    assert payload["seed"] == 42
    # The plain call still returns just the model, for every other caller.
    assert load_forecaster_file(path, sha) is not None
