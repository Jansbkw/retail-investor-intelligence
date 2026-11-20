from fastapi.testclient import TestClient

from app.api.main import app


def test_health() -> None:
    response = TestClient(app).get("/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["database"] == "ready"
    assert isinstance(payload["posts"], int)


def test_unknown_company_is_controlled() -> None:
    response = TestClient(app).get("/analytics/overview", params={"company_id": "NOPE"})
    assert response.status_code == 404
