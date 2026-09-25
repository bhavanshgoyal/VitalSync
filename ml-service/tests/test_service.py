"""HTTP contract tests for the inference service."""

import pytest
from fastapi.testclient import TestClient

from vitalsync_ml.news2 import BANDS
from vitalsync_ml.service import ARTIFACTS, app

STABLE = {
    "heart_rate": 72, "spo2": 98, "temperature_c": 36.7,
    "respiratory_rate": 16, "systolic_bp": 122, "diastolic_bp": 78,
}
CRITICAL = {
    "heart_rate": 132, "spo2": 88, "temperature_c": 39.3,
    "respiratory_rate": 29, "systolic_bp": 84, "diastolic_bp": 52,
}

needs_model = pytest.mark.skipif(
    not (ARTIFACTS / "risk_model.joblib").exists(),
    reason="model artifact absent; run vitalsync_ml.train first",
)


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def test_health_is_unauthenticated_and_reports_model_state(client):
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert "model_loaded" in body


@needs_model
def test_predict_returns_the_full_contract(client):
    body = client.post("/predict", json=STABLE).json()
    for key in ("risk", "probabilities", "confidence", "news2",
                "derived", "model_version", "disclaimer"):
        assert key in body, f"missing contract key {key}"
    assert body["risk"] in BANDS
    assert set(body["probabilities"]) == set(BANDS)
    assert body["probabilities"][body["risk"]] == pytest.approx(body["confidence"])


@needs_model
def test_probabilities_sum_to_one(client):
    body = client.post("/predict", json=STABLE).json()
    assert sum(body["probabilities"].values()) == pytest.approx(1.0, abs=1e-6)


@needs_model
def test_deterministic_news2_accompanies_every_prediction(client):
    """The auditable number must ride along with the opaque one."""
    stable = client.post("/predict", json=STABLE).json()
    critical = client.post("/predict", json=CRITICAL).json()
    assert stable["news2"]["total"] == 0
    assert stable["news2"]["band"] == "LOW"
    assert critical["news2"]["total"] >= 7
    assert critical["news2"]["band"] == "HIGH"


@needs_model
def test_derived_features_are_returned(client):
    body = client.post("/predict", json=STABLE).json()
    assert body["derived"]["shock_index"] == pytest.approx(72 / 122, abs=1e-3)
    assert body["derived"]["pulse_pressure"] == pytest.approx(44)


@needs_model
def test_glucose_is_optional(client):
    assert client.post("/predict", json=STABLE).status_code == 200
    with_glucose = dict(STABLE, glucose_mgdl=112.0)
    assert client.post("/predict", json=with_glucose).status_code == 200


@needs_model
def test_context_flags_change_the_news2_score(client):
    on_oxygen = client.post("/predict", json=dict(STABLE, on_oxygen=True)).json()
    assert on_oxygen["news2"]["total"] == 2
    not_alert = client.post("/predict", json=dict(STABLE, alert=False)).json()
    assert not_alert["news2"]["total"] == 3
    assert not_alert["news2"]["band"] == "MEDIUM"


def test_physiologically_impossible_input_is_rejected(client):
    r = client.post("/predict", json=dict(STABLE, heart_rate=900))
    assert r.status_code == 422
    assert "validation_errors" in r.json()["error"]


def test_diastolic_above_systolic_is_rejected(client):
    r = client.post("/predict", json=dict(STABLE, systolic_bp=100, diastolic_bp=110))
    assert r.status_code == 422


def test_missing_required_field_is_rejected(client):
    incomplete = {k: v for k, v in STABLE.items() if k != "heart_rate"}
    assert client.post("/predict", json=incomplete).status_code == 422


@needs_model
def test_batch_endpoint(client):
    r = client.post(
        "/predict/batch", json={"observations": [STABLE, CRITICAL]}
    ).json()
    assert r["count"] == 2
    assert r["results"][0]["risk"] in BANDS
    assert r["results"][1]["news2"]["band"] == "HIGH"


def test_empty_batch_is_rejected(client):
    assert client.post("/predict/batch", json={"observations": []}).status_code == 422


@needs_model
def test_model_card_exposes_provenance(client):
    card = client.get("/model").json()
    assert card["classes"] == list(BANDS)
    assert "artifact_sha256" in card
    assert "out_of_scope" in card


@needs_model
def test_every_response_carries_the_disclaimer(client):
    body = client.post("/predict", json=STABLE).json()
    assert "not a medical device" in body["disclaimer"].lower()
