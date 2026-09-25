"""IoMT telemetry simulator.

Drives the backend the way a fleet of wearables would: authenticate once, then
stream observations for one or more patients. Scenario modes let a demo or a
benchmark reproduce a specific clinical trajectory rather than random noise.

Examples::

    python simulate.py --count 30 --interval 0.5
    python simulate.py --patient-id P002 --scenario deteriorating --count 40
    python simulate.py --patients P001,P002,P003 --scenario mixed --count 60
"""

from __future__ import annotations

import argparse
import json
import math
import random
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Optional


@dataclass
class Vitals:
    heart_rate: float
    spo2: float
    temperature_c: float
    respiratory_rate: float
    systolic_bp: float
    diastolic_bp: float
    glucose_mgdl: Optional[float] = None
    on_oxygen: bool = False
    alert: bool = True

    def payload(self, patient_id: str) -> Dict:
        body = {
            "patientId": patient_id,
            "heartRate": round(self.heart_rate),
            "spo2": round(self.spo2, 1),
            "temperatureC": round(self.temperature_c, 1),
            "respiratoryRate": round(self.respiratory_rate),
            "systolicBp": round(self.systolic_bp),
            "diastolicBp": round(self.diastolic_bp),
            "onOxygen": self.on_oxygen,
            "alert": self.alert,
            "observedAt": datetime.now(timezone.utc).isoformat(),
        }
        if self.glucose_mgdl is not None:
            body["glucoseMgdl"] = round(self.glucose_mgdl, 1)
        return body


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def vitals_for(scenario: str, step: int, total: int, rng: random.Random) -> Vitals:
    """Generate one observation for a scenario at a given point in the run.

    ``severity`` moves between 0 and 1 over the run; every channel is derived
    from it so the stream shows a coherent trajectory instead of independently
    jittering numbers.
    """
    progress = step / max(total - 1, 1)

    if scenario == "stable":
        severity = 0.05 + 0.05 * math.sin(progress * math.pi * 2)
    elif scenario == "deteriorating":
        severity = progress ** 1.3
    elif scenario == "recovering":
        severity = (1.0 - progress) ** 1.3
    elif scenario == "septic":
        # Slow burn, then a sharp turn in the last third.
        severity = 0.15 + (0.75 * max(progress - 0.6, 0) / 0.4 if progress > 0.6 else 0.15 * progress)
    elif scenario == "high":
        severity = 0.85
    else:  # "random"
        severity = rng.random()

    severity = _clamp(severity + rng.gauss(0, 0.03), 0.0, 1.0)
    j = lambda sd: rng.gauss(0, sd)  # noqa: E731 - local shorthand

    return Vitals(
        heart_rate=_clamp(70 + 62 * severity + j(3.5), 40, 190),
        spo2=_clamp(98.2 - 10.5 * severity + j(1.0), 70, 100),
        temperature_c=_clamp(36.8 + 2.3 * severity + j(0.2), 34.5, 41.0),
        respiratory_rate=_clamp(14 + 13 * severity + j(1.2), 8, 40),
        systolic_bp=_clamp(122 - 40 * severity + j(6), 70, 190),
        diastolic_bp=_clamp(78 - 22 * severity + j(5), 45, 110),
        glucose_mgdl=_clamp(95 + 55 * severity + j(12), 55, 350),
        on_oxygen=severity > 0.6 and rng.random() < 0.7,
        alert=not (severity > 0.8 and rng.random() < 0.35),
    )


def post_json(url: str, body: Dict, token: Optional[str] = None, timeout: float = 10.0):
    data = json.dumps(body).encode("utf-8")
    request = urllib.request.Request(url, data=data, method="POST")
    request.add_header("Content-Type", "application/json")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read().decode("utf-8")
        return response.status, (json.loads(raw) if raw else {})


def authenticate(base_url: str, username: str, password: str) -> str:
    status, body = post_json(
        f"{base_url}/api/v1/auth/token",
        {"username": username, "password": password},
    )
    if status != 200 or "token" not in body:
        raise SystemExit(f"Authentication failed ({status}): {body}")
    return body["token"]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="VitalSync telemetry simulator")
    ap.add_argument("--base-url", default="http://localhost:8080")
    ap.add_argument("--patient-id", default="P001")
    ap.add_argument("--patients", default=None,
                    help="comma-separated ids; overrides --patient-id")
    ap.add_argument("--count", type=int, default=20, help="readings per patient")
    ap.add_argument("--interval", type=float, default=0.5, help="seconds between readings")
    ap.add_argument(
        "--scenario",
        default="stable",
        choices=["stable", "deteriorating", "recovering", "septic", "high", "random", "mixed"],
        help="'mixed' assigns a different scenario to each patient",
    )
    ap.add_argument("--username", default="clinician")
    ap.add_argument("--password", default="vitalsync-demo")
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)

    rng = random.Random(args.seed)

    patients: List[str] = (
        [p.strip() for p in args.patients.split(",") if p.strip()]
        if args.patients else [args.patient_id]
    )

    rotation = ["stable", "deteriorating", "septic", "recovering"]
    scenarios = {
        pid: (rotation[i % len(rotation)] if args.scenario == "mixed" else args.scenario)
        for i, pid in enumerate(patients)
    }

    print(f"Authenticating against {args.base_url} ...")
    token = authenticate(args.base_url, args.username, args.password)
    print(f"Token acquired. Streaming {args.count} readings for "
          f"{len(patients)} patient(s).")
    for pid in patients:
        print(f"  {pid}: scenario={scenarios[pid]}")

    url = f"{args.base_url}/api/v1/telemetry"
    sent = 0
    failed = 0
    latencies: List[float] = []

    for step in range(args.count):
        for pid in patients:
            vitals = vitals_for(scenarios[pid], step, args.count, rng)
            try:
                t0 = time.perf_counter()
                status, body = post_json(url, vitals.payload(pid), token)
                latencies.append((time.perf_counter() - t0) * 1000.0)
                if status == 202:
                    sent += 1
                    if not args.quiet:
                        print(f"[{step + 1:>3}/{args.count}] {pid} "
                              f"HR={vitals.heart_rate:5.1f} "
                              f"SpO2={vitals.spo2:5.1f} "
                              f"BP={vitals.systolic_bp:5.1f}/{vitals.diastolic_bp:4.1f} "
                              f"T={vitals.temperature_c:4.1f} "
                              f"RR={vitals.respiratory_rate:4.1f} "
                              f"-> reading {body.get('readingId')}")
                else:
                    failed += 1
                    print(f"  unexpected status {status}: {body}", file=sys.stderr)
            except urllib.error.HTTPError as e:
                failed += 1
                print(f"  HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:200]}",
                      file=sys.stderr)
            except Exception as e:  # network down, backend restarting
                failed += 1
                print(f"  request failed: {e}", file=sys.stderr)

        if args.interval > 0 and step < args.count - 1:
            time.sleep(args.interval)

    print(f"\nAccepted {sent}, failed {failed}.")
    if latencies:
        latencies.sort()
        p95 = latencies[int(len(latencies) * 0.95) - 1] if len(latencies) > 1 else latencies[0]
        print(f"Ingestion latency: mean {sum(latencies) / len(latencies):.1f} ms, "
              f"p50 {latencies[len(latencies) // 2]:.1f} ms, p95 {p95:.1f} ms")
    print(f"Dashboard: {args.base_url}/")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
