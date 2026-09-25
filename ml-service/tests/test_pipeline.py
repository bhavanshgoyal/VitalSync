"""Feature, generator, split and service tests."""

import math

import numpy as np
import pandas as pd
import pytest

from vitalsync_ml.datagen import (
    CohortConfig,
    NoiseConfig,
    generate_cohort,
    news2_on_observed,
)
from vitalsync_ml.features import (
    TRIAGE_FEATURES,
    add_derived,
    mean_arterial_pressure,
    pulse_pressure,
    shock_index,
    to_model_matrix,
)
from vitalsync_ml.train import split_by_patient
from vitalsync_ml.validation import validate

SMALL = CohortConfig(n_patients=1500, readings_per_patient=2, seed=7)


# ---------------------------------------------------------------- features

def test_shock_index():
    assert shock_index(100, 100) == pytest.approx(1.0)
    assert shock_index(60, 120) == pytest.approx(0.5)


def test_shock_index_guards_zero_systolic():
    """A failed cuff can report 0; the feature must not raise or return inf."""
    assert math.isnan(shock_index(80, 0))
    assert math.isnan(shock_index(80, -5))


def test_pulse_pressure_and_map():
    assert pulse_pressure(120, 80) == 40
    assert mean_arterial_pressure(120, 60) == pytest.approx(80.0)


def test_add_derived_matches_scalar_functions():
    df = pd.DataFrame(
        [{"heart_rate": 88, "spo2": 96, "temperature_c": 37.1,
          "respiratory_rate": 18, "systolic_bp": 118, "diastolic_bp": 74}]
    )
    out = add_derived(df).iloc[0]
    assert out["shock_index"] == pytest.approx(shock_index(88, 118))
    assert out["pulse_pressure"] == pytest.approx(pulse_pressure(118, 74))
    assert out["map_mmhg"] == pytest.approx(mean_arterial_pressure(118, 74))


def test_model_matrix_column_order_is_contractual():
    df = pd.DataFrame(
        [{"heart_rate": 80, "spo2": 97, "temperature_c": 36.9,
          "respiratory_rate": 16, "systolic_bp": 120, "diastolic_bp": 78}]
    )
    assert list(to_model_matrix(df).columns) == TRIAGE_FEATURES


def test_model_matrix_defaults_context_flags():
    df = pd.DataFrame(
        [{"heart_rate": 80, "spo2": 97, "temperature_c": 36.9,
          "respiratory_rate": 16, "systolic_bp": 120, "diastolic_bp": 78}]
    )
    row = to_model_matrix(df).iloc[0]
    assert row["on_oxygen"] == 0.0
    assert row["alert"] == 1.0


# --------------------------------------------------------------- validation

def test_validation_accepts_normal_observation():
    assert validate(
        {"heart_rate": 72, "spo2": 98, "temperature_c": 36.8,
         "respiratory_rate": 16, "systolic_bp": 120, "diastolic_bp": 78}
    ) == []


def test_validation_rejects_impossible_values():
    problems = validate({"heart_rate": 900, "spo2": 140})
    assert len(problems) == 2


def test_validation_rejects_diastolic_above_systolic():
    problems = validate({"systolic_bp": 100, "diastolic_bp": 110})
    assert any("diastolic" in p for p in problems)


def test_validation_ignores_absent_optional_channel():
    assert validate({"heart_rate": 72, "glucose_mgdl": None}) == []


# ---------------------------------------------------------------- generator

def test_generator_populates_all_three_bands():
    df = generate_cohort(SMALL)
    counts = df["band_true"].value_counts()
    for band in ("LOW", "MEDIUM", "HIGH"):
        assert counts.get(band, 0) > 0, f"band {band} never generated"


def test_generator_is_deterministic_for_a_seed():
    a = generate_cohort(SMALL)
    b = generate_cohort(SMALL)
    pd.testing.assert_frame_equal(a, b)


def test_zero_noise_is_an_exact_identity():
    """The critical sanity check.

    At noise scale 0 the observation equals the latent signal, so NEWS2 scored
    on the observation must reproduce the ground-truth band for every row. If
    this drifts below 1.0, the generator and the scorer disagree and every
    downstream comparison is meaningless.
    """
    df = generate_cohort(SMALL, NoiseConfig().scaled(0.0))
    obs = news2_on_observed(df)
    assert (obs["band_obs"] == df["band_true"]).all()


def test_noise_degrades_the_rule_baseline():
    """Sanity in the other direction: noise must actually cost the rule."""
    clean = generate_cohort(SMALL, NoiseConfig().scaled(0.0))
    noisy = generate_cohort(SMALL, NoiseConfig().scaled(1.0))
    clean_acc = (news2_on_observed(clean)["band_obs"] == clean["band_true"]).mean()
    noisy_acc = (news2_on_observed(noisy)["band_obs"] == noisy["band_true"]).mean()
    assert clean_acc == 1.0
    assert noisy_acc < clean_acc


def test_noise_introduces_missing_values():
    df = generate_cohort(SMALL, NoiseConfig().scaled(1.0))
    assert df["heart_rate"].isna().sum() > 0


def test_diastolic_never_exceeds_systolic_after_corruption():
    df = generate_cohort(SMALL, NoiseConfig().scaled(2.0))
    both = df[["systolic_bp", "diastolic_bp"]].dropna()
    assert (both["diastolic_bp"] < both["systolic_bp"]).all()


# -------------------------------------------------------------------- split

def test_patient_level_split_has_no_overlap():
    df = generate_cohort(SMALL)
    train, test = split_by_patient(df, seed=7)
    assert not (set(train["patient_id"]) & set(test["patient_id"]))
    assert len(train) + len(test) == len(df)


def test_split_would_leak_if_done_by_row():
    """Documents why the group split exists rather than assuming it."""
    df = generate_cohort(SMALL)
    rng = np.random.default_rng(0)
    idx = rng.permutation(len(df))
    row_train = df.iloc[idx[: int(0.8 * len(df))]]
    row_test = df.iloc[idx[int(0.8 * len(df)) :]]
    shared = set(row_train["patient_id"]) & set(row_test["patient_id"])
    assert shared, "a naive row split shares patients -- which is the leak"
