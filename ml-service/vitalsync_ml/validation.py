"""Physiological plausibility bounds.

These are *sanity* bounds for rejecting impossible sensor output, deliberately
much wider than clinical normal ranges. A value inside these bounds is not
"normal"; it is merely not physically absurd.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

PLAUSIBLE_RANGES: Dict[str, Tuple[float, float]] = {
    "heart_rate": (20.0, 300.0),
    "spo2": (50.0, 100.0),
    "temperature_c": (25.0, 45.0),
    "respiratory_rate": (3.0, 70.0),
    "systolic_bp": (40.0, 300.0),
    "diastolic_bp": (20.0, 200.0),
    "glucose_mgdl": (10.0, 900.0),
}


def validate(obs: Dict[str, Optional[float]]) -> List[str]:
    """Return a list of human-readable problems; empty list means valid."""
    problems: List[str] = []
    for name, (lo, hi) in PLAUSIBLE_RANGES.items():
        value = obs.get(name)
        if value is None:
            continue
        if not (lo <= float(value) <= hi):
            problems.append(
                f"{name}={value} outside plausible range [{lo}, {hi}]"
            )

    sbp = obs.get("systolic_bp")
    dbp = obs.get("diastolic_bp")
    if sbp is not None and dbp is not None and float(dbp) >= float(sbp):
        problems.append(
            f"diastolic_bp={dbp} must be less than systolic_bp={sbp}"
        )
    return problems
