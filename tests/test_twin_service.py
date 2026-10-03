"""Digital twin through the service and the API: the closed loop.

Critical test (brief section 33): inject a fault into a board in BLIND mode,
run the whole screen, and prove Sentinel never received the component, the
fault label or any truth - and that ground truth is only opened after the
prediction exists.
"""

from __future__ import annotations

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from backend.app.core.config import get_settings
from backend.app.models.database_models import init_db
from backend.app.repositories.repositories import AgentRepository
from backend.app.repositories.simulation import GroundTruthRepository
from backend.app.services import simulation_service as sim_mod
from backend.app.services.dataset_service import DatasetService
from backend.app.services.simulation_service import SimulationService
from src.features import PARAM_NAMES


@pytest.fixture()
def settings(tmp_path, monkeypatch):
    monkeypatch.setenv("SENTINEL_DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setenv("SENTINEL_ARTIFACT_DIR", str(tmp_path / "artifacts"))
    monkeypatch.setenv("SENTINEL_UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setenv("SENTINEL_REPORT_DIR", str(tmp_path / "reports"))
    s = get_settings(refresh=True)
    s.ensure_dirs()
    init_db(s.sqlite_path)
    sim_mod._CACHE.clear()
    yield s
    sim_mod._CACHE.clear()
    get_settings(refresh=True)


@pytest.fixture()
def client(settings):
    from backend.app.main import create_app
    with TestClient(create_app()) as c:
        yield c


def _truth_forbidden(monkeypatch):
    """Make every door to ground truth explode. Screening must not need one."""
    def boom(*_a, **_k):
        raise AssertionError("ground truth was read before reveal")
    monkeypatch.setattr(GroundTruthRepository, "read", boom)
    from src.twin.engine import SimResult
    monkeypatch.setattr(SimResult, "truth_frame", boom)


@pytest.fixture()
def demo(client, monkeypatch):
    """The SIH demo, blind, screened and investigated - with truth forbidden.

    The simulator itself writes the ground-truth record when the soak ends
    (the simulator is allowed to know). From the moment the measurements go
    to Sentinel, every door to that truth raises.
    """
    sim = client.post("/v1/simulations", json={"scenario": "sih_demo",
                                               "auto_screen": False}).json()
    sid = sim["simulation_id"]
    r = client.post(f"/v1/simulations/{sid}/start?sync=true")
    assert r.status_code == 202 and r.json()["status"] == "SIMULATED", r.text
    _truth_forbidden(monkeypatch)
    r = client.post(f"/v1/simulations/{sid}/screen?sync=true")
    assert r.status_code == 202, r.text
    monkeypatch.undo()
    return client.get(f"/v1/simulations/{sid}").json()


# ----------------------------------------------------------------- identity
def test_board_endpoint_publishes_one_id_per_component(client):
    b = client.get("/v1/twin/board").json()
    ids = [c["component_id"] for c in b["board"]["components"]]
    assert len(ids) == len(set(ids)) and {"C001", "R001", "Q001", "U001", "J001"} <= set(ids)
    assert b["time_base"] == "ACCELERATED SIMULATION TIME"
    assert b["detectability"]["C002"]["ESR_INCREASE"] == []
    assert "ESR_INCREASE" in [f["fault_type"] for f in b["faults"]["capacitor"]]


# ----------------------------------------------------------------- creation
def test_create_validates_components_and_fault_types(client):
    ok = client.post("/v1/simulations", json={"boards": 40, "faults": [
        {"component_id": "Q001", "fault_type": "VTH_DRIFT", "severity": 0.5, "board": 3}]})
    assert ok.status_code == 201 and ok.json()["status"] == "CREATED"
    assert ok.json()["faults"][0]["board_serial"].endswith("-B004")      # VISIBLE shows it
    bad = client.post("/v1/simulations", json={"faults": [
        {"component_id": "C001", "fault_type": "VTH_DRIFT"}]})
    assert bad.status_code == 409
    assert client.post("/v1/simulations", json={"faults": [
        {"component_id": "C999", "fault_type": "ESR_INCREASE"}]}).status_code == 409
    assert client.post("/v1/simulations", json={"boards": 10}).status_code == 422


def test_step_advances_one_read_point_and_never_shows_the_future(client):
    sid = client.post("/v1/simulations", json={"boards": 40, "auto_screen": False}).json()[
        "simulation_id"]
    s = client.post(f"/v1/simulations/{sid}/step").json()
    assert s["status"] == "PAUSED" and s["sim_time_h"] == 0
    s = client.post(f"/v1/simulations/{sid}/step").json()
    assert s["sim_time_h"] == 24
    tl = client.get(f"/v1/simulations/{sid}/timeline",
                    params={"serial": f"{s['lot_id']}-B001"}).json()
    assert max(tl["hours"]) == 24
    assert all(r["time_h"] <= 24 for r in tl["observed"]["ate"]["Tpd_ns"])
    client.post(f"/v1/simulations/{sid}/step")
    s = client.post(f"/v1/simulations/{sid}/step").json()
    assert s["status"] == "SIMULATED" and s["sim_time_h"] == 168
    assert client.post(f"/v1/simulations/{sid}/step").status_code == 409


# ------------------------------------------------ THE critical blind test
def test_blind_sentinel_never_receives_the_component_or_the_fault(demo, settings):
    assert demo["mode"] == "BLIND"
    assert demo["status"] == "INVESTIGATED"          # screened and investigated with truth forbidden
    assert demo["faults"] == {"hidden": True, "count": "hidden until reveal"}

    frame = DatasetService(settings).load_frame(demo["dataset_id"])
    expected = ["serial", "lot"] + [f"{p}_{h}h" for p in PARAM_NAMES for h in (0, 24, 96, 168)]
    assert list(frame.columns) == expected
    blob = frame.to_csv(index=False)
    for leak in ("C001", "ESR", "ESR_INCREASE", "severity", "fault", "capacitor", "latent"):
        assert leak not in blob
    ds = DatasetService(settings).get(demo["dataset_id"])
    assert ds["source"] == "simulation"


def test_blind_api_withholds_truth_until_reveal(client, demo):
    sid, focus = demo["simulation_id"], demo["focus_serial"]
    tl = client.get(f"/v1/simulations/{sid}/timeline", params={"serial": focus}).json()
    assert tl["truth_visible"] is False and "truth" not in tl
    comps = client.get(f"/v1/simulations/{sid}/components", params={"serial": focus}).json()
    assert all("truth" not in c for c in comps["components"])
    assert all(c["failure_probability"] is None for c in comps["components"])
    lot = client.get(f"/v1/simulations/{sid}/boards").json()
    assert all("is_faulty" not in b for b in lot["boards"])


def test_reveal_is_refused_before_a_prediction_exists(client):
    sid = client.post("/v1/simulations", json={"mode": "BLIND", "boards": 40,
                                               "hidden_faults": {"count": 2}}).json()[
        "simulation_id"]
    r = client.post(f"/v1/simulations/{sid}/reveal")
    assert r.status_code == 409 and "after Sentinel" in r.json()["error"]["message"]


# --------------------------------------------- Sentinel + agent integration
def test_sentinel_screens_the_lot_and_the_agents_investigate(client, demo, settings):
    sid = demo["simulation_id"]
    assert sum(demo["verdicts"].values()) == 200
    run = client.get(f"/v1/screening/runs/{demo['run_id']}").json()     # existing API, reused
    assert run["status"] == "COMPLETED"

    repo = AgentRepository(settings.sqlite_path)
    phase1 = repo.get_workflow(demo["workflow_id"])
    assert phase1["status"] == "COMPLETED" and phase1["data_class"] == "simulated"
    inv = repo.get_workflow(demo["investigation_id"])
    assert inv["trigger"] == "sentinel_alert" and inv["status"] == "COMPLETED"
    assert [s["agent"] for s in repo.steps(inv["workflow_id"])] == [
        "diagnostic", "root_cause", "qa_safety", "report", "explainer"]
    codes = {f["code"] for f in repo.findings(inv["workflow_id"])}
    assert {"HUMAN-REVIEW-REQUIRED", "DIAG-SUSPECT", "AI-EXPLANATION"} <= codes
    assert demo["investigation"]["explanation"]["plain_summary"]

    rep = demo["investigation"]["report"]
    assert rep["focus_serial"] == demo["focus_serial"]
    assert rep["suspect_component"] == "C001" and rep["suspect_fault_type"] == "ESR_INCREASE"
    events = client.get(f"/v1/simulations/{sid}/events?follow=false").text
    for e in ("CHECKPOINT_REACHED", "MEASUREMENTS_SENT", "SENTINEL_RESULT",
              "SENTINEL_FLAGGED", "DIAGNOSIS_COMPLETE"):
        assert f"event: {e}" in events


def test_investigation_only_runs_on_a_flag():
    from backend.app.agents.investigation import investigate
    with pytest.raises(ValueError):
        investigate("sim_x", "ds_x", "run_x", [])


# ------------------------------------------------ replacement and compare
def test_replace_rerun_and_compare_before_after(client, demo):
    sid, focus = demo["simulation_id"], demo["focus_serial"]
    offer = client.get(f"/v1/simulations/{sid}/candidates",
                       params={"serial": focus, "component_id": "C001"}).json()
    assert len(offer["candidates"]) == 3 and "not a health" in offer["score_kind"]
    assert all("values" not in c for c in offer["candidates"])            # hidden truth
    best = offer["candidates"][0]["candidate_id"]
    cmp_ = client.post(f"/v1/simulations/{sid}/replace", json={
        "serial": focus, "component_id": "C001", "candidate_id": best}).json()
    r = cmp_["replacements"][0]
    assert r["before"]["verdict"] in ("REJECT", "WATCH")
    assert r["after"]["risk_score"] < r["before"]["risk_score"]
    assert r["after"]["ir_temp_c"] < r["before"]["ir_temp_c"]                # the hot spot is gone
    assert r["before"]["bench_removed_part"]["esr"] > 5 * r["after"]["incoming_inspection"]["esr"]
    assert "truth" not in r                                                   # still blind
    tl = client.get(f"/v1/simulations/{sid}/timeline",
                    params={"serial": focus, "phase": "rework-1"}).json()
    assert tl["phase"] == "rework-1" and max(tl["hours"]) == 168
    assert client.get(f"/v1/simulations/{sid}/candidates",
                      params={"serial": focus, "component_id": "PR001"}).status_code == 409


# ------------------------------------------------------- blind benchmark
def test_reveal_scores_the_prediction_through_the_one_scorer(client, demo):
    sid = demo["simulation_id"]
    rv = client.post(f"/v1/simulations/{sid}/reveal").json()
    assert rv["faults"][0]["component_id"] == "C001"
    assert rv["faulty_boards"][0]["serial"] == demo["focus_serial"]
    b = rv["benchmark"]
    assert b["confusion"]["tp"] == 1 and b["confusion"]["fn"] == 0
    assert b["localization"]["top1"] == 1.0
    assert "not reported" in b["accuracy"]                  # rule 5: never plain accuracy
    for k in ("recall", "precision", "f2", "pr_auc", "false_positive_rate"):
        assert k in b
    # After reveal the truth is visible.
    after = client.get(f"/v1/simulations/{sid}").json()
    assert after["truth_visible"] is True and after["faults"][0]["fault_type"] == "ESR_INCREASE"
    audit = client.get(f"/v1/simulations/{sid}/audit").json()
    assert any(e["event_type"] == "GROUND_TRUTH_REVEALED" for e in audit["events"])


def test_human_disposition_is_recorded_not_automated(client, demo):
    sid, focus = demo["simulation_id"], demo["focus_serial"]
    r = client.post(f"/v1/simulations/{sid}/boards/{focus}/decision",
                    json={"decision": "REWORK", "note": "replace C001"})
    assert r.status_code == 200 and r.json()["recorded"]
    ev = client.get(f"/v1/simulations/{sid}/events?follow=false").text
    assert "event: HUMAN_DISPOSITION" in ev


# ------------------------------------------------------ reproducibility
def test_a_restarted_service_rebuilds_the_same_lot(client, demo, settings):
    sid = demo["simulation_id"]
    before = client.get(f"/v1/simulations/{sid}/boards").json()
    sim_mod._CACHE.clear()                     # as if the server restarted
    after = client.get(f"/v1/simulations/{sid}/boards").json()
    assert before == after


# ------------------------------------------------------------ experiments
def test_experiment_campaign_runs_and_never_reports_accuracy(client):
    r = client.post("/v1/experiments?sync=true", json={
        "kind": "monte_carlo", "runs": 2, "boards": 60, "train_lots": 2, "seed": 7})
    assert r.status_code == 202, r.text
    e = r.json()
    assert e["status"] == "COMPLETED"
    o = e["summary"]["overall"]
    assert o["boards"] == 120 and "recall_at_overkill" in o and "localization" in o
    assert isinstance(o["accuracy"], str)
    assert e["summary"]["forecaster"]["trained_on_lots"] == 2
