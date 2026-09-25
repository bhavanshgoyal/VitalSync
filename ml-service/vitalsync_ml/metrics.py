"""Clinical-cost and calibration metrics.

Macro-F1 alone is not an adequate selection criterion for a triage model. It
treats a missed HIGH exactly like a spurious HIGH, and those two errors are not
remotely equivalent at a bedside: one is a delayed escalation, the other is a
wasted review. This module adds the asymmetric view, plus the calibration check
that tells you whether a reported confidence means anything at all.

Nothing here is validated against clinical outcomes. The cost weights are a
stated, arbitrary, and deliberately conservative assumption -- documented as
such so a reader can substitute their own.
"""

from __future__ import annotations

from typing import Dict, List, Sequence

import numpy as np

from .news2 import BANDS

# Ordinal severity so "how far wrong, and in which direction" is well defined.
BAND_RANK: Dict[str, int] = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}

# Asymmetric misclassification cost, indexed [true_rank][predicted_rank].
#
# ASSUMPTION, NOT EVIDENCE. Under-triage (predicting a calmer band than the
# truth) is penalised far more heavily than over-triage, and missing a HIGH
# entirely is penalised an order of magnitude beyond a one-band slip. These
# numbers encode a clinical intuition -- escalating unnecessarily costs a
# review, failing to escalate can cost a patient -- but they are not derived
# from outcome data and must not be presented as if they were.
COST_MATRIX: List[List[float]] = [
    #  pred LOW  MEDIUM  HIGH      <- true
    [0.0, 1.0, 2.0],   # true LOW      (over-triage only)
    [5.0, 0.0, 1.0],   # true MEDIUM
    [25.0, 5.0, 0.0],  # true HIGH     (25 = missed deterioration)
]


def clinical_metrics(y_true: Sequence[str], y_pred: Sequence[str]) -> Dict:
    """Safety-oriented metrics that macro-F1 hides.

    ``missed_high_rate`` is the headline: the fraction of genuinely HIGH
    observations that the model called LOW. That is the failure mode a triage
    system exists to prevent, and it is invisible in an aggregate F1 score.
    """
    true = np.asarray([BAND_RANK.get(b, 0) for b in y_true])
    pred = np.asarray([BAND_RANK.get(b, 0) for b in y_pred])
    n = len(true)
    if n == 0:
        return {}

    delta = pred - true
    under = delta < 0
    over = delta > 0

    is_high = true == BAND_RANK["HIGH"]
    n_high = int(is_high.sum())
    is_escalation = true >= BAND_RANK["MEDIUM"]
    n_escalation = int(is_escalation.sum())

    total_cost = float(sum(COST_MATRIX[t][p] for t, p in zip(true, pred)))

    return {
        # Recall on the class that matters most.
        "high_recall": float((pred[is_high] == BAND_RANK["HIGH"]).mean()) if n_high else None,
        # Any escalation detected at all (MEDIUM or HIGH called MEDIUM-or-higher).
        "escalation_recall": (
            float((pred[is_escalation] >= BAND_RANK["MEDIUM"]).mean())
            if n_escalation else None
        ),
        # The catastrophic case: true HIGH reported as LOW.
        "missed_high_count": int((is_high & (pred == BAND_RANK["LOW"])).sum()),
        "missed_high_rate": (
            float((pred[is_high] == BAND_RANK["LOW"]).mean()) if n_high else None
        ),
        "undertriage_rate": float(under.mean()),
        "overtriage_rate": float(over.mean()),
        "mean_cost": total_cost / n,
        "total_cost": total_cost,
        "cost_matrix": COST_MATRIX,
        "cost_matrix_note": (
            "Asymmetric cost weights are a stated assumption, not derived from "
            "clinical outcome data."
        ),
        "support": {"n": n, "n_high": n_high, "n_escalation": n_escalation},
    }


