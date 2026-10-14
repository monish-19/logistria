from __future__ import annotations

import json
import os
from typing import Any
from urllib import error, parse, request

from ..bus import DEFAULT_BUS, Event
from .mock import MockAdapter


class ERPNextAdapter:
    """ERPNext REST adapter with deterministic SQLite fallback.

    The endpoint paths are intentionally small integration endpoints. They can be
    implemented as whitelisted ERPNext methods without coupling agents to ERPNext
    document internals.
    """

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        api_secret: str | None = None,
        session: Any | None = None,
        timeout: float | None = None,
        bus: Any | None = None,
        fallback: bool | None = None,
    ) -> None:
        self.base_url = (base_url or os.getenv("ERP_NEXT_BASE_URL") or os.getenv("ERP_BASE_URL") or "").rstrip("/")
        self.api_key = api_key or os.getenv("ERP_NEXT_API_KEY") or os.getenv("ERP_API_KEY") or ""
        self.api_secret = api_secret or os.getenv("ERP_NEXT_API_SECRET") or os.getenv("ERP_API_SECRET") or ""
        self.timeout = timeout or float(os.getenv("ERP_NEXT_TIMEOUT", "10"))
        self.fallback_enabled = fallback if fallback is not None else os.getenv("ADAPTER_FALLBACK", "true").lower() in {"1", "true", "yes", "on"}
        self.bus = bus or DEFAULT_BUS
        self.mock = MockAdapter(session=session)

    def _fallback(self, method_name: str, *args: Any) -> Any:
        return getattr(self.mock, method_name)(*args)

    def _recover(self, method_name: str, exc: Exception, *args: Any) -> Any:
        self.bus.emit(Event(
            run_id=args[2] if method_name == "reserve_stock" and len(args) > 2 else None,
            sender="ERPNextAdapter",
            receiver="MonitorAgent",
            type="alert",
            payload={"adapter": "erpnext", "method": method_name, "error": str(exc), "fallback": self.fallback_enabled},
            human_text=f"ERPNext {method_name} failed; {'using the mock adapter fallback' if self.fallback_enabled else 'the operation was not completed'}.",
            severity="alert",
        ))
        if not self.fallback_enabled:
            raise exc
        return self._fallback(method_name, *args)

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if self.api_key and self.api_secret:
            headers["Authorization"] = f"token {self.api_key}:{self.api_secret}"
        return headers

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> Any:
        if not self.base_url:
            raise RuntimeError("ERPNext base URL is not configured")
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        req = request.Request(f"{self.base_url}{path}", data=body, headers=self._headers(), method=method.upper())
        try:
            with request.urlopen(req, timeout=self.timeout) as response:
                raw = response.read()
        except error.HTTPError as exc:
            raise RuntimeError(f"ERPNext request failed with HTTP {exc.code}") from exc
        except error.URLError as exc:
            raise TimeoutError(f"ERPNext request failed: {exc.reason}") from exc
        if not raw:
            return {}
        decoded = json.loads(raw.decode("utf-8"))
        return decoded.get("data", decoded) if isinstance(decoded, dict) else decoded

    @staticmethod
    def _segment(value: str) -> str:
        return parse.quote(value, safe="")

    def get_bom(self, product_name: str) -> list[dict[str, Any]]:
        try:
            payload = self._request("GET", f"/api/products/{self._segment(product_name)}/bom")
            rows = payload.get("items", payload.get("bom", [])) if isinstance(payload, dict) else payload
            return rows if isinstance(rows, list) else []
        except (RuntimeError, TimeoutError, error.URLError, ValueError) as exc:
            return self._recover("get_bom", exc, product_name)

    def get_stock(self, material_name: str) -> float:
        try:
            payload = self._request("GET", f"/api/materials/{self._segment(material_name)}/stock")
            if isinstance(payload, dict):
                return float(payload.get("available_qty", payload.get("available", payload.get("actual_qty", 0.0))))
            if isinstance(payload, list) and payload:
                return float(payload[0].get("available_qty", payload[0].get("actual_qty", 0.0)))
            return 0.0
        except (RuntimeError, TimeoutError, error.URLError, ValueError, TypeError) as exc:
            return self._recover("get_stock", exc, material_name)

    def reserve_stock(self, material_name: str, quantity: float, run_id: str | None = None) -> bool:
        try:
            payload = self._request("POST", "/api/inventory/reserve", {"material_name": material_name, "quantity": quantity, "run_id": run_id})
            return bool(payload.get("reserved", True)) if isinstance(payload, dict) else bool(payload)
        except (RuntimeError, TimeoutError, error.URLError, ValueError, TypeError) as exc:
            return self._recover("reserve_stock", exc, material_name, quantity, run_id)

    def list_suppliers(self, material_name: str) -> list[dict[str, Any]]:
        try:
            payload = self._request("GET", f"/api/materials/{self._segment(material_name)}/suppliers")
            rows = payload.get("suppliers", []) if isinstance(payload, dict) else payload
            return rows if isinstance(rows, list) else []
        except (RuntimeError, TimeoutError, error.URLError, ValueError) as exc:
            return self._recover("list_suppliers", exc, material_name)

    def get_supplier_history(self, supplier_name: str, material_name: str) -> dict[str, Any]:
        try:
            payload = self._request(
                "GET",
                f"/api/suppliers/{self._segment(supplier_name)}/history?{parse.urlencode({'material_name': material_name})}",
            )
            return payload if isinstance(payload, dict) else {}
        except (RuntimeError, TimeoutError, error.URLError, ValueError) as exc:
            return self._recover("get_supplier_history", exc, supplier_name, material_name)

    def create_purchase_order(self, run_id: str, supplier_name: str, material_name: str, quantity: float, unit_price: float) -> dict[str, Any]:
        payload = {"run_id": run_id, "supplier_name": supplier_name, "material_name": material_name, "quantity": quantity, "unit_price": unit_price}
        try:
            result = self._request("POST", "/api/purchase-orders", payload)
            return result if isinstance(result, dict) else {**payload, "status": "created"}
        except (RuntimeError, TimeoutError, error.URLError, ValueError) as exc:
            return self._recover("create_purchase_order", exc, run_id, supplier_name, material_name, quantity, unit_price)

    def update_work_order(self, run_id: str, status: str, notes: str | None = None) -> None:
        try:
            self._request("POST", f"/api/work-orders/{self._segment(run_id)}/status", {"status": status, "notes": notes})
        except (RuntimeError, TimeoutError, error.URLError, ValueError) as exc:
            self._recover("update_work_order", exc, run_id, status, notes)

    def record_receipt(self, supplier_name: str, material_name: str, quantity: float) -> None:
        try:
            self._request("POST", "/api/receipts", {"supplier_name": supplier_name, "material_name": material_name, "quantity": quantity})
        except (RuntimeError, TimeoutError, error.URLError, ValueError) as exc:
            self._recover("record_receipt", exc, supplier_name, material_name, quantity)

    def record_supplier_history(
        self,
        supplier_name: str,
        material_name: str,
        event_type: str,
        run_id: str | None = None,
        status: str = "ok",
        notes: str | None = None,
    ) -> None:
        payload = {"supplier_name": supplier_name, "material_name": material_name, "event_type": event_type, "run_id": run_id, "status": status, "notes": notes}
        try:
            self._request("POST", "/api/supplier-history", payload)
        except (RuntimeError, TimeoutError, error.URLError, ValueError) as exc:
            self._recover("record_supplier_history", exc, supplier_name, material_name, event_type, run_id, status, notes)
