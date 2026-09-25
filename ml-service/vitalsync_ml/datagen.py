"""Simulated IoMT cohort with an explicit latent-truth / observation split.

Why this exists
---------------
NEWS2 is a deterministic function of clean vitals, so training a model to
reproduce NEWS2 from clean vitals is circular and proves nothing. This generator
separates two things that are conflated in naive setups::

    latent physiology x*  --NEWS2-->  y*      (ground truth; never observed)
            |
            +-- sensor noise, quantisation, dropout, motion artifact
            v
    observed telemetry x^                     (what any model actually sees)

Ground truth is scored on x*. Every model -- including the NEWS2 rule baseline --
sees only x^. That makes "learned model vs. threshold rule" a real, falsifiable
comparison rather than a tautology.

Nothing here is real patient data. The cohort is a physiological plausibility
simulation for software evaluation, not a clinical population model.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Dict, Optional

import numpy as np
import pandas as pd

from .features import add_derived
from .news2 import news2

# Deterioration archetypes.
SUBTYPES = ("respiratory", "circulatory", "febrile", "mixed")


@dataclass(frozen=True)
class NoiseConfig:
    """Per-channel sensor corruption.

    Defaults are plausible for consumer/clinical-grade wearables and an
    oscillometric cuff. They are configuration, not findings -- a reviewer can
    and should vary them.
    """

    hr_sigma: float = 2.5
    hr_artifact_rate: float = 0.015
    hr_artifact_magnitude: tuple = (15.0, 40.0)

    spo2_sigma: float = 1.5
    spo2_dropout_rate: float = 0.02
    spo2_dropout_magnitude: tuple = (3.0, 8.0)

    rr_sigma: float = 1.5
    temp_sigma: float = 0.15
    sbp_sigma: float = 5.0
    dbp_sigma: float = 4.0

    missing_rate: float = 0.03

    scale: float = 1.0  # global multiplier; 0.0 == clean passthrough

    def scaled(self, factor: float) -> "NoiseConfig":
        return NoiseConfig(**{**asdict(self), "scale": factor})


@dataclass(frozen=True)
class CohortConfig:
    n_patients: int = 30_000
    readings_per_patient: int = 4
    p_stable: float = 0.60
    p_mild: float = 0.25
    p_acute: float = 0.15
    seed: int = 42


def _sample_severity(rng: np.random.Generator, cfg: CohortConfig) -> np.ndarray:
    """Latent severity z in [0, 1], one per patient.

    Three-component mixture; Beta shapes keep each component inside its own
    region without hard truncation artefacts at the boundaries.
    """
    n = cfg.n_patients
    component = rng.choice(3, size=n, p=[cfg.p_stable, cfg.p_mild, cfg.p_acute])
    z = np.empty(n, dtype=float)
    stable = component == 0
    mild = component == 1
    acute = component == 2

    z[stable] = rng.beta(1.6, 12.0, size=int(stable.sum()))
    z[mild] = 0.20 + 0.35 * rng.beta(2.0, 2.0, size=int(mild.sum()))
    z[acute] = 0.50 + 0.50 * rng.beta(2.2, 1.6, size=int(acute.sum()))
    return np.clip(z, 0.0, 1.0)


def _latent_physiology(
    rng: np.random.Generator, z: np.ndarray, subtype: np.ndarray
) -> Dict[str, np.ndarray]:
    """Map latent severity to correlated clean vital signs.

    Channels share a severity term and add subtype-specific emphasis, so
    deterioration shows up across several parameters at once -- which is the
    structure the NEWS2 aggregate is designed to catch.
    """
    n = z.size

    resp = (subtype == 0).astype(float)
    circ = (subtype == 1).astype(float)
    feb = (subtype == 2).astype(float)
    mixed = (subtype == 3).astype(float)

    w_resp = 0.55 + 1.15 * resp + 0.55 * mixed
    w_circ = 0.55 + 1.15 * circ + 0.55 * mixed
    w_feb = 0.45 + 1.35 * feb + 0.55 * mixed

    hr = 70.0 + 62.0 * z * w_circ + rng.normal(0, 5.5, n)
    rr = 14.0 + 14.0 * z * w_resp + rng.normal(0, 1.6, n)
    spo2 = 98.2 - 11.0 * z * w_resp + rng.normal(0, 0.9, n)
    sbp = 122.0 - 42.0 * z * w_circ + rng.normal(0, 9.0, n)
    dbp = sbp * 0.63 + rng.normal(0, 4.5, n)

    # Temperature is bidirectional: fever in febrile presentations, plus a
    # hypothermic tail in severe circulatory collapse (NEWS2 scores that 3).
    temp = 36.8 + 2.6 * z * w_feb + rng.normal(0, 0.28, n)
    hypothermic = (z > 0.6) & (rng.random(n) < 0.18)
    n_hypo = int(hypothermic.sum())
    if n_hypo:
        temp[hypothermic] = (
            35.6 - 1.6 * z[hypothermic] + rng.normal(0, 0.3, n_hypo)
        )

    on_oxygen = rng.random(n) < np.clip(0.02 + 0.55 * z, 0, 0.85)
    alert = rng.random(n) > np.clip(0.002 + 0.30 * np.maximum(z - 0.45, 0), 0, 0.5)

    # Glucose reflects a stress response; carried but never a NEWS2 input.
    glucose = 95.0 + 55.0 * z + rng.normal(0, 18.0, n)

    return {
        "heart_rate": np.clip(hr, 25, 240),
        "respiratory_rate": np.clip(rr, 4, 60),
        "spo2": np.clip(spo2, 60, 100),
        "systolic_bp": np.clip(sbp, 55, 230),
        "diastolic_bp": np.clip(dbp, 30, 150),
        "temperature_c": np.clip(temp, 30.0, 43.0),
        "glucose_mgdl": np.clip(glucose, 40, 500),
        "on_oxygen": on_oxygen,
        "alert": alert,
    }


def _score_many(
    hr, spo2, temp, rr, sbp, on_oxygen, alert
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    n = len(hr)
    totals = np.empty(n, dtype=int)
    bands = np.empty(n, dtype=object)
    max_single = np.empty(n, dtype=int)
    for i in range(n):
        r = news2(
            heart_rate=hr[i],
            spo2=spo2[i],
            temperature_c=temp[i],
            respiratory_rate=rr[i],
            systolic_bp=sbp[i],
            on_oxygen=bool(on_oxygen[i]),
            alert=bool(alert[i]),
        )
        totals[i] = r.total
        bands[i] = r.band
        max_single[i] = r.max_single
    return totals, bands, max_single


def _label(latent: Dict[str, np.ndarray]) -> pd.DataFrame:
    """Score NEWS2 on the latent values -> ground truth."""
    totals, bands, max_single = _score_many(
        latent["heart_rate"],
        latent["spo2"],
        latent["temperature_c"],
        latent["respiratory_rate"],
        latent["systolic_bp"],
        latent["on_oxygen"],
        latent["alert"],
    )
    return pd.DataFrame(
        {"news2_true": totals, "band_true": bands, "max_single_true": max_single}
    )


def _corrupt(
    rng: np.random.Generator, latent: Dict[str, np.ndarray], noise: NoiseConfig
) -> Dict[str, np.ndarray]:
    """Apply the sensor model. scale == 0.0 yields a clean passthrough."""
    s = noise.scale
    n = latent["heart_rate"].size

    hr = latent["heart_rate"] + rng.normal(0, noise.hr_sigma * s, n)
    if s > 0:
        artefact = rng.random(n) < noise.hr_artifact_rate * s
        lo, hi = noise.hr_artifact_magnitude
        hr = hr + artefact * rng.uniform(lo, hi, n)

    spo2 = latent["spo2"] + rng.normal(0, noise.spo2_sigma * s, n)
    if s > 0:
        drop = rng.random(n) < noise.spo2_dropout_rate * s
        lo, hi = noise.spo2_dropout_magnitude
        spo2 = spo2 - drop * rng.uniform(lo, hi, n)

    rr = latent["respiratory_rate"] + rng.normal(0, noise.rr_sigma * s, n)
    temp = latent["temperature_c"] + rng.normal(0, noise.temp_sigma * s, n)
    sbp = latent["systolic_bp"] + rng.normal(0, noise.sbp_sigma * s, n)
    dbp = latent["diastolic_bp"] + rng.normal(0, noise.dbp_sigma * s, n)

    # Display quantisation is itself a corruption: rounding can push a value
    # across a NEWS2 threshold. It is therefore part of the noise model and is
    # switched off at scale == 0, so that scale == 0 is an exact passthrough and
    # can serve as an identity check on the generator and the scorer.
    if s > 0:
        obs = {
            "heart_rate": np.round(np.clip(hr, 20, 300)),
            "respiratory_rate": np.round(np.clip(rr, 3, 70)),
            "spo2": np.round(np.clip(spo2, 50, 100), 1),
            "systolic_bp": np.round(np.clip(sbp, 40, 300)),
            "diastolic_bp": np.round(np.clip(dbp, 20, 200)),
            "temperature_c": np.round(np.clip(temp, 25, 45), 1),
            "glucose_mgdl": np.round(latent["glucose_mgdl"], 1),
        }
    else:
        obs = {
            "heart_rate": np.clip(hr, 20, 300),
            "respiratory_rate": np.clip(rr, 3, 70),
            "spo2": np.clip(spo2, 50, 100),
            "systolic_bp": np.clip(sbp, 40, 300),
            "diastolic_bp": np.clip(dbp, 20, 200),
            "temperature_c": np.clip(temp, 25, 45),
            "glucose_mgdl": latent["glucose_mgdl"],
        }

    # Keep DBP strictly below SBP after independent perturbation.
    bad = obs["diastolic_bp"] >= obs["systolic_bp"]
    obs["diastolic_bp"] = np.where(
        bad, obs["systolic_bp"] - 10, obs["diastolic_bp"]
    )

    if s > 0 and noise.missing_rate > 0:
        for ch in (
            "heart_rate",
            "spo2",
            "respiratory_rate",
            "temperature_c",
            "systolic_bp",
            "diastolic_bp",
        ):
            miss = rng.random(n) < noise.missing_rate * s
            obs[ch] = np.where(miss, np.nan, obs[ch])

    # Context flags are recorded by staff, not sensed; they pass through clean.
    obs["on_oxygen"] = latent["on_oxygen"]
    obs["alert"] = latent["alert"]
    return obs


def generate_cohort(
    cohort: Optional[CohortConfig] = None,
    noise: Optional[NoiseConfig] = None,
) -> pd.DataFrame:
    """Build the cohort: observed telemetry plus latent ground truth.

    Columns: patient_id, reading_index, observed channels, derived features,
    news2_true / band_true, and the latent channels prefixed ``latent_``.
    """
    cohort = cohort or CohortConfig()
    noise = noise or NoiseConfig()
    rng = np.random.default_rng(cohort.seed)

    z_patient = _sample_severity(rng, cohort)
    subtype_patient = rng.integers(0, len(SUBTYPES), size=cohort.n_patients)

    frames = []
    for k in range(cohort.readings_per_patient):
        # Severity drifts slightly between readings of the same patient, so
        # repeated readings are correlated but not identical.
        z_k = np.clip(z_patient + rng.normal(0, 0.05, cohort.n_patients), 0, 1)

        latent = _latent_physiology(rng, z_k, subtype_patient)
        truth = _label(latent)
        obs = _corrupt(rng, latent, noise)

        frame = pd.DataFrame(obs)
        frame["patient_id"] = np.arange(cohort.n_patients)
        frame["reading_index"] = k
        frame["severity"] = z_k
        frame["subtype"] = [SUBTYPES[i] for i in subtype_patient]
        for key, arr in latent.items():
            frame[f"latent_{key}"] = arr
        frame = pd.concat([frame, truth], axis=1)
        frames.append(frame)

    df = pd.concat(frames, ignore_index=True)
    df = add_derived(df)
    return df.sort_values(["patient_id", "reading_index"]).reset_index(drop=True)


def news2_on_observed(
    df: pd.DataFrame, median_fill: Optional[pd.Series] = None
) -> pd.DataFrame:
    """Baseline B0: apply the NEWS2 rule to the corrupted observations.

    Missing channels are median-imputed first. That is the charitable reading of
    what a threshold monitor does on dropout; refusing to score would make the
    baseline artificially worse.
    """
    cols = ["heart_rate", "spo2", "temperature_c", "respiratory_rate", "systolic_bp"]
    filled = df[cols].astype(float).copy()
    if median_fill is None:
        median_fill = filled.median()
    filled = filled.fillna(median_fill)

    totals, bands, _ = _score_many(
        filled["heart_rate"].to_numpy(),
        filled["spo2"].to_numpy(),
        filled["temperature_c"].to_numpy(),
        filled["respiratory_rate"].to_numpy(),
        filled["systolic_bp"].to_numpy(),
        df["on_oxygen"].to_numpy(),
        df["alert"].to_numpy(),
    )
    return pd.DataFrame({"news2_obs": totals, "band_obs": bands}, index=df.index)
