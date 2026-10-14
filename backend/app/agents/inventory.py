from __future__ import annotations

from typing import Any

from ..bus import Event, EventBus


class InventoryAgent:
    def __init__(self, adapter: Any, bus: EventBus | None = None) -> None:
        self.adapter = adapter
        self.bus = bus

    def check_materials(self, product_name: str, quantity: float, run_id: str) -> dict[str, Any]:
        bom = self.adapter.get_bom(product_name)
        shortages: list[dict[str, Any]] = []

        for item in bom:
            needed = float(item["quantity"]) * float(quantity)
            available = float(self.adapter.get_stock(item["material"]))
            if available < needed:
                shortages.append({
                    "material": item["material"],
                    "needed": needed,
                    "available": available,
                    "shortage": max(needed - available, 0.0),
                })

        if shortages:
            event = Event(
                run_id=run_id,
                sender="InventoryAgent",
                receiver="SupplierRankingAgent",
                type="shortage_detected",
                payload={"product_name": product_name, "shortages": shortages},
                human_text=f"Shortage detected for {product_name}; ranking suppliers.",
                severity="warning",
            )
            if self.bus:
                self.bus.emit(event)
            return {"has_shortage": True, "shortages": shortages, "status": "shortage_detected"}

        event = Event(
            run_id=run_id,
            sender="InventoryAgent",
            receiver="ManufacturingStep",
            type="inventory_check",
            payload={"product_name": product_name, "quantity": quantity},
            human_text=f"Inventory available for {product_name}; production can proceed without procurement.",
            severity="info",
        )
        if self.bus:
            self.bus.emit(event)
        return {"has_shortage": False, "shortages": [], "status": "manufacturing"}
