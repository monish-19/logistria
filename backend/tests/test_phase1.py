from __future__ import annotations

from app.adapters.mock import MockAdapter
from app.agents.ranking import SupplierRankingAgent
from app.graph import build_phase1_graph
from app.seed import seed_database


def setup_function() -> None:
    seed_database()


def test_supplier_ranking_confidence_stays_below_threshold_for_ambiguous_case() -> None:
    class AmbiguousAdapter:
        def list_suppliers(self, material_name):
            return [
                {
                    "name": "Apex Industrial Supplies",
                    "unit_price": 6.10,
                    "lead_time_days": 9,
                    "minimum_order_qty": 50,
                    "performance_history": {"past_orders": 9, "on_time_delivery_rate": 0.82, "defect_rate": 0.03},
                },
                {
                    "name": "Meridian Components Co.",
                    "unit_price": 6.05,
                    "lead_time_days": 9,
                    "minimum_order_qty": 100,
                    "performance_history": {"past_orders": 8, "on_time_delivery_rate": 0.82, "defect_rate": 0.035},
                },
                {
                    "name": "NovaTrade Logistics",
                    "unit_price": 5.80,
                    "lead_time_days": 11,
                    "minimum_order_qty": 200,
                    "performance_history": {"past_orders": 0, "on_time_delivery_rate": None, "defect_rate": None},
                },
                {
                    "name": "SwiftSource Global",
                    "unit_price": 7.20,
                    "lead_time_days": 8,
                    "minimum_order_qty": 50,
                    "performance_history": {"past_orders": 0, "on_time_delivery_rate": None, "defect_rate": None},
                },
            ]

    ranking = SupplierRankingAgent(AmbiguousAdapter()).rank_material("Copper", 250, "2035-01-01", "normal")
    assert ranking["top_pick"] in {"Apex Industrial Supplies", "Meridian Components Co."}
    assert ranking["confidence"] < 0.8


def test_cold_start_supplier_can_win_when_established_suppliers_are_poor() -> None:
    class ColdStartAdapter:
        def list_suppliers(self, material_name):
            return [
                {
                    "name": "OldGuard Manufacturing",
                    "unit_price": 12.50,
                    "lead_time_days": 18,
                    "minimum_order_qty": 100,
                    "performance_history": {"past_orders": 14, "on_time_delivery_rate": 0.58, "defect_rate": 0.18},
                },
                {
                    "name": "Legacy Fulfillment Corp.",
                    "unit_price": 11.00,
                    "lead_time_days": 16,
                    "minimum_order_qty": 150,
                    "performance_history": {"past_orders": 12, "on_time_delivery_rate": 0.62, "defect_rate": 0.15},
                },
                {
                    "name": "NexGen Procure",
                    "unit_price": 5.00,
                    "lead_time_days": 5,
                    "minimum_order_qty": 250,
                    "performance_history": {"past_orders": 0, "on_time_delivery_rate": None, "defect_rate": None},
                },
            ]

    ranking = SupplierRankingAgent(ColdStartAdapter()).rank_material("Resin", 250, "2035-01-01", "high")
    assert ranking["top_pick"] == "NexGen Procure"
    assert ranking["cold_start"] is True


def test_inventory_run_with_enough_stock_routes_to_manufacturing() -> None:
    result = build_phase1_graph(adapter=MockAdapter()).create_run("Widget Pro", 5, "2035-01-20", "normal")
    assert result["status"] == "completed"
    assert result["approval_required"] is False


def test_pending_review_can_be_approved_and_resumed(monkeypatch) -> None:
    import app.agents.procurement as procurement_mod

    monkeypatch.setattr(procurement_mod, "AUTO_LIMIT", 1.0)
    graph = build_phase1_graph(adapter=MockAdapter())
    result = graph.create_run("Sensor Module B3", 50, "2035-01-10", "high")
    assert result["status"] == "pending_human_review"
    assert result["approval_required"] is True

    approved = graph.approve_run(result["run_id"], approved=True)
    assert approved["status"] == "completed"
    assert approved["approved"] is True
