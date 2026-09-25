"""Quantify the wearable-only deployment gap.

Two of NEWS2's seven parameters -- supplemental oxygen and consciousness (AVPU)
-- are recorded by staff, not sensed by a wearable. The training cohort makes
both vary with severity, so the model learns to use them. A sensor-only
deployment cannot supply either and the API defaults them to the benign case.

This measures what that costs, instead of leaving it as a caveat:

  S1  full observation      both flags as generated            (the reported setting)
  S2  wearable-only serving trained with flags, served without (the silent mismatch)
  S3  wearable-only trained trained and served without         (honest retraining)

S2 is the dangerous configuration -- it is what happens if a team deploys the
Track B model against a wearable feed without noticing. S3 is what they should
do instead.

Run::

    python -m vitalsync_ml.wearable_ablation
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict

import pandas as pd

from .datagen import CohortConfig, NoiseConfig, generate_cohort
from .features import to_model_matrix
from .metrics import clinical_metrics
from .train import build_estimators, split_by_patient

ARTIFACTS = Path(__file__).resolve().parent.parent / "artifacts"


def _strip_context(df: pd.DataFrame) -> pd.DataFrame:
    """Force both staff-recorded flags to the benign default a wearable implies."""
    out = df.copy()
    out["on_oxygen"] = False
    out["alert"] = True
    return out


def _evaluate(pipe, X, y) -> Dict:
    pred = pipe.predict(X)
    clin = clinical_metrics(y, pred)
    from sklearn.metrics import accuracy_score, f1_score
    from .news2 import BANDS
    return {
        "accuracy": float(accuracy_score(y, pred)),
        "macro_f1": float(f1_score(y, pred, average="macro", labels=list(BANDS))),
        "high_recall": clin["high_recall"],
        "missed_high_rate": clin["missed_high_rate"],
        "mean_cost": clin["mean_cost"],
    }


def run(patients: int, readings: int, seed: int, model_name: str) -> Dict:
    cfg = CohortConfig(n_patients=patients, readings_per_patient=readings, seed=seed)
    df = generate_cohort(cfg, NoiseConfig())
    train_df, test_df = split_by_patient(df, seed)

    y_tr = train_df["band_true"].to_numpy()
    y_te = test_df["band_true"].to_numpy()

    X_tr_full = to_model_matrix(train_df)
    X_te_full = to_model_matrix(test_df)
    X_tr_bare = to_model_matrix(_strip_context(train_df))
    X_te_bare = to_model_matrix(_strip_context(test_df))

    print("[ablation] fitting model with full observation ...")
    full_model = build_estimators(seed)[model_name]
    full_model.fit(X_tr_full, y_tr)

    print("[ablation] fitting model on wearable-only inputs ...")
    bare_model = build_estimators(seed)[model_name]
    bare_model.fit(X_tr_bare, y_tr)

    scenarios = {
        "S1_full_observation": _evaluate(full_model, X_te_full, y_te),
        "S2_trained_full_served_wearable_only": _evaluate(full_model, X_te_bare, y_te),
        "S3_trained_and_served_wearable_only": _evaluate(bare_model, X_te_bare, y_te),
    }

    s1, s2, s3 = (scenarios["S1_full_observation"],
                  scenarios["S2_trained_full_served_wearable_only"],
                  scenarios["S3_trained_and_served_wearable_only"])

    payload = {
        "experiment": "Wearable-only deployment ablation",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "model": model_name,
        "cohort": {"patients": patients, "readings_per_patient": readings, "seed": seed},
        "scenarios": scenarios,
        "cost_of_silent_mismatch": {
            "macro_f1_drop": s1["macro_f1"] - s2["macro_f1"],
            "high_recall_drop": s1["high_recall"] - s2["high_recall"],
            "missed_high_rate_increase": s2["missed_high_rate"] - s1["missed_high_rate"],
        },
        "benefit_of_honest_retraining": {
            "macro_f1_recovered": s3["macro_f1"] - s2["macro_f1"],
            "high_recall_recovered": s3["high_recall"] - s2["high_recall"],
            "missed_high_rate_reduced": s2["missed_high_rate"] - s3["missed_high_rate"],
        },
        "interpretation": (
            "S1 is the setting reported in the main Track B results and assumes "
            "supplemental-oxygen and AVPU observations are available. S2 is the "
            "failure mode of deploying that model against a wearable-only feed. "
            "S3 shows how much of the loss is recovered by training for the "
            "inputs that will actually be present at inference."
        ),
    }

    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    (ARTIFACTS / "wearable_ablation.json").write_text(json.dumps(payload, indent=2))

    print()
    print(f"  {'scenario':<40} {'macro-F1':>9} {'HIGH-rec':>9} {'missed-HIGH':>12}")
    for name, r in scenarios.items():
        print(f"  {name:<40} {r['macro_f1']:>9.4f} {r['high_recall']:>9.4f} "
              f"{r['missed_high_rate']:>12.4f}")
    print()
    print(f"  silent mismatch costs {payload['cost_of_silent_mismatch']['macro_f1_drop']:+.4f} "
          f"macro-F1 and raises missed-HIGH by "
          f"{payload['cost_of_silent_mismatch']['missed_high_rate_increase']:+.4f}")
    print(f"[ok] wrote {ARTIFACTS / 'wearable_ablation.json'}")
    return payload


def main(argv=None):
    ap = argparse.ArgumentParser(description="Wearable-only deployment ablation")
    ap.add_argument("--patients", type=int, default=12_000)
    ap.add_argument("--readings", type=int, default=3)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--model", default="random_forest",
                    help="random_forest is the default here: it fits fast enough "
                         "for an ablation and the effect under test is about "
                         "inputs, not estimator family")
    args = ap.parse_args(argv)
    run(args.patients, args.readings, args.seed, args.model)


if __name__ == "__main__":
    main()
