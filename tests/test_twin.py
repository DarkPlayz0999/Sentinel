"""Digital twin engine: identity, circuit, faults, measurements, reproducibility.

Service-level behaviour (blind isolation through the API, Sentinel and agent
integration, replacement, reveal) is in test_twin_service.py.
"""

from __future__ import annotations

import sys
import textwrap
from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from src.features import PARAM_NAMES
from src.twin.board import RB1, get_board
from src.twin.circuit import (Netlist, SimulationFailed, find_ngspice,
                              parse_ngspice_output, run_ngspice)
from src.twin.diagnose import board_evidence, detectability, diagnose, fault_dictionary
from src.twin.engine import NETLISTS, NoiseConfig, SimConfig, Swap, ate_read, simulate
from src.twin.faults import CATALOGUE, FaultSpec, profile
from src.twin.replace import candidates

DEMO = FaultSpec("C001", "ESR_INCREASE", 0.8, 24.0, 0.015, board=17)


@pytest.fixture(scope="module")
def demo():
    return simulate(SimConfig(boards=200, seed=42, faults=(DEMO,)))


# ------------------------------------------------------------- identity
def test_component_ids_are_unique_ordered_and_map_to_models():
    ids = RB1.ids
    assert len(ids) == len(set(ids))
    assert 5 <= len([c for c in RB1.components if c.params]) <= 20
    # The mapping 3D object -> backend ID -> simulation model is a fixed table.
    for c in RB1.components:
        assert c.as_dict()["component_id"] == c.component_id
        assert c.model == c.as_dict()["component_model"]
    assert get_board("RB-1") is RB1
    # Every net member exists; every component that has physics sits on a net.
    for net, members in RB1.nets.items():
        assert all(RB1.has(m) for m in members), net
    assert RB1.get("C001").kind == "capacitor" and RB1.get("Q001").kind == "mosfet"


def test_every_fault_in_the_catalogue_targets_a_real_parameter():
    for m in CATALOGUE:
        comps = [c for c in RB1.simulated if c.kind == m.kind]
        assert comps, m.fault_type
        for e in m.effects:
            assert all(e.param in c.params or e.param == "theta" for c in comps), (m.fault_type, e.param)


# -------------------------------------------------------------- circuit
def test_mna_solves_a_divider_and_follows_spice_sign_convention():
    nl = (Netlist("divider").add("V1", "a", "0", "v").add("R1", "a", "b", "r1")
          .add("R2", "b", "0", "r2"))
    sol = nl.solve({"v": np.array([10.0, 5.0]), "r1": 1000.0, "r2": np.array([1000.0, 3000.0])})
    np.testing.assert_allclose(sol["b"], [5.0, 3.75])
    # SPICE: current INTO the + terminal of a source that delivers power is negative.
    np.testing.assert_allclose(sol["i(v1)"], [-0.005, -0.00125])


def test_mna_refuses_a_floating_node_instead_of_returning_garbage():
    nl = Netlist("floating").add("V1", "a", "0", "v").add("R1", "b", "c", "r")
    with pytest.raises(SimulationFailed):
        nl.solve({"v": 1.0, "r": 1.0})


def test_nominal_board_reads_near_the_committed_dataset_centres():
    params = {}
    for c in RB1.simulated:
        for name, p in c.params.items():
            params[f"{c.component_id}.{name}"] = np.array([p.nominal])
        if c.theta_c_per_w:
            params[f"{c.component_id}.theta"] = np.array([c.theta_c_per_w])
    obs, nodes = ate_read(params)
    assert 8 < obs["Iddq_uA"][0] < 12          # dataset centre 10 uA
    assert 15 < obs["Ileak_nA"][0] < 25        # dataset centre 20 nA
    assert 3.0 < obs["Tpd_ns"][0] < 3.5        # dataset centre 3.2 ns
    assert 190 < obs["Vol_mV"][0] < 220        # dataset centre 210 mV
    assert all(obs[p][0] < {"Iddq_uA": 50, "Ileak_nA": 200, "Tpd_ns": 4.6, "Vol_mV": 400}[p]
               for p in PARAM_NAMES)


