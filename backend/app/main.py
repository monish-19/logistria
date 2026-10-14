from __future__ import annotations

import os
import json
from datetime import datetime
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, ConfigDict, Field

from .adapters import build_adapter
from .agents.chat import OrchestratorChat
from .bus import DEFAULT_BUS, Event, WebSocketManager
from .config import ADMIN_API_KEY
from .graph import build_phase1_graph
from .models import (
    Approval,
    EventLog,
    Inventory,
    Material,
    Product,
    ProductionRun,
    PurchaseOrder,
    SessionLocal,
    Supplier,
    SupplierMaterial,
)
from .seed import seed_database


class RunRequest(BaseModel):
    product_name: str = Field(..., description="Product to process")
    quantity: float = Field(..., gt=0)
    due_date: str | None = None
    urgency: str = "normal"


class ApprovalRequest(BaseModel):
    approved: bool = True
    supplier_name: str | None = None


class ChatRequest(BaseModel):
    message: str = Field(..., description="Natural-language demand spike request")


class ChatConfirmation(BaseModel):
    plan_id: str
    product_name: str | None = None
    quantity: float | None = None
    due_date: str | None = None
    urgency: str = "normal"


class SupplierOverride(BaseModel):
    supplier_id: int


class RunSummary(BaseModel):
    run_id: str
    product_name: str
    quantity: float
    status: str
    decision: Any = None
    created_at: datetime | None = None


class RunDetail(RunSummary):
    approval_required: bool
    due_date: str | None = None
    urgency: str
    nodes: dict[str, str]
    materials: list[dict[str, Any]]
    selected_supplier: dict[str, Any] | None = None
    purchase_orders: list[dict[str, Any]]
    route: dict[str, Any] | None = None
    distance_km: float | None = None
    eta_minutes: float | None = None
    delivery_cost: float | None = None


class EventResponse(BaseModel):
    id: int
    run_id: str | None = None
    sender: str
    receiver: str
    type: str
    payload_json: dict[str, Any]
    human_text: str | None = None
    severity: str
    ts: datetime


class ProductResponse(BaseModel):
    id: int
    name: str
    sku: str | None = None
    reorder_threshold: float


class InventoryResponse(BaseModel):
    id: int
    material: str
    sku: str | None = None
    available_qty: float
    reserved_qty: float


class SupplierResponse(BaseModel):
    id: int
    name: str
    is_cold_start: bool
    materials: list[dict[str, Any]]


class ApprovalResponse(BaseModel):
    id: int
    run_id: str | None = None
    status: str
    comments: str | None = None
    approved_by: str | None = None


class RunActionResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    run_id: str | None = None
    status: str | None = None
    decision: Any = None
    approved: bool | None = None


class RouteResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    geometry: Any | None = None
    method: str | None = None
    total_distance_km: float | None = None
    eta_minutes: float | None = None


seed_database()
ws_manager = WebSocketManager()
DEFAULT_BUS.set_websocket_manager(ws_manager)
chat_agent = OrchestratorChat(adapter=build_adapter())


def get_chat_agent() -> OrchestratorChat:
    return chat_agent


NODE_NAMES = ("inventory", "ranking", "procurement", "manufacturing", "logistics", "monitor")


def _node_statuses(run: ProductionRun) -> dict[str, str]:
    if run.status == "rejected":
        return {name: ("done" if name in {"inventory", "ranking", "procurement"} else "failed") for name in NODE_NAMES}
    if run.status == "pending_human_review":
        return {
            "inventory": "done",
            "ranking": "done",
            "procurement": "paused",
            "manufacturing": "pending",
            "logistics": "pending",
            "monitor": "active",
        }
    if run.status in {"manufacturing", "completed"}:
        return {name: "done" for name in NODE_NAMES}
    return {name: "active" if name == "inventory" else "pending" for name in NODE_NAMES}


