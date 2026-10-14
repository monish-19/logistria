import os

import pytest

from app.adapters.erpnext import ERPNextAdapter


pytestmark = pytest.mark.integration


@pytest.fixture
def erpnext() -> ERPNextAdapter:
    url = os.getenv("ERPNEXT_URL")
    if not url:
        pytest.skip("ERPNEXT_URL is not configured")
    return ERPNextAdapter(
        base_url=url,
        api_key=os.getenv("ERPNEXT_API_KEY"),
        api_secret=os.getenv("ERPNEXT_API_SECRET"),
    )


def test_seeded_catalog_is_available(erpnext: ERPNextAdapter) -> None:
    bom = erpnext.get_bom("Widget Pro")
    assert {row["material"] for row in bom} >= {"Steel", "Copper"}
    assert erpnext.get_stock("Steel") >= 0
    assert erpnext.list_suppliers("Copper")


def test_erpnext_purchase_and_receipt_flow(erpnext: ERPNextAdapter) -> None:
    order = erpnext.create_purchase_order("integration-run", "Apex Industrial Supplies", "Copper", 4, 8.1)
    assert order.get("status") in {"created", "submitted"}
    erpnext.record_receipt("Apex Industrial Supplies", "Copper", 4)
