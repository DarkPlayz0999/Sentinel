"""Smoke tests for app/dashboard.py.

A dashboard that raises on one screen is worse than no dashboard: it fails
during the demo, in front of the judges, on the one screen you skipped.
``AppTest`` actually executes the script, which an HTTP request against the
server does not - Streamlit only runs it when a session connects.
"""

from pathlib import Path

import pytest

streamlit_testing = pytest.importorskip("streamlit.testing.v1")
AppTest = streamlit_testing.AppTest

APP = Path(__file__).resolve().parent.parent / "app" / "dashboard.py"
DATA = Path(__file__).resolve().parent.parent / "data" / "burnin_wide.csv"

pytestmark = pytest.mark.skipif(
    not DATA.exists(), reason="data/ not generated in this working tree")

SCREENS = ["Lot Overview", "Part Table", "Part Detail", "Distributions",
           "Model Performance", "Decision Policy"]


def _run(screen: str | None = None):
    at = AppTest.from_file(str(APP), default_timeout=180)
    at.run()
    assert not at.exception, f"dashboard raised on load: {at.exception}"
    if screen is not None:
        at.sidebar.radio[0].set_value(screen).run()
        assert not at.exception, f"screen {screen!r} raised: {at.exception}"
    return at


def test_dashboard_loads():
    at = _run()
    assert at.title[0].value == "Lot overview"


@pytest.mark.parametrize("screen", SCREENS)
def test_every_screen_renders(screen):
    """All six, because the demo walks all six."""
    _run(screen)


def test_sidebar_states_the_data_is_simulated():
    at = _run()
    text = " ".join(c.value for c in at.sidebar.caption)
    assert "simulated" in text.lower(), (
        "every submission must label this dataset as simulated")


def test_model_performance_refuses_to_show_accuracy():
    """Rule 5, enforced in the UI as well as the scorer."""
    at = _run("Model Performance")
    rendered = " ".join(
        [m.label for m in at.metric] + [w.value for w in at.warning]).lower()
    assert "accuracy" not in [m.label.lower() for m in at.metric]
    assert "recall" in rendered and "pr-auc" in rendered
    assert "92%" in rendered, "the warning should say why accuracy is absent"


def test_decision_policy_warns_when_the_cost_optimum_breaches_pda():
    """The demo centrepiece. At 100:1 the cost-optimal threshold flags far more
    than the PDA gate allows, and the UI has to say so rather than presenting an
    unimplementable operating point as the answer."""
    at = _run("Decision Policy")
    assert at.error, "expected a PDA warning at the default 100:1 cost ratio"
    assert "PDA" in " ".join(e.value for e in at.error)
