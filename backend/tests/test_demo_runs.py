from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from app.models import Material, SessionLocal, SupplierMaterial
from app.seed import seed_database


def setup_function() -> None:
    seed_database()


def test_seeded_demo_products_cover_all_four_procurement_paths(monkeypatch) -> None:
    monkeypatch.setenv("ALLOW_INSECURE_DEV", "true")
    client = TestClient(app)
    demos = [
        ("Widget Pro", 100, "completed"),
        ("Sensor Module B3", 50, "pending_human_review"),
        ("Precision Gear", 50, "pending_human_review"),
        ("Stocked Widget", 10, "completed"),
    ]

    for product_name, quantity, expected_status in demos:
        response = client.post(
            "/api/runs",
            headers={"X-Admin-Key": "demo-test"},
            json={"product_name": product_name, "quantity": quantity},
        )
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["status"] == expected_status
        if product_name == "Widget Pro":
            assert payload["decision"]["status"] == "auto_approved"
            assert payload["decision"]["confidence"] >= 0.8
            assert payload["decision"]["order_value"] < 5000


def test_every_seeded_material_has_three_suppliers_with_established_and_new_mix() -> None:
    session = SessionLocal()
    try:
        materials = session.query(Material).all()
        for material in materials:
            rows = (
                session.query(SupplierMaterial)
                .filter(SupplierMaterial.material_id == material.id)
                .all()
            )
            assert len(rows) >= 3, material.name
            assert all(row.unit_price > 0 and row.lead_time_days > 0 and row.minimum_order_qty > 0 for row in rows)
            assert any(row.past_orders >= 10 for row in rows)
            assert any(row.past_orders == 0 for row in rows)
    finally:
        session.close()
