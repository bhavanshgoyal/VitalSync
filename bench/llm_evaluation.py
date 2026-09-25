"""E9: evaluate the live LLM summarization tiers.

This is the experiment that fills the reserved LLM section of the paper. It
does nothing useful until at least one LLM tier is enabled in .env, because
with both off every summary comes from the deterministic tier and there is no
model output to assess.

What it measures, per provider:

  * share of assessments each tier actually answered (cascade behaviour)
  * faithfulness pass rate -- did the tier invent numbers or name conditions
  * latency distribution
  * agreement between the tier's stated priority and the NEWS2 band

The faithfulness rate is the number that matters. Everything else in this
system is deterministic and auditable; the generated text is the one component
that can assert something the data does not support, and until a real model has
been run this figure is unmeasured.

Prerequisites::

    # in .env
    VITALSYNC_OLLAMA_ENABLED=true      # and: ollama pull llama3.1:8b
    #   and/or
    VITALSYNC_GEMINI_ENABLED=true
    GEMINI_API_KEY=...

    docker compose up -d --build
    python bench/llm_evaluation.py
"""

from __future__ import annotations

import argparse
import json
import random
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

DETERMINISTIC_TIER = "rule-based"


def make_case(rng: random.Random, patient_id: str, severity: float) -> dict:
    """One observation at a controlled severity, so all three bands are covered."""
    return {
        "patientId": patient_id,
        "heartRate": round(70 + 62 * severity + rng.gauss(0, 3)),
        "spo2": round(max(75.0, 98.2 - 11 * severity + rng.gauss(0, 1)), 1),
        "temperatureC": round(36.8 + 2.4 * severity + rng.gauss(0, 0.2), 1),
        "respiratoryRate": round(14 + 13 * severity + rng.gauss(0, 1)),
        "systolicBp": round(122 - 40 * severity + rng.gauss(0, 5)),
        "diastolicBp": round(78 - 20 * severity + rng.gauss(0, 4)),
        "onOxygen": severity > 0.6,
        "alert": severity < 0.85,
        "observedAt": datetime.now(timezone.utc).isoformat(),
    }


