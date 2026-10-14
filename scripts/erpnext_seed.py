"""Seed the ERPNext catalog used by Logistria's deterministic demo.

Run after the ERPNext site is reachable:
    ERPNEXT_URL=http://localhost:8080 ERPNEXT_API_KEY=... \
      ERPNEXT_API_SECRET=... python scripts/erpnext_seed.py
"""

from __future__ import annotations

import os
import sys
from typing import Any

import requests


PRODUCTS = {
    "Widget Pro": ("WPRO", [("Steel", 2), ("Copper", 1), ("Plastic", 1), ("Electronics", 1)]),
    "Sensor Module B3": ("SENS-B3", [("Copper", 5), ("Resin", 3), ("Packaging", 2)]),
    "Precision Gear": ("GEAR-7", [("Steel", 3), ("Bearing", 2), ("Coating", 1)]),
}
MATERIALS = [
    ("Steel", "STEEL"),
    ("Copper", "COPPER"),
    ("Plastic", "PLASTIC"),
    ("Resin", "RESIN"),
    ("Electronics", "ELEC"),
    ("Packaging", "PKG"),
    ("Bearing", "BRG"),
    ("Coating", "COAT"),
]
SUPPLIERS = [
    "Apex Industrial Supplies",
    "Meridian Components Co.",
    "NovaTrade Logistics",
    "SwiftSource Global",
    "NexGen Procure",
]


class ERPNext:
    def __init__(self) -> None:
        self.base_url = os.getenv("ERPNEXT_URL", "http://localhost:8080").rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({"Accept": "application/json", "Content-Type": "application/json"})
        api_key = os.getenv("ERPNEXT_API_KEY", "")
        api_secret = os.getenv("ERPNEXT_API_SECRET", "")
        if api_key and api_secret:
            self.session.headers["Authorization"] = f"token {api_key}:{api_secret}"

    def request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        response = self.session.request(method, f"{self.base_url}{path}", timeout=20, **kwargs)
        if not response.ok:
            raise RuntimeError(f"{method} {path} failed ({response.status_code}): {response.text[:300]}")
        return response.json() if response.content else {}

    def exists(self, doctype: str, name: str) -> bool:
        response = self.session.get(f"{self.base_url}/api/resource/{doctype}/{name}", timeout=20)
        if response.status_code == 404:
            return False
        if not response.ok:
            raise RuntimeError(f"GET {doctype}/{name} failed ({response.status_code}): {response.text[:300]}")
        return True

    def create(self, doctype: str, data: dict[str, Any]) -> None:
        name = str(data.get("item_code") or data.get("supplier_name") or data.get("warehouse_name") or data.get("bom_name") or data.get("name"))
        if not self.exists(doctype, name):
            self.request("POST", f"/api/resource/{doctype}", json=data)


def seed(client: ERPNext) -> None:
    client.create("Warehouse", {"warehouse_name": "Logistria Stores", "company": os.getenv("ERPNEXT_COMPANY", "Logistria Demo")})
    for name, sku in MATERIALS:
        client.create("Item", {"item_code": sku, "item_name": name, "item_group": "Raw Material", "stock_uom": "Nos", "is_stock_item": 1})
    for product_name, (sku, _) in PRODUCTS.items():
        client.create("Item", {"item_code": sku, "item_name": product_name, "item_group": "Finished Goods", "stock_uom": "Nos", "is_stock_item": 1})
    for supplier in SUPPLIERS:
        client.create("Supplier", {"supplier_name": supplier, "supplier_group": "Local", "supplier_type": "Company"})
    for product_name, (sku, components) in PRODUCTS.items():
        bom_name = f"{sku}-BOM"
        if not client.exists("BOM", bom_name):
            client.request(
                "POST",
                "/api/resource/BOM",
                json={
                    "name": bom_name,
                    "item": sku,
                    "quantity": 1,
                    "is_active": 1,
                    "is_default": 1,
                    "items": [{"item_code": dict(MATERIALS)[material], "qty": quantity} for material, quantity in components],
                },
            )


if __name__ == "__main__":
    try:
        seed(ERPNext())
    except (requests.RequestException, RuntimeError, KeyError) as exc:
        print(f"ERPNext seed failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    print("ERPNext Logistria catalog seeded.")
