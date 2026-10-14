from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.agents.logistics import LogisticsAgent
from app.agents.monitor import MonitorAgent
from app.graph import build_phase1_graph
from app.seed import seed_database


def setup_function() -> None:
    seed_database()


def test_full_run_finishes_end_to_end_and_routes_delivery() -> None:
    graph = build_phase1_graph()
    result = graph.create_run("Widget Pro", 5, "2035-01-20", "normal")
    assert result["status"] == "completed"
    assert result["manufacturing"]["status"] == "completed"
    route = result["route"]
    assert route["ordered_stops"]
    assert route["distance_km"] > 0
    assert route["eta_minutes"] > 0
    assert route["eta_minutes"] < 24 * 60
    assert route["total_distance_km"] == route["distance_km"]
    assert any(
        event.sender == "LogisticsAgent"
        and event.type == "response"
        and event.payload.get("status") == "completed"
        for event in graph.bus.list_events(result["run_id"])
    )


def test_monitor_raises_alert_when_run_stalls_or_po_is_late() -> None:
    monitor = MonitorAgent()
    stale = monitor.check_run(
        "run-test",
        "manufacturing",
        last_event_ts=datetime.now(timezone.utc) - timedelta(minutes=5),
        route={"eta_minutes": 120},
        purchase_orders=[{"status": "late"}],
    )
    assert any(alert["type"] in {"stalled", "late_delivery", "late_purchase_order"} for alert in stale)


def test_logistics_route_orders_stops_and_reports_cost() -> None:
    route = LogisticsAgent(osrm_url="").optimize_delivery("run-route", "Widget Pro", 15)
    assert route["ordered_stops"][0] == "Warehouse"
    assert len(route["ordered_stops"]) >= 2
    assert route["distance_km"] > 0
    assert route["delivery_cost"] > 0


def test_logistics_uses_haversine_and_geometry_fallback() -> None:
    route = LogisticsAgent(osrm_url="").optimize_delivery(
        "run-haversine",
        "Widget Pro",
        1,
        stops=[
            {"name": "A", "lat": 0.0, "lon": 1.0},
            {"name": "B", "lat": 0.0, "lon": 2.0},
        ],
    )

    assert route["method"] == "ortools+haversine"
    assert route["distance_km"] == route["total_distance_km"]
    assert route["distance_km"] > 0
    assert route["geometry"]["type"] == "LineString"
    assert route["stops"][1]["lat"] == 0.0


def test_logistics_uses_mocked_osrm(monkeypatch) -> None:
    class Response:
        def __init__(self, payload):
            self.payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self.payload

    responses = iter([
        Response({"distances": [[0, 1000, 2500], [1000, 0, 1500], [2500, 1500, 0]]}),
        Response({"routes": [{"geometry": {"type": "LineString", "coordinates": [[0, 0], [1, 2]]}}]}),
    ])
    monkeypatch.setattr("app.agents.logistics.httpx.get", lambda *args, **kwargs: next(responses))

    route = LogisticsAgent(osrm_url="http://osrm.test").optimize_delivery(
        "run-osrm",
        "Widget Pro",
        1,
        stops=[
            {"name": "A", "lat": 1.0, "lon": 1.0},
            {"name": "B", "lat": 2.0, "lon": 2.0},
        ],
    )

    assert route["method"] == "ortools+osrm"
    assert route["distance_km"] == 2.5
    assert route["geometry"]["coordinates"] == [[0, 0], [1, 2]]


def test_logistics_falls_back_when_osrm_fails(monkeypatch) -> None:
    def fail(*args, **kwargs):
        raise RuntimeError("network unavailable")

    monkeypatch.setattr("app.agents.logistics.httpx.get", fail)
    route = LogisticsAgent(osrm_url="http://osrm.test").optimize_delivery(
        "run-osrm-failure",
        "Widget Pro",
        1,
        stops=[{"name": "A", "lat": 0.0, "lon": 1.0}],
    )

    assert route["method"] == "ortools+haversine"
    assert route["geometry"]["coordinates"] == [[80.2707, 13.0827], [1.0, 0.0]]
