"""Shared helpers for the experiment scripts."""

from __future__ import annotations

import json
import statistics
import urllib.error
import urllib.request
from typing import Dict, List, Optional

DEFAULT_BASE_URL = "http://localhost:8080"


def request_json(
    url: str,
    body: Optional[Dict] = None,
    token: Optional[str] = None,
    method: str = "GET",
    timeout: float = 30.0,
):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8")
        return resp.status, (json.loads(raw) if raw else {})


def authenticate(
    base_url: str = DEFAULT_BASE_URL,
    username: str = "clinician",
    password: str = "vitalsync-demo",
) -> str:
    status, body = request_json(
        f"{base_url}/api/v1/auth/token",
        {"username": username, "password": password},
        method="POST",
    )
    if status != 200:
        raise SystemExit(f"authentication failed: {status} {body}")
    return body["token"]


def percentile(values: List[float], pct: float) -> float:
    """Nearest-rank percentile; stable for the small samples used here."""
    if not values:
        return float("nan")
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int(round(pct / 100.0 * len(ordered))) - 1))
    return ordered[index]


def summarise(values: List[float]) -> Dict[str, float]:
    if not values:
        return {"n": 0}
    return {
        "n": len(values),
        "mean": statistics.fmean(values),
        "p50": percentile(values, 50),
        "p95": percentile(values, 95),
        "p99": percentile(values, 99),
        "max": max(values),
        "min": min(values),
    }


ENVIRONMENT_NOTE = (
    "Measured on a single developer workstation with all services in local "
    "Docker containers. Numbers characterise this configuration only and are "
    "not production service-level objectives."
)
