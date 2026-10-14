from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .agents.narrator import DEFAULT_NARRATOR, Narrator
from .models import EventLog, SessionLocal, ProductionRun


@dataclass
class Event:
    run_id: str | None
    sender: str
    receiver: str = "system"
    type: str = "info"
    payload: dict[str, Any] | None = None
    human_text: str | None = None
    severity: str = "info"
    ts: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class WebSocketManager:
    def __init__(self) -> None:
        self.connections: set[Any] = set()

    async def connect(self, websocket: Any) -> None:
        await websocket.accept()
        self.connections.add(websocket)

    async def disconnect(self, websocket: Any) -> None:
        self.connections.discard(websocket)

    async def broadcast(self, event: Event) -> None:
        await self._broadcast_payload({
            "run_id": event.run_id,
            "sender": event.sender,
            "receiver": event.receiver,
            "type": event.type,
            "payload": event.payload or {},
            "human_text": event.human_text,
            "severity": event.severity,
            "ts": event.ts.isoformat(),
        })

    async def broadcast_updated(self, event: Event) -> None:
        await self._broadcast_payload({
            "type": "event_updated",
            "event": {
                "run_id": event.run_id,
                "sender": event.sender,
                "receiver": event.receiver,
                "original_type": event.type,
                "payload": event.payload or {},
                "human_text": event.human_text,
                "severity": event.severity,
                "ts": event.ts.isoformat(),
            },
        })

    async def _broadcast_payload(self, payload: dict[str, Any]) -> None:
        stale: list[Any] = []
        for socket in list(self.connections):
            try:
                await socket.send_json(payload)
            except Exception:
                stale.append(socket)
        for socket in stale:
            self.connections.discard(socket)


class EventBus:
    def __init__(self, narrator: Narrator | None = None) -> None:
        self._events: list[Event] = []
        self.websocket_manager: WebSocketManager | None = None
        self.narrator = narrator or DEFAULT_NARRATOR

    def set_websocket_manager(self, manager: WebSocketManager | None) -> None:
        self.websocket_manager = manager

    def emit(self, event: Event) -> Event:
        if not event.human_text:
            event.human_text = self.narrator.template(event)
        self._events.append(event)
        self._persist(event)
        self._broadcast(event)
        self._schedule_upgrade(event)
        return event

    async def publish(self, event: Event) -> Event:
        return self.emit(event)

    def _broadcast(self, event: Event) -> None:
        if self.websocket_manager is None:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop and loop.is_running():
            loop.create_task(self.websocket_manager.broadcast(event))
        else:
            asyncio.run(self.websocket_manager.broadcast(event))

    def _schedule_upgrade(self, event: Event) -> None:
        if event.sender in {"LLMWrapper", "ERPNextAdapter"}:
            return
        if not self.narrator.should_use_llm(event):
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        loop.create_task(self._upgrade_event(event))

    async def _upgrade_event(self, event: Event) -> None:
        upgraded = await self.narrator.upgrade(event)
        if not upgraded or upgraded == event.human_text:
            return
        event.human_text = upgraded
        self._update_persisted(event)
        if self.websocket_manager is not None:
            await self.websocket_manager.broadcast_updated(event)

    def _persist(self, event: Event) -> None:
        with SessionLocal() as session:
            run = session.query(ProductionRun).filter(ProductionRun.run_id == event.run_id).first() if event.run_id else None
            row = EventLog(
                run_id=run.id if run else None,
                sender=event.sender,
                receiver=event.receiver,
                type=event.type,
                payload_json=json.dumps(event.payload or {}, default=str),
                human_text=event.human_text,
                severity=event.severity,
            )
            session.add(row)
            session.commit()
            event._event_log_id = row.id

    def _update_persisted(self, event: Event) -> None:
        if not getattr(event, "_event_log_id", None):
            return
        with SessionLocal() as session:
            row = session.get(EventLog, event._event_log_id)
            if row is not None:
                row.human_text = event.human_text
                session.commit()

    def list_events(self, run_id: str | None = None) -> list[Event]:
        if run_id is None:
            return list(self._events)
        return [item for item in self._events if item.run_id == run_id]

    def get_events_for_run(self, run_id: str) -> list[dict[str, Any]]:
        with SessionLocal() as session:
            run = session.query(ProductionRun).filter(ProductionRun.run_id == run_id).first()
            if run is None:
                return []
            rows = session.query(EventLog).filter(EventLog.run_id == run.id).all()
            return [
                {
                    "id": row.id,
                    "sender": row.sender,
                    "receiver": row.receiver,
                    "type": row.type,
                    "payload_json": json.loads(row.payload_json or "{}"),
                    "human_text": row.human_text,
                    "severity": row.severity,
                    "ts": row.ts.isoformat(),
                }
                for row in rows
            ]


DEFAULT_BUS = EventBus()