CANNED = textwrap.dedent("""
    Circuit: * test
    Doing analysis at TEMP = 27.000000 and TNOM = 27.000000
    a = 1.000000e+01
    v(b) = 5.000000e+00
    v1#branch = -5.00000e-03
""")


def test_ngspice_output_parser_normalises_names():
    sol = parse_ngspice_output(CANNED)
    assert sol == {"a": 10.0, "b": 5.0, "i(v1)": -0.005}


FAKE_NGSPICE = textwrap.dedent('''
    """Stand-in for ngspice in tests: solves the .cir with the twin's own MNA
    and prints it in ngspice's `print all` format."""
    import re, sys
    sys.path.insert(0, {repo!r})
    from src.twin.circuit import Netlist
    text = open(sys.argv[-1]).read()
    nl, vals = Netlist("fake"), {{}}
    for i, line in enumerate(text.splitlines()):
        t = line.split()
        if not t or t[0][0] in "*." or t[0] in ("op", "print", "quit"):
            continue
        nl.add(t[0], t[1], t[2], f"k{{i}}")
        vals[f"k{{i}}"] = float(t[-1])
    sol = nl.solve(vals)
    for k, v in sol.items():
        k = k[2:-1] + "#branch" if k.startswith("i(") else k
        print(f"{{k}} = {{float(v[0]):.9e}}")
''')


def test_run_ngspice_plumbing_matches_mna_through_a_stand_in(tmp_path):
    from pathlib import Path
    script = tmp_path / "fake_ngspice.py"
    script.write_text(FAKE_NGSPICE.format(repo=str(Path(__file__).resolve().parents[1])))
    vals = {"vsup": 3.3, "rc": 0.02, "r001": 1.0, "iddq": 9e-6,
            "rleak_c001": 3.3 / 0.8e-6, "rleak_c002": 3.3 / 0.05e-6}
    sol, text = run_ngspice(NETLISTS["iddq"], vals, executable=[sys.executable, str(script)])
    ref = NETLISTS["iddq"].solve(vals)
    for k, v in sol.items():
        assert v == pytest.approx(float(ref[k][0]), rel=1e-6), k
    assert ".op" not in text and "op" in text and "R001 vdd_j rail" in text


def test_ngspice_failure_records_exit_code_stderr_and_netlist(tmp_path):
    bad = tmp_path / "broken.py"
    bad.write_text("import sys; sys.stderr.write('Error: no such model'); sys.exit(3)")
    with pytest.raises(SimulationFailed) as info:
        run_ngspice(NETLISTS["ileak"], {"vsup": 3.3, "rc": 0.02, "rtrace": 0.05,
                                        "rleak_q001": 2e8, "rleak_c003": 1e9},
                    executable=[sys.executable, str(bad)], simulation_id="sim_x")
    rec = info.value.as_dict()
    assert rec["status"] == "SIMULATION_FAILED" and rec["exit_code"] == 3
    assert "no such model" in rec["stderr"] and "VFRC" in rec["netlist"]
    assert rec["simulation_id"] == "sim_x"


@pytest.mark.skipif(find_ngspice() is None, reason="ngspice not installed")
def test_real_ngspice_agrees_with_mna():
    vals = {"vsup": 3.3, "rc": 0.02, "r001": 1.0, "iddq": 9e-6,
            "rleak_c001": 3.3 / 0.8e-6, "rleak_c002": 3.3 / 0.05e-6}
    sol, _ = run_ngspice(NETLISTS["iddq"], vals)
    ref = NETLISTS["iddq"].solve(vals)
    for k, v in sol.items():
        assert v == pytest.approx(float(ref[k][0]), rel=1e-4), k


# --------------------------------------------------------------- faults
def test_profile_reaches_severity_at_168h_and_accelerates():
    tau = np.array([0.0, 72.0, 144.0])
    d = profile(tau, 0.8, 24.0, 0.015)
    assert d[0] == 0 and d[-1] == pytest.approx(0.8)
    assert d[1] < 0.8 * 72 / 144                      # convex: below the straight line
    assert profile(np.array([144.0]), 0.8, 24.0, 0.0)[0] == pytest.approx(0.8)


