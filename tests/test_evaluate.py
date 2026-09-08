"""Tests for src/evaluate.py.

Required by the definition of done: evaluate.py is the only source of any
number that reaches a slide, so a silent error here would corrupt every claim
in the deck.

Metrics are checked against hand-computed confusion matrices rather than
against another library, so the test fails if the definition drifts rather than
if a dependency changes.
"""

import numpy as np
import pytest

from src.evaluate import (
    accuracy,
    confusion_counts,
    cost_minimising_threshold,
    evaluate_screening,
    expected_cost,
    format_report,
    grouped_folds,
    pr_auc,
    recall_at_overkill,
    regression_metrics,
    screening_metrics,
    sweep,
)


# ---------------------------------------------------------------- refusal
def test_accuracy_is_refused_not_returned():
    """Rule 5, enforced rather than merely documented. With ~8% defects,
    predicting "all good" scores 92% while catching nothing."""
    with pytest.raises(NotImplementedError, match="all good"):
        accuracy([1, 0, 1], [0, 0, 0])


# ------------------------------------------------------- hand-checked math
#   y    1 1 1 1 0 0 0 0 0 0
#   pred 1 1 0 0 1 0 0 0 0 0   ->  tp=2 fn=2 fp=1 tn=5
Y_TRUE = [1, 1, 1, 1, 0, 0, 0, 0, 0, 0]
Y_PRED = [1, 1, 0, 0, 1, 0, 0, 0, 0, 0]


def test_confusion_counts_are_real_counts():
    assert confusion_counts(Y_TRUE, Y_PRED) == dict(tp=2, fp=1, fn=2, tn=5)


def test_recall_and_precision_match_the_hand_computation():
    m = screening_metrics(Y_TRUE, Y_PRED)
    assert m["recall"] == pytest.approx(2 / 4)
    assert m["precision"] == pytest.approx(2 / 3)
    assert m["flagged"] == 3
    assert m["n_positive"] == 4


def test_f_beta_weights_recall_beta_squared_times_more_than_precision():
    """F2 = 5PR / (4P + R). Written out so the test fails if beta is silently
    dropped back to 1."""
    p, r = 2 / 3, 0.5
    expected_f2 = 5 * p * r / (4 * p + r)
    assert screening_metrics(Y_TRUE, Y_PRED, beta=2.0)["f_beta"] == pytest.approx(expected_f2)

    expected_f1 = 2 * p * r / (p + r)
    assert screening_metrics(Y_TRUE, Y_PRED, beta=1.0)["f_beta"] == pytest.approx(expected_f1)

    # The whole point of beta >= 2: it must prefer the higher-recall screen.
    catch_all = [1] * 10
    assert (screening_metrics(Y_TRUE, catch_all, beta=2.0)["f_beta"]
            > screening_metrics(Y_TRUE, Y_PRED, beta=2.0)["f_beta"])


def test_expected_cost_is_asymmetric_by_100_to_1():
    # 2 misses and 1 over-reject at the default ratio.
    assert expected_cost(Y_TRUE, Y_PRED) == pytest.approx(100 * 2 + 1 * 1)
    assert expected_cost(Y_TRUE, Y_PRED, c_fn=1, c_fp=1) == pytest.approx(3)


# ------------------------------------------------- the two overkill rates
def test_overkill_excludes_gross_failures_when_the_healthy_mask_is_given():
    """The negative class contains healthy parts AND gross failures. Flagging a
    gross part is correct behaviour, not over-rejection, so the operationally
    honest overkill rate counts only good silicon."""
    y = [1, 0, 0, 0, 0]                     # one latent defect
    healthy = [False, False, True, True, True]   # index 1 is a gross failure
    pred = [1, 1, 1, 0, 0]                  # flags the defect, the gross, one healthy

    with_mask = screening_metrics(y, pred, healthy_mask=healthy)
    without = screening_metrics(y, pred)

    assert with_mask["overkill"] == 1 and with_mask["n_healthy"] == 3
    assert with_mask["overkill_rate"] == pytest.approx(1 / 3)

    # Standard convention counts the gross part against us.
    assert without["overkill"] == 2 and without["overkill_rate"] == pytest.approx(2 / 4)

    # Precision is unchanged - it stays comparable with the blueprint table.
    assert with_mask["precision"] == without["precision"] == pytest.approx(1 / 3)


