from __future__ import annotations

import pytest

from fastapi.testclient import TestClient

from app.main import app
from app.seed import seed_database
from app.forecast import forecast_demand
from app.agents.chat import OrchestratorChat


def setup_function() -> None:
    seed_database()


def test_chat_plan_returns_shortfall_and_requires_confirmation() -> None:
    client = TestClient(app)
    response = client.post("/api/chat", json={"message": "Demand for Product X will jump 40% next month"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["requires_confirmation"] is True
    assert "plan_id" in payload
    assert payload["message"]
    assert "shortfall_table" in payload
    assert "proposed_plan" in payload
    assert payload["recommended_quantity"] > 0
    assert "shortfall" in payload
    assert payload["summary"]


def test_forecast_uses_seeded_order_history() -> None:
    result = forecast_demand("Widget Pro", 60)

    assert result["history_points"] >= 12
    assert len(result["forecast"]) == 2
    assert result["baseline"] > 0
    assert len(result["confidence_interval"]["lower"]) == 2


def test_chat_confirmation_starts_a_run(monkeypatch) -> None:
    monkeypatch.setenv("ALLOW_INSECURE_DEV", "true")
    client = TestClient(app)
    response = client.post("/api/chat", json={"message": "Demand for Product X will jump 40% next month"})
    payload = response.json()

    confirm = client.post(
        "/api/chat/confirm",
        json={
            "plan_id": payload["plan_id"],
            "product_name": payload["product_name"],
            "quantity": payload["recommended_quantity"],
            "due_date": "2035-02-15",
            "urgency": "high",
        },
    )

    assert confirm.status_code == 200
    body = confirm.json()
    assert body["status"] == "confirmed"
    assert body["run"]["run_id"]
    assert body["run"]["status"] in {"completed", "manufacturing", "pending_human_review"}


def test_chat_start_requires_confirmed_plan() -> None:
    agent = OrchestratorChat()

    with pytest.raises(ValueError, match="valid confirmed plan_id"):
        agent.start_production("Widget Pro", 1)
