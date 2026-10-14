from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from urllib import parse, request

try:
    import yaml  # type: ignore
except Exception:  # pragma: no cover
    yaml = None

from .mock import MockAdapter


class GenericRESTAdapter:
    def __init__(self, config_path: str | None = None, base_url: str | None = None, session: Any | None = None) -> None:
        self.config_path = config_path or os.getenv("GENERIC_ADAPTER_CONFIG") or os.getenv("ERP_GENERIC_CONFIG")
        self.base_url = (base_url or os.getenv("GENERIC_BASE_URL") or os.getenv("ERP_BASE_URL") or "").rstrip("/")
        self.mock = MockAdapter(session=session)
        self.config = self._load_config()

    def _load_config(self) -> dict[str, Any]:
        if not self.config_path:
            return {}
        path = Path(self.config_path)
        if not path.exists():
            return {}
        text = path.read_text(encoding="utf-8")
        try:
            if yaml is not None:
                payload = yaml.safe_load(text) or {}
                if isinstance(payload, dict):
                    return payload
            if text.strip().startswith("{"):
                payload = json.loads(text)
                if isinstance(payload, dict):
                    return payload
        except Exception:
            pass
        return {}

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> Any:
        if not self.base_url:
            raise RuntimeError("Generic REST adapter base URL is not configured")
        url = f"{self.base_url}{path}"
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        req = request.Request(url, data=data, headers={"Accept": "application/json", "Content-Type": "application/json"}, method=method.upper())
        with request.urlopen(req, timeout=10) as response:
            raw = response.read()
            return json.loads(raw.decode("utf-8")) if raw else {}

    def _choose_endpoint(self, function_name: str, material_name: str | None = None) -> str:
        endpoints = self.config.get("endpoints", {})
        target = endpoints.get(function_name)
        if isinstance(target, str):
            if material_name is not None and "{material_name}" in target:
                return target.format(material_name=self._path_value(material_name))
            if material_name is not None and "{product_name}" in target:
                return target.format(product_name=self._path_value(material_name))
            return target
        defaults = {
            "get_bom": "/api/products/{product_name}/bom",
            "get_stock": "/api/materials/{material_name}/stock",
            "list_suppliers": "/api/materials/{material_name}/suppliers",
            "get_supplier_history": "/api/suppliers/{supplier_name}/history",
            "create_purchase_order": "/api/purchase-orders",
        }
        path = defaults.get(function_name, "/api/health")
        if material_name is not None and "{material_name}" in path:
            return path.format(material_name=material_name)
        return path

    @staticmethod
    def _path_value(value: str) -> str:
        return parse.quote(value, safe="")

    def get_bom(self, product_name: str) -> list[dict[str, Any]]:
        try:
            data = self._request("GET", self._choose_endpoint("get_bom", product_name).replace("{product_name}", self._path_value(product_name)))
            if isinstance(data, list):
                return data
            if isinstance(data, dict):
                return data.get("bom", [])
        except Exception:
            pass
        return self.mock.get_bom(product_name)

    def get_stock(self, material_name: str) -> float:
        try:
            data = self._request("GET", self._choose_endpoint("get_stock", material_name).replace("{material_name}", self._path_value(material_name)))
            if isinstance(data, dict):
                return float(data.get("available_qty", data.get("available", 0.0)))
            if isinstance(data, list):
                return float(data[0].get("available_qty", data[0].get("available", 0.0)))
        except Exception:
            pass
        return self.mock.get_stock(material_name)

    def reserve_stock(self, material_name: str, quantity: float, run_id: str | None = None) -> bool:
        try:
            data = self._request("POST", self._choose_endpoint("reserve_stock", material_name), {"material_name": material_name, "quantity": quantity, "run_id": run_id})
            return bool(data.get("reserved", True)) if isinstance(data, dict) else True
        except Exception:
            return self.mock.reserve_stock(material_name, quantity, run_id)

    def list_suppliers(self, material_name: str) -> list[dict[str, Any]]:
        try:
            data = self._request("GET", self._choose_endpoint("list_suppliers", material_name).replace("{material_name}", self._path_value(material_name)))
            if isinstance(data, list):
                return data
            if isinstance(data, dict):
                return data.get("suppliers", [])
        except Exception:
            pass
        return self.mock.list_suppliers(material_name)

    def get_supplier_history(self, supplier_name: str, material_name: str) -> dict[str, Any]:
        try:
            data = self._request("GET", self._choose_endpoint("get_supplier_history", material_name).replace("{material_name}", self._path_value(material_name)).replace("{supplier_name}", self._path_value(supplier_name)))
            if isinstance(data, dict):
                return data
        except Exception:
            pass
        return self.mock.get_supplier_history(supplier_name, material_name)

    def create_purchase_order(self, run_id: str, supplier_name: str, material_name: str, quantity: float, unit_price: float) -> dict[str, Any]:
        try:
            data = self._request("POST", self._choose_endpoint("create_purchase_order", material_name), {"run_id": run_id, "supplier_name": supplier_name, "material_name": material_name, "quantity": quantity, "unit_price": unit_price})
            if isinstance(data, dict):
                return data
        except Exception:
            pass
        return self.mock.create_purchase_order(run_id, supplier_name, material_name, quantity, unit_price)

    def update_work_order(self, run_id: str, status: str, notes: str | None = None) -> None:
        try:
            self._request("POST", "/api/work-orders/{run_id}/status".format(run_id=run_id), {"status": status, "notes": notes})
        except Exception:
            pass

    def record_receipt(self, supplier_name: str, material_name: str, quantity: float) -> None:
        try:
            self._request("POST", "/api/receipts", {"supplier_name": supplier_name, "material_name": material_name, "quantity": quantity})
        except Exception:
            self.mock.record_receipt(supplier_name, material_name, quantity)