def _run_detail(session: Any, run: ProductionRun) -> RunDetail:
    materials: list[dict[str, Any]] = []
    for event in session.query(EventLog).filter(EventLog.run_id == run.id).order_by(EventLog.id.asc()).all():
        payload = json.loads(event.payload_json or "{}")
        if event.sender == "InventoryAgent":
            materials.extend(payload.get("shortages", []))
    purchase_orders = [
        {
            "id": po.id,
            "supplier_id": po.supplier_id,
            "material_id": po.material_id,
            "quantity": po.quantity,
            "unit_price": po.unit_price,
            "status": po.status,
        }
        for po in session.query(PurchaseOrder).filter(PurchaseOrder.run_id == run.run_id).all()
    ]
    selected_supplier = None
    if purchase_orders:
        selected_supplier = {
            "id": purchase_orders[0]["supplier_id"],
            "name": session.get(Supplier, purchase_orders[0]["supplier_id"]).name,
        }
    return RunDetail(
        run_id=run.run_id,
        product_name=run.product_name,
        quantity=run.quantity,
        status=run.status,
        decision=run.decision,
        created_at=run.created_at,
        approval_required=run.approval_required,
        due_date=run.due_date,
        urgency=run.urgency,
        nodes=_node_statuses(run),
        materials=materials,
        selected_supplier=selected_supplier,
        purchase_orders=purchase_orders,
        route=json.loads(run.route_json) if run.route_json else None,
        distance_km=run.distance_km,
        eta_minutes=run.eta_minutes,
        delivery_cost=run.delivery_cost,
    )


def _event_response(row: EventLog, run_id: str | None = None) -> EventResponse:
    return EventResponse(
        id=row.id,
        run_id=run_id,
        sender=row.sender,
        receiver=row.receiver,
        type=row.type,
        payload_json=json.loads(row.payload_json or "{}"),
        human_text=row.human_text,
        severity=row.severity,
        ts=row.ts,
    )


def _admin_key() -> str:
    return (os.getenv("ADMIN_API_KEY") or ADMIN_API_KEY or "").strip()


def _allow_insecure_dev() -> bool:
    return (os.getenv("ALLOW_INSECURE_DEV") or "").strip().lower() in {"1", "true", "yes", "on"}


def require_admin(request: Request) -> None:
    key = _admin_key()
    if not key:
        if _allow_insecure_dev():
            return
        raise HTTPException(status_code=503, detail="ADMIN_API_KEY not configured")
    provided = request.headers.get("X-Admin-Key") or request.headers.get("x-admin-key")
    if not provided:
        auth = request.headers.get("Authorization") or request.headers.get("authorization") or ""
        if auth.lower().startswith("bearer "):
            provided = auth[7:]
    if provided != key:
        raise HTTPException(status_code=401, detail="Admin authentication required")


