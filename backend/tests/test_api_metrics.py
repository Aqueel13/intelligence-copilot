import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client(db_engine, client_as) -> TestClient:
    return client_as("guest")


def test_catalogue_lists_metrics_with_their_dimensions(client) -> None:
    body = client.get("/api/metrics").json()
    metrics = {m["name"]: m for m in body}
    assert "sla_breach_rate" in metrics
    event_dims = {d["name"] for d in metrics["avg_wait_hours"]["dimensions"]}
    case_dims = {d["name"] for d in metrics["sla_breach_rate"]["dimensions"]}
    assert "activity" in event_dims
    assert "activity" not in case_dims


def test_query_returns_rows_and_the_sql_used(client) -> None:
    response = client.post(
        "/api/metrics/query", json={"metric": "sla_breach_rate", "group_by": ["channel"]}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert {r["group"]["channel"] for r in body["rows"]} == {"direct", "broker", "agent"}
    assert body["sql"].startswith("SELECT")
    assert body["unit"] == "ratio"


def test_invalid_query_is_422_with_guidance(client) -> None:
    response = client.post("/api/metrics/query", json={"metric": "nope"})
    assert response.status_code == 422
    assert "Allowed:" in response.json()["detail"]