def test_fault_moves_only_its_own_board(demo):
    clean = simulate(SimConfig(boards=200, seed=42))
    others = [i for i in range(200) if i != DEMO.board]
    for p in PARAM_NAMES:
        np.testing.assert_array_equal(demo.ate_obs[p][others], clean.ate_obs[p][others])
    # ... and moves the faulty board the way the signature says: Tpd up, C001 hotter.
    i = DEMO.board
    assert demo.ate_true["Tpd_ns"][i, -1] > clean.ate_true["Tpd_ns"][i, -1] + 0.2
    assert demo.temps["C001"][i, -1] > clean.temps["C001"][i, -1] + 2.0
    assert demo.values["C001.esr"][i, -1] > 10 * clean.values["C001.esr"][i, -1]


def test_the_demo_defect_is_latent_it_never_breaches_a_datasheet_limit(demo):
    usl = {"Iddq_uA": 50, "Ileak_nA": 200, "Tpd_ns": 4.6, "Vol_mV": 400}
    for p in PARAM_NAMES:
        assert np.nanmax(demo.ate_obs[p][DEMO.board]) < usl[p]


def test_esr_self_heating_accelerates_its_own_fault(demo):
    """ESR growth heats the capacitor; the hotter part's clock runs faster, so
    the fault overshoots its nominal-conditions severity."""
    esr0 = demo.as_built["C001.esr"][DEMO.board]
    nominal_end = esr0 * (1 + 19.0 * DEMO.severity)
    assert demo.values["C001.esr"][DEMO.board, -1] > nominal_end


def test_hotter_chamber_ages_the_whole_lot_faster():
    cool = simulate(SimConfig(boards=60, seed=3, noise=NoiseConfig(0, 0, 0, 0, 0, 0)))
    hot = simulate(SimConfig(boards=60, seed=3, stress_temp_c=150.0,
                             noise=NoiseConfig(0, 0, 0, 0, 0, 0)))
    d_cool = np.median(np.log(cool.ate_true["Iddq_uA"][:, -1] / cool.ate_true["Iddq_uA"][:, 0]))
    d_hot = np.median(np.log(hot.ate_true["Iddq_uA"][:, -1] / hot.ate_true["Iddq_uA"][:, 0]))
    assert d_hot > 1.5 * d_cool


def test_unobservable_faults_are_declared_not_discovered():
    det = detectability()
    assert det["C002"]["ESR_INCREASE"] == []           # masked by C001 at 1 MHz
    assert "Tpd_ns" in det["C001"]["ESR_INCREASE"] and "IR C001" in det["C001"]["ESR_INCREASE"]
    assert det["C003"]["LEAKAGE_INCREASE"] == ["Ileak_nA"]


# ---------------------------------------------------------- measurement
def test_sentinel_frame_contains_only_serial_lot_and_ate_reads(demo):
    f = demo.sentinel_frame()
    expected = ["serial", "lot"] + [f"{p}_{h}h" for p in PARAM_NAMES for h in (0, 24, 96, 168)]
    assert list(f.columns) == expected
    blob = f.to_csv(index=False)
    for leak in ("C001", "ESR", "severity", "fault", "healthy", "latent"):
        assert leak not in blob


def test_noise_is_separate_from_truth_and_dropouts_hit_96h_only(demo):
    j0 = 0
    assert not np.allclose(demo.ate_obs["Tpd_ns"][:, j0], demo.ate_true["Tpd_ns"][:, 0])
    missing = {h: int(np.isnan(demo.ate_obs["Iddq_uA"][:, j]).sum())
               for j, h in enumerate(demo.read_hours)}
    assert missing[0] == missing[24] == missing[168] == 0
    quiet = simulate(SimConfig(boards=40, seed=5, noise=NoiseConfig(0, 0, 0, 0, 0, 0)))
    for p in PARAM_NAMES:
        np.testing.assert_allclose(quiet.ate_obs[p][:, -1], quiet.ate_true[p][:, -1], rtol=1e-12)


