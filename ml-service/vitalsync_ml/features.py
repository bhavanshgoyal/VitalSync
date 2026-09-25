"""Feature engineering shared by training, evaluation and the inference service.

Single source of truth: the service must never compute a feature differently
from the trainer. Both import from here.
"""

from __future__ import annotations

from typing import Dict, List, Optional

import numpy as np
import pandas as pd

# Raw channels accepted from a device or simulator.
RAW_FEATURES: List[str] = [
    "heart_rate",
    "spo2",
    "temperature_c",
    "respiratory_rate",
    "systolic_bp",
    "diastolic_bp",
]

# Optional channel: absent from the Kaggle cohort, nullable in the API.
OPTIONAL_FEATURES: List[str] = ["glucose_mgdl"]

DERIVED_FEATURES: List[str] = ["shock_index", "pulse_pressure", "map_mmhg"]

# Clinical context recorded by staff rather than sensed. These are NEWS2
# parameters, so the learned model is given them too -- withholding them would
# handicap the model against the rule baseline and make the comparison unfair.
CONTEXT_FEATURES: List[str] = ["on_oxygen", "alert"]

# Order is contractual: the persisted model expects exactly this, in order.
MODEL_FEATURES: List[str] = RAW_FEATURES + DERIVED_FEATURES

# Full input vector for the triage estimator.
TRIAGE_FEATURES: List[str] = MODEL_FEATURES + CONTEXT_FEATURES


def shock_index(heart_rate: float, systolic_bp: float) -> float:
    """SI = HR / SBP. Elevated SI is associated with haemodynamic compromise.

    Guarded against a zero/negative SBP, which a faulty cuff can report.
    """
    if systolic_bp is None or systolic_bp <= 0:
        return float("nan")
    return float(heart_rate) / float(systolic_bp)


def pulse_pressure(systolic_bp: float, diastolic_bp: float) -> float:
    return float(systolic_bp) - float(diastolic_bp)


def mean_arterial_pressure(systolic_bp: float, diastolic_bp: float) -> float:
    """MAP ~= (SBP + 2*DBP) / 3, the standard bedside approximation."""
    return (float(systolic_bp) + 2.0 * float(diastolic_bp)) / 3.0


def derive_row(obs: Dict[str, Optional[float]]) -> Dict[str, float]:
    """Compute derived features for a single observation dict."""
    sbp = obs["systolic_bp"]
    dbp = obs["diastolic_bp"]
    return {
        "shock_index": shock_index(obs["heart_rate"], sbp),
        "pulse_pressure": pulse_pressure(sbp, dbp),
        "map_mmhg": mean_arterial_pressure(sbp, dbp),
    }


def add_derived(df: pd.DataFrame) -> pd.DataFrame:
    """Vectorised derived features for a DataFrame carrying RAW_FEATURES."""
    out = df.copy()
    sbp = out["systolic_bp"].astype(float)
    dbp = out["diastolic_bp"].astype(float)
    hr = out["heart_rate"].astype(float)

    safe_sbp = sbp.where(sbp > 0, np.nan)
    out["shock_index"] = hr / safe_sbp
    out["pulse_pressure"] = sbp - dbp
    out["map_mmhg"] = (sbp + 2.0 * dbp) / 3.0
    return out


def to_model_matrix(df: pd.DataFrame) -> pd.DataFrame:
    """Select TRIAGE_FEATURES in contractual order, adding derived if missing.

    Context flags default to the benign case (breathing air, alert) when the
    caller omits them, which matches how a wearable-only feed would report.
    """
    if not set(DERIVED_FEATURES).issubset(df.columns):
        df = add_derived(df)
    out = df.copy()
    if "on_oxygen" not in out.columns:
        out["on_oxygen"] = False
    if "alert" not in out.columns:
        out["alert"] = True
    out["on_oxygen"] = out["on_oxygen"].astype(float)
    out["alert"] = out["alert"].astype(float)
    return out[TRIAGE_FEATURES]
