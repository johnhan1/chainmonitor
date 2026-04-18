from fastapi.testclient import TestClient
from src.app.main import app


def test_healthz() -> None:
    client = TestClient(app)
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_metrics() -> None:
    client = TestClient(app)
    response = client.get("/metrics")
    assert response.status_code == 200
    assert "cm_http_requests_total" in response.text
    assert "cm_bsc_pipeline_runs_total" in response.text

