"""E4: ingestion throughput and latency under concurrent load.

Measures the *synchronous* ingestion path only -- the one the architecture
claims is decoupled from triage and summarization. Analysis proceeds on the
bounded executor behind it, so a growing gap between accepted readings and
completed assessments is the expected behaviour under load, not a defect. The
script reports that gap explicitly rather than hiding it.

Run the stack first, then::

    python bench/throughput.py --rates 10,50,100,250 --seconds 10
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import (  # noqa: E402
    DEFAULT_BASE_URL,
    ENVIRONMENT_NOTE,
    authenticate,
    request_json,
    summarise,
)

ARTIFACTS = Path(__file__).resolve().parent.parent / "ml-service" / "artifacts"


def make_reading(rng: random.Random, patient_id: str) -> dict:
    severity = rng.random()
    return {
        "patientId": patient_id,
        "heartRate": round(70 + 60 * severity + rng.gauss(0, 4)),
        "spo2": round(max(70.0, 98.0 - 10 * severity + rng.gauss(0, 1)), 1),
        "temperatureC": round(36.8 + 2.0 * severity + rng.gauss(0, 0.2), 1),
        "respiratoryRate": round(14 + 12 * severity + rng.gauss(0, 1.2)),
        "systolicBp": round(122 - 38 * severity + rng.gauss(0, 6)),
        "diastolicBp": round(78 - 20 * severity + rng.gauss(0, 5)),
        "observedAt": datetime.now(timezone.utc).isoformat(),
    }


def run_rate(base_url: str, token: str, rate: int, seconds: int, patients: list) -> dict:
    """Drive `rate` requests/second for `seconds` using an open-loop schedule.

    Open loop matters: a closed loop (fire, wait for the reply, fire again)
    silently throttles itself to whatever the server can manage and therefore
    cannot detect saturation. Here the schedule is fixed in advance, so a server
    that falls behind shows up as rising latency rather than a lower offered rate.
    """
    url = f"{base_url}/api/v1/telemetry"
    total = rate * seconds
    rng = random.Random(1234 + rate)
    schedule = [i / rate for i in range(total)]

    latencies = []
    errors = 0
    lock = threading.Lock()
    start = time.perf_counter()

    def fire(offset: float, index: int):
        nonlocal errors
        delay = offset - (time.perf_counter() - start)
        if delay > 0:
            time.sleep(delay)
        body = make_reading(rng, patients[index % len(patients)])
        t0 = time.perf_counter()
        try:
            status, _ = request_json(url, body, token, method="POST", timeout=30)
            elapsed = (time.perf_counter() - t0) * 1000.0
            if status != 202:
                with lock:
                    errors += 1
            else:
                with lock:
                    latencies.append(elapsed)
        except Exception:
            with lock:
                errors += 1

    workers = min(256, max(16, rate))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(fire, schedule[i], i) for i in range(total)]
        for f in as_completed(futures):
            f.result()

    wall = time.perf_counter() - start
    return {
        "target_rate_rps": rate,
        "duration_s": seconds,
        "requests_attempted": total,
        "requests_accepted": len(latencies),
        "errors": errors,
        "error_rate": errors / total if total else 0.0,
        "wall_clock_s": round(wall, 3),
        "achieved_rps": round(len(latencies) / wall, 2) if wall > 0 else 0.0,
        "ingest_latency_ms": summarise(latencies),
    }


def assessment_count(base_url: str, token: str) -> int:
    _, body = request_json(f"{base_url}/api/v1/system/providers", token=token)
    return int(body.get("totalAssessments", 0))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="VitalSync ingestion throughput")
    ap.add_argument("--base-url", default=DEFAULT_BASE_URL)
    ap.add_argument("--rates", default="10,50,100,250")
    ap.add_argument("--seconds", type=int, default=10)
    ap.add_argument("--patients", default="P001,P002,P003,P004")
    ap.add_argument("--drain-seconds", type=int, default=25,
                    help="time allowed for the async backlog to clear")
    ap.add_argument("--out", default=str(ARTIFACTS / "throughput.json"))
    args = ap.parse_args(argv)

    rates = [int(r) for r in args.rates.split(",") if r.strip()]
    patients = [p.strip() for p in args.patients.split(",") if p.strip()]

    token = authenticate(args.base_url)
    results = []

    for rate in rates:
        before = assessment_count(args.base_url, token)
        print(f"[E4] offering {rate} req/s for {args.seconds}s ...")
        result = run_rate(args.base_url, token, rate, args.seconds, patients)

        # Let the bounded executor work through whatever it queued.
        deadline = time.perf_counter() + args.drain_seconds
        accepted = result["requests_accepted"]
        while time.perf_counter() < deadline:
            done = assessment_count(args.base_url, token) - before
            if done >= accepted:
                break
            time.sleep(1.0)

        completed = assessment_count(args.base_url, token) - before
        result["assessments_completed_within_drain"] = completed
        result["analysis_backlog_after_drain"] = max(0, accepted - completed)
        result["drain_seconds"] = args.drain_seconds

        lat = result["ingest_latency_ms"]
        print(f"     accepted={accepted} errors={result['errors']} "
              f"achieved={result['achieved_rps']} rps "
              f"p50={lat.get('p50', float('nan')):.1f}ms "
              f"p95={lat.get('p95', float('nan')):.1f}ms "
              f"analysis_done={completed}")
        results.append(result)

    payload = {
        "experiment": "E4 ingestion throughput",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "base_url": args.base_url,
        "note": ENVIRONMENT_NOTE,
        "measures": (
            "Synchronous ingestion only. Risk analysis runs asynchronously; the "
            "backlog column shows how far analysis trails ingestion, which is "
            "the intended behaviour of the decoupled design."
        ),
        "results": results,
    }
    Path(args.out).write_text(json.dumps(payload, indent=2))
    print(f"[ok] wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
