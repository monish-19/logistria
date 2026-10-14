from __future__ import annotations

import json
import uuid
from typing import Any

from .adapters.mock import MockAdapter
from .agents.inventory import InventoryAgent
from .agents.logistics import LogisticsAgent
from .agents.manufacturing import ManufacturingStep
from .agents.monitor import MonitorAgent
from .agents.procurement import ProcurementAgent
from .agents.ranking import SupplierRankingAgent
from .bus import DEFAULT_BUS, Event
from .llm import DEFAULT_LLM
from .models import Approval, ProductionRun, PurchaseOrder, SessionLocal


class Phase1Graph:
    def __init__(self, adapter: MockAdapter | None = None, bus: Any | None = None, llm: Any | None = None) -> None:
        self.adapter = adapter or MockAdapter()
        self.bus = bus or DEFAULT_BUS
        self.llm = llm or DEFAULT_LLM

    def _load_run(self, run_id: str) -> ProductionRun:
        session = SessionLocal()
        try:
            run = session.query(ProductionRun).filter(ProductionRun.run_id == run_id).one()
            return run
        finally:
            session.close()

    def create_run(self, product_name: str, quantity: float, due_date: str | None = None, urgency: str = "normal") -> dict[str, Any]:
        run_id = f"run-{uuid.uuid4().hex[:8]}"
        session = SessionLocal()
        try:
            run = ProductionRun(
                run_id=run_id,
                product_name=product_name,
                quantity=quantity,
                due_date=due_date,
                urgency=urgency,
                status="queued",
                decision="checking_inventory",
                notes=json.dumps({"quantity": quantity, "due_date": due_date, "urgency": urgency}),
            )
            session.add(run)
            session.commit()
            session.refresh(run)
        finally:
            session.close()

        self.bus.emit(Event(
            run_id=run_id,
            sender="Admin",
            receiver="InventoryAgent",
            type="request",
            payload={"product_name": product_name, "quantity": quantity, "due_date": due_date, "urgency": urgency},
            human_text=f"Production run started for {product_name} at quantity {quantity}.",
            severity="info",
        ))

        inventory = InventoryAgent(self.adapter, self.bus).check_materials(product_name, float(quantity), run_id)
        if not inventory["has_shortage"]:
            self._set_run_status(run_id, "manufacturing", "inventory_ok")
            return self._finalize_run(run_id, product_name, quantity, shortages=[], approval_required=False, decision={"status": "inventory_ok"})

        rankings = []
        for item in inventory["shortages"]:
            ranked = SupplierRankingAgent(self.adapter, self.bus).rank_material(item["material"], item["needed"], due_date, urgency)
            rankings.append(ranked)

        total_value = 0.0
        for item in inventory["shortages"]:
            ranking = next((entry for entry in rankings if entry.get("material") == item["material"]), None)
            if ranking is None or not ranking.get("top_pick"):
                continue
            supplier = next(
                (
                    candidate
                    for candidate in self.adapter.list_suppliers(item["material"])
                    if candidate.get("name") == ranking["top_pick"]
                ),
                None,
            )
            if supplier is not None:
                total_value += float(supplier["unit_price"]) * float(item["needed"])
        decision = ProcurementAgent(self.adapter, self.bus).decide(rankings, total_value, run_id)

        if decision["status"] == "auto_approved":
            for item in inventory["shortages"]:
                ranking = next((entry for entry in rankings if entry.get("material") == item["material"]), None)
                if ranking is None:
                    continue
                suppliers = self.adapter.list_suppliers(item["material"])
                supplier_data = next((supplier for supplier in suppliers if supplier["name"] == ranking["top_pick"]), None)
                if supplier_data is None:
                    continue
                po = self.adapter.create_purchase_order(run_id, supplier_data["name"], item["material"], item["needed"], float(supplier_data["unit_price"]))
                self.adapter.record_supplier_history(supplier_data["name"], item["material"], "po_created", run_id=run_id, status="ok", notes=json.dumps(po))
            self._set_run_status(run_id, "manufacturing", "auto_approved")
            return self._finalize_run(run_id, product_name, quantity, shortages=inventory["shortages"], approval_required=False, decision=decision, rankings=rankings)

        self._set_run_status(run_id, "pending_human_review", "pending_human_review")
        session = SessionLocal(); session.add(Approval(run_id=self._load_run(run_id).id, status="pending", comments="Awaiting procurement approval")); session.commit(); session.close()
        return {"run_id": run_id, "status": "pending_human_review", "approval_required": True, "shortages": inventory["shortages"], "rankings": rankings, "decision": decision}

    def _finalize_run(self, run_id: str, product_name: str, quantity: float, shortages: list[dict[str, Any]] | None = None, approval_required: bool = False, decision: dict[str, Any] | None = None, rankings: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        manufacturing = ManufacturingStep(self.adapter, self.bus).simulate(run_id, product_name, quantity)
        route = LogisticsAgent(self.adapter, self.bus).optimize_delivery(run_id, product_name, quantity)
        session = SessionLocal()
        try:
            purchase_orders = [
                {
                    "id": po.id,
                    "supplier_id": po.supplier_id,
                    "material_id": po.material_id,
                    "quantity": po.quantity,
                    "unit_price": po.unit_price,
                    "status": po.status,
                }
                for po in session.query(PurchaseOrder).filter(PurchaseOrder.run_id == run_id).all()
            ]
        finally:
            session.close()
        alerts = MonitorAgent(self.bus).raise_alerts_for_run(
            run_id,
            "manufacturing",
            last_event_ts=None,
            route=route,
            purchase_orders=purchase_orders,
        )

        session = SessionLocal()
        try:
            run = session.query(ProductionRun).filter(ProductionRun.run_id == run_id).one()
            run.status = "completed"
            run.decision = decision["status"] if decision else "completed"
            run.route_json = json.dumps(route)
            run.distance_km = float(route.get("distance_km", 0.0))
            run.eta_minutes = float(route.get("eta_minutes", 0.0))
            run.delivery_cost = float(route.get("delivery_cost", 0.0))
            session.commit()
        finally:
            session.close()

        self.bus.emit(Event(
            run_id=run_id,
            sender="LogisticsAgent",
            receiver="Admin",
            type="response",
            payload={"status": "completed", "route": route},
            human_text=f"Logistics completed delivery for {product_name}; the production run is complete.",
            severity="success",
        ))

        payload = {
            "run_id": run_id,
            "status": "completed",
            "approval_required": approval_required,
            "shortages": shortages or [],
            "rankings": rankings or [],
            "decision": decision,
            "manufacturing": manufacturing,
            "route": route,
            "alerts": alerts,
        }
        if decision is not None and "approved" in decision:
            payload["approved"] = decision["approved"]
        return payload

    def _set_run_status(self, run_id: str, status: str, decision: str) -> None:
        session = SessionLocal()
        try:
            run = session.query(ProductionRun).filter(ProductionRun.run_id == run_id).one()
            run.status = status
            run.decision = decision
            run.approval_required = status == "pending_human_review"
            session.commit()
        finally:
            session.close()

    def approve_run(self, run_id: str, approved: bool = True, supplier_name: str | None = None) -> dict[str, Any]:
        session = SessionLocal()
        try:
            run = session.query(ProductionRun).filter(ProductionRun.run_id == run_id).one()
            if run.status != "pending_human_review":
                return {"run_id": run_id, "status": run.status, "decision": run.decision, "approved": False}
            if approved:
                run.status = "manufacturing"
                run.decision = "approved_by_human"
                run.approval_required = False
                session.add(Approval(run_id=run.id, status="approved", comments=(supplier_name or "approved by admin"), approved_by="admin"))
                session.commit()
                session.close()
                result = self._finalize_run(run_id, run.product_name, float(run.quantity), shortages=[], approval_required=False, decision={"status": "approved_by_human"})
                result["approved"] = True
                return result
            run.status = "rejected"
            run.decision = "rejected_by_human"
            run.approval_required = False
            session.add(Approval(run_id=run.id, status="rejected", comments="Rejected by admin", approved_by="admin"))
            session.commit()
            session.close()
            return {"run_id": run_id, "status": "rejected", "decision": "rejected_by_human", "approved": False}
        finally:
            session.close()

    def get_run(self, run_id: str) -> dict[str, Any]:
        session = SessionLocal()
        try:
            run = session.query(ProductionRun).filter(ProductionRun.run_id == run_id).one()
            route = json.loads(run.route_json) if run.route_json else None
            return {
                "run_id": run.run_id,
                "status": run.status,
                "decision": run.decision,
                "product_name": run.product_name,
                "quantity": run.quantity,
                "approval_required": run.approval_required,
                "due_date": run.due_date,
                "urgency": run.urgency,
                "route": route,
                "distance_km": run.distance_km,
                "eta_minutes": run.eta_minutes,
                "delivery_cost": run.delivery_cost,
            }
        finally:
            session.close()


def build_phase1_graph(adapter: MockAdapter | None = None, bus: Any | None = None, llm: Any | None = None) -> Phase1Graph:
    return Phase1Graph(adapter=adapter, bus=bus, llm=llm)