def test_sensor_bias_shifts_the_lot_but_not_lot_relative_evidence():
    base = simulate(SimConfig(boards=80, seed=9))
    biased = simulate(SimConfig(boards=80, seed=9, noise=NoiseConfig(sensor_bias={"Vol_mV": 0.05})))
    ratio = biased.ate_obs["Vol_mV"][:, 0] / base.ate_obs["Vol_mV"][:, 0]
    np.testing.assert_allclose(ratio, 1.05, rtol=1e-9)


# ------------------------------------------------------- reproducibility
def test_same_seed_same_bytes_different_seed_different_lot():
    a = simulate(SimConfig(boards=60, seed=11, faults=(replace(DEMO, board=5),))).sentinel_frame()
    b = simulate(SimConfig(boards=60, seed=11, faults=(replace(DEMO, board=5),))).sentinel_frame()
    c = simulate(SimConfig(boards=60, seed=12, faults=(replace(DEMO, board=5),))).sentinel_frame()
    assert a.to_csv(index=False) == b.to_csv(index=False)
    assert a.to_csv(index=False) != c.to_csv(index=False)


def test_a_rework_never_changes_the_original_reads(demo):
    cfg = demo.config
    part = {k.split(".", 1)[1]: v for k, v in {
        "C001.capacitance": 10e-6, "C001.esr": 0.11, "C001.leakage": 0.8e-6}.items()}
    rw = simulate(cfg, swap=Swap(board=DEMO.board, component_id="C001", values=part),
                  only_board=DEMO.board)
    for p in PARAM_NAMES:
        np.testing.assert_array_equal(rw.ate_obs[p][0, :4], demo.ate_obs[p][DEMO.board])
    # the new part is healthy, so the second soak shows no ESR runaway
    assert rw.values["C001.esr"][0, -1] < 0.2


# ------------------------------------------------------ diagnose/replace
def test_diagnosis_localises_the_demo_fault_from_observed_data_only(demo):
    frame = demo.sentinel_frame()
    d = diagnose(demo.serials[DEMO.board], frame, board_evidence(frame, demo.ir_rise()))
    assert d["suspect_component"] == "C001"
    assert d["hypotheses"][0]["fault_type"] == "ESR_INCREASE"
    # Separable: the IR hot spot is what no Tpd-only hypothesis can explain.
    assert d["ambiguity_group"] == []
    assert d["hypotheses"][0]["evidence_score"] > d["hypotheses"][1]["evidence_score"]
    assert "not probabilities" in d["method"]


def test_identical_signatures_are_reported_as_an_ambiguity_group():
    det = detectability()
    # Output leakage from C003 and from Q001 move exactly the same channel.
    assert det["C003"]["LEAKAGE_INCREASE"] == det["Q001"]["LEAKAGE_INCREASE"] == ["Ileak_nA"]
    r = simulate(SimConfig(boards=200, seed=7, faults=(
        FaultSpec("C003", "LEAKAGE_INCREASE", 0.6, 24, 0.015, board=40),)))
    f = r.sentinel_frame()
    d = diagnose(r.serials[40], f, board_evidence(f, r.ir_rise()))
    assert {"C003", "Q001"} <= set(d["ambiguity_group"])
    assert d["discriminating_tests"]


def test_candidates_are_deterministic_ranked_and_never_called_health(demo):
    s = demo.serials[DEMO.board]
    a = candidates(demo, s, "C001")
    b = candidates(demo, s, "C001")
    assert [c.public() for c in a] == [c.public() for c in b]
    scores = [c.ranking_score for c in a]
    assert scores == sorted(scores, reverse=True)
    pub = a[0].public()
    assert "values" not in pub and "latent_fault" not in pub
    assert "not a health" in pub["score_kind"]
    with pytest.raises(ValueError):
        candidates(demo, s, "PR001")
