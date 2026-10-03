"""SENTINEL AI: grounded, number-checked explanations (Mistral optional).

No test calls the real Mistral API: the model is replaced by a stand-in that
returns fixed text, so both paths are exercised - an answer whose numbers all
come from the facts (kept) and one that invents a number (discarded).
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from backend.app.ai import facts as F
from backend.app.ai import narrator
from backend.app.ai.narrator import check_numbers
from backend.app.core.config import get_settings
from backend.app.models.database_models import init_db
from backend.app.services import simulation_service as sim_mod


@pytest.fixture()
def settings(tmp_path, monkeypatch):
    monkeypatch.setenv("SENTINEL_DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setenv("SENTINEL_ARTIFACT_DIR", str(tmp_path / "artifacts"))
    monkeypatch.setenv("SENTINEL_UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setenv("SENTINEL_REPORT_DIR", str(tmp_path / "reports"))
    monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
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


@pytest.fixture()
def blind_sim(client):
    sim = client.post("/v1/simulations", json={"scenario": "sih_demo"}).json()
    r = client.post(f"/v1/simulations/{sim['simulation_id']}/start?sync=true")
    assert r.json()["status"] == "INVESTIGATED"
    return client.get(f"/v1/simulations/{sim['simulation_id']}").json()


# ------------------------------------------------------------ number check
FACTS = {"risk_score": 53.1, "recall": 0.25, "board": "SIM0001-B094", "component": "C001",
         "codes": [{"code": "R-401"}], "parts": 200}


def test_number_check_allows_rounding_percentages_and_known_ids():
    ok = "Board SIM0001-B094 scored 53.1 (about 53) and C001 was named under R-401; 25% of 200."
    assert check_numbers(ok, FACTS) == []


def test_number_check_accepts_rounding_but_not_a_different_value():
    facts = {"watch_band_starts_at_risk": 36.3, "evidence": 97.34}
    assert check_numbers("Watch starts near 36; evidence 97.3 (about 97).", facts) == []
    assert check_numbers("Watch starts near 37.", facts) == ["37"]


def test_numbers_with_unit_words_are_checked_as_numbers():
    facts = {"read_points_h": [0, 24, 96, 168], "temp": 125}
    assert check_numbers("After the 168-hour soak at 125C (a 24-hour early read)", facts) == []
    assert check_numbers("After the 200-hour soak", facts) == ["200"]


def test_number_check_rejects_invented_numbers_and_ids():
    bad = "Risk rose by 17.4 points and C002 is at fault; R-601 fired; 5% overall."
    rejected = check_numbers(bad, FACTS)
    assert {"17.4", "C002", "R-601", "5%"} <= set(rejected)


# ---------------------------------------------------------- without a key
def test_without_a_key_the_builtin_summary_is_used(client, blind_sim):
    st = client.get("/v1/ai/status").json()
    assert st["enabled"] is False and st["data_leaves_machine"] is False
    r = client.post("/v1/ai/summary", json={"context": "simulation", "id": blind_sim["simulation_id"]})
    out = r.json()
    assert r.status_code == 200 and out["source"] == "built-in"
    assert "simulated" in out["summary"].lower() and blind_sim["focus_serial"] in out["summary"]
    q = client.post("/v1/ai/ask", json={"context": "simulation", "id": blind_sim["simulation_id"],
                                        "question": "Which part failed?"}).json()
    assert q["source"] == "built-in" and "MISTRAL_API_KEY" in q["note"]


def test_blind_fact_sheet_never_contains_the_hidden_fault(settings, blind_sim):
    sheet = F.build("simulation", id=blind_sim["simulation_id"])
    blob = json.dumps(sheet["facts"])
    # The injected fault record never reaches the model. (The agents' own
    # diagnosis may name ESR_INCREASE - that is observed evidence, not truth.)
    assert sheet["facts"]["injected_faults"] == "hidden until the reveal (blind evaluation)"
    for truth_field in ("start_h", "growth_rate", "board_index", "after_reveal", "is_faulty"):
        assert truth_field not in blob


# ------------------------------------------------------------- with Mistral
def _fake_mistral(monkeypatch, text_for):
    monkeypatch.setenv("MISTRAL_API_KEY", "test-key-not-real")
    calls = []

    def fake_chat(messages, **kw):
        calls.append(messages)
        facts = json.loads(messages[1]["content"].split("Facts (JSON):\n", 1)[1].split("\n\n", 1)[0])
        return text_for(facts)

    monkeypatch.setattr(narrator, "chat", fake_chat)
    return calls


def test_a_grounded_mistral_answer_is_kept(client, blind_sim, monkeypatch):
    calls = _fake_mistral(monkeypatch, lambda f: (
        f"This simulated lot of {f['boards']} boards ranked {f['board_ranked_first_by_sentinel']} "
        f"first. The agents point to {f['investigation']['suspect_component']} with an evidence score "
        f"of {f['investigation']['evidence_score_out_of_100']}, which is a match score.\n"
        "- Check the replacement candidates."))
    out = client.post("/v1/ai/summary", json={"context": "simulation", "id": blind_sim["simulation_id"],
                                              "refresh": True}).json()
    assert out["source"] == "mistral" and out["number_check"] == "passed"
    assert out["next_steps"] == ["Check the replacement candidates."]
    # The system prompt carries the rules; the facts are the only data sent.
    assert "NOT probabilities" in calls[0][0]["content"] or "not probabilities" in calls[0][0]["content"].lower()


def test_an_answer_with_an_invented_number_is_discarded(client, blind_sim, monkeypatch):
    _fake_mistral(monkeypatch, lambda f: "The board has a 92% chance of failing within 3000 hours.")
    out = client.post("/v1/ai/summary", json={"context": "simulation", "id": blind_sim["simulation_id"],
                                              "refresh": True}).json()
    assert out["source"] == "built-in" and out["number_check"] == "rejected"
    assert "92%" in out["rejected_numbers"] and "discarded" in out["note"]


def test_summaries_are_cached_until_the_facts_change(client, blind_sim, monkeypatch):
    calls = _fake_mistral(monkeypatch, lambda f: f"Lot of {f['boards']} simulated boards.")
    body = {"context": "simulation", "id": blind_sim["simulation_id"]}
    a = client.post("/v1/ai/summary", json=body).json()
    b = client.post("/v1/ai/summary", json=body).json()
    assert a["cached"] is False and b["cached"] is True and len(calls) == 1


def test_bad_context_arguments_are_refused(client):
    assert client.post("/v1/ai/summary", json={"context": "part"}).status_code == 409
    assert client.post("/v1/ai/summary", json={"context": "nonsense"}).status_code == 422
