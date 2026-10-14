from __future__ import annotations

import asyncio
import hashlib
import json
import os
import time
from collections import OrderedDict, deque
from typing import Any

try:
    from litellm import completion
except Exception:  # pragma: no cover
    completion = None

from .config import FALLBACK_MODEL, NARRATOR_MODEL, PRIMARY_MODEL


class AsyncTokenBucket:
    def __init__(self, rpm: int = 30, tpm: int = 8000, tpd: int = 200000) -> None:
        self.rpm = rpm
        self.tpm = tpm
        self.tpd = tpd
        self._minute: deque[tuple[float, int]] = deque()
        self._day: deque[tuple[float, int]] = deque()
        self._lock = asyncio.Lock()

    @staticmethod
    def _prune(entries: deque[tuple[float, int]], cutoff: float) -> None:
        while entries and entries[0][0] <= cutoff:
            entries.popleft()

    async def try_acquire(self, tokens: int) -> bool:
        now = time.monotonic()
        async with self._lock:
            self._prune(self._minute, now - 60)
            self._prune(self._day, now - 86400)
            minute_requests = len(self._minute)
            minute_tokens = sum(item[1] for item in self._minute)
            day_tokens = sum(item[1] for item in self._day)
            if (
                minute_requests >= self.rpm
                or minute_tokens + tokens > self.tpm
                or day_tokens + tokens > self.tpd
            ):
                return False
            entry = (now, tokens)
            self._minute.append(entry)
            self._day.append(entry)
            return True


class LLMWrapper:
    def __init__(
        self,
        primary_model: str | None = None,
        fallback_model: str | None = None,
        narrator_model: str | None = None,
        limiter: AsyncTokenBucket | None = None,
        cache_size: int = 256,
        cache_ttl: float = 300,
        bus: Any | None = None,
    ) -> None:
        self.primary_model = primary_model or PRIMARY_MODEL
        self.fallback_model = fallback_model or FALLBACK_MODEL
        self.narrator_model = narrator_model or NARRATOR_MODEL
        self.limiter = limiter or AsyncTokenBucket(
            rpm=int(os.getenv("LLM_RPM", "30")),
            tpm=int(os.getenv("LLM_TPM", "8000")),
            tpd=int(os.getenv("LLM_TPD", "200000")),
        )
        self.cache_size = cache_size
        self.cache_ttl = cache_ttl
        self._cache: OrderedDict[str, tuple[float, str]] = OrderedDict()
        self.bus = bus

    def _report_rate_limit(self, model: str, exc: Exception) -> None:
        message = str(exc).lower()
        if not any(marker in message for marker in ("429", "rate limit", "rate-limit", "too many requests")):
            return
        from .bus import DEFAULT_BUS, Event

        (self.bus or DEFAULT_BUS).emit(Event(
            run_id=None,
            sender="LLMWrapper",
            receiver="MonitorAgent",
            type="alert",
            payload={"model": model, "error": str(exc), "category": "rate_limit"},
            human_text="The language model provider is rate-limiting requests; deterministic fallback is active.",
            severity="alert",
        ))

    def _fallback_text(self, prompt: str, system: str | None = None) -> str:
        if "ranking" in prompt.lower() or "supplier" in prompt.lower():
            return "Supplier ranking completed from scored inputs; top pick selected using weighted criteria and cold-start checks."
        if "narrat" in prompt.lower() or "event" in prompt.lower():
            return "Workflow update: the pipeline advanced with the latest decision and preserved a full audit trail."
        return "Model unavailable; using template fallback for the request."

    @staticmethod
    def _cache_key(model: str, messages: list[dict[str, str]]) -> str:
        encoded = json.dumps({"model": model, "messages": messages}, sort_keys=True)
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def _cache_get(self, key: str) -> str | None:
        cached = self._cache.get(key)
        if cached is None:
            return None
        created, value = cached
        if time.monotonic() - created >= self.cache_ttl:
            del self._cache[key]
            return None
        self._cache.move_to_end(key)
        return value

    def _cache_put(self, key: str, value: str) -> None:
        self._cache[key] = (time.monotonic(), value)
        self._cache.move_to_end(key)
        while len(self._cache) > self.cache_size:
            self._cache.popitem(last=False)

    async def acall(
        self,
        prompt: str,
        *,
        system: str | None = None,
        model: str | None = None,
        temperature: float = 0.2,
        template: str | None = None,
    ) -> str:
        target_model = model or self.primary_model
        messages = [
            {"role": "system", "content": system or "You are a helpful logistics agent."},
            {"role": "user", "content": prompt},
        ]
        key = self._cache_key(target_model, messages)
        cached = self._cache_get(key)
        if cached is not None:
            return cached
        estimate = max(1, sum(len(message["content"]) for message in messages) // 4)
        if completion is None or not await self.limiter.try_acquire(estimate):
            return template or self._fallback_text(prompt, system)

        response_text = await self._complete_with_retry(target_model, messages, temperature)
        if not response_text and self.fallback_model and self.fallback_model != target_model:
            if await self.limiter.try_acquire(estimate):
                response_text = await self._complete_with_retry(self.fallback_model, messages, temperature)
        result = response_text or template or self._fallback_text(prompt, system)
        if response_text:
            self._cache_put(key, response_text)
        return result

    async def _complete_with_retry(
        self,
        model: str,
        messages: list[dict[str, str]],
        temperature: float,
    ) -> str | None:
        for attempt in range(2):
            try:
                response = await asyncio.wait_for(
                    asyncio.to_thread(
                        completion,
                        model=model,
                        messages=messages,
                        temperature=temperature,
                        timeout=30,
                    ),
                    timeout=30,
                )
                choice = response.choices[0].message.content if getattr(response, "choices", None) else ""
                if isinstance(choice, str) and choice.strip():
                    return choice.strip()
                return None
            except Exception as exc:
                self._report_rate_limit(model, exc)
                if attempt == 0:
                    continue
        return None

    def call(
        self,
        prompt: str,
        *,
        system: str | None = None,
        model: str | None = None,
        temperature: float = 0.2,
        template: str | None = None,
    ) -> str:
        return asyncio.run(
            self.acall(
                prompt,
                system=system,
                model=model,
                temperature=temperature,
                template=template,
            )
        )

    def explain_ranking(self, ranking: dict[str, Any]) -> str:
        top = ranking["top_pick"]
        confidence = ranking.get("confidence", 0)
        return f"Supplier {top} ranked highest with an overall confidence of {confidence:.2f}. The ranking is based on price, lead time, reliability, quality, and MOQ fit, with cold-start logic applied as needed."


DEFAULT_LLM = LLMWrapper()
