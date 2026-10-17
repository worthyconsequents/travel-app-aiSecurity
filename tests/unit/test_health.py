from fastapi.testclient import TestClient

from services.health import app


def test_foundation_health():
    response = TestClient(app).get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
