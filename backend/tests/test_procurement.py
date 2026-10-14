from __future__ import annotations

from app.agents.procurement import ProcurementAgent
from app.agents.ranking import SupplierRankingAgent


def test_procurement_uses_minimum_confidence_and_rejects_zero_confidence_material() -> None:
    decision = ProcurementAgent(adapter=None).decide(
        [
            {"material": "Steel", "top_pick": "Apex", "confidence": 0.93},
            {"material": "Copper", "top_pick": None, "confidence": 0.0},
        ],
        order_value=100.0,
        run_id="run-mixed-confidence",
    )

    assert decision["status"] == "pending_human_review"
    assert decision["confidence"] == 0.0


def test_ranking_forces_review_for_single_supplier_and_reduced_constraint_fit() -> None:
    class SingleSupplierAdapter:
        def list_suppliers(self, material_name):
            return [{
                "name": "Only Supplier",
                "unit_price": 10.0,
                "lead_time_days": 2,
                "minimum_order_qty": 1,
                "performance_history": {"past_orders": 20, "on_time_delivery_rate": 0.98, "defect_rate": 0.01},
            }]

    result = SupplierRankingAgent(SingleSupplierAdapter()).rank_material("Steel", 10)

    assert result["requires_human_review"] is True
    assert result["constraint_fit"] == 0.5


def test_ranking_forces_review_when_price_exceeds_historical_average() -> None:
    class HistoricalPriceAdapter:
        def list_suppliers(self, material_name):
            return [
                {
                    "name": "Expensive Supplier",
                    "unit_price": 13.0,
                    "historical_average_unit_price": 10.0,
                    "lead_time_days": 2,
                    "minimum_order_qty": 1,
                    "performance_history": {"past_orders": 20, "on_time_delivery_rate": 0.98, "defect_rate": 0.01},
                },
                {
                    "name": "Alternative Supplier",
                    "unit_price": 20.0,
                    "lead_time_days": 20,
                    "minimum_order_qty": 1,
                    "performance_history": {"past_orders": 1, "on_time_delivery_rate": 0.5, "defect_rate": 0.2},
                },
            ]

    result = SupplierRankingAgent(HistoricalPriceAdapter()).rank_material("Steel", 10)

    assert result["top_pick"] == "Expensive Supplier"
    assert result["requires_human_review"] is True
    assert result["constraint_fit"] == 0.5


def test_ranking_forces_review_when_supplier_data_is_missing() -> None:
    class IncompleteSupplierAdapter:
        def list_suppliers(self, material_name):
            return [{
                "name": "Incomplete Supplier",
                "unit_price": 10.0,
                "lead_time_days": 2,
                "minimum_order_qty": 1,
            }]

    result = SupplierRankingAgent(IncompleteSupplierAdapter()).rank_material("Steel", 10)

    assert result["top_pick"] == "Incomplete Supplier"
    assert result["requires_human_review"] is True
    assert result["constraint_fit"] == 0.5


def test_graph_values_shortages_using_selected_supplier_prices(monkeypatch) -> None:
    from app.adapters.mock import MockAdapter
    from app.graph import build_phase1_graph
    from app.seed import seed_database

    seed_database()
    captured = {}

    def capture_decision(self, ranking_results, order_value, run_id):
        captured["rankings"] = ranking_results
        captured["order_value"] = order_value
        return {
            "status": "pending_human_review",
            "needs_approval": True,
            "decision": "pending_human_review",
            "order_value": order_value,
            "confidence": 0.0,
        }

    monkeypatch.setattr("app.agents.procurement.ProcurementAgent.decide", capture_decision)
    graph = build_phase1_graph(adapter=MockAdapter())
    run = graph.create_run("Sensor Module B3", 50, "2035-01-10", "high")

    expected = 0.0
    adapter = graph.adapter
    for ranking in captured["rankings"]:
        if ranking["top_pick"]:
            supplier = next(
                supplier
                for supplier in adapter.list_suppliers(ranking["material"])
                if supplier["name"] == ranking["top_pick"]
            )
            shortage = next(item for item in run["shortages"] if item["material"] == ranking["material"])
            expected += supplier["unit_price"] * shortage["needed"]

    assert captured["order_value"] == expected


def test_monitor_receives_real_purchase_orders(monkeypatch) -> None:
    from app.graph import build_phase1_graph
    from app.models import PurchaseOrder, SessionLocal
    from app.seed import seed_database

    seed_database()
    graph = build_phase1_graph()
    run = graph.create_run("Sensor Module B3", 50, "2035-01-10", "high")
    assert run["status"] == "pending_human_review"

    session = SessionLocal()
    try:
        # The graph's normal auto-approval path creates these records; this
        # regression verifies finalization forwards persisted PO records.
        from app.models import ProductionRun, Supplier, Material
        production_run = session.query(ProductionRun).filter_by(run_id=run["run_id"]).one()
        supplier = session.query(Supplier).first()
        material = session.query(Material).filter_by(name="Copper").one()
        session.add(PurchaseOrder(
            run_id=production_run.run_id,
            supplier_id=supplier.id,
            material_id=material.id,
            quantity=10,
            unit_price=1,
            status="late",
        ))
        session.commit()
    finally:
        session.close()

    captured = {}

    def capture(self, run_id, status, **kwargs):
        captured["purchase_orders"] = kwargs["purchase_orders"]
        return []

    monkeypatch.setattr("app.agents.monitor.MonitorAgent.raise_alerts_for_run", capture)
    graph._finalize_run(run["run_id"], "Sensor Module B3", 50)

    assert captured["purchase_orders"][0]["status"] == "late"
