from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from app.seed import seed_database


def setup_function() -> None:
    seed_database()


def test_websocket_events_stream_and_event_log_is_persisted(monkeypatch) -> None:
    monkeypatch.setenv("ALLOW_INSECURE_DEV", "true")
    client = TestClient(app)
    with client.websocket_connect("/ws/events") as websocket:
        response = client.post(
            "/api/runs",
            headers={"X-Admin-Key": "test-admin-key"},
            json={"product_name": "Widget Pro", "quantity": 5, "due_date": "2035-01-20", "urgency": "normal"},
        )
        payload = response.json()
        assert payload["status"] == "completed"
        message = websocket.receive_json()
        assert message["run_id"] == payload["run_id"]

        events = client.get(f"/api/events?run_id={payload['run_id']}")
        assert events.status_code == 200
        assert len(events.json()) >= 1


def test_approval_queue_and_human_action_are_visible(monkeypatch) -> None:
    monkeypatch.setenv("ALLOW_INSECURE_DEV", "true")
    client = TestClient(app)
    response = client.post(
        "/api/runs",
        headers={"X-Admin-Key": "test-admin-key"},
        json={"product_name": "Sensor Module B3", "quantity": 50, "due_date": "2035-01-10", "urgency": "high"},
    )
    data = response.json()
    assert data["status"] == "pending_human_review"

    queue = client.get("/api/approvals")
    assert queue.status_code == 200
    assert any(item["run_id"] == data["run_id"] for item in queue.json())

    approved = client.post(
        f"/api/runs/{data['run_id']}/approve",
        headers={"X-Admin-Key": "test-admin-key"},
        json={"approved": True},
    )
    assert approved.json()["status"] == "completed"

    events = client.get(f"/api/events?run_id={data['run_id']}")
    assert any(item["type"] == "human_action" for item in events.json())
