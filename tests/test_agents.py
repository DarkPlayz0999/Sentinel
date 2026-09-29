"""Agent team, phase 1: Data Quality -> (Anomaly || Forecast) -> Combine.

Each test uses a temporary database and checkpoint file (the `settings`
fixture), so nothing touches var/.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from backend.app.agents import graph as agents
from backend.app.core.config import get_settings
from backend.app.models.database_models import init_db
from backend.app.repositories.repositories import AgentRepository
from backend.app.services.dataset_service import DatasetService
from backend.app.services.screening_service import ScreeningService


@pytest.fixture()
def settings(tmp_path, monkeypatch):
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
def dataset_id(settings, wide) -> str:
    two_lots = (wide[wide.lot.isin(["L03", "L04"])]
                .drop(columns=["true_class", "is_latent_defect", "static_fail_168h"])
                .reset_index(drop=True))
    return DatasetService(settings).ingest(two_lots.to_csv(index=False).encode(),
                                           "lot.csv")["dataset_id"]


def _repo(settings) -> AgentRepository:
    return AgentRepository(settings.sqlite_path)


def _verdicts(run_id: str) -> dict[str, str]:
    return {c["serial"]: c["verdict"]
            for c in ScreeningService().list_components(run_id, limit=100_000)}


def test_valid_dataset_runs_three_agents_then_combines(settings, dataset_id):
    wf, created = agents.submit(dataset_id)
    assert created
    done = agents.execute(wf["workflow_id"])
    assert done["status"] == "COMPLETED"

    steps = _repo(settings).steps(wf["workflow_id"])
    assert [s["status"] for s in steps] == ["COMPLETED"] * 4
    order = [s["agent"] for s in steps]
    assert order[0] == "data_quality" and order[-1] == "combine"
    assert set(order[1:3]) == {"anomaly", "forecast"}     # same superstep
    assert done["summary"]["data_quality"]["hash_verified"] is True


def test_agents_reproduce_the_existing_screen_exactly(settings, dataset_id):
    """The agents call Module A/B; they must not change a single verdict."""
    wf, _ = agents.submit(dataset_id)
    agent_run = agents.execute(wf["workflow_id"])["summary"]["result"]["run_id"]

    svc = ScreeningService()
    direct_run = svc.create_run(dataset_id)
    svc.execute(direct_run)

    assert _verdicts(agent_run) == _verdicts(direct_run)


def test_resubmitting_the_same_dataset_is_idempotent(settings, dataset_id):
    a, created_a = agents.submit(dataset_id)
    b, created_b = agents.submit(dataset_id)
    assert created_a and not created_b
    assert a["workflow_id"] == b["workflow_id"]


def test_tampered_file_is_quarantined_and_nothing_downstream_runs(settings, dataset_id):
    ds = DatasetService().get(dataset_id)
    path = Path(settings.upload_dir) / ds["stored_path"]
    df = pd.read_csv(path)
    df.loc[0, "Iddq_uA_0h"] += 1.0                         # silent edit after upload
    df.to_csv(path, index=False)

    wf, _ = agents.submit(dataset_id)
    done = agents.execute(wf["workflow_id"])
    assert done["status"] == "QUARANTINED"
    assert done["run_id"] is None
    assert [s["agent"] for s in _repo(settings).steps(wf["workflow_id"])] == [
        "data_quality", "quarantine"]
    codes = {f["code"] for f in _repo(settings).findings(wf["workflow_id"])}
    assert {"DQ-HASH-MISMATCH", "DQ-QUARANTINE"} <= codes
    assert ScreeningService().runs.list() == []            # no run was created


def test_a_transient_io_error_is_retried(settings, dataset_id, monkeypatch):
    real = DatasetService.load_frame
    calls = {"n": 0}

    def flaky(self, did):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError("disk hiccup")
        return real(self, did)

    monkeypatch.setattr(DatasetService, "load_frame", flaky)
    wf, _ = agents.submit(dataset_id)
    assert agents.execute(wf["workflow_id"])["status"] == "COMPLETED"
    dq = [s for s in _repo(settings).steps(wf["workflow_id"]) if s["agent"] == "data_quality"]
    assert [s["status"] for s in dq] == ["FAILED", "COMPLETED"]


def test_failed_workflow_resumes_from_checkpoint(settings, dataset_id, monkeypatch):
    def boom(*a, **k):
        raise ValueError("forecast broke")                  # not transient: no retry

    real = agents.run_module_b
    monkeypatch.setattr(agents, "run_module_b", boom)
    wf, _ = agents.submit(dataset_id)
    with pytest.raises(ValueError):
        agents.execute(wf["workflow_id"])
    assert _repo(settings).get_workflow(wf["workflow_id"])["status"] == "FAILED"

    monkeypatch.setattr(agents, "run_module_b", real)
    done = agents.execute(wf["workflow_id"], resume=True)
    assert done["status"] == "COMPLETED"
    runs = [s["agent"] for s in _repo(settings).steps(wf["workflow_id"])]
    assert runs.count("data_quality") == 1                 # not re-run: checkpoint
    assert runs.count("forecast") == 2                     # failed once, then resumed


def test_flagged_parts_require_human_review_and_nothing_is_released(settings, dataset_id):
    wf, _ = agents.submit(dataset_id)
    done = agents.execute(wf["workflow_id"])
    result = done["summary"]["result"]
    assert result["human_review_required"] is True
    assert set(result["verdicts"]) <= {"ACCEPT", "WATCH", "REJECT"}
    codes = {f["code"] for f in _repo(settings).findings(wf["workflow_id"])}
    assert "HUMAN-REVIEW-REQUIRED" in codes


def test_api_submit_detail_and_event_stream(settings, dataset_id):
    from src.api import app
    client = TestClient(app)
    r = client.post(f"/v1/agents/workflows?dataset_id={dataset_id}&sync=true")
    assert r.status_code == 202
    wid = r.json()["workflow"]["workflow_id"]
    assert r.json()["workflow"]["status"] == "COMPLETED"

    again = client.post(f"/v1/agents/workflows?dataset_id={dataset_id}&sync=true").json()
    assert again["deduplicated"] is True and again["workflow"]["workflow_id"] == wid

    detail = client.get(f"/v1/agents/workflows/{wid}").json()
    assert {s["agent"] for s in detail["steps"]} == {
        "data_quality", "anomaly", "forecast", "combine"}
    assert client.get("/v1/agents/status").json()["agents"]["combine"]["status"] == "COMPLETED"

    body = client.get("/v1/agents/events?follow=false&since=0").text
    assert "event: workflow" in body and "event: step" in body
    assert f'"workflow_id": "{wid}"' in body


def test_submit_requires_the_api_key_when_one_is_configured(settings, dataset_id, monkeypatch):
    monkeypatch.setenv("SENTINEL_API_KEY", "secret")
    get_settings(refresh=True)
    from src.api import app
    client = TestClient(app)
    assert client.post(f"/v1/agents/workflows?dataset_id={dataset_id}").status_code == 401
