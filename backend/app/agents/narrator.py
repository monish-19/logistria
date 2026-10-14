from __future__ import annotations

import asyncio
import json
from typing import Any

from ..llm import DEFAULT_LLM


TEMPLATES: dict[tuple[str | None, str | None], str] = {
    ("request", "InventoryAgent"): "The inventory agent started a check for {product_name}.",
    ("response", "InventoryAgent"): "Inventory is available for {product_name}; production can proceed.",
    ("response", "SupplierRankingAgent"): "Supplier ranking completed for {material}; {top_supplier} is ranked first.",
    ("decision", "ProcurementAgent"): "Procurement approved the order automatically; manufacturing can continue.",
    ("escalation", None): "Procurement requires human review before the run can resume.",
    ("alert", None): "An operational alert was raised for the active run.",
    ("manufacturing", None): "Production progress was recorded for {product_name}.",
    ("purchase_order_created", None): "A purchase order was created for {supplier_name} for {material_name}.",
}


def _numeric_payload(payload: dict[str, Any]) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for key, value in payload.items():
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            values[key] = value
        elif isinstance(value, dict):
            nested = _numeric_payload(value)
            if nested:
                values[key] = nested
        elif isinstance(value, list):
            nested_items = [_numeric_payload(item) for item in value if isinstance(item, dict)]
            if any(nested_items):
                values[key] = nested_items
    return values


class Narrator:
    def __init__(self, llm: Any = DEFAULT_LLM) -> None:
        self.llm = llm

    def template(self, event: Any) -> str:
        payload = event.payload or {}
        template = TEMPLATES.get((event.type, event.sender)) or TEMPLATES.get((event.type, None))
        if template is None:
            return "Pipeline update recorded for the active run."
        try:
            return template.format(**payload)
        except (KeyError, IndexError, ValueError):
            return template

    def should_use_llm(self, event: Any) -> bool:
        return (
            event.type in {"alert", "escalation"}
            or event.severity in {"alert", "escalation"}
            or event.sender == "SupplierRankingAgent"
        )

    async def upgrade(self, event: Any) -> str | None:
        if not self.should_use_llm(event):
            return None
        numeric_payload = _numeric_payload(event.payload or {})
        prompt = (
            "Write one concise plain-English operational sentence using only these numeric "
            f"decision values: {json.dumps(numeric_payload, sort_keys=True)}"
        )
        try:
            return await asyncio.to_thread(
                self.llm.call,
                prompt,
                system="You narrate logistics decisions. Return one sentence and no invented facts.",
                model=getattr(self.llm, "narrator_model", None),
                temperature=0,
                template=self.template(event),
            )
        except Exception:
            return None


DEFAULT_NARRATOR = Narrator()