def expected_calibration_error(
    confidences: np.ndarray, correct: np.ndarray, n_bins: int = 10
) -> Dict:
    """Equal-width-bin ECE, MCE and the reliability table behind them.

    A model that says 0.99 should be right about 99% of the time it says 0.99.
    Tree ensembles routinely are not: voting fractions look like probabilities
    but are not calibrated, and an over-confident number shown next to a
    clinical band is actively misleading. ECE quantifies the gap.
    """
    confidences = np.asarray(confidences, dtype=float)
    correct = np.asarray(correct, dtype=bool)
    n = len(confidences)
    if n == 0:
        return {}

    edges = np.linspace(0.0, 1.0, n_bins + 1)
    bins = []
    ece = 0.0
    mce = 0.0

    for i in range(n_bins):
        lo, hi = edges[i], edges[i + 1]
        # Last bin is closed on the right so confidence == 1.0 is counted.
        mask = (confidences > lo) & (confidences <= hi) if i > 0 else (confidences <= hi)
        count = int(mask.sum())
        if count == 0:
            bins.append({
                "bin_lower": round(lo, 3), "bin_upper": round(hi, 3),
                "count": 0, "mean_confidence": None, "accuracy": None, "gap": None,
            })
            continue

        mean_conf = float(confidences[mask].mean())
        accuracy = float(correct[mask].mean())
        gap = abs(mean_conf - accuracy)
        ece += (count / n) * gap
        mce = max(mce, gap)

        bins.append({
            "bin_lower": round(lo, 3),
            "bin_upper": round(hi, 3),
            "count": count,
            "mean_confidence": mean_conf,
            "accuracy": accuracy,
            "gap": gap,
            # Positive => over-confident (claims more than it delivers).
            "signed_gap": mean_conf - accuracy,
        })

    return {
        "n_bins": n_bins,
        "ece": ece,
        "mce": mce,
        "bins": bins,
        "interpretation": (
            "ECE is the support-weighted mean gap between stated confidence and "
            "observed accuracy. A positive signed_gap in a bin means the model "
            "is over-confident in that range."
        ),
    }


def multiclass_brier(probabilities: np.ndarray, y_true: Sequence[str],
                     classes: Sequence[str]) -> float:
    """Brier score over the full probability vector (lower is better).

    Unlike ECE this penalises both miscalibration and plain inaccuracy, so the
    two are reported together rather than either alone.
    """
    probabilities = np.asarray(probabilities, dtype=float)
    class_index = {c: i for i, c in enumerate(classes)}
    onehot = np.zeros_like(probabilities)
    for row, label in enumerate(y_true):
        idx = class_index.get(label)
        if idx is not None:
            onehot[row, idx] = 1.0
    return float(np.mean(np.sum((probabilities - onehot) ** 2, axis=1)))


def calibration_report(model, X, y_true: Sequence[str], n_bins: int = 10) -> Dict:
    """Full calibration assessment for a fitted probabilistic classifier."""
    proba = model.predict_proba(X)
    classes = list(model.classes_)

    confidences = proba.max(axis=1)
    predicted = np.asarray([classes[i] for i in proba.argmax(axis=1)])
    correct = predicted == np.asarray(list(y_true))

    report = expected_calibration_error(confidences, correct, n_bins=n_bins)
    report["brier_score"] = multiclass_brier(proba, y_true, classes)
    report["mean_confidence"] = float(confidences.mean())
    report["overall_accuracy"] = float(correct.mean())
    report["overconfidence"] = float(confidences.mean() - correct.mean())

    # Per-class confidence, to expose a model that is well calibrated on the
    # majority class and badly calibrated exactly where it matters.
    per_class = {}
    for band in BANDS:
        mask = predicted == band
        if mask.sum():
            per_class[band] = {
                "n_predicted": int(mask.sum()),
                "mean_confidence": float(confidences[mask].mean()),
                "precision": float(correct[mask].mean()),
                "overconfidence": float(confidences[mask].mean() - correct[mask].mean()),
            }
    report["per_predicted_class"] = per_class
    return report
