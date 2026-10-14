from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

import numpy as np
from statsmodels.tsa.holtwinters import ExponentialSmoothing

from .models import OrderHistory, Product, SessionLocal


def _moving_average(values: list[float], periods: int) -> list[float]:
    window = values[-min(3, len(values)):]
    average = sum(window) / len(window)
    return [average for _ in range(periods)]


def forecast_demand(product: str, horizon_days: int) -> dict[str, Any]:
    periods = max(1, math.ceil(horizon_days / 30))
    with SessionLocal() as session:
        row = session.query(Product).filter(Product.name.ilike(product.strip())).first()
        if row is None:
            raise ValueError(f"Unknown product: {product}")
        history_rows = (
            session.query(OrderHistory)
            .filter(OrderHistory.product_id == row.id)
            .order_by(OrderHistory.period_start.asc())
            .all()
        )
        values = [float(item.quantity) for item in history_rows]

    if not values:
        raise ValueError(f"No order history for product: {row.name}")

    baseline = sum(values[-min(3, len(values)):]) / min(3, len(values))
    if len(values) < 6:
        predicted = _moving_average(values, periods)
        confidence = max(0.35, min(0.75, 1.0 - (1.0 / len(values))))
    else:
        try:
            model = ExponentialSmoothing(values, trend="add", initialization_method="estimated").fit(
                optimized=True
            )
            predicted = [max(0.0, float(item)) for item in model.forecast(periods)]
            confidence = 0.8
        except (ValueError, np.linalg.LinAlgError):
            predicted = _moving_average(values, periods)
            confidence = 0.5

    residual_scale = max(1.0, float(np.std(values[-min(6, len(values)):])) * 1.96)
    lower = [round(max(0.0, value - residual_scale), 2) for value in predicted]
    upper = [round(value + residual_scale, 2) for value in predicted]
    return {
        "product_name": row.name,
        "horizon_days": horizon_days,
        "forecast": [round(value, 2) for value in predicted],
        "baseline": round(baseline, 2),
        "confidence": round(confidence, 2),
        "confidence_interval": {"lower": lower, "upper": upper},
        "history_points": len(values),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
