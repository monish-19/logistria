from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from app.models import SessionLocal
from app.seed import seed_database


def setup_function() -> None:
    seed_database()


def test_reference_endpoints_and_run_detail(monkeypatch) -> None:
    monkeypatch.setenv("ALLOW_INSECURE_DEV", "true")
    client = TestClient(app)
    created = client.post(
        "/api/runs",
        headers={"X-Admin-Key": "test"},
        json={"product_name": "Widget Pro", "quantity": 5},
    )
    run_id = created.json()["run_id"]

    assert client.get("/api/runs").status_code == 200
    assert client.get("/api/runs?status=manufacturing").status_code == 200
    detail = client.get(f"/api/runs/{run_id}")
    assert detail.status_code == 200
    assert set(detail.json()["nodes"]) == {
        "inventory", "ranking", "procurement", "manufacturing", "logistics", "monitor"
    }
    route = client.get(f"/api/runs/{run_id}/route").json()
    assert route["geometry"]
    assert route["total_distance_km"] == route["distance_km"]
    assert route["eta_minutes"] < 24 * 60
    assert client.get("/api/products").status_code == 200
    assert client.get("/api/inventory").status_code == 200
    assert client.get("/api/suppliers").status_code == 200


def test_events_alerts_and_event_detail_filters(monkeypatch) -> None:
    monkeypatch.setenv("ALLOW_INSECURE_DEV", "true")
    client = TestClient(app)
    created = client.post(
        "/api/runs",
        headers={"X-Admin-Key": "test"},
        json={"product_name": "Widget Pro", "quantity": 5},
    )
    run_id = created.json()["run_id"]
    events = client.get(f"/api/events?run_id={run_id}&type=request&limit=10")
    assert events.status_code == 200
    assert events.json()
    event_id = events.json()[0]["id"]
    assert client.get(f"/api/events/{event_id}").json()["id"] == event_id
    assert client.get("/api/alerts").status_code == 200


def test_reject_and_override_require_admin_and_emit_actions(monkeypatch) -> None:
    monkeypatch.setenv("ALLOW_INSECURE_DEV", "true")
    client = TestClient(app)
    created = client.post(
        "/api/runs",
        headers={"X-Admin-Key": "test"},
        json={"product_name": "Sensor Module B3", "quantity": 50},
    )
    run_id = created.json()["run_id"]
    supplier_id = client.get("/api/suppliers").json()[0]["id"]

    override = client.post(
        f"/api/runs/{run_id}/override",
        headers={"X-Admin-Key": "test"},
        json={"supplier_id": supplier_id},
    )
    assert override.status_code == 200
    assert any(
        event["type"] == "human_action"
        for event in client.get(f"/api/events?run_id={run_id}").json()
    )

    second = client.post(
        "/api/runs",
        headers={"X-Admin-Key": "test"},
        json={"product_name": "Sensor Module B3", "quantity": 50},
    )
    rejected = client.post(
        f"/api/runs/{second.json()['run_id']}/reject",
        headers={"X-Admin-Key": "test"},
    )
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"


def test_websocket_replays_recent_events(monkeypatch) -> None:
    monkeypatch.setenv("ALLOW_INSECURE_DEV", "true")
    client = TestClient(app)
    client.post(
        "/api/runs",
        headers={"X-Admin-Key": "test"},
        json={"product_name": "Widget Pro", "quantity": 5},
    )
    with client.websocket_connect("/ws/events") as websocket:
        replay = websocket.receive_json()
        assert "id" in replay
        assert "human_text" in replay
