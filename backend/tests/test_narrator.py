from __future__ import annotations

import asyncio

import pytest

from app.agents.narrator import Narrator
from app.bus import Event, EventBus


class FakeLLM:
    narrator_model = "test-model"

    def __init__(self) -> None:
        self.calls = 0

    def call(self, prompt: str, **kwargs: object) -> str:
        self.calls += 1
        return "The scored decision requires review."


@pytest.mark.asyncio
async def test_event_uses_template_immediately_and_upgrades_alert_in_background() -> None:
    llm = FakeLLM()
    bus = EventBus(narrator=Narrator(llm))
    event = Event(
        run_id=None,
        sender="MonitorAgent",
        receiver="Admin",
        type="alert",
        payload={"threshold": 90},
        severity="error",
    )

    bus.emit(event)
    assert event.human_text == "An operational alert was raised for the active run."

    await asyncio.sleep(0.05)
    assert event.human_text == "The scored decision requires review."
    assert llm.calls == 1


def test_info_event_does_not_call_llm() -> None:
    llm = FakeLLM()
    bus = EventBus(narrator=Narrator(llm))
    event = Event(
        run_id=None,
        sender="InventoryAgent",
        type="response",
        payload={"product_name": "Widget Pro"},
    )

    bus.emit(event)

    assert event.human_text == "Inventory is available for Widget Pro; production can proceed."
    assert llm.calls == 0
