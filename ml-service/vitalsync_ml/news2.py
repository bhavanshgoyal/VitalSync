"""NEWS2 — National Early Warning Score 2 (Royal College of Physicians, 2017).

Implemented as the *clinical labeler* for the VitalSync triage model. NEWS2 is a
published, peer-reviewed escalation standard; using it as the training target
replaces the arbitrary threshold labels used in the earlier milestone.

Scope note: NEWS2 is a deterministic aggregate score, not a diagnosis, and it is
validated for acutely-ill adults in hospital. Nothing here is clinical advice.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Literal

Band = Literal["LOW", "MEDIUM", "HIGH"]
BANDS: tuple[Band, ...] = ("LOW", "MEDIUM", "HIGH")

# Ordinal encoding used by the models; keep stable across retrains.
BAND_TO_INT: Dict[str, int] = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}
INT_TO_BAND: Dict[int, str] = {v: k for k, v in BAND_TO_INT.items()}


def score_respiratory_rate(rr: float) -> int:
    """Breaths per minute."""
    if rr <= 8:
        return 3
    if rr <= 11:
        return 1
    if rr <= 20:
        return 0
    if rr <= 24:
        return 2
    return 3


def score_spo2_scale1(spo2: float) -> int:
    """Oxygen saturation, NEWS2 Scale 1 (patients without hypercapnic failure)."""
    if spo2 <= 91:
        return 3
    if spo2 <= 93:
        return 2
    if spo2 <= 95:
        return 1
    return 0


def score_supplemental_oxygen(on_oxygen: bool) -> int:
    return 2 if on_oxygen else 0


def score_systolic_bp(sbp: float) -> int:
    """Systolic blood pressure, mmHg."""
    if sbp <= 90:
        return 3
    if sbp <= 100:
        return 2
    if sbp <= 110:
        return 1
    if sbp <= 219:
        return 0
    return 3


def score_pulse(hr: float) -> int:
    """Pulse, beats per minute."""
    if hr <= 40:
        return 3
    if hr <= 50:
        return 1
    if hr <= 90:
        return 0
    if hr <= 110:
        return 1
    if hr <= 130:
        return 2
    return 3


def score_consciousness(alert: bool) -> int:
    """Alert (0) vs CVPU — confusion, voice, pain, unresponsive (3)."""
    return 0 if alert else 3


def score_temperature(temp_c: float) -> int:
    """Body temperature, degrees Celsius."""
    if temp_c <= 35.0:
        return 3
    if temp_c <= 36.0:
        return 1
    if temp_c <= 38.0:
        return 0
    if temp_c <= 39.0:
        return 1
    return 2


@dataclass(frozen=True)
class News2Result:
    total: int
    band: Band
    per_parameter: Dict[str, int] = field(default_factory=dict)
    max_single: int = 0

    def to_dict(self) -> dict:
        return {
            "total": self.total,
            "band": self.band,
            "max_single": self.max_single,
            "per_parameter": dict(self.per_parameter),
        }


def band_from_score(total: int, max_single: int) -> Band:
    """Map an aggregate NEWS2 score to the VitalSync escalation band.

    Follows the RCP clinical-response bands:
      * aggregate >= 7                       -> high
      * aggregate 5-6, or any single param 3 -> medium (urgent review)
      * otherwise                            -> low

    The "single parameter scores 3" clause is what makes this non-monotonic in
    the aggregate alone, and is the most commonly mis-implemented part of NEWS2.
    """
    if total >= 7:
        return "HIGH"
    if total >= 5 or max_single >= 3:
        return "MEDIUM"
    return "LOW"


def news2(
    *,
    heart_rate: float,
    spo2: float,
    temperature_c: float,
    respiratory_rate: float,
    systolic_bp: float,
    on_oxygen: bool = False,
    alert: bool = True,
) -> News2Result:
    """Compute the full NEWS2 aggregate score and escalation band.

    Diastolic BP and glucose are not NEWS2 parameters; they are carried by the
    system for display and as model features, but never affect this score.
    """
    per = {
        "respiratory_rate": score_respiratory_rate(respiratory_rate),
        "spo2": score_spo2_scale1(spo2),
        "supplemental_oxygen": score_supplemental_oxygen(on_oxygen),
        "systolic_bp": score_systolic_bp(systolic_bp),
        "pulse": score_pulse(heart_rate),
        "consciousness": score_consciousness(alert),
        "temperature": score_temperature(temperature_c),
    }
    total = sum(per.values())
    max_single = max(per.values())
    return News2Result(
        total=total,
        band=band_from_score(total, max_single),
        per_parameter=per,
        max_single=max_single,
    )
