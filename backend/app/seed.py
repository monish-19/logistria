from __future__ import annotations

from datetime import datetime, timezone

from .models import (
    Base,
    BOMItem,
    Inventory,
    Material,
    OrderHistory,
    Product,
    SessionLocal,
    Supplier,
    SupplierMaterial,
)


def seed_database() -> None:
    engine = SessionLocal.kw.get("bind")
    if engine is not None:
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)

    with SessionLocal() as session:
        existing_products = session.query(Product).count()
        if existing_products:
            return

        materials = [
            Material(name="Steel", sku="STEEL"),
            Material(name="Copper", sku="COPPER"),
            Material(name="Plastic", sku="PLASTIC"),
            Material(name="Resin", sku="RESIN"),
            Material(name="Electronics", sku="ELEC"),
            Material(name="Packaging", sku="PKG"),
            Material(name="Bearing", sku="BRG"),
            Material(name="Coating", sku="COAT"),
        ]
        session.add_all(materials)
        session.flush()

        products = [
            Product(name="Widget Pro", sku="WPRO", reorder_threshold=25),
            Product(name="Sensor Module B3", sku="SENS-B3", reorder_threshold=40),
            Product(name="Precision Gear", sku="GEAR-7", reorder_threshold=30),
            Product(name="Stocked Widget", sku="STOCK-W", reorder_threshold=10),
        ]
        session.add_all(products)
        session.flush()

        now = datetime.now(timezone.utc)
        for product in products:
            for months_ago in range(12, 0, -1):
                month_index = now.year * 12 + now.month - 1 - months_ago
                period = now.replace(
                    year=month_index // 12,
                    month=(month_index % 12) + 1,
                    day=1,
                    hour=0,
                    minute=0,
                    second=0,
                    microsecond=0,
                )
                baseline = float(product.reorder_threshold or 25.0)
                quantity = baseline + float((12 - months_ago) * 0.8) + float((product.id % 3) * 2)
                session.add(OrderHistory(product_id=product.id, period_start=period, quantity=quantity))

        bom_map = {
            "Widget Pro": [("Steel", 1), ("Plastic", 1)],
            "Sensor Module B3": [("Copper", 5), ("Resin", 3), ("Packaging", 2)],
            "Precision Gear": [("Steel", 3), ("Bearing", 2), ("Coating", 1)],
            "Stocked Widget": [("Steel", 1), ("Plastic", 1)],
        }
        for product in products:
            for material_name, quantity in bom_map.get(product.name, []):
                material = session.query(Material).filter(Material.name == material_name).one()
                session.add(BOMItem(product_id=product.id, material_id=material.id, quantity=quantity))

        inventory_rows = [
            ("Steel", 300),
            ("Copper", 12),
            ("Plastic", 80),
            ("Resin", 8),
            ("Electronics", 70),
            ("Packaging", 50),
            ("Bearing", 200),
            ("Coating", 20),
        ]
        for material_name, qty in inventory_rows:
            material = session.query(Material).filter(Material.name == material_name).one()
            session.add(Inventory(material_id=material.id, available_qty=qty, reserved_qty=0))

        suppliers = [
            Supplier(name="Apex Industrial Supplies", is_cold_start=False),
            Supplier(name="Meridian Components Co.", is_cold_start=False),
            Supplier(name="NovaTrade Logistics", is_cold_start=True),
            Supplier(name="SwiftSource Global", is_cold_start=True),
            Supplier(name="NexGen Procure", is_cold_start=True),
        ]
        session.add_all(suppliers)
        session.flush()

        supplier_materials = [
            # Widget Pro: Apex is an established, unambiguous winner.
            ("Apex Industrial Supplies", "Copper", 7.20, 3, 10, 0.90, 0.04, 18),
            ("Meridian Components Co.", "Copper", 7.22, 3, 10, 0.90, 0.04, 18),
            ("NovaTrade Logistics", "Copper", 8.60, 7, 10, 0.82, 0.06, 0),
            ("Apex Industrial Supplies", "Plastic", 2.40, 3, 10, 0.98, 0.01, 24),
            ("Meridian Components Co.", "Plastic", 3.80, 8, 10, 0.78, 0.08, 12),
            ("NovaTrade Logistics", "Plastic", 4.50, 10, 10, 0.75, 0.10, 0),
            # Sensor Module B3: the two established suppliers are intentionally close.
            ("Apex Industrial Supplies", "Resin", 7.80, 5, 10, 0.90, 0.04, 18),
            ("Meridian Components Co.", "Resin", 7.82, 5, 10, 0.90, 0.04, 18),
            ("NovaTrade Logistics", "Resin", 8.60, 7, 10, 0.82, 0.06, 0),
            ("Apex Industrial Supplies", "Packaging", 1.90, 4, 10, 0.90, 0.04, 18),
            ("Meridian Components Co.", "Packaging", 1.91, 4, 10, 0.90, 0.04, 18),
            ("NovaTrade Logistics", "Packaging", 2.40, 7, 10, 0.82, 0.06, 0),
            # Precision Gear: established suppliers are poor; a cold-start supplier wins.
            ("Apex Industrial Supplies", "Steel", 8.80, 12, 10, 0.45, 0.20, 16),
            ("Meridian Components Co.", "Steel", 9.10, 13, 10, 0.42, 0.22, 14),
            ("NexGen Procure", "Steel", 6.40, 4, 10, 0.88, 0.03, 0),
            ("Apex Industrial Supplies", "Bearing", 14.00, 12, 10, 0.45, 0.20, 16),
            ("Meridian Components Co.", "Bearing", 14.40, 13, 10, 0.42, 0.22, 14),
            ("NexGen Procure", "Bearing", 10.50, 4, 10, 0.88, 0.03, 0),
            ("Apex Industrial Supplies", "Coating", 6.50, 12, 10, 0.45, 0.20, 16),
            ("Meridian Components Co.", "Coating", 6.70, 13, 10, 0.42, 0.22, 14),
            ("NexGen Procure", "Coating", 4.20, 4, 10, 0.88, 0.03, 0),
            # Additional material coverage for the no-purchase demo and catalog completeness.
            ("Apex Industrial Supplies", "Electronics", 18.00, 5, 10, 0.94, 0.02, 20),
            ("Meridian Components Co.", "Electronics", 19.50, 7, 10, 0.86, 0.05, 11),
            ("NovaTrade Logistics", "Electronics", 21.00, 9, 10, 0.80, 0.06, 0),
        ]
        for supplier_name, material_name, unit_price, lead_time_days, moq, on_time_rate, defect_rate, past_orders in supplier_materials:
            supplier = session.query(Supplier).filter(Supplier.name == supplier_name).one()
            material = session.query(Material).filter(Material.name == material_name).one()
            session.add(
                SupplierMaterial(
                    supplier_id=supplier.id,
                    material_id=material.id,
                    unit_price=unit_price,
                    lead_time_days=lead_time_days,
                    minimum_order_qty=moq,
                    on_time_rate=on_time_rate,
                    defect_rate=defect_rate,
                    past_orders=past_orders,
                )
            )

        session.commit()
