from __future__ import annotations

import os

from fastapi.testclient import TestClient

from app.adapters import build_adapter
from app.bus import EventBus
from app.main import app
from app.seed import seed_database


def setup_function() -> None:
    seed_database()


def test_adapter_factory_uses_erpnext_fallback_without_remote_service(monkeypatch) -> None:
    monkeypatch.setenv("ADAPTER", "erpnext")
    adapter = build_adapter()
    assert adapter.__class__.__name__ == "ERPNextAdapter"
    assert adapter.get_bom("Widget Pro")[0]["material"] == "Steel"


def test_erpnext_outage_emits_alert_and_uses_mock_fallback() -> None:
    bus = EventBus()
    adapter = build_adapter("erpnext", base_url="http://127.0.0.1:1", timeout=0.01, bus=bus, fallback=True)

    assert adapter.get_stock("Steel") == 300
    alert = bus.list_events()[-1]
    assert alert.type == "alert"
    assert alert.receiver == "MonitorAgent"
    assert alert.payload["fallback"] is True


def test_admin_key_enforced_when_configured(monkeypatch) -> None:
    monkeypatch.setenv("ADMIN_API_KEY", "top-secret")
    client = TestClient(app)
    unauth = client.post("/api/runs", json={"product_name": "Widget Pro", "quantity": 1})
    assert unauth.status_code == 401

    authed = client.post(
        "/api/runs",
        headers={"X-Admin-Key": "top-secret"},
        json={"product_name": "Widget Pro", "quantity": 1},
    )
    assert authed.status_code == 200
    assert authed.json()["status"] in {"completed", "pending_human_review"}


def test_admin_key_missing_fails_closed(monkeypatch) -> None:
    monkeypatch.delenv("ADMIN_API_KEY", raising=False)
    monkeypatch.delenv("ALLOW_INSECURE_DEV", raising=False)
    client = TestClient(app)
    response = client.post("/api/runs", json={"product_name": "Widget Pro", "quantity": 1})
    assert response.status_code == 503
    assert response.json()["detail"] == "ADMIN_API_KEY not configured"


def test_authentication_runs_before_body_validation(monkeypatch) -> None:
    monkeypatch.setenv("ADMIN_API_KEY", "top-secret")
    client = TestClient(app)

    response = client.post("/api/runs", json={"quantity": "not-a-number"})

    assert response.status_code == 401
    assert response.json()["detail"] == "Admin authentication required"
