from __future__ import annotations

import json
import re
import uuid
from typing import Any

from ..adapters.mock import MockAdapter
from ..bus import DEFAULT_BUS, Event
from ..forecast import forecast_demand as run_forecast
from ..graph import build_phase1_graph
from ..models import Approval, EventLog, ProductionRun, Product, SessionLocal


class OrchestratorChat:
    def __init__(self, adapter: Any | None = None, graph: Any | None = None, bus: Any | None = None) -> None:
        self.adapter = adapter or MockAdapter()
        self.graph = graph or build_phase1_graph(adapter=self.adapter)
        self.bus = bus or DEFAULT_BUS
        self.active_plans: dict[str, dict[str, Any]] = {}

    def _resolve_product_name(self, product_name: str) -> str:
        normalized = (product_name or "").strip()
        if not normalized:
            normalized = "Widget Pro"
        with SessionLocal() as session:
            product = session.query(Product).filter(Product.name.ilike(normalized)).first()
            if product is not None:
                return product.name
            if normalized.lower() in {"product x", "product x 1", "product 1"}:
                default = session.query(Product).order_by(Product.id).first()
                return default.name if default else "Widget Pro"
            default = session.query(Product).order_by(Product.id).first()
            return default.name if default else normalized

    def get_inventory(self, product_name: str) -> dict[str, Any]:
        resolved_name = self._resolve_product_name(product_name)
        bom = self.adapter.get_bom(resolved_name)
        materials: list[dict[str, Any]] = []
        for item in bom:
            quantity = float(item.get("quantity") or 0.0)
            materials.append({
                "material": item["material"],
                "bom_qty": quantity,
                "available": float(self.adapter.get_stock(item["material"])),
                "required_for_one_unit": quantity,
            })
        return {"product_name": resolved_name, "materials": materials}

    def get_run_status(self, run_id: str) -> dict[str, Any]:
        return self.graph.get_run(run_id) if self.graph is not None else {"run_id": run_id, "status": "unknown"}

    def forecast_demand(self, product_name: str, pct: float = 0.0, days: int = 30) -> dict[str, Any]:
        resolved_name = self._resolve_product_name(product_name)
        forecast = run_forecast(resolved_name, days)
        multiplier = 1.0 + (pct / 100.0)
        baseline = float(forecast["baseline"])
        projected_units = max(1.0, baseline * multiplier)
        inventory = self.get_inventory(resolved_name)
        shortfall: list[dict[str, Any]] = []
        for material in inventory["materials"]:
            needed = material["bom_qty"] * projected_units
            if material["available"] < needed:
                shortfall.append({
                    "material": material["material"],
                    "needed": round(needed, 2),
                    "available": round(material["available"], 2),
                    "delta": round(needed - material["available"], 2),
                })
        return {
            **forecast,
            "product_name": resolved_name,
            "baseline_units": round(baseline, 2),
            "projected_units": round(projected_units, 2),
            "projected_demand": round(projected_units, 2),
            "shortfall": shortfall,
        }

    def simulate_spike(self, product_name: str, pct: float, days: int = 30) -> dict[str, Any]:
        resolved_name = self._resolve_product_name(product_name)
        forecast = self.forecast_demand(resolved_name, pct=pct, days=days)
        recommended_quantity = max(1.0, float(forecast["projected_units"]))
        plan_id = f"plan-{uuid.uuid4().hex[:8]}"
        proposed_plan = {
            "product_name": resolved_name,
            "quantity": recommended_quantity,
            "due_date": None,
            "urgency": "normal",
        }
        plan = {
            "plan_id": plan_id,
            "product_name": resolved_name,
            "pct_increase": pct,
            "days": days,
            "recommended_quantity": recommended_quantity,
            "requires_confirmation": True,
            "shortfall": forecast["shortfall"],
            "shortfall_table": forecast["shortfall"],
            "proposed_plan": proposed_plan,
            "summary": (
                f"Projected demand for {resolved_name} rises by {pct}% over the next {days} days. "
                f"Recommended run quantity is {recommended_quantity:.0f} units."
            ),
            "message": f"Demand spike plan prepared for {resolved_name}.",
            "forecast": forecast,
        }
        self.active_plans[plan_id] = plan
        return plan

    def start_production(
        self,
        product_name: str,
        quantity: float,
        due_date: str | None = None,
        urgency: str = "normal",
        *,
        plan_id: str | None = None,
    ) -> dict[str, Any]:
        if not plan_id or plan_id not in self.active_plans:
            raise ValueError("Production requires a valid confirmed plan_id")
        plan = self.active_plans[plan_id]
        if plan.get("confirmed"):
            raise ValueError("Chat plan has already been confirmed")
        plan["confirmed"] = True
        if self.graph is None:
            self.graph = build_phase1_graph(adapter=self.adapter)
        return self.graph.create_run(product_name, float(quantity), due_date, urgency)

    def list_pending_reviews(self) -> list[dict[str, Any]]:
        with SessionLocal() as session:
            rows = session.query(Approval).filter(Approval.status == "pending").all()
            return [
                {
                    "run_id": session.query(ProductionRun).filter(ProductionRun.id == row.run_id).first().run_id,
                    "status": row.status,
                    "comments": row.comments,
                }
                for row in rows
            ]

    def explain_decision(self, event_id: int | str) -> dict[str, Any]:
        with SessionLocal() as session:
            row = session.query(EventLog).filter(EventLog.id == int(event_id)).first()
            if row is None:
                return {"event_id": event_id, "error": "Event not found"}
            return {
                "event_id": row.id,
                "sender": row.sender,
                "receiver": row.receiver,
                "type": row.type,
                "human_text": row.human_text,
                "payload": json.loads(row.payload_json or "{}"),
            }

    def handle_message(self, message: str) -> dict[str, Any]:
        msg = (message or "").strip()
        product_match = re.search(
            r"demand\s+for\s+([A-Za-z0-9][A-Za-z0-9\s\-]*?)(?:\s+will|\s+up|\s+is|\s+to\s+|$)",
            msg,
            flags=re.IGNORECASE,
        )
        product_name = product_match.group(1).strip() if product_match else "Widget Pro"
        pct_match = re.search(r"(?:up|jump|increase|rise)\s+(\d+(?:\.\d+)?)%?", msg, flags=re.IGNORECASE)
        pct_match = pct_match or re.search(r"(\d+(?:\.\d+)?)%", msg)
        pct = float(pct_match.group(1)) if pct_match else 40.0
        days_match = re.search(r"(?:next\s+)?(\d+)\s+days?", msg, flags=re.IGNORECASE)
        days = int(days_match.group(1)) if days_match else 30
        plan = self.simulate_spike(product_name, pct, days)
        plan["next_action"] = "Confirm to start the recommended production run."
        self.bus.emit(Event(
            run_id=None,
            sender="Admin",
            receiver="OrchestratorChat",
            type="human_action",
            payload={"message": msg, "plan_id": plan["plan_id"]},
            human_text=plan["message"],
        ))
        return plan
