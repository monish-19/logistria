from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from ..models import (
    BOMItem,
    Inventory,
    Material,
    Product,
    PurchaseOrder,
    Supplier,
    SupplierHistory,
    SupplierMaterial,
    SessionLocal,
)


class MockAdapter:
    def __init__(self, session: Session | None = None) -> None:
        self.session = session or SessionLocal()

    def _material_id(self, material_name: str) -> int:
        material = self.session.query(Material).filter(Material.name == material_name).one()
        return material.id

    def _supplier_id(self, supplier_name: str) -> int:
        supplier = self.session.query(Supplier).filter(Supplier.name == supplier_name).one()
        return supplier.id

    def get_bom(self, product_name: str) -> list[dict[str, Any]]:
        product = self.session.query(Product).filter(Product.name == product_name).one()
        rows = self.session.query(BOMItem, Material).join(Material, BOMItem.material_id == Material.id).filter(BOMItem.product_id == product.id).all()
        return [{"material": material.name, "quantity": bom_item.quantity, "sku": material.sku} for bom_item, material in rows]

    def get_stock(self, material_name: str) -> float:
        inventory = self.session.query(Inventory).join(Material, Inventory.material_id == Material.id).filter(Material.name == material_name).first()
        return float(inventory.available_qty if inventory else 0.0)

    def reserve_stock(self, material_name: str, quantity: float, run_id: str | None = None) -> bool:
        inventory = self.session.query(Inventory).join(Material, Inventory.material_id == Material.id).filter(Material.name == material_name).first()
        if inventory is None or inventory.available_qty < quantity:
            return False
        inventory.available_qty -= quantity
        inventory.reserved_qty += quantity
        self.session.commit()
        return True

    def list_suppliers(self, material_name: str) -> list[dict[str, Any]]:
        rows = self.session.query(SupplierMaterial, Supplier).join(Supplier, SupplierMaterial.supplier_id == Supplier.id).join(Material, SupplierMaterial.material_id == Material.id).filter(Material.name == material_name).all()
        payload = []
        for supplier_material, supplier in rows:
            payload.append(
                {
                    "name": supplier.name,
                    "unit_price": supplier_material.unit_price,
                    "lead_time_days": supplier_material.lead_time_days,
                    "minimum_order_qty": supplier_material.minimum_order_qty,
                    "performance_history": {
                        "past_orders": supplier_material.past_orders,
                        "on_time_delivery_rate": supplier_material.on_time_rate,
                        "defect_rate": supplier_material.defect_rate,
                    },
                }
            )
        return payload

    def get_supplier_history(self, supplier_name: str, material_name: str) -> dict[str, Any]:
        row = self.session.query(SupplierMaterial).join(Supplier, SupplierMaterial.supplier_id == Supplier.id).join(Material, SupplierMaterial.material_id == Material.id).filter(Supplier.name == supplier_name, Material.name == material_name).first()
        if row is None:
            return {"past_orders": 0, "on_time_delivery_rate": None, "defect_rate": None}
        return {
            "past_orders": row.past_orders,
            "on_time_delivery_rate": row.on_time_rate,
            "defect_rate": row.defect_rate,
        }

    def create_purchase_order(self, run_id: str, supplier_name: str, material_name: str, quantity: float, unit_price: float) -> dict[str, Any]:
        supplier_id = self._supplier_id(supplier_name)
        material_id = self._material_id(material_name)
        order = PurchaseOrder(
            run_id=run_id,
            supplier_id=supplier_id,
            material_id=material_id,
            quantity=quantity,
            unit_price=unit_price,
            status="created",
        )
        self.session.add(order)
        self.session.commit()
        return {"supplier": supplier_name, "material": material_name, "quantity": quantity, "unit_price": unit_price, "status": "created"}

    def update_work_order(self, run_id: str, status: str, notes: str | None = None) -> None:
        return None

    def record_receipt(self, supplier_name: str, material_name: str, quantity: float) -> None:
        inventory = self.session.query(Inventory).join(Material, Inventory.material_id == Material.id).filter(Material.name == material_name).first()
        if inventory is not None:
            inventory.available_qty += quantity
        supplier = self.session.query(Supplier).filter(Supplier.name == supplier_name).first()
        material = self.session.query(Material).filter(Material.name == material_name).first()
        if supplier is not None and material is not None:
            self.session.add(
                SupplierHistory(
                    supplier_id=supplier.id,
                    material_id=material.id,
                    event_type="received",
                    status="ok",
                    notes=f"Received {quantity} units",
                )
            )
        self.session.commit()

    def record_supplier_history(self, supplier_name: str, material_name: str, event_type: str, run_id: str | None = None, status: str = "ok", notes: str | None = None) -> None:
        supplier = self.session.query(Supplier).filter(Supplier.name == supplier_name).first()
        material = self.session.query(Material).filter(Material.name == material_name).first()
        if supplier is not None:
            self.session.add(
                SupplierHistory(
                    supplier_id=supplier.id,
                    material_id=material.id if material is not None else None,
                    run_id=run_id,
                    event_type=event_type,
                    status=status,
                    notes=notes,
                )
            )
            self.session.commit()
