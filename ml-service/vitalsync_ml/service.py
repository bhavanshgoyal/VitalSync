"""FastAPI inference service.

Stateless: the model artifact is loaded once at startup and never mutated. The
service returns the learned band *and* the deterministic NEWS2 score for the
same observation, so the caller always has an auditable number next to the
opaque one.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Dict, List, Optional

import joblib
import pandas as pd
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from . import DISCLAIMER, MODEL_VERSION, __version__
from .features import TRIAGE_FEATURES, derive_row, to_model_matrix
from .news2 import BANDS, news2
from .validation import validate

ARTIFACTS = Path(os.environ.get("VITALSYNC_ARTIFACTS", Path(__file__).resolve().parent.parent / "artifacts"))

_state: Dict[str, object] = {"model": None, "card": None, "metrics": None}


@asynccontextmanager
async def lifespan(_: FastAPI):
    _load()
    yield


app = FastAPI(
    title="VitalSync ML Service",
    version=__version__,
    lifespan=lifespan,
    description=(
        "Risk triage for simulated IoMT vital-sign telemetry. "
        "Research prototype: not a medical device."
    ),
)


class Observation(BaseModel):
    """A single vital-sign observation.

    Glucose is optional: it is not a NEWS2 parameter and is absent from several
    public cohorts. Context flags default to the benign case, matching a
    wearable-only feed where nobody has recorded oxygen therapy or AVPU.
    """

    heart_rate: float = Field(..., description="beats per minute")
    spo2: float = Field(..., description="peripheral oxygen saturation, %")
    temperature_c: float = Field(..., description="body temperature, Celsius")
    respiratory_rate: float = Field(..., description="breaths per minute")
    systolic_bp: float = Field(..., description="systolic blood pressure, mmHg")
    diastolic_bp: float = Field(..., description="diastolic blood pressure, mmHg")
    glucose_mgdl: Optional[float] = Field(None, description="optional, mg/dL")
    on_oxygen: bool = Field(False, description="receiving supplemental oxygen")
    alert: bool = Field(True, description="Alert on AVPU; False means CVPU")
    patient_id: Optional[str] = None


class BatchRequest(BaseModel):
    observations: List[Observation]


def _load() -> None:
    model_path = ARTIFACTS / "risk_model.joblib"
    if model_path.exists():
        _state["model"] = joblib.load(model_path)
    for name in ("model_card", "metrics"):
        p = ARTIFACTS / f"{name}.json"
        if p.exists():
            _state[name.replace("model_card", "card")] = json.loads(p.read_text())


def _predict_frame(frame: pd.DataFrame) -> List[Dict]:
    model = _state["model"]
    if model is None:
        raise HTTPException(
            status_code=503,
            detail="Model artifact not loaded. Run vitalsync_ml.train first.",
        )
    X = to_model_matrix(frame)
    proba = model.predict_proba(X)
    classes = list(model.classes_)
    out = []
    for i in range(len(frame)):
        probs = {cls: float(proba[i][j]) for j, cls in enumerate(classes)}
        # Fill any band the estimator never saw, so the contract is stable.
        for band in BANDS:
            probs.setdefault(band, 0.0)
        top = max(probs, key=probs.get)
        out.append({"risk": top, "probabilities": probs, "confidence": probs[top]})
    return out


def _assess(obs: Observation) -> Dict:
    payload = obs.model_dump()
    problems = validate(payload)
    if problems:
        raise HTTPException(status_code=422, detail={"validation_errors": problems})

    frame = pd.DataFrame([payload])
    result = _predict_frame(frame)[0]

    score = news2(
        heart_rate=obs.heart_rate,
        spo2=obs.spo2,
        temperature_c=obs.temperature_c,
        respiratory_rate=obs.respiratory_rate,
        systolic_bp=obs.systolic_bp,
        on_oxygen=obs.on_oxygen,
        alert=obs.alert,
    )
    derived = derive_row(payload)

    return {
        **result,
        "news2": score.to_dict(),
        "derived": {k: round(v, 4) for k, v in derived.items()},
        "model_version": MODEL_VERSION,
        "patient_id": obs.patient_id,
        "disclaimer": DISCLAIMER,
    }


@app.get("/health")
def health() -> Dict:
    return {
        "status": "ok",
        "model_loaded": _state["model"] is not None,
        "model_version": MODEL_VERSION,
        "service_version": __version__,
    }


@app.get("/model")
def model_card() -> Dict:
    if _state["card"] is None:
        raise HTTPException(status_code=503, detail="Model card not available.")
    card = dict(_state["card"])
    metrics = _state.get("metrics")
    if isinstance(metrics, dict):
        card["headline_metrics"] = metrics.get("headline")
        card["selection_metric"] = metrics.get("selection_metric")
    card["features"] = TRIAGE_FEATURES
    card["classes"] = list(BANDS)
    card["disclaimer"] = DISCLAIMER
    return card


@app.post("/predict")
def predict(obs: Observation) -> Dict:
    t0 = time.perf_counter()
    result = _assess(obs)
    result["inference_ms"] = round((time.perf_counter() - t0) * 1000.0, 3)
    return result


@app.post("/predict/batch")
def predict_batch(req: BatchRequest) -> Dict:
    if not req.observations:
        raise HTTPException(status_code=422, detail="observations must be non-empty")
    t0 = time.perf_counter()
    results = [_assess(o) for o in req.observations]
    total = (time.perf_counter() - t0) * 1000.0
    return {
        "count": len(results),
        "total_ms": round(total, 3),
        "mean_ms": round(total / len(results), 4),
        "results": results,
    }


@app.exception_handler(HTTPException)
def http_exception_handler(_, exc: HTTPException) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": exc.detail, "disclaimer": DISCLAIMER},
    )
