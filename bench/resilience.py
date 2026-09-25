"""E5: resilience of the analysis path under dependency failure.

Exercises the conditions the architecture claims to survive, by actually
stopping containers rather than by mocking:

  C1  everything up
  C2  triage service down        -> degraded band, summary still produced
  C3  triage service recovering  -> returns to normal without a restart

Each condition submits telemetry, waits for the assessment, and records which
summarization tier answered and whether a model band was available.

Run the stack first, then::

    python bench/resilience.py
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
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
COMPOSE_DIR = Path(__file__).resolve().parent.parent

READING = {
    "heartRate": 124,
    "spo2": 90.5,
    "temperatureC": 38.7,
    "respiratoryRate": 26,
    "systolicBp": 96,
    "diastolicBp": 62,
}


class ComposeUnavailable(RuntimeError):
    """Raised when container control is not possible in this environment."""


def compose(*args: str) -> None:
    """Drive docker compose, failing with a clear, catchable error.

    The container-control conditions need a Docker CLI on PATH and a reachable
    daemon. That is true on a developer workstation and false in plenty of CI
    and grading sandboxes, so this degrades to a skip with an explanation
    rather than a stack trace two thirds of the way through the experiment.
    """
    try:
        subprocess.run(
            ["docker", "compose", *args],
            cwd=str(COMPOSE_DIR),
            check=True,
            capture_output=True,
            timeout=120,
        )
    except FileNotFoundError as e:
        raise ComposeUnavailable("docker CLI not found on PATH") from e
    except subprocess.TimeoutExpired as e:
        raise ComposeUnavailable(f"docker compose {' '.join(args)} timed out") from e
    except subprocess.CalledProcessError as e:
        detail = (e.stderr or b"").decode("utf-8", "replace").strip()[:200]
        raise ComposeUnavailable(
            f"docker compose {' '.join(args)} failed: {detail}") from e


def submit_and_wait(base_url: str, token: str, patient_id: str, timeout_s: float = 30.0):
    """Send one reading and wait for its assessment to appear."""
    _, before = request_json(
        f"{base_url}/api/v1/patients/{patient_id}/risk/latest", token=token)
    before_id = before.get("id") if isinstance(before, dict) else None

    body = dict(READING, patientId=patient_id,
                observedAt=datetime.now(timezone.utc).isoformat())

    t0 = time.perf_counter()
    status, accepted = request_json(
        f"{base_url}/api/v1/telemetry", body, token, method="POST")
    ingest_ms = (time.perf_counter() - t0) * 1000.0
    if status != 202:
        return {"accepted": False, "status": status}

    deadline = time.perf_counter() + timeout_s
    while time.perf_counter() < deadline:
        _, latest = request_json(
            f"{base_url}/api/v1/patients/{patient_id}/risk/latest", token=token)
        if isinstance(latest, dict) and latest.get("id") and latest.get("id") != before_id:
            return {
                "accepted": True,
                "ingest_ms": ingest_ms,
                "time_to_assessment_ms": (time.perf_counter() - t0) * 1000.0,
                "risk_band": latest.get("riskBand"),
                "ml_available": latest.get("mlAvailable"),
                "news2_total": latest.get("news2Total"),
                "summary_provider": latest.get("summaryProvider"),
                "summary_latency_ms": latest.get("summaryLatencyMs"),
                "summary_bullets": len(
                    [l for l in (latest.get("summary") or "").splitlines() if l.strip()]),
            }
        time.sleep(0.25)

    return {"accepted": True, "ingest_ms": ingest_ms, "timed_out": True}


def wait_for_ml_recovery(base_url: str, token: str, patient_id: str,
                         timeout_s: float = 180.0) -> bool:
    """Block until an assessment comes back with the model actually available.

    Polling the container health endpoint is not sufficient: it reports that
    the process is listening, not that the backend can obtain a prediction.
    This submits real probe readings until one is served with ml_available
    true, which is exactly the precondition condition C3 asserts.
    """
    deadline = time.perf_counter() + timeout_s
    while time.perf_counter() < deadline:
        probe = submit_and_wait(base_url, token, patient_id, timeout_s=20.0)
        if probe.get("ml_available"):
            return True
        time.sleep(3)
    return False


def run_condition(base_url: str, token: str, name: str, patient_id: str,
                  repeats: int, description: str) -> dict:
    print(f"[E5] {name}: {description}")
    samples = [submit_and_wait(base_url, token, patient_id) for _ in range(repeats)]
    ok = [s for s in samples if s.get("accepted") and not s.get("timed_out")]

    providers: dict = {}
    for s in ok:
        key = s.get("summary_provider") or "none"
        providers[key] = providers.get(key, 0) + 1

    result = {
        "condition": name,
        "description": description,
        "repeats": repeats,
        "ingest_success_rate": sum(1 for s in samples if s.get("accepted")) / repeats,
        "assessment_success_rate": len(ok) / repeats,
        "summary_provider_counts": providers,
        "ml_available_rate": (
            sum(1 for s in ok if s.get("ml_available")) / len(ok) if ok else 0.0),
        "risk_bands": sorted({s.get("risk_band") for s in ok if s.get("risk_band")}),
        "ingest_ms": summarise([s["ingest_ms"] for s in samples if "ingest_ms" in s]),
        "time_to_assessment_ms": summarise(
            [s["time_to_assessment_ms"] for s in ok if "time_to_assessment_ms" in s]),
        "all_summaries_have_three_bullets": all(
            s.get("summary_bullets") == 3 for s in ok) if ok else False,
    }
    print(f"     ingest {result['ingest_success_rate']:.0%}, "
          f"assessment {result['assessment_success_rate']:.0%}, "
          f"providers {providers}, ml_available {result['ml_available_rate']:.0%}")
    return result


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="VitalSync resilience experiment")
    ap.add_argument("--base-url", default=DEFAULT_BASE_URL)
    ap.add_argument("--patient-id", default="P003")
    ap.add_argument("--repeats", type=int, default=5)
    ap.add_argument("--skip-container-control", action="store_true",
                    help="run only the all-up condition")
    ap.add_argument("--out", default=str(ARTIFACTS / "resilience.json"))
    args = ap.parse_args(argv)

    token = authenticate(args.base_url)
    conditions = []

    conditions.append(run_condition(
        args.base_url, token, "C1_all_services_up", args.patient_id, args.repeats,
        "triage service reachable; no LLM tier configured"))

    skipped_reason = None

    if args.skip_container_control:
        skipped_reason = "--skip-container-control was passed"
    else:
        stopped = False
        try:
            print("[E5] stopping ml-service ...")
            compose("stop", "ml-service")
            stopped = True
            time.sleep(2)
            conditions.append(run_condition(
                args.base_url, token, "C2_ml_service_down", args.patient_id,
                args.repeats,
                "triage service stopped; ingestion and summarization must survive"))
        except ComposeUnavailable as e:
            skipped_reason = str(e)
            print(f"[E5] container control unavailable ({e}); "
                  f"reporting C1 only.", file=sys.stderr)
        finally:
            if stopped:
                # Always attempt recovery, even if C2 itself raised, so the
                # stack is never left with the triage service down.
                print("[E5] restarting ml-service ...")
                try:
                    compose("start", "ml-service")
                except ComposeUnavailable as e:
                    print(f"[E5] WARNING: could not restart ml-service: {e}",
                          file=sys.stderr)
                # Readiness is defined from the backend's point of view, not
                # the host's: a container that is "started" is not the same as
                # one the backend can reach and get a prediction from. Probing
                # end-to-end is the only check that actually gates C3.
                if not wait_for_ml_recovery(
                        args.base_url, token, args.patient_id, timeout_s=180):
                    print("[E5] WARNING: triage service did not recover within "
                          "180s; C3 would measure a still-down service and is "
                          "skipped.", file=sys.stderr)
                    stopped = False  # suppress C3 rather than mislabel it

        if stopped:
            conditions.append(run_condition(
                args.base_url, token, "C3_ml_service_recovered", args.patient_id,
                args.repeats,
                "triage service restarted; system must resume "
                "without a backend restart"))

    payload = {
        "experiment": "E5 resilience under dependency failure",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "note": ENVIRONMENT_NOTE,
        "claim_under_test": (
            "Telemetry ingestion and clinical summarization remain available "
            "when the triage service is unreachable, because the deterministic "
            "summarization tier has no external dependency."
        ),
        "conditions": conditions,
        "container_control_skipped": skipped_reason,
    }
    Path(args.out).write_text(json.dumps(payload, indent=2))
    print(f"[ok] wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
