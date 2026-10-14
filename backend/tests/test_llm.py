from __future__ import annotations

from types import SimpleNamespace

import pytest

import app.llm as llm_module
from app.llm import AsyncTokenBucket, LLMWrapper
from app.bus import EventBus


def response(text: str) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=text))]
    )


@pytest.mark.asyncio
async def test_rate_limit_skips_provider_and_returns_template(monkeypatch) -> None:
    calls = 0

    def fake_completion(**kwargs):
        nonlocal calls
        calls += 1
        return response("provider")

    monkeypatch.setattr(llm_module, "completion", fake_completion)
    wrapper = LLMWrapper(limiter=AsyncTokenBucket(rpm=0), cache_ttl=60)

    result = await wrapper.acall("short", template="deterministic fallback")

    assert result == "deterministic fallback"
    assert calls == 0


@pytest.mark.asyncio
async def test_cache_hit_avoids_second_provider_call(monkeypatch) -> None:
    calls = 0

    def fake_completion(**kwargs):
        nonlocal calls
        calls += 1
        return response("cached answer")

    monkeypatch.setattr(llm_module, "completion", fake_completion)
    wrapper = LLMWrapper(limiter=AsyncTokenBucket(), cache_ttl=60)

    assert await wrapper.acall("same prompt") == "cached answer"
    assert await wrapper.acall("same prompt") == "cached answer"
    assert calls == 1


@pytest.mark.asyncio
async def test_fallback_model_is_used_after_primary_failure(monkeypatch) -> None:
    models: list[str] = []

    def fake_completion(**kwargs):
        models.append(kwargs["model"])
        if kwargs["model"] == "primary":
            raise RuntimeError("429")
        return response("fallback answer")

    monkeypatch.setattr(llm_module, "completion", fake_completion)
    wrapper = LLMWrapper(
        primary_model="primary",
        fallback_model="fallback",
        limiter=AsyncTokenBucket(),
    )

    assert await wrapper.acall("retry me") == "fallback answer"
    assert models == ["primary", "primary", "fallback"]


@pytest.mark.asyncio
async def test_total_provider_failure_returns_template(monkeypatch) -> None:
    def fake_completion(**kwargs):
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(llm_module, "completion", fake_completion)
    wrapper = LLMWrapper(limiter=AsyncTokenBucket())

    assert await wrapper.acall("unavailable", template="safe template") == "safe template"


@pytest.mark.asyncio
async def test_rate_limit_failure_emits_monitor_alert(monkeypatch) -> None:
    def fake_completion(**kwargs):
        raise RuntimeError("429 rate limit exceeded")

    monkeypatch.setattr(llm_module, "completion", fake_completion)
    bus = EventBus()
    wrapper = LLMWrapper(limiter=AsyncTokenBucket(), bus=bus)

    assert await wrapper.acall("rate limited", template="safe template") == "safe template"
    alerts = [event for event in bus.list_events() if event.type == "alert"]
    assert alerts
    assert alerts[-1].receiver == "MonitorAgent"
