"""E6: event-count arithmetic for three notification policies.

IMPORTANT FRAMING
-----------------
This counts *events*, nothing more. It is arithmetic over a simulated telemetry
stream, and it is NOT a measurement of clinician alert fatigue, workload, or
patient benefit. Those require a study with real clinicians and real patients.
Every output of this script carries that caveat, and the paper must repeat it
wherever these numbers appear.

Policies compared over the same stream:

  A  per-parameter thresholds    one event per breaching parameter per reading
                                 (what a conventional bedside monitor emits)
  B  aggregate band              one event per reading whose band is not LOW
  C  band-transition             one event only when the band *changes* upward,
                                 which is what a triage-then-summarise pipeline
                                 would actually surface to a clinician

Run::

    python bench/alert_compression.py --patients 200 --readings 24
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "ml-service"))

from vitalsync_ml.datagen import (  # noqa: E402
    CohortConfig,
    NoiseConfig,
    generate_cohort,
)

ARTIFACTS = ROOT / "ml-service" / "artifacts"

# Conventional single-parameter alarm limits.
THRESHOLDS = {
    "heart_rate": lambda v: v > 100 or v < 50,
    "spo2": lambda v: v < 92,
    "systolic_bp": lambda v: v < 100 or v > 180,
    "temperature_c": lambda v: v > 38.0 or v < 36.0,
    "respiratory_rate": lambda v: v > 20 or v < 12,
}

BAND_RANK = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}


def count_policy_a(df) -> int:
    """One event per breaching parameter per reading."""
    events = 0
    for channel, breaches in THRESHOLDS.items():
        series = df[channel].astype(float)
        events += int(series.dropna().map(breaches).sum())
    return events


def count_policy_b(df) -> int:
    """One event per reading whose band is not LOW."""
    return int((df["band_true"] != "LOW").sum())


def count_policy_c(df) -> int:
    """One event per upward band transition, per patient, in reading order."""
    events = 0
    for _, group in df.sort_values(["patient_id", "reading_index"]).groupby("patient_id"):
        previous = 0
        for band in group["band_true"]:
            rank = BAND_RANK.get(band, 0)
            if rank > previous:
                events += 1
            previous = rank
    return events


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="VitalSync event-count comparison")
    ap.add_argument("--patients", type=int, default=200)
    ap.add_argument("--readings", type=int, default=24)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", default=str(ARTIFACTS / "alert_compression.json"))
    args = ap.parse_args(argv)

    df = generate_cohort(
        CohortConfig(n_patients=args.patients, readings_per_patient=args.readings,
                     seed=args.seed),
        NoiseConfig(),
    )

    total_readings = len(df)
    a = count_policy_a(df)
    b = count_policy_b(df)
    c = count_policy_c(df)

    def per_100(n: int) -> float:
        return round(100.0 * n / total_readings, 3)

    payload = {
        "experiment": "E6 notification event counts",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "cohort": {
            "patients": args.patients,
            "readings_per_patient": args.readings,
            "total_readings": total_readings,
            "seed": args.seed,
            "band_counts": {k: int(v) for k, v in df["band_true"].value_counts().items()},
        },
        "policies": {
            "A_per_parameter_thresholds": {
                "events": a,
                "events_per_100_readings": per_100(a),
                "definition": "one event per breaching parameter per reading",
            },
            "B_aggregate_band": {
                "events": b,
                "events_per_100_readings": per_100(b),
                "definition": "one event per reading whose band is not LOW",
            },
            "C_band_transition": {
                "events": c,
                "events_per_100_readings": per_100(c),
                "definition": "one event per upward band transition per patient",
            },
        },
        "ratios": {
            "A_over_B": round(a / b, 3) if b else None,
            "A_over_C": round(a / c, 3) if c else None,
            "B_over_C": round(b / c, 3) if c else None,
        },
        "CAVEAT": (
            "These are event counts over a simulated stream. They are NOT a "
            "measurement of alert fatigue, clinician workload, diagnostic "
            "accuracy, or patient outcome, and must not be reported as such. "
            "Policy C emits fewer events by construction; whether that is "
            "clinically safe is unknown and untested here -- fewer "
            "notifications can mean missed deterioration."
        ),
    }

    Path(args.out).write_text(json.dumps(payload, indent=2))

    print(f"[E6] over {total_readings:,} simulated readings")
    print(f"     A per-parameter thresholds : {a:>7,} events "
          f"({per_100(a)} per 100 readings)")
    print(f"     B aggregate band           : {b:>7,} events "
          f"({per_100(b)} per 100 readings)")
    print(f"     C band transition          : {c:>7,} events "
          f"({per_100(c)} per 100 readings)")
    print("     CAVEAT: event arithmetic only -- not a clinical or workload claim.")
    print(f"[ok] wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
