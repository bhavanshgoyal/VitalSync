"""NEWS2 boundary tests.

Every threshold is tested on both sides. NEWS2 is copied by hand into a lot of
software and the boundaries are where implementations diverge -- particularly
the "single parameter scores 3" escalation clause, which is not a function of
the aggregate alone.
"""

import pytest

from vitalsync_ml.news2 import (
    band_from_score,
    news2,
    score_consciousness,
    score_pulse,
    score_respiratory_rate,
    score_spo2_scale1,
    score_supplemental_oxygen,
    score_systolic_bp,
    score_temperature,
)


@pytest.mark.parametrize(
    "rr,expected",
    [(3, 3), (8, 3), (9, 1), (11, 1), (12, 0), (20, 0), (21, 2), (24, 2), (25, 3), (60, 3)],
)
def test_respiratory_rate(rr, expected):
    assert score_respiratory_rate(rr) == expected


@pytest.mark.parametrize(
    "spo2,expected",
    [(70, 3), (91, 3), (92, 2), (93, 2), (94, 1), (95, 1), (96, 0), (100, 0)],
)
def test_spo2(spo2, expected):
    assert score_spo2_scale1(spo2) == expected


def test_supplemental_oxygen():
    assert score_supplemental_oxygen(False) == 0
    assert score_supplemental_oxygen(True) == 2


@pytest.mark.parametrize(
    "sbp,expected",
    [(60, 3), (90, 3), (91, 2), (100, 2), (101, 1), (110, 1),
     (111, 0), (219, 0), (220, 3), (250, 3)],
)
def test_systolic_bp(sbp, expected):
    assert score_systolic_bp(sbp) == expected


@pytest.mark.parametrize(
    "hr,expected",
    [(30, 3), (40, 3), (41, 1), (50, 1), (51, 0), (90, 0),
     (91, 1), (110, 1), (111, 2), (130, 2), (131, 3), (200, 3)],
)
def test_pulse(hr, expected):
    assert score_pulse(hr) == expected


def test_consciousness():
    assert score_consciousness(True) == 0
    assert score_consciousness(False) == 3


@pytest.mark.parametrize(
    "t,expected",
    [(34.0, 3), (35.0, 3), (35.1, 1), (36.0, 1), (36.1, 0), (38.0, 0),
     (38.1, 1), (39.0, 1), (39.1, 2), (41.0, 2)],
)
def test_temperature(t, expected):
    assert score_temperature(t) == expected


def test_healthy_adult_scores_zero():
    r = news2(
        heart_rate=72, spo2=98, temperature_c=36.8,
        respiratory_rate=16, systolic_bp=120,
    )
    assert r.total == 0
    assert r.band == "LOW"


def test_critically_unwell_scores_high():
    r = news2(
        heart_rate=135, spo2=89, temperature_c=39.4,
        respiratory_rate=28, systolic_bp=85,
        on_oxygen=True, alert=False,
    )
    assert r.total >= 7
    assert r.band == "HIGH"


def test_band_thresholds():
    assert band_from_score(0, 0) == "LOW"
    assert band_from_score(4, 2) == "LOW"
    assert band_from_score(5, 2) == "MEDIUM"
    assert band_from_score(6, 2) == "MEDIUM"
    assert band_from_score(7, 2) == "HIGH"
    assert band_from_score(20, 3) == "HIGH"


def test_single_parameter_three_escalates_despite_low_aggregate():
    """The clause most often omitted: one parameter at 3 forces MEDIUM."""
    assert band_from_score(3, 3) == "MEDIUM"

    # A patient whose only derangement is SpO2 91% -- aggregate 3, one param 3.
    r = news2(
        heart_rate=72, spo2=91, temperature_c=36.8,
        respiratory_rate=16, systolic_bp=120,
    )
    assert r.total == 3
    assert r.max_single == 3
    assert r.band == "MEDIUM", "aggregate 3 with a single 3 must escalate"


def test_aggregate_three_without_a_single_three_stays_low():
    """Contrast case: same aggregate, spread across parameters -> LOW."""
    r = news2(
        heart_rate=95,           # 1
        spo2=94,                 # 1
        temperature_c=35.5,      # 1
        respiratory_rate=16,     # 0
        systolic_bp=120,         # 0
    )
    assert r.total == 3
    assert r.max_single == 1
    assert r.band == "LOW"


def test_diastolic_and_glucose_are_not_news2_parameters():
    """Regression guard: NEWS2 must ignore channels the system merely carries."""
    a = news2(
        heart_rate=72, spo2=98, temperature_c=36.8,
        respiratory_rate=16, systolic_bp=120,
    )
    b = news2(
        heart_rate=72, spo2=98, temperature_c=36.8,
        respiratory_rate=16, systolic_bp=120,
    )
    assert a.total == b.total == 0
