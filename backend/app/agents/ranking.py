from __future__ import annotations

import math
from datetime import date
from typing import Any

from ..bus import Event, EventBus


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


class SupplierRankingAgent:
    def __init__(self, adapter: Any, bus: EventBus | None = None) -> None:
        self.adapter = adapter
        self.bus = bus

    def _days_to_due(self, due_date: str | None) -> int | None:
        if due_date is None:
            return None
        try:
            due = date.fromisoformat(due_date)
        except ValueError:
            return None
        today = date.today()
        delta = (due - today).days
        return max(delta, 1)

    def rank_material(self, material_name: str, required_qty: float, due_date: str | None = None, urgency: str = "normal") -> dict[str, Any]:
        suppliers = self.adapter.list_suppliers(material_name)
        if not suppliers:
            return {
                "material": material_name,
                "ranked_suppliers": [],
                "top_pick": None,
                "confidence": 0.0,
                "constraint_fit": 0.5,
                "requires_human_review": True,
                "cold_start": False,
                "reasoning": "No suppliers available.",
            }

        due_lead_days = self._days_to_due(due_date)
        eligible: list[dict[str, Any]] = []
        portfolio_on_time = 0.85
        portfolio_defect = 0.04

        for supplier in suppliers:
            required_fields = ("name", "unit_price", "lead_time_days", "minimum_order_qty")
            supplier_data_missing = any(field not in supplier or supplier[field] is None for field in required_fields)
            if supplier_data_missing:
                continue
            history = supplier.get("performance_history", {})
            on_time_rate = history.get("on_time_delivery_rate")
            defect_rate = history.get("defect_rate")
            past_orders = int(history.get("past_orders") or 0)
            moq = supplier.get("minimum_order_qty", 0)
            lead_days = int(supplier.get("lead_time_days", 0))

            if moq > required_qty * 3:
                continue
            if due_lead_days is not None and lead_days > due_lead_days:
                continue

            if on_time_rate is None:
                on_time_rate = portfolio_on_time
            if defect_rate is None:
                defect_rate = portfolio_defect

            price_value = float(supplier.get("unit_price", 0.0))
            price_norm = 1.0
            lead_norm = 1.0
            prices = [float(s["unit_price"]) for s in suppliers]
            lead_vals = [float(s["lead_time_days"]) for s in suppliers]
            if len(prices) > 1:
                min_price = min(prices)
                max_price = max(prices)
                price_norm = 1.0 if max_price == min_price else (max_price - price_value) / (max_price - min_price)
                min_lead = min(lead_vals)
                max_lead = max(lead_vals)
                lead_norm = 1.0 if max_lead == min_lead else (max_lead - lead_days) / (max_lead - min_lead)

            k = 5
            on_time_hat = (past_orders * on_time_rate + k * portfolio_on_time) / (past_orders + k)
            defect_hat = (past_orders * defect_rate + k * portfolio_defect) / (past_orders + k)
            quality_score = max(0.0, 1.0 - defect_hat)
            moq_fit = 1.0 if moq <= required_qty else max(0.0, 1.0 - ((moq - required_qty) / max(required_qty, 1)))

            if urgency == "high":
                weights = {"price": 0.20, "lead": 0.35, "reliability": 0.25, "quality": 0.15, "moq_fit": 0.05}
            else:
                weights = {"price": 0.30, "lead": 0.20, "reliability": 0.25, "quality": 0.20, "moq_fit": 0.05}

            n_total = len(suppliers)
            bonus = 0.0
            cold_start = past_orders == 0
            if cold_start:
                bonus = min(0.12, 0.10 * math.sqrt(math.log(n_total + 1) / (past_orders + 1))) * 0.5

            raw_score = (
                price_norm * weights["price"]
                + lead_norm * weights["lead"]
                + on_time_hat * weights["reliability"]
                + quality_score * weights["quality"]
                + moq_fit * weights["moq_fit"]
            )
            score = min(1.0, raw_score + bonus)
            eligible.append({
                "name": supplier["name"],
                "price_score": price_norm,
                "lead_score": lead_norm,
                "reliability": on_time_hat,
                "quality_score": quality_score,
                "moq_fit": moq_fit,
                "score": score,
                "past_orders": past_orders,
                "cold_start": cold_start,
                "bonus": bonus,
                "unit_price": supplier["unit_price"],
                "lead_time_days": supplier["lead_time_days"],
                "minimum_order_qty": supplier["minimum_order_qty"],
                "supplier_data_missing": supplier_data_missing or "performance_history" not in supplier or not isinstance(history, dict),
                "historical_average_unit_price": next(
                    (
                        supplier.get(field, history.get(field))
                        for field in (
                            "historical_average_unit_price",
                            "historical_average_price",
                            "average_unit_price",
                            "avg_unit_price",
                        )
                        if supplier.get(field) is not None
                    ),
                    None,
                ),
            })

        if not eligible:
            return {
                "material": material_name,
                "ranked_suppliers": [],
                "top_pick": None,
                "confidence": 0.0,
                "constraint_fit": 0.5,
                "requires_human_review": True,
                "cold_start": False,
                "reasoning": "No eligible supplier met hard constraints.",
            }

        eligible.sort(key=lambda item: item["score"], reverse=True)
        top = eligible[0]
        second = eligible[1]["score"] if len(eligible) > 1 else 0.0
        margin = clamp((top["score"] - second) / 0.15, 0.0, 1.0)
        data_sufficiency = top["past_orders"] / (top["past_orders"] + 5)
        constraint_fit = 1.0
        review_reasons: list[str] = []
        if len(eligible) == 1:
            review_reasons.append("only one eligible supplier")

        historical_average = top.get("historical_average_unit_price")
        if historical_average is not None and float(historical_average) > 0:
            if float(top["unit_price"]) > float(historical_average) * 1.25:
                review_reasons.append("price exceeds historical average")

        if top.get("supplier_data_missing"):
            review_reasons.append("supplier data is missing")

        if review_reasons:
            constraint_fit = 0.5
        confidence = 0.5 * margin + 0.3 * data_sufficiency + 0.2 * constraint_fit
        confidence = round(clamp(confidence, 0.0, 1.0), 3)

        ranked_names = [item["name"] for item in eligible]
        reasoning = (
            f"{top['name']} ranked highest because its weighted score was best across price, lead time, reliability, quality, and MOQ fit. "
            f"Cold-start bonus={'yes' if top['cold_start'] else 'no'}; confidence={confidence:.2f}."
        )

        result = {
            "material": material_name,
            "ranked_suppliers": ranked_names,
            "top_pick": top["name"],
            "confidence": confidence,
            "constraint_fit": constraint_fit,
            "requires_human_review": bool(review_reasons),
            "review_reasons": review_reasons,
            "cold_start": top["cold_start"],
            "reasoning": reasoning,
            "breakdown": [
                {
                    "name": item["name"],
                    "score": item["score"],
                    "price_score": item["price_score"],
                    "lead_score": item["lead_score"],
                    "reliability": item["reliability"],
                    "quality_score": item["quality_score"],
                    "moq_fit": item["moq_fit"],
                    "cold_start": item["cold_start"],
                    "bonus": item["bonus"],
                }
                for item in eligible
            ],
        }

        if self.bus:
            self.bus.emit(Event(
                run_id=None,
                sender="SupplierRankingAgent",
                receiver="ProcurementAgent",
                type="response",
                payload={"material": material_name, "result": result},
                human_text=f"Supplier ranking for {material_name} completed with {top['name']} ranked first.",
                severity="info",
            ))
        return result
