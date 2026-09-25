"""Tests for the clinical-cost and calibration metrics."""

import numpy as np
import pytest

from vitalsync_ml.metrics import (
    COST_MATRIX,
    clinical_metrics,
    expected_calibration_error,
    multiclass_brier,
)


# ------------------------------------------------------------ clinical cost

def test_perfect_prediction_has_zero_cost():
    y = ["LOW", "MEDIUM", "HIGH", "LOW"]
    m = clinical_metrics(y, y)
    assert m["mean_cost"] == 0.0
    assert m["missed_high_rate"] == 0.0
    assert m["high_recall"] == 1.0
    assert m["undertriage_rate"] == 0.0
    assert m["overtriage_rate"] == 0.0


def test_missed_high_is_counted_only_when_predicted_low():
    """HIGH called MEDIUM is under-triage but not a *missed* HIGH."""
    partial = clinical_metrics(["HIGH"], ["MEDIUM"])
    assert partial["missed_high_count"] == 0
    assert partial["undertriage_rate"] == 1.0

    total = clinical_metrics(["HIGH"], ["LOW"])
    assert total["missed_high_count"] == 1
    assert total["missed_high_rate"] == 1.0


def test_undertriage_costs_more_than_overtriage():
    """The asymmetry is the entire point of the cost matrix."""
    under = clinical_metrics(["HIGH"], ["LOW"])["mean_cost"]
    over = clinical_metrics(["LOW"], ["HIGH"])["mean_cost"]
    assert under > over
    assert under == COST_MATRIX[2][0]
    assert over == COST_MATRIX[0][2]


def test_macro_f1_blind_spot_is_visible_here():
    """Two models, same error count, very different clinical cost.

    Model A turns HIGH into LOW; model B turns LOW into HIGH. An aggregate
    metric that ignores direction scores these the same; mean_cost does not.
    """
    truth = ["HIGH", "LOW", "LOW", "LOW"]
    dangerous = ["LOW", "LOW", "LOW", "LOW"]     # misses the HIGH
    cautious = ["HIGH", "HIGH", "LOW", "LOW"]    # one false alarm

    a = clinical_metrics(truth, dangerous)
    b = clinical_metrics(truth, cautious)

    assert a["missed_high_count"] == 1
    assert b["missed_high_count"] == 0
    assert a["mean_cost"] > b["mean_cost"]


def test_escalation_recall_treats_medium_and_high_together():
    truth = ["MEDIUM", "HIGH", "LOW"]
    pred = ["HIGH", "MEDIUM", "LOW"]
    m = clinical_metrics(truth, pred)
    # Both escalations were flagged as escalations, though bands were swapped.
    assert m["escalation_recall"] == 1.0


def test_empty_input_returns_empty():
    assert clinical_metrics([], []) == {}


def test_high_recall_is_none_without_any_high():
    m = clinical_metrics(["LOW", "MEDIUM"], ["LOW", "MEDIUM"])
    assert m["high_recall"] is None
    assert m["missed_high_rate"] is None


# ------------------------------------------------------------- calibration

def test_perfectly_calibrated_model_has_near_zero_ece():
    # 100 samples at confidence 0.8, exactly 80 of them correct.
    conf = np.full(100, 0.8)
    correct = np.array([True] * 80 + [False] * 20)
    report = expected_calibration_error(conf, correct, n_bins=10)
    assert report["ece"] == pytest.approx(0.0, abs=1e-9)


def test_overconfident_model_is_flagged_with_positive_gap():
    # Claims 0.95 confidence, is right half the time.
    conf = np.full(100, 0.95)
    correct = np.array([True] * 50 + [False] * 50)
    report = expected_calibration_error(conf, correct, n_bins=10)
    assert report["ece"] == pytest.approx(0.45, abs=1e-6)

    populated = [b for b in report["bins"] if b["count"]]
    assert len(populated) == 1
    assert populated[0]["signed_gap"] > 0  # positive == over-confident


def test_underconfident_model_has_negative_gap():
    conf = np.full(100, 0.55)
    correct = np.array([True] * 95 + [False] * 5)
    report = expected_calibration_error(conf, correct, n_bins=10)
    populated = [b for b in report["bins"] if b["count"]]
    assert populated[0]["signed_gap"] < 0


def test_confidence_of_one_lands_in_the_top_bin():
    """Guards the bin-edge handling: 1.0 must not fall outside every bin."""
    conf = np.ones(10)
    correct = np.ones(10, dtype=bool)
    report = expected_calibration_error(conf, correct, n_bins=10)
    assert sum(b["count"] for b in report["bins"]) == 10


def test_mce_is_the_worst_bin_not_the_average():
    conf = np.concatenate([np.full(90, 0.9), np.full(10, 0.5)])
    correct = np.concatenate([np.ones(90, dtype=bool), np.zeros(10, dtype=bool)])
    report = expected_calibration_error(conf, correct, n_bins=10)
    assert report["mce"] >= report["ece"]


def test_brier_rewards_confident_correctness():
    classes = ["LOW", "MEDIUM", "HIGH"]
    confident_right = np.array([[1.0, 0.0, 0.0]])
    confident_wrong = np.array([[0.0, 0.0, 1.0]])

    assert multiclass_brier(confident_right, ["LOW"], classes) == pytest.approx(0.0)
    assert multiclass_brier(confident_wrong, ["LOW"], classes) == pytest.approx(2.0)


def test_empty_calibration_input_returns_empty():
    assert expected_calibration_error(np.array([]), np.array([])) == {}
