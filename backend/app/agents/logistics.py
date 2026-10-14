from __future__ import annotations

import math
import os
from typing import Any

import httpx
from ortools.constraint_solver import pywrapcp, routing_enums_pb2

from ..config import DEPOT_LAT, DEPOT_LON


class LogisticsAgent:
    def __init__(
        self,
        adapter: Any | None = None,
        bus: Any | None = None,
        osrm_url: str | None = None,
    ) -> None:
        self.adapter = adapter
        self.bus = bus
        configured_url = osrm_url if osrm_url is not None else (os.getenv("OSRM_URL") or "https://router.project-osrm.org")
        self.osrm_url = configured_url.rstrip("/")

    @staticmethod
    def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        radius_km = 6371.0
        p1 = math.radians(lat1)
        p2 = math.radians(lat2)
        dlat = math.radians(lat2 - lat1)
        dlon = math.radians(lon2 - lon1)
        a = math.sin(dlat / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlon / 2) ** 2
        return 2 * radius_km * math.asin(math.sqrt(a))

    @staticmethod
    def _empty_matrix(size: int) -> list[list[float]]:
        return [[0.0 for _ in range(size)] for _ in range(size)]

    def _haversine_matrix(self, points: list[dict[str, Any]]) -> list[list[float]]:
        return [
            [
                self._haversine_km(a["lat"], a["lon"], b["lat"], b["lon"])
                for b in points
            ]
            for a in points
        ]

    def _osrm_matrix(self, points: list[dict[str, Any]]) -> tuple[list[list[float]], dict[str, Any] | None] | None:
        if not self.osrm_url:
            return None
        coordinates = ";".join(f"{point['lon']},{point['lat']}" for point in points)
        try:
            table = httpx.get(
                f"{self.osrm_url}/table/v1/driving/{coordinates}",
                params={"annotations": "distance,duration"},
                timeout=5.0,
            )
            table.raise_for_status()
            body = table.json()
            distances = body.get("distances")
            if not distances:
                return None
            matrix = [[float(value) / 1000.0 for value in row] for row in distances]

            route = httpx.get(
                f"{self.osrm_url}/route/v1/driving/{coordinates}",
                params={"overview": "full", "geometries": "geojson"},
                timeout=5.0,
            )
            route.raise_for_status()
            geometry = route.json().get("routes", [{}])[0].get("geometry")
            return matrix, geometry
        except Exception:
            return None

    @staticmethod
    def _straight_geometry(points: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "type": "LineString",
            "coordinates": [[point["lon"], point["lat"]] for point in points],
        }

    def _solve_order(
        self,
        matrix: list[list[float]],
        stops: list[dict[str, Any]],
        vehicles: int,
        capacities: list[float],
    ) -> list[int]:
        manager = pywrapcp.RoutingIndexManager(len(matrix), vehicles, 0)
        routing = pywrapcp.RoutingModel(manager)
        distance_callback = routing.RegisterTransitCallback(
            lambda from_index, to_index: int(
                round(matrix[manager.IndexToNode(from_index)][manager.IndexToNode(to_index)] * 1000)
            )
        )
        routing.SetArcCostEvaluatorOfAllVehicles(distance_callback)

        demands = [0] + [float(stop.get("demand", 1.0)) for stop in stops]
        demand_callback = routing.RegisterUnaryTransitCallback(
            lambda index: int(round(demands[manager.IndexToNode(index)]))
        )
        routing.AddDimensionWithVehicleCapacity(
            demand_callback,
            0,
            [int(math.ceil(capacity)) for capacity in capacities],
            True,
            "Capacity",
        )

        time_windows = [None] + [stop.get("time_window") for stop in stops]
        if any(window for window in time_windows[1:]):
            routing.AddDimension(
                distance_callback,
                0,
                int(max(1, max(max(window or (0, 0)) for window in time_windows) * 1000)),
                False,
                "Time",
            )
            time_dimension = routing.GetDimensionOrDie("Time")
            for node, window in enumerate(time_windows):
                if window:
                    index = manager.NodeToIndex(node)
                    time_dimension.CumulVar(index).SetRange(int(window[0] * 1000), int(window[1] * 1000))

        params = pywrapcp.DefaultRoutingSearchParameters()
        params.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
        params.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
        params.time_limit.seconds = 1
        solution = routing.SolveWithParameters(params)
        if solution is None:
            return list(range(len(matrix)))

        ordered: list[int] = [0]
        for vehicle in range(vehicles):
            index = routing.Start(vehicle)
            vehicle_nodes: list[int] = []
            while not routing.IsEnd(index):
                node = manager.IndexToNode(index)
                if node != 0:
                    vehicle_nodes.append(node)
                index = solution.Value(routing.NextVar(index))
            if vehicle_nodes:
                ordered.extend(vehicle_nodes)
        return ordered

    def optimize_delivery(
        self,
        run_id: str,
        product_name: str,
        quantity: float,
        stops: list[dict[str, Any]] | None = None,
        *,
        vehicles: int = 1,
        vehicle_capacities: list[float] | None = None,
    ) -> dict[str, Any]:
        warehouse = {"name": "Warehouse", "lat": DEPOT_LAT, "lon": DEPOT_LON}
        default_stops = [
            {"name": "Customer A", "lat": 13.1143, "lon": 80.1548},
            {"name": "Customer B", "lat": 13.0067, "lon": 80.2206},
            {"name": "Customer C", "lat": 12.9249, "lon": 80.1000},
        ]
        route_stops = stops or default_stops
        vehicles = max(1, min(3, vehicles))
        points = [warehouse, *route_stops]
        haversine_matrix = self._haversine_matrix(points)
        osrm_result = self._osrm_matrix(points)
        if osrm_result is None:
            matrix = haversine_matrix
            method = "ortools+haversine"
            geometry = None
        else:
            matrix, geometry = osrm_result
            method = "ortools+osrm"

        total_demand = sum(float(stop.get("demand", 1.0)) for stop in route_stops)
        capacities = vehicle_capacities or [max(1.0, total_demand)] * vehicles
        if len(capacities) != vehicles:
            capacities = [max(1.0, total_demand)] * vehicles
        order = self._solve_order(matrix, route_stops, vehicles, capacities)
        ordered_points = [points[index] for index in order]
        legs: list[dict[str, Any]] = []
        cumulative_km = 0.0
        for previous, current in zip(order, order[1:]):
            leg_km = matrix[previous][current]
            cumulative_km += leg_km
            legs.append({
                "from": points[previous]["name"],
                "to": points[current]["name"],
                "distance_km": round(leg_km, 2),
                "eta_minutes": round(cumulative_km / 40.0 * 60.0, 2),
            })

        distance_km = sum(leg["distance_km"] for leg in legs)
        stop_payload = [
            {
                "name": point["name"],
                "lat": point["lat"],
                "lon": point["lon"],
                "eta_minutes": 0.0 if index == 0 else legs[index - 1]["eta_minutes"],
            }
            for index, point in enumerate(ordered_points)
        ]
        geometry = geometry or self._straight_geometry(ordered_points)
        return {
            "run_id": run_id,
            "product_name": product_name,
            "ordered_stops": [stop["name"] for stop in ordered_points],
            "stops": stop_payload,
            "legs": legs,
            "distance_km": round(distance_km, 2),
            "total_distance_km": round(distance_km, 2),
            "eta_minutes": round(max(35.0, cumulative_km / 40.0 * 60.0), 2),
            "delivery_cost": round(max(80.0, quantity * 0.35 + distance_km * 1.5), 2),
            "method": method,
            "geometry": geometry,
        }
