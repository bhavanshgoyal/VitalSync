"""Track B: train and select the deployable triage model.

The comparison that matters is *not* "which classifier is best" in the abstract.
It is whether a learned model recovers the clean-signal NEWS2 escalation band
from corrupted telemetry better than the NEWS2 rule applied to that same
corrupted telemetry -- which is what a conventional threshold monitor does.

Run::

    python -m vitalsync_ml.train --patients 30000 --readings 4
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.ensemble import GradientBoostingClassifier, RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    classification_report,
    confusion_matrix,
    f1_score,
)
from sklearn.model_selection import GroupShuffleSplit
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from . import MODEL_VERSION
from .datagen import CohortConfig, NoiseConfig, generate_cohort, news2_on_observed
from .features import TRIAGE_FEATURES, to_model_matrix
from .metrics import calibration_report, clinical_metrics
from .news2 import BANDS

ARTIFACTS = Path(__file__).resolve().parent.parent / "artifacts"


# --------------------------------------------------------------------------
# Baselines
# --------------------------------------------------------------------------

def threshold_alarm_baseline(df: pd.DataFrame) -> np.ndarray:
    """B1: a conventional single-parameter alarm set.

    This is the "dumb monitor" every ward already has: independent thresholds,
    no aggregation. Included because it is the honest status quo that an ML
    triage layer would actually be replacing.
    """
    hr = df["heart_rate"].astype(float).fillna(75)
    spo2 = df["spo2"].astype(float).fillna(97)
    sbp = df["systolic_bp"].astype(float).fillna(120)
    temp = df["temperature_c"].astype(float).fillna(36.8)
    rr = df["respiratory_rate"].astype(float).fillna(16)

    critical = (hr > 130) | (spo2 < 90) | (sbp < 90) | (temp > 39.0) | (rr > 25)
    warning = (hr > 100) | (spo2 < 92) | (sbp < 100) | (temp > 38.0) | (rr > 20)

    out = np.full(len(df), "LOW", dtype=object)
    out[warning.to_numpy()] = "MEDIUM"
    out[critical.to_numpy()] = "HIGH"
    return out


# --------------------------------------------------------------------------
# Metrics
# --------------------------------------------------------------------------

def score_predictions(y_true, y_pred, label: str) -> Dict:
    return {
        "model": label,
        "accuracy": float(accuracy_score(y_true, y_pred)),
        "macro_f1": float(f1_score(y_true, y_pred, average="macro", labels=list(BANDS))),
        "weighted_f1": float(
            f1_score(y_true, y_pred, average="weighted", labels=list(BANDS))
        ),
        "per_class": classification_report(
            y_true, y_pred, labels=list(BANDS), output_dict=True, zero_division=0
        ),
        "confusion_matrix": confusion_matrix(
            y_true, y_pred, labels=list(BANDS)
        ).tolist(),
        "confusion_labels": list(BANDS),
        # Safety view: macro-F1 treats a missed HIGH like a spurious HIGH, so
        # the asymmetric metrics are reported next to it for every model,
        # baselines included.
        "clinical": clinical_metrics(y_true, y_pred),
    }


def build_estimators(seed: int) -> Dict[str, Pipeline]:
    """Each estimator ships as a Pipeline so preprocessing can never drift.

    A bare estimator plus a separately-pickled scaler is the classic way to get
    silent train/serve skew; one artifact removes the possibility.
    """
    def wrap(est):
        return Pipeline(
            [
                ("impute", SimpleImputer(strategy="median")),
                ("scale", StandardScaler()),
                ("est", est),
            ]
        )

    return {
        "logistic_regression": wrap(
            # sklearn >= 1.7 dropped the multi_class argument; multinomial is
            # the default for a multiclass target.
            LogisticRegression(
                max_iter=2000, class_weight="balanced", random_state=seed,
            )
        ),
        "random_forest": wrap(
            RandomForestClassifier(
                n_estimators=100, max_depth=15, class_weight="balanced",
                n_jobs=-1, random_state=seed,
            )
        ),
        "gradient_boosting": wrap(
            GradientBoostingClassifier(
                n_estimators=100, max_depth=5, random_state=seed,
            )
        ),
    }


def split_by_patient(df: pd.DataFrame, seed: int, test_size: float = 0.2):
    """Group split on patient_id.

    A row-level split would leak: the same simulated patient contributes several
    correlated readings, so a row split puts near-duplicates on both sides and
    inflates every score.
    """
    splitter = GroupShuffleSplit(n_splits=1, test_size=test_size, random_state=seed)
    train_idx, test_idx = next(
        splitter.split(df, groups=df["patient_id"].to_numpy())
    )
    return df.iloc[train_idx].copy(), df.iloc[test_idx].copy()


def run(args) -> Dict:
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    cohort = CohortConfig(
        n_patients=args.patients,
        readings_per_patient=args.readings,
        seed=args.seed,
    )

    print(f"[1/5] generating cohort: {args.patients} patients x {args.readings} readings")
    t0 = time.perf_counter()
    df = generate_cohort(cohort, NoiseConfig())
    gen_s = time.perf_counter() - t0
    print(f"      {len(df):,} rows in {gen_s:.1f}s")
    print(f"      band distribution: {df['band_true'].value_counts().to_dict()}")

    train_df, test_df = split_by_patient(df, args.seed)
    overlap = set(train_df["patient_id"]) & set(test_df["patient_id"])
    assert not overlap, f"patient leakage across split: {len(overlap)} ids"
    print(f"[2/5] split by patient: train={len(train_df):,} test={len(test_df):,} "
          f"(no shared patients)")

    X_train = to_model_matrix(train_df)
    y_train = train_df["band_true"].to_numpy()
    X_test = to_model_matrix(test_df)
    y_test = test_df["band_true"].to_numpy()

    results: List[Dict] = []

    # --- Baselines, evaluated on the same corrupted observations -----------
    print("[3/5] scoring baselines")
    rule_pred = news2_on_observed(test_df)["band_obs"].to_numpy()
    rule_result = score_predictions(y_test, rule_pred, "news2_rule_on_observed")
    results.append(rule_result)
    results.append(
        score_predictions(y_test, threshold_alarm_baseline(test_df), "threshold_alarms")
    )

    # --- Learned models ----------------------------------------------------
    print("[4/5] training models")
    fitted: Dict[str, Pipeline] = {}
    for name, pipe in build_estimators(args.seed).items():
        t0 = time.perf_counter()
        pipe.fit(X_train, y_train)
        fit_s = time.perf_counter() - t0
        pred = pipe.predict(X_test)
        res = score_predictions(y_test, pred, name)
        res["fit_seconds"] = round(fit_s, 2)
        results.append(res)
        fitted[name] = pipe
        clin = res["clinical"]
        print(f"      {name:22s} macro-F1={res['macro_f1']:.4f} "
              f"acc={res['accuracy']:.4f} "
              f"HIGH-recall={clin['high_recall']:.4f} "
              f"missed-HIGH={clin['missed_high_rate']:.4f} "
              f"cost={clin['mean_cost']:.4f} ({fit_s:.1f}s)")

    # --- Selection ---------------------------------------------------------
    #
    # macro_f1 is the PRE-REGISTERED criterion from the plan and stays the
    # default. It is kept even though the safety metrics below sometimes
    # disagree with it: swapping criteria after seeing the results would be
    # exactly the kind of post-hoc choice that makes a reported number
    # untrustworthy. The disagreement is recorded as a finding instead.
    learned = [r for r in results if r["model"] in fitted]
    if args.select_by == "mean_cost":
        best = min(learned, key=lambda r: r["clinical"]["mean_cost"])
    else:
        best = max(learned, key=lambda r: r["macro_f1"])
    best_name = best["model"]
    best_pipe = fitted[best_name]
    rule_result_f1 = rule_result["macro_f1"]
    rule_f1 = rule_result_f1

    by_f1 = max(learned, key=lambda r: r["macro_f1"])["model"]
    by_cost = min(learned, key=lambda r: r["clinical"]["mean_cost"])["model"]
    by_missed_high = min(
        learned, key=lambda r: (r["clinical"]["missed_high_rate"] is None,
                                r["clinical"]["missed_high_rate"] or 0.0))["model"]
    criteria_agree = by_f1 == by_cost

    print(f"[5/5] selected: {best_name} (by {args.select_by}; macro-F1 "
          f"{best['macro_f1']:.4f} vs rule {rule_f1:.4f}, "
          f"delta {best['macro_f1'] - rule_f1:+.4f})")
    if not criteria_agree:
        print(f"      NOTE: criteria disagree -- macro-F1 picks {by_f1}, "
              f"asymmetric cost picks {by_cost}, "
              f"fewest missed HIGH is {by_missed_high}.")
        print("      Reported as a finding; the pre-registered criterion is "
              "not changed retrospectively.")

    # Calibration of the model actually shipped. A confidence number is
    # surfaced to the clinician-facing layer, so whether it means anything is
    # part of the result, not an afterthought.
    print("      calibrating selected model ...")
    calibration = calibration_report(best_pipe, X_test, y_test)
    print(f"      ECE={calibration['ece']:.4f} "
          f"Brier={calibration['brier_score']:.4f} "
          f"mean-confidence={calibration['mean_confidence']:.4f} "
          f"vs accuracy={calibration['overall_accuracy']:.4f} "
          f"(over-confidence {calibration['overconfidence']:+.4f})")

    joblib.dump(best_pipe, ARTIFACTS / "risk_model.joblib")

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "model_version": MODEL_VERSION,
        "selected_model": best_name,
        "selection_metric": args.select_by,
        "selection_criteria_comparison": {
            "by_macro_f1": by_f1,
            "by_mean_cost": by_cost,
            "by_fewest_missed_high": by_missed_high,
            "criteria_agree": criteria_agree,
            "note": (
                "macro_f1 is the pre-registered criterion. Where it disagrees "
                "with the asymmetric-cost criterion, the disagreement is a "
                "result: the F1-optimal model can carry a higher rate of "
                "HIGH-graded observations reported as LOW."
            ),
        },
        "classes": list(BANDS),
        "features": TRIAGE_FEATURES,
        "label_definition": (
            "NEWS2 (RCP 2017) escalation band computed on LATENT clean "
            "physiology; models observe only sensor-corrupted telemetry."
        ),
        "cohort": {
            "n_patients": cohort.n_patients,
            "readings_per_patient": cohort.readings_per_patient,
            "rows": int(len(df)),
            "seed": cohort.seed,
            "band_counts": {
                k: int(v) for k, v in df["band_true"].value_counts().items()
            },
        },
        "split": {
            "strategy": "GroupShuffleSplit on patient_id",
            "test_size": 0.2,
            "train_rows": int(len(train_df)),
            "test_rows": int(len(test_df)),
            "patient_overlap": 0,
        },
        "results": results,
        "headline": {
            "best_learned_macro_f1": best["macro_f1"],
            "news2_rule_macro_f1": rule_f1,
            "delta": best["macro_f1"] - rule_f1,
            "best_learned_missed_high_rate": best["clinical"]["missed_high_rate"],
            "news2_rule_missed_high_rate": rule_result["clinical"]["missed_high_rate"],
            "best_learned_mean_cost": best["clinical"]["mean_cost"],
            "news2_rule_mean_cost": rule_result["clinical"]["mean_cost"],
        },
        "calibration": calibration,
        "environment": {
            "python": sys.version.split()[0],
            "sklearn": sklearn.__version__,
            "numpy": np.__version__,
            "pandas": pd.__version__,
            "platform": platform.platform(),
        },
        "disclaimer": (
            "Simulated cohort. Software evaluation only. Not clinical validation."
        ),
    }

    (ARTIFACTS / "metrics.json").write_text(json.dumps(payload, indent=2))

    model_bytes = (ARTIFACTS / "risk_model.joblib").read_bytes()
    card = {
        "model_version": MODEL_VERSION,
        "selected_model": best_name,
        "classes": list(BANDS),
        "features": TRIAGE_FEATURES,
        "artifact_sha256": hashlib.sha256(model_bytes).hexdigest(),
        "artifact_bytes": len(model_bytes),
        "trained_at": payload["generated_at"],
        "macro_f1": best["macro_f1"],
        "accuracy": best["accuracy"],
        "high_recall": best["clinical"]["high_recall"],
        "missed_high_rate": best["clinical"]["missed_high_rate"],
        "expected_calibration_error": calibration["ece"],
        "brier_score": calibration["brier_score"],
        "confidence_caveat": (
            "Reported confidence is an uncalibrated ensemble score unless "
            "expected_calibration_error is small. See artifacts/metrics.json "
            "for the reliability table."
        ),
        "intended_use": (
            "Research prototype triage of simulated IoMT vital-sign telemetry."
        ),
        "out_of_scope": [
            "diagnosis", "treatment decisions", "real patient care",
            "any use on real PHI",
        ],
    }
    (ARTIFACTS / "model_card.json").write_text(json.dumps(card, indent=2))
    print(f"      wrote {ARTIFACTS/'risk_model.joblib'}")
    return payload


def main(argv=None):
    ap = argparse.ArgumentParser(description="Train the VitalSync triage model")
    ap.add_argument("--patients", type=int, default=30_000)
    ap.add_argument("--readings", type=int, default=4)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument(
        "--select-by", default="macro_f1", choices=["macro_f1", "mean_cost"],
        help="model-selection criterion; macro_f1 is the pre-registered default",
    )
    args = ap.parse_args(argv)
    run(args)


if __name__ == "__main__":
    main()