app = FastAPI(title="Logistria Phase 5")
cors_origins = [
    origin.strip()
    for origin in (os.getenv("CORS_ORIGINS") or "http://localhost:5173").split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/war-room")
def war_room() -> RedirectResponse:
    return RedirectResponse(url=os.getenv("FRONTEND_URL", "http://localhost:5173"))

@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.websocket("/ws/events")
async def events_ws(websocket: WebSocket) -> None:
    key = _admin_key()
    if key and websocket.query_params.get("token") != key:
        await websocket.close(code=1008, reason="Admin authentication required")
        return
    await ws_manager.connect(websocket)
    with SessionLocal() as session:
        rows = session.query(EventLog).order_by(EventLog.id.desc()).limit(50).all()
        for row in reversed(rows):
            run = session.get(ProductionRun, row.run_id) if row.run_id else None
            await websocket.send_json(_event_response(row, run.run_id if run else None).model_dump(mode="json"))
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        await ws_manager.disconnect(websocket)


@app.get("/api/events", response_model=list[EventResponse])
def list_events(
    run_id: str | None = None,
    severity: str | None = None,
    type: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    before: int | None = None,
) -> list[EventResponse]:
    with SessionLocal() as session:
        query = session.query(EventLog).order_by(EventLog.id.desc())
        if run_id:
            run = session.query(ProductionRun).filter(ProductionRun.run_id == run_id).first()
            query = query.filter(EventLog.run_id == (run.id if run else -1))
        if severity:
            query = query.filter(EventLog.severity == severity)
        if type:
            query = query.filter(EventLog.type == type)
        if before:
            query = query.filter(EventLog.id < before)
        rows = query.limit(limit).all()
        return [_event_response(row, run_id) for row in reversed(rows)]


@app.get("/api/events/{event_id}", response_model=EventResponse)
def get_event(event_id: int) -> EventResponse:
    with SessionLocal() as session:
        row = session.get(EventLog, event_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Event not found")
        run = session.get(ProductionRun, row.run_id) if row.run_id else None
        return _event_response(row, run.run_id if run else None)


@app.get("/api/approvals", response_model=list[ApprovalResponse])
def pending_approvals() -> list[ApprovalResponse]:
    with SessionLocal() as session:
        rows = session.query(Approval).filter(Approval.status == "pending").all()
        payload: list[ApprovalResponse] = []
        for row in rows:
            run = session.query(ProductionRun).filter(ProductionRun.id == row.run_id).first()
            payload.append(ApprovalResponse(
                id=row.id,
                run_id=run.run_id if run else None,
                status=row.status,
                comments=row.comments,
                approved_by=row.approved_by,
            ))
        return payload


@app.get("/api/alerts", response_model=list[EventResponse])
def list_alerts(limit: int = Query(default=100, ge=1, le=500)) -> list[EventResponse]:
    with SessionLocal() as session:
        rows = session.query(EventLog).filter(EventLog.type.in_(("alert", "escalation"))).order_by(EventLog.id.desc()).limit(limit).all()
        return [_event_response(row) for row in reversed(rows)]


@app.get("/api/products", response_model=list[ProductResponse])
def list_products() -> list[ProductResponse]:
    with SessionLocal() as session:
        return [ProductResponse.model_validate(row, from_attributes=True) for row in session.query(Product).order_by(Product.name).all()]


@app.get("/api/inventory", response_model=list[InventoryResponse])
def list_inventory() -> list[InventoryResponse]:
    with SessionLocal() as session:
        rows = session.query(Inventory, Material).join(Material, Inventory.material_id == Material.id).order_by(Material.name).all()
        return [
            InventoryResponse(
                id=inventory.id,
                material=material.name,
                sku=material.sku,
                available_qty=inventory.available_qty,
                reserved_qty=inventory.reserved_qty,
            )
            for inventory, material in rows
        ]


@app.get("/api/suppliers", response_model=list[SupplierResponse])
def list_suppliers() -> list[SupplierResponse]:
    with SessionLocal() as session:
        rows = session.query(Supplier).order_by(Supplier.name).all()
        return [
            SupplierResponse(
                id=supplier.id,
                name=supplier.name,
                is_cold_start=supplier.is_cold_start,
                materials=[
                    {
                        "material_id": item.material_id,
                        "unit_price": item.unit_price,
                        "lead_time_days": item.lead_time_days,
                        "minimum_order_qty": item.minimum_order_qty,
                    }
                    for item in session.query(SupplierMaterial).filter(SupplierMaterial.supplier_id == supplier.id).all()
                ],
            )
            for supplier in rows
        ]


@app.post("/api/chat")
def chat_query(payload: ChatRequest) -> dict[str, Any]:
    return get_chat_agent().handle_message(payload.message)


@app.post("/api/chat/confirm", dependencies=[Depends(require_admin)])
def confirm_chat_plan(request: Request, payload: ChatConfirmation) -> dict[str, Any]:
    require_admin(request)
    chat_agent = get_chat_agent()
    plan = chat_agent.active_plans.get(payload.plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="Chat plan not found")
    quantity = float(payload.quantity or plan.get("recommended_quantity") or 1.0)
    try:
        run = chat_agent.start_production(
            payload.product_name or plan["product_name"],
            quantity,
            payload.due_date,
            payload.urgency,
            plan_id=payload.plan_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    DEFAULT_BUS.emit(Event(
        run_id=run.get("run_id"),
        sender="Admin",
        receiver="OrchestratorChat",
        type="human_action",
        payload={"plan_id": payload.plan_id, "quantity": quantity},
        human_text=f"Admin confirmed the production plan for {plan['product_name']}.",
        severity="success",
    ))
    plan["run_id"] = run.get("run_id")
    return {"status": "confirmed", "plan_id": payload.plan_id, "run": run}


@app.post("/api/runs", dependencies=[Depends(require_admin)])
def create_run(request: Request, payload: RunRequest) -> dict[str, Any]:
    require_admin(request)
    graph = build_phase1_graph(adapter=build_adapter())
    return graph.create_run(payload.product_name, payload.quantity, payload.due_date, payload.urgency)


@app.get("/api/runs", response_model=list[RunSummary])
def list_runs(status: str | None = None) -> list[RunSummary]:
    with SessionLocal() as session:
        query = session.query(ProductionRun).order_by(ProductionRun.created_at.desc())
        if status:
            query = query.filter(ProductionRun.status == status)
        return [
            RunSummary(
                run_id=run.run_id,
                product_name=run.product_name,
                quantity=run.quantity,
                status=run.status,
                decision=run.decision,
                created_at=run.created_at,
            )
            for run in query.all()
        ]


@app.post("/api/runs/{run_id}/approve", dependencies=[Depends(require_admin)])
def approve_run(request: Request, run_id: str, payload: ApprovalRequest) -> dict[str, Any]:
    require_admin(request)
    graph = build_phase1_graph(adapter=build_adapter())
    result = graph.approve_run(run_id, payload.approved, payload.supplier_name)
    DEFAULT_BUS.emit(Event(
        run_id=run_id,
        sender="Admin",
        receiver="ProcurementAgent",
        type="human_action",
        payload={"approved": payload.approved, "supplier_name": payload.supplier_name},
        human_text=f"Admin {'approved' if payload.approved else 'rejected'} the run {run_id}.",
        severity="success" if payload.approved else "warning",
    ))
    return result


@app.post("/api/runs/{run_id}/reject", response_model=RunActionResponse, dependencies=[Depends(require_admin)])
def reject_run(request: Request, run_id: str) -> RunActionResponse:
    require_admin(request)
    graph = build_phase1_graph(adapter=build_adapter())
    result = graph.approve_run(run_id, approved=False)
    DEFAULT_BUS.emit(Event(
        run_id=run_id,
        sender="Admin",
        receiver="ProcurementAgent",
        type="human_action",
        payload={"action": "reject"},
        human_text=f"Admin rejected the run {run_id}.",
        severity="warning",
    ))
    return RunActionResponse.model_validate(result)


@app.post("/api/runs/{run_id}/override", response_model=RunActionResponse, dependencies=[Depends(require_admin)])
def override_run(request: Request, run_id: str, payload: SupplierOverride) -> RunActionResponse:
    require_admin(request)
    with SessionLocal() as session:
        supplier = session.get(Supplier, payload.supplier_id)
        if supplier is None:
            raise HTTPException(status_code=404, detail="Supplier not found")
        supplier_name = supplier.name
    graph = build_phase1_graph(adapter=build_adapter())
    result = graph.approve_run(run_id, approved=True, supplier_name=supplier_name)
    DEFAULT_BUS.emit(Event(
        run_id=run_id,
        sender="Admin",
        receiver="ProcurementAgent",
        type="human_action",
        payload={"action": "override", "supplier_id": payload.supplier_id, "supplier_name": supplier_name},
        human_text=f"Admin selected {supplier_name} for run {run_id}.",
        severity="success",
    ))
    return RunActionResponse.model_validate(result)


@app.get("/api/runs/{run_id}/route", response_model=RouteResponse)
def get_run_route(run_id: str) -> RouteResponse:
    with SessionLocal() as session:
        run = session.query(ProductionRun).filter(ProductionRun.run_id == run_id).first()
        if run is None:
            raise HTTPException(status_code=404, detail="Run not found")
        return RouteResponse.model_validate(json.loads(run.route_json) if run.route_json else {})


@app.get("/api/runs/{run_id}", response_model=RunDetail)
def get_run(run_id: str) -> RunDetail:
    with SessionLocal() as session:
        run = session.query(ProductionRun).filter(ProductionRun.run_id == run_id).first()
        if run is None:
            raise HTTPException(status_code=404, detail="Run not found")
        return _run_detail(session, run)
