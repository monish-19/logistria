from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from ..bus import Event, EventBus


class ManufacturingStep:
    def __init__(self, adapter: Any, bus: EventBus | None = None) -> None:
        self.adapter = adapter
        self.bus = bus

    def simulate(self, run_id: str, product_name: str, quantity: float) -> dict[str, Any]:
        progress_steps = [25, 50, 80, 100]
        for percent in progress_steps:
            payload = {"product_name": product_name, "quantity": quantity, "progress_pct": percent}
            event = Event(
                run_id=run_id,
                sender="ManufacturingStep",
                receiver="LogisticsAgent",
                type="decision",
                payload=payload,
                human_text=f"Manufacturing progress for {product_name}: {percent}% complete.",
                severity="info" if percent < 100 else "success",
            )
            if self.bus:
                self.bus.emit(event)
            if hasattr(self.adapter, "update_work_order"):
                self.adapter.update_work_order(run_id, "manufacturing", f"Progress {percent}%")

        result = {
            "run_id": run_id,
            "product_name": product_name,
            "quantity": quantity,
            "status": "completed",
            "progress_pct": 100,
            "line": "Line-3",
        }
        return result