def submit_and_collect(base_url: str, token: str, body: dict, timeout_s: float = 60.0):
    patient_id = body["patientId"]
    _, before = request_json(
        f"{base_url}/api/v1/patients/{patient_id}/risk/latest", token=token)
    before_id = before.get("id") if isinstance(before, dict) else None

    t0 = time.perf_counter()
    status, _ = request_json(
        f"{base_url}/api/v1/telemetry", body, token, method="POST")
    if status != 202:
        return None

    deadline = time.perf_counter() + timeout_s
    while time.perf_counter() < deadline:
        _, latest = request_json(
            f"{base_url}/api/v1/patients/{patient_id}/risk/latest", token=token)
        if isinstance(latest, dict) and latest.get("id") and latest.get("id") != before_id:
            latest["_elapsed_ms"] = (time.perf_counter() - t0) * 1000.0
            return latest
        time.sleep(0.4)
    return None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Evaluate the live LLM tiers")
    ap.add_argument("--base-url", default=DEFAULT_BASE_URL)
    ap.add_argument("--patient-id", default="P004")
    ap.add_argument("--cases", type=int, default=30)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", default=str(ARTIFACTS / "llm_evaluation.json"))
    ap.add_argument("--allow-deterministic-only", action="store_true",
                    help="write a result even if no LLM tier answered")
    args = ap.parse_args(argv)

    rng = random.Random(args.seed)
    token = authenticate(args.base_url)

    _, providers = request_json(
        f"{args.base_url}/api/v1/system/providers", token=token)
    active = providers.get("active", [])
    llm_tiers = [p for p in active if p != DETERMINISTIC_TIER]

    print(f"[E9] active summarization tiers: {active}")
    if not llm_tiers:
        print(
            "\n  No LLM tier is enabled, so there is no model output to assess.\n"
            "  Enable one in .env and restart the stack:\n"
            "      VITALSYNC_OLLAMA_ENABLED=true   (ollama pull llama3.1:8b)\n"
            "      VITALSYNC_GEMINI_ENABLED=true   (set GEMINI_API_KEY)\n"
            "      docker compose up -d\n",
            file=sys.stderr)
        if not args.allow_deterministic_only:
            return 3

    # Spread severity evenly so LOW, MEDIUM and HIGH are all represented.
    severities = [i / max(args.cases - 1, 1) for i in range(args.cases)]
    records = []

    print(f"[E9] submitting {args.cases} cases across the severity range ...")
    for i, sev in enumerate(severities):
        result = submit_and_collect(
            args.base_url, token, make_case(rng, args.patient_id, sev))
        if result is None:
            print(f"     case {i + 1}: no assessment returned", file=sys.stderr)
            continue
        records.append({
            "severity": round(sev, 3),
            "provider": result.get("summaryProvider"),
            "faithful": result.get("summaryFaithful"),
            "risk_band": result.get("riskBand"),
            "news2_total": result.get("news2Total"),
            "news2_band": result.get("news2Band"),
            "summary_latency_ms": result.get("summaryLatencyMs"),
            "end_to_end_ms": result.get("_elapsed_ms"),
            "summary": result.get("summary"),
        })

    by_provider: dict = {}
    for r in records:
        p = r["provider"] or "none"
        entry = by_provider.setdefault(p, {
            "answered": 0, "faithful": 0, "unfaithful": 0,
            "latencies": [], "bands": {},
        })
        entry["answered"] += 1
        if r["faithful"] is True:
            entry["faithful"] += 1
        elif r["faithful"] is False:
            entry["unfaithful"] += 1
        if r["summary_latency_ms"] is not None:
            entry["latencies"].append(r["summary_latency_ms"])
        band = r["risk_band"] or "UNKNOWN"
        entry["bands"][band] = entry["bands"].get(band, 0) + 1

    summary_by_provider = {}
    for name, e in by_provider.items():
        summary_by_provider[name] = {
            "answered": e["answered"],
            "share_of_assessments": e["answered"] / len(records) if records else 0.0,
            "faithful": e["faithful"],
            "unfaithful": e["unfaithful"],
            "faithfulness_rate": (
                e["faithful"] / e["answered"] if e["answered"] else None),
            "summary_latency_ms": summarise(e["latencies"]),
            "bands_seen": e["bands"],
        }

    payload = {
        "experiment": "E9 live LLM summarization tiers",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "note": ENVIRONMENT_NOTE,
        "active_tiers": active,
        "llm_tiers_enabled": llm_tiers,
        "deterministic_only": not llm_tiers,
        "cases": len(records),
        "by_provider": summary_by_provider,
        "unfaithful_examples": [
            {k: r[k] for k in ("severity", "provider", "risk_band", "summary")}
            for r in records if r["faithful"] is False
        ][:10],
        "records": records,
        "interpretation": (
            "faithfulness_rate is the share of a tier's summaries that cited "
            "only supplied numbers and named no condition. A tier that produced "
            "an unfaithful summary was overridden at request time -- the "
            "cascade falls through -- so this measures how often that guard "
            "fired, not how often a bad summary reached a clinician."
        ),
        "caveat": (
            "Faithfulness checking is necessary, not sufficient. It cannot "
            "detect a fluent, numerically correct, clinically wrong reading of "
            "the data. No claim is made about clinical quality of the text."
        ),
    }

    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(payload, indent=2))

    print()
    print(f"  {'provider':<16} {'answered':>9} {'faithful':>9} {'rate':>8} {'p50 ms':>9}")
    for name, e in summary_by_provider.items():
        rate = e["faithfulness_rate"]
        p50 = e["summary_latency_ms"].get("p50")
        print(f"  {name:<16} {e['answered']:>9} {e['faithful']:>9} "
              f"{(f'{rate:.3f}' if rate is not None else '--'):>8} "
              f"{(f'{p50:.1f}' if p50 is not None else '--'):>9}")
    print()
    print(f"[ok] wrote {args.out}")
    print("     now run: python paper/make_tables.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
