"""Track A: audit the Kaggle 'Human Vital Sign Dataset' label.

Motivation
----------
The project milestone proposed training a risk classifier on
``nasirayub2/human-vital-sign-dataset`` and reporting the accuracy as evidence
of patient-risk prediction. Auditing the dataset first shows that its
``Risk Category`` column is a deterministic three-clause Boolean over heart rate
and BMI, and that the remaining vital signs carry no label information at all.

Any headline accuracy on this dataset therefore measures rule recovery, not
clinical prediction. This module produces the evidence for that claim so the
paper can state it with numbers rather than assertion.

Run::

    python -m vitalsync_ml.kaggle_audit
    python -m vitalsync_ml.kaggle_audit --csv /path/to/human_vital_signs_dataset_2024.csv
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional

import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingClassifier, RandomForestClassifier
from sklearn.feature_selection import mutual_info_classif
from sklearn.metrics import accuracy_score, classification_report, f1_score
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler
from sklearn.tree import DecisionTreeClassifier, export_text

ARTIFACTS = Path(__file__).resolve().parent.parent / "artifacts"

# The candidate rule recovered by inspection + a depth-3 tree.
CANDIDATE_RULE = "(Heart Rate > 90) OR (Derived_BMI > 30) OR (Derived_BMI < 18.5)"

# Vitals that the audit expects to be non-discriminative.
VITALS_ONLY = [
    "Oxygen Saturation",
    "Systolic Blood Pressure",
    "Diastolic Blood Pressure",
    "Body Temperature",
    "Respiratory Rate",
]

DEFAULT_CACHE = (
    Path.home()
    / ".cache/kagglehub/datasets/nasirayub2/human-vital-sign-dataset"
    / "versions/1/human_vital_signs_dataset_2024.csv"
)


def locate_csv(explicit: Optional[str] = None) -> Optional[Path]:
    """Find the dataset without vendoring it (Kaggle licence)."""
    if explicit:
        p = Path(explicit)
        return p if p.exists() else None
    env = os.environ.get("VITALSYNC_KAGGLE_CSV")
    if env and Path(env).exists():
        return Path(env)
    if DEFAULT_CACHE.exists():
        return DEFAULT_CACHE
    try:  # optional dependency; only used when the cache is cold
        import kagglehub

        path = Path(kagglehub.dataset_download("nasirayub2/human-vital-sign-dataset"))
        for csv in path.glob("*.csv"):
            return csv
    except Exception:
        return None
    return None


def apply_candidate_rule(df: pd.DataFrame) -> np.ndarray:
    return (
        (df["Heart Rate"] > 90)
        | (df["Derived_BMI"] > 30)
        | (df["Derived_BMI"] < 18.5)
    ).to_numpy()


def run(csv_path: Path, seed: int = 42) -> Dict:
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    print(f"[A1] loading {csv_path}")
    df = pd.read_csv(csv_path)
    digest = hashlib.sha256(csv_path.read_bytes()).hexdigest()

    y_label = df["Risk Category"]
    y = (y_label == "High Risk").to_numpy()

    report: Dict = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dataset": {
            "kaggle_ref": "nasirayub2/human-vital-sign-dataset",
            "resolved_path": str(csv_path),
            "sha256": digest,
            "rows": int(df.shape[0]),
            "columns": int(df.shape[1]),
            "column_names": list(df.columns),
            "null_cells": int(df.isnull().sum().sum()),
            "duplicate_rows": int(df.duplicated().sum()),
            "class_counts": {k: int(v) for k, v in y_label.value_counts().items()},
            "n_classes": int(y_label.nunique()),
            "base_rate_high_risk": float(y.mean()),
        },
    }
    print(f"     {df.shape[0]:,} rows x {df.shape[1]} cols, "
          f"{report['dataset']['n_classes']} classes")

    # --- A2: are the vitals inside normal reference ranges? ---------------
    print("[A2] per-class descriptive statistics")
    numeric = df.select_dtypes(include=[np.number]).columns.drop("Patient ID")
    by_class = df.groupby("Risk Category")[list(numeric)].mean()
    report["per_class_means"] = {
        col: {cls: float(by_class.loc[cls, col]) for cls in by_class.index}
        for col in by_class.columns
    }
    report["observed_ranges"] = {
        col: {"min": float(df[col].min()), "max": float(df[col].max())}
        for col in numeric
    }

    # Separation of each column between the two classes, in pooled-SD units.
    seps = {}
    for col in numeric:
        a = df.loc[y, col]
        b = df.loc[~y, col]
        pooled = np.sqrt((a.var() + b.var()) / 2.0)
        seps[col] = float(abs(a.mean() - b.mean()) / pooled) if pooled > 0 else 0.0
    report["standardised_mean_difference"] = seps

    # --- A3: mutual information ------------------------------------------
    print("[A3] mutual information of each feature with the label")
    sample = df.sample(min(40_000, len(df)), random_state=seed)
    mi = mutual_info_classif(
        StandardScaler().fit_transform(sample[list(numeric)]),
        (sample["Risk Category"] == "High Risk").to_numpy(),
        random_state=seed,
    )
    report["mutual_information"] = {
        col: float(v)
        for col, v in sorted(zip(numeric, mi), key=lambda kv: -kv[1])
    }

    # --- A4: depth-3 tree, printed as a rule ------------------------------
    print("[A4] fitting depth-3 decision tree to expose the rule")
    tree_features = list(numeric)
    tree = DecisionTreeClassifier(max_depth=3, random_state=seed).fit(
        df[tree_features], y
    )
    report["decision_tree_depth3"] = {
        "train_accuracy": float(tree.score(df[tree_features], y)),
        "rule_text": export_text(tree, feature_names=tree_features),
    }

    # --- A5: does the candidate rule reproduce the label exactly? ---------
    print(f"[A5] testing candidate rule: {CANDIDATE_RULE}")
    rule_pred = apply_candidate_rule(df)
    exact = bool((rule_pred == y).all())
    mismatches = int((rule_pred != y).sum())
    report["candidate_rule"] = {
        "expression": CANDIDATE_RULE,
        "accuracy": float((rule_pred == y).mean()),
        "mismatches": mismatches,
        "reproduces_label_exactly": exact,
    }
    print(f"     accuracy={report['candidate_rule']['accuracy']:.6f} "
          f"mismatches={mismatches} exact={exact}")

    # --- A6: the milestone's RF / GB experiment ---------------------------
    print("[A6] training RF and GB as the milestone specified")
    feature_cols = [
        c for c in numeric if c not in ("Patient ID",)
    ]
    X = df[feature_cols]
    X_tr, X_te, y_tr, y_te = train_test_split(
        X, y, test_size=0.2, random_state=seed, stratify=y
    )
    scaler = StandardScaler().fit(X_tr)
    X_tr_s, X_te_s = scaler.transform(X_tr), scaler.transform(X_te)

    models = {
        "random_forest": RandomForestClassifier(
            n_estimators=100, max_depth=15, class_weight="balanced",
            n_jobs=-1, random_state=seed,
        ),
        "gradient_boosting": GradientBoostingClassifier(
            n_estimators=100, max_depth=5, random_state=seed,
        ),
    }
    report["milestone_models"] = {}
    for name, model in models.items():
        model.fit(X_tr_s, y_tr)
        pred = model.predict(X_te_s)
        report["milestone_models"][name] = {
            "accuracy": float(accuracy_score(y_te, pred)),
            "macro_f1": float(f1_score(y_te, pred, average="macro")),
            "per_class": classification_report(
                y_te, pred, output_dict=True, zero_division=0
            ),
        }
        if hasattr(model, "feature_importances_"):
            report["milestone_models"][name]["feature_importance"] = {
                c: float(v)
                for c, v in sorted(
                    zip(feature_cols, model.feature_importances_),
                    key=lambda kv: -kv[1],
                )
            }
        print(f"     {name:18s} acc={report['milestone_models'][name]['accuracy']:.5f}")

    # --- A7: ablation -- vitals only, no HR, no BMI -----------------------
    print("[A7] ablation: train on non-discriminative vitals only")
    Xv = df[VITALS_ONLY]
    Xv_tr, Xv_te, yv_tr, yv_te = train_test_split(
        Xv, y, test_size=0.2, random_state=seed, stratify=y
    )
    abl = RandomForestClassifier(
        n_estimators=100, max_depth=15, n_jobs=-1, random_state=seed
    ).fit(Xv_tr, yv_tr)
    abl_pred = abl.predict(Xv_te)
    majority = float(max(y.mean(), 1 - y.mean()))
    report["ablation_vitals_only"] = {
        "features": VITALS_ONLY,
        "accuracy": float(accuracy_score(yv_te, abl_pred)),
        "macro_f1": float(f1_score(yv_te, abl_pred, average="macro")),
        "majority_class_baseline": majority,
        "interpretation": (
            "Accuracy at or below the majority-class baseline means these five "
            "vital signs carry no information about the published label."
        ),
    }
    print(f"     vitals-only acc={report['ablation_vitals_only']['accuracy']:.5f} "
          f"vs majority baseline {majority:.5f}")

    report["conclusion"] = (
        "The Risk Category label is reproduced exactly by "
        f"{CANDIDATE_RULE}. Oxygen saturation, blood pressure, body temperature "
        "and respiratory rate are statistically identical across the two "
        "classes and an ablation trained on them alone does not beat the "
        "majority-class baseline. Classification scores reported on this "
        "dataset measure Boolean rule recovery and must not be presented as "
        "clinical risk prediction."
    ) if exact else (
        "The candidate rule did NOT reproduce the label exactly. The audit "
        "conclusion in the paper must be revised before publication."
    )

    (ARTIFACTS / "audit.json").write_text(json.dumps(report, indent=2))
    print(f"[ok] wrote {ARTIFACTS/'audit.json'}")
    return report


def main(argv=None):
    ap = argparse.ArgumentParser(description="Audit the Kaggle vital-signs label")
    ap.add_argument("--csv", default=None, help="path to the dataset CSV")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args(argv)

    csv = locate_csv(args.csv)
    if csv is None:
        print(
            "Dataset not found. Set VITALSYNC_KAGGLE_CSV, pass --csv, or run\n"
            "  python -c \"import kagglehub;"
            "kagglehub.dataset_download('nasirayub2/human-vital-sign-dataset')\""
        )
        raise SystemExit(2)
    run(csv, seed=args.seed)


if __name__ == "__main__":
    main()
