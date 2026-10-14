from __future__ import annotations

from typing import Any

from ..bus import Event, EventBus
from ..config import AUTO_LIMIT


class ProcurementAgent:
    def __init__(self, adapter: Any, bus: EventBus | None = None) -> None:
        self.adapter = adapter
        self.bus = bus
        self.auto_limit = AUTO_LIMIT

    def decide(self, ranking_results: list[dict[str, Any]], order_value: float, run_id: str) -> dict[str, Any]:
        confidence = min((float(item.get("confidence", 0.0)) for item in ranking_results), default=0.0)
        requires_human_review = any(
            not item.get("top_pick")
            or float(item.get("confidence", 0.0)) <= 0.0
            or item.get("requires_human_review", False)
            for item in ranking_results
        )
        if confidence >= 0.80 and order_value <= self.auto_limit and not requires_human_review:
            decision = {
                "status": "auto_approved",
                "needs_approval": False,
                "decision": "auto_approve",
                "order_value": order_value,
                "confidence": confidence,
            }
            if self.bus:
                self.bus.emit(Event(
                    run_id=run_id,
                    sender="ProcurementAgent",
                    receiver="ManufacturingStep",
                    type="decision",
                    payload={"decision": decision},
                    human_text="Procurement auto-approved the order; manufacturing can continue.",
                    severity="info",
                ))
            return decision

        decision = {
            "status": "pending_human_review",
            "needs_approval": True,
            "decision": "pending_human_review",
            "order_value": order_value,
            "confidence": confidence,
        }
        if self.bus:
            self.bus.emit(Event(
                run_id=run_id,
                sender="ProcurementAgent",
                receiver="HumanApproval",
                type="human_action",
                payload={"decision": decision},
                human_text="Human approval is required before the procurement can proceed.",
                severity="warning",
            ))
        return decision