# ------------------------------------------------------------ score sweep
def test_sweep_endpoints_and_monotonicity():
    rng = np.random.default_rng(0)
    y = (rng.random(500) < 0.08).astype(int)
    s = rng.random(500) + y * 0.4

    curve = sweep(y, s)

    assert curve.recall.is_monotonic_increasing
    assert curve.flagged.is_monotonic_increasing
    assert curve.recall.iloc[-1] == pytest.approx(1.0)      # flag everything
    assert curve.flagged.iloc[-1] == len(y)
    np.testing.assert_array_equal(curve.tp + curve.fn, y.sum())


def test_sweep_never_splits_a_tie():
    """Two parts the score cannot separate must move together; otherwise the
    curve advertises an operating point that cannot be implemented."""
    y = [1, 0, 1, 0]
    s = [2.0, 2.0, 1.0, 1.0]
    curve = sweep(y, s)

    assert len(curve) == 2                       # two distinct scores
    assert curve.flagged.tolist() == [2, 4]


def test_sweep_rejects_non_finite_scores():
    with pytest.raises(ValueError, match="NaN"):
        sweep([1, 0, 1], [1.0, np.nan, 0.5])


def test_pr_auc_is_1_for_a_perfect_ranking_and_near_prevalence_for_noise():
    y = [1, 1, 0, 0, 0, 0, 0, 0, 0, 0]
    assert pr_auc(y, [9, 8, 1, 1, 1, 1, 1, 1, 1, 1]) == pytest.approx(1.0)

    rng = np.random.default_rng(1)
    y_big = (rng.random(20_000) < 0.08).astype(int)
    assert pr_auc(y_big, rng.random(20_000)) == pytest.approx(0.08, abs=0.02)


# ----------------------------------------------------- threshold policy
def test_cost_minimising_threshold_finds_the_known_argmin():
    """Enumerated by hand at C_FN/C_FP = 100:

        thr>=5  tp=1 fp=0 fn=1  cost=100
        thr>=4  tp=1 fp=1 fn=1  cost=101
        thr>=3  tp=2 fp=1 fn=0  cost=1     <- minimum
        thr>=2  tp=2 fp=2 fn=0  cost=2
        thr>=1  tp=2 fp=3 fn=0  cost=3
    """
    y = [1, 0, 1, 0, 0]
    s = [5.0, 4.0, 3.0, 2.0, 1.0]

    best = cost_minimising_threshold(y, s)

    assert best["threshold"] == pytest.approx(3.0)
    assert best["cost"] == pytest.approx(1.0)
    assert best["recall"] == pytest.approx(1.0)


def test_raising_the_miss_cost_never_lowers_recall():
    """The demo centrepiece: drag the slider, watch recall climb. If this ever
    fails, the slider is lying."""
    rng = np.random.default_rng(2)
    y = (rng.random(2000) < 0.08).astype(int)
    s = rng.random(2000) + y * 0.35

    recalls = [cost_minimising_threshold(y, s, c_fn=r, c_fp=1.0)["recall"]
               for r in (1, 5, 20, 100, 500)]

    assert all(b >= a - 1e-12 for a, b in zip(recalls, recalls[1:])), recalls
    assert recalls[-1] > recalls[0]


def test_ties_in_cost_break_toward_flagging_fewer_parts():
    # thr>=2 and thr>=1 both cost 0 misses; the cheaper one in silicon wins.
    y = [1, 1, 0]
    s = [3.0, 2.0, 1.0]
    assert cost_minimising_threshold(y, s)["threshold"] == pytest.approx(2.0)


def test_recall_at_overkill_respects_the_budget():
    rng = np.random.default_rng(4)
    y = (rng.random(3000) < 0.08).astype(int)
    s = rng.random(3000) + y * 0.5

    tight = recall_at_overkill(y, s, budget=0.02)
    loose = recall_at_overkill(y, s, budget=0.20)

    assert tight["overkill_rate"] <= 0.02 + 1e-12
    assert loose["overkill_rate"] <= 0.20 + 1e-12
    assert loose["recall"] >= tight["recall"]


