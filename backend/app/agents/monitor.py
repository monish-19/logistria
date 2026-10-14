from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ..bus import Event, EventBus


class MonitorAgent:
    def __init__(self, bus: EventBus | None = None) -> None:
        self.bus = bus

    def check_run(self, run_id: str, status: str, *, last_event_ts: datetime | None = None, route: dict[str, Any] | None = None, purchase_orders: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
        alerts: list[dict[str, Any]] = []
        now = datetime.now(timezone.utc)

        if last_event_ts is not None and (now - last_event_ts).total_seconds() > 120:
            alerts.append({"type": "stalled", "message": "Run appears stalled; no progress detected recently."})
        if route and route.get("eta_minutes", 0) > 90:
            alerts.append({"type": "late_delivery", "message": "Route ETA exceeds the planned threshold."})
        if purchase_orders:
            late_po = [po for po in purchase_orders if po.get("status") == "late"]
            if late_po:
                alerts.append({"type": "late_purchase_order", "message": "At least one purchase order is late."})

        if alerts and self.bus is not None:
            for alert in alerts:
                self.bus.emit(Event(
                    run_id=run_id,
                    sender="MonitorAgent",
                    receiver="Admin",
                    type="alert",
                    payload={"status": status, "alert": alert},
                    human_text=f"Alert: {alert['message']}",
                    severity="error",
                ))
        return alerts

    def raise_alerts_for_run(self, run_id: str, status: str, **kwargs: Any) -> list[dict[str, Any]]:
        return self.check_run(run_id, status, **kwargs)
