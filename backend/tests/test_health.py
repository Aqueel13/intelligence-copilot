"""Health endpoint tests. Require a migrated Postgres at DATABASE_URL."""

from fastapi.testclient import TestClient

from watchdog_backend.main import app

client = TestClient(app)


def test_health_reports_database_ready() -> None:
    response = client.get("/api/health")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "ok"
    assert body["database"]["ok"] is True
    assert body["database"]["pgvector_version"]
    assert body["database"]["missing_schemas"] == []


def test_openapi_served_under_api_prefix() -> None:
    assert client.get("/api/openapi.json").status_code == 200