def test_recall_at_overkill_reports_infeasible_rather_than_guessing():
    """Every part scores the same, so the smallest possible flag set is all of
    them. There is no operating point inside a 1% budget and the report must
    say so instead of returning a number."""
    out = recall_at_overkill([1, 0, 0, 0], [1.0, 1.0, 1.0, 1.0], budget=0.01)
    assert out["feasible"] is False
    assert out["recall"] == 0.0


# ------------------------------------------------------------- validation
def test_grouped_folds_never_put_one_lot_on_both_sides():
    """Rule 6. A random part-level split leaks lot statistics and inflates
    every score - this is the mistake judges look for first."""
    lots = np.repeat([f"L{i:02d}" for i in range(6)], 350)

    folds = grouped_folds(lots, n_splits=6)
    assert len(folds) == 6

    seen_test = set()
    for train_idx, test_idx in folds:
        train_lots = set(lots[train_idx])
        test_lots = set(lots[test_idx])
        assert train_lots.isdisjoint(test_lots)
        seen_test |= test_lots

    assert seen_test == set(lots)      # every lot is tested exactly once


def test_grouped_folds_caps_splits_at_the_number_of_lots():
    lots = np.repeat(["L01", "L02", "L03"], 10)
    assert len(grouped_folds(lots, n_splits=10)) == 3


def test_grouped_folds_refuses_a_single_group():
    with pytest.raises(ValueError, match="at least 2"):
        grouped_folds(["L01"] * 20, n_splits=5)


# -------------------------------------------------------------- module B
def test_regression_metrics_mae_and_normalisation():
    y_true = [10.0, 20.0, 30.0, 40.0]
    y_pred = [11.0, 19.0, 33.0, 39.0]      # abs errors 1, 1, 3, 1 -> MAE 1.5

    m = regression_metrics(y_true, y_pred)

    assert m["mae"] == pytest.approx(1.5)
    assert m["normalised_mae"] == pytest.approx(1.5 / 25.0)   # median truth = 25
    assert m["n"] == 4


def test_tail_mae_measures_the_parts_that_actually_drifted():
    """Nobody cares about accuracy on flat parts. With baseline_true given,
    "drifter" means largest real movement, not largest absolute value."""
    v0 = np.full(10, 10.0)
    y_true = np.array([10.1] * 9 + [30.0])       # one real drifter
    y_pred = np.array([10.1] * 9 + [20.0])       # missed by 10 on that part

    m = regression_metrics(y_true, y_pred, baseline_true=v0, tail_quantile=0.9)

    assert m["mae"] == pytest.approx(1.0)        # diluted by nine flat parts
    assert m["tail_mae"] == pytest.approx(10.0)  # the number that matters
    assert m["n_tail"] == 1


def test_regression_metrics_ignore_non_finite_pairs():
    m = regression_metrics([1.0, 2.0, np.nan], [1.0, 3.0, 5.0])
    assert m["n"] == 2 and m["mae"] == pytest.approx(0.5)


# ----------------------------------------------------------- the report
def test_evaluate_screening_defaults_to_the_cost_optimal_threshold():
    rng = np.random.default_rng(6)
    y = (rng.random(1000) < 0.08).astype(int)
    s = rng.random(1000) + y * 0.5

    rep = evaluate_screening(y, s, name="test")

    assert rep.threshold == pytest.approx(rep.cost_optimal["threshold"])
    assert rep.metrics["recall"] == pytest.approx(rep.cost_optimal["recall"])
    assert 0.0 <= rep.pr_auc <= 1.0


def test_formatted_report_never_prints_the_word_accuracy():
    rng = np.random.default_rng(8)
    y = (rng.random(300) < 0.1).astype(int)
    s = rng.random(300) + y * 0.4

    text = format_report(evaluate_screening(y, s, name="test"))

    assert "accuracy" not in text.lower()
    assert "recall" in text and "PR-AUC" in text and "overkill" in text
