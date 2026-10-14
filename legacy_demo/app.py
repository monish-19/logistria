"""
LOGISTRIA - Flask Web Backend
Wraps the existing two-agent pipeline and exposes it over HTTP.

Setup & run:
    pip install flask groq
    python app.py

Then open http://localhost:5000 in your browser.
GROQ_API_KEY must be set in the environment (or hardcoded in logistria_demo.py).
"""

import sys
import json
import uuid
import threading
from datetime import datetime, timezone
from flask import Flask, jsonify, render_template, request

# ---------------------------------------------------------------------------
# Import all agent logic from the existing demo script (no duplication)
# ---------------------------------------------------------------------------
sys.path.insert(0, ".")
from logistria_demo import (
    configure_groq,
    agent1_supplier_ranking,
    agent2_procurement_orchestrator,
)

# ---------------------------------------------------------------------------
# Scenario datasets  (product + suppliers for each demo scenario)
# ---------------------------------------------------------------------------

SCENARIOS = {
    # ── Scenario 1: Clear Auto-Approve ──────────────────────────────────
    # One supplier dominates on every dimension → model should pick it with
    # high confidence (>=0.8).  Order value stays well under $5 k.
    1: {
        "product": {
            "name": "Component Alpha-7",
            "current_stock": 12,
            "reorder_threshold": 150,
            "quantity_needed": 180,
        },
        "suppliers": [
            {
                "name": "Pinnacle Parts Ltd",
                "unit_price": 6.50,
                "lead_time_days": 4,
                "minimum_order_qty": 50,
                "performance_history": {
                    "past_orders": 18,
                    "on_time_delivery_rate": 0.98,
                    "defect_rate": 0.007,
                },
            },
            {
                "name": "Reliable Supplies Co.",
                "unit_price": 7.10,
                "lead_time_days": 11,
                "minimum_order_qty": 100,
                "performance_history": {
                    "past_orders": 9,
                    "on_time_delivery_rate": 0.81,
                    "defect_rate": 0.06,
                },
            },
            {
                "name": "FastShip Traders",
                "unit_price": 8.20,
                "lead_time_days": 7,
                "minimum_order_qty": 100,
                "performance_history": {
                    "past_orders": 0,
                    "on_time_delivery_rate": None,
                    "defect_rate": None,
                },
            },
            {
                "name": "BudgetSource Inc.",
                "unit_price": 9.50,
                "lead_time_days": 6,
                "minimum_order_qty": 200,
                "performance_history": {
                    "past_orders": 0,
                    "on_time_delivery_rate": None,
                    "defect_rate": None,
                },
            },
        ],
    },

    # ── Scenario 2: Escalated for Review ────────────────────────────────
    # Both established suppliers are IDENTICAL on the two primary metrics
    # (on_time_delivery_rate 0.82, lead_time 9d) and nearly identical on
    # price ($6.10 vs $6.05). The model cannot confidently pick one over
    # the other → confidence should drop below 0.80 → pending_human_approval.
    2: {
        "product": {
            "name": "Product X",
            "current_stock": 40,
            "reorder_threshold": 100,
            "quantity_needed": 200,
            "scenario_hint": (
                "IMPORTANT CALIBRATION NOTE: The two established suppliers in this dataset "
                "have almost identical performance metrics (same on_time_delivery_rate of 0.82, "
                "same lead time, prices within $0.10 of each other). When metrics are this close, "
                "a well-calibrated ranking agent cannot be highly confident. Your confidence score "
                "MUST reflect this uncertainty. If the difference between the top two candidates is "
                "less than 5 percentage points on the primary metrics, confidence MUST be set below "
                "0.80. Do NOT round up to a high confidence value when the data is ambiguous."
            ),
        },
        "suppliers": [
            {
                "name": "Apex Industrial Supplies",
                "unit_price": 6.10,
                "lead_time_days": 9,
                "minimum_order_qty": 50,
                "performance_history": {
                    "past_orders": 9,
                    "on_time_delivery_rate": 0.82,
                    "defect_rate": 0.030,
                },
            },
            {
                "name": "Meridian Components Co.",
                "unit_price": 6.05,
                "lead_time_days": 9,
                "minimum_order_qty": 100,
                "performance_history": {
                    "past_orders": 8,
                    "on_time_delivery_rate": 0.82,
                    "defect_rate": 0.035,
                },
            },
            {
                "name": "NovaTrade Logistics",
                "unit_price": 5.80,
                "lead_time_days": 11,
                "minimum_order_qty": 200,
                "performance_history": {
                    "past_orders": 0,
                    "on_time_delivery_rate": None,
                    "defect_rate": None,
                },
            },
            {
                "name": "SwiftSource Global",
                "unit_price": 7.20,
                "lead_time_days": 8,
                "minimum_order_qty": 50,
                "performance_history": {
                    "past_orders": 0,
                    "on_time_delivery_rate": None,
                    "defect_rate": None,
                },
            },
        ],
    },

    # ── Scenario 3: Cold-Start Supplier Wins ────────────────────────────
    # Established suppliers are catastrophically unreliable (on-time
    # 0.58/0.62, defect 0.18/0.15, very expensive, very slow).
    # NexGen Procure (0 orders) wins outright: lowest price by 2x,
    # fastest lead time, MOQ exactly matches the quantity needed.
    # Reasoning MUST reference NexGen's lack of history + cold-start logic.
    3: {
        "product": {
            "name": "Sensor Module B3",
            "current_stock": 22,
            "reorder_threshold": 120,
            "quantity_needed": 250,
            "scenario_hint": (
                "IMPORTANT WEIGHTING NOTE: The established suppliers in this dataset have "
                "catastrophically poor track records (on_time_delivery_rate below 0.65, "
                "defect_rate above 0.15). Per the cold-start rules, when established suppliers "
                "perform this poorly, a new supplier with a substantially better price, "
                "faster lead time, and MOQ that closely matches the order quantity SHOULD "
                "rank above them. NexGen Procure has the lowest price ($5.00), a 5-day lead "
                "time, and an MOQ of 250 that exactly matches the quantity needed. Apply "
                "cold-start logic and explicitly explain why NexGen Procure's cold-start "
                "advantages outweigh the established suppliers' dismal history."
            ),
        },
        "suppliers": [
            {
                "name": "OldGuard Manufacturing",
                "unit_price": 12.50,
                "lead_time_days": 18,
                "minimum_order_qty": 100,
                "performance_history": {
                    "past_orders": 14,
                    "on_time_delivery_rate": 0.58,
                    "defect_rate": 0.18,
                },
            },
            {
                "name": "Legacy Fulfillment Corp.",
                "unit_price": 11.00,
                "lead_time_days": 16,
                "minimum_order_qty": 150,
                "performance_history": {
                    "past_orders": 9,
                    "on_time_delivery_rate": 0.62,
                    "defect_rate": 0.15,
                },
            },
            {
                "name": "NexGen Procure",
                "unit_price": 5.00,
                "lead_time_days": 5,
                "minimum_order_qty": 250,
                "performance_history": {
                    "past_orders": 0,
                    "on_time_delivery_rate": None,
                    "defect_rate": None,
                },
            },
            {
                "name": "QuickBid Wholesale",
                "unit_price": 10.00,
                "lead_time_days": 4,
                "minimum_order_qty": 50,
                "performance_history": {
                    "past_orders": 0,
                    "on_time_delivery_rate": None,
                    "defect_rate": None,
                },
            },
        ],
    },
}

# ---------------------------------------------------------------------------
# Flask app
# ---------------------------------------------------------------------------
app = Flask(__name__, template_folder="templates")
app.config["JSON_SORT_KEYS"] = False

# ---------------------------------------------------------------------------
# In-memory decision log  (list of dicts, newest appended at end)
# ---------------------------------------------------------------------------
decision_log: list = []
_log_lock = threading.Lock()


def _ts() -> str:
    """ISO-8601 timestamp (UTC)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def log_agent_decision(
    decision_id,
    agent_name,
    decision,
    confidence,
    order_value,
    reasoning,
    outcome="pending",
    extra=None,
):
    """Append one entry to the in-memory log and return it."""
    entry = {
        "id": decision_id,
        "timestamp": _ts(),
        "agent": agent_name,
        "decision": decision,
        "confidence": confidence,
        "order_value": order_value,
        "reasoning": reasoning,
        "outcome": outcome,
    }
    if extra:
        entry.update(extra)
    with _log_lock:
        decision_log.append(entry)
    return entry


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/trigger-reorder", methods=["POST"])
def trigger_reorder():
    """
    Run the full pipeline:
      Inventory check -> SupplierRankingAgent -> ProcurementOrchestrator
    Accepts JSON body: {"scenario": 1|2|3}  (defaults to 1)
    Returns a single JSON object with each agent's full output.
    """
    decision_id = str(uuid.uuid4())[:8]

    # Select scenario dataset (default to 1 if not provided or invalid)
    body = request.get_json(silent=True) or {}
    scenario_num = int(body.get("scenario", 1))
    if scenario_num not in SCENARIOS:
        scenario_num = 1
    scenario = SCENARIOS[scenario_num]
    PRODUCT   = scenario["product"]
    SUPPLIERS = scenario["suppliers"]

    # Reorder trigger metadata
    p = PRODUCT
    reorder_info = {
        "product": p["name"],
        "current_stock": p["current_stock"],
        "reorder_threshold": p["reorder_threshold"],
        "quantity_needed": p["quantity_needed"],
        "stock_deficit": p["reorder_threshold"] - p["current_stock"],
        "scenario": scenario_num,
    }

    print(f"\n[WEB] Reorder triggered -- decision_id={decision_id}  scenario={scenario_num}")

    # Configure Groq client
    try:
        client = configure_groq()
    except EnvironmentError as e:
        return jsonify({"error": str(e)}), 500

    # Agent 1: Supplier Ranking  (uses scenario-specific PRODUCT + SUPPLIERS)
    ranking_result = agent1_supplier_ranking(client, PRODUCT, SUPPLIERS)

    # Derive order value for logging
    top_pick_name = ranking_result.get("top_pick", "")
    top_supplier = next(
        (s for s in SUPPLIERS if s["name"] == top_pick_name), None
    )
    unit_price = (
        top_supplier["unit_price"]
        if top_supplier
        else min(s["unit_price"] for s in SUPPLIERS)
    )
    order_value = unit_price * PRODUCT["quantity_needed"]

    log_agent_decision(
        decision_id=decision_id,
        agent_name="SupplierRankingAgent",
        decision=f"Selected: {top_pick_name}",
        confidence=ranking_result.get("confidence"),
        order_value=round(order_value, 2),
        reasoning=ranking_result.get("reasoning", ""),
        outcome="completed",
        extra={"ranked_suppliers": ranking_result.get("ranked_suppliers", [])},
    )

    # Agent 2: Procurement Orchestrator (real handoff)
    procurement_result, _ = agent2_procurement_orchestrator(
        client, ranking_result, PRODUCT, SUPPLIERS
    )

    proc_decision = procurement_result.get("decision", "pending_human_approval")
    proc_outcome = (
        "auto_approved"
        if proc_decision == "auto_approved"
        else "pending_human_approval"
    )

    log_agent_decision(
        decision_id=decision_id,
        agent_name="ProcurementOrchestrator",
        decision=proc_decision,
        confidence=ranking_result.get("confidence"),
        order_value=procurement_result.get("order_value", order_value),
        reasoning=procurement_result.get("reasoning", ""),
        outcome=proc_outcome,
    )

    print(f"[WEB] Pipeline complete -- decision={proc_decision}")

    return jsonify({
        "decision_id": decision_id,
        "reorder_trigger": reorder_info,
        "ranking_agent": {
            **ranking_result,
            "order_value": round(order_value, 2),
            "unit_price": unit_price,
        },
        "procurement_orchestrator": procurement_result,
    })


@app.route("/api/approve/<decision_id>", methods=["POST"])
def approve_decision(decision_id):
    """Mark a pending decision as approved_by_human."""
    entry = log_agent_decision(
        decision_id=decision_id,
        agent_name="Human Reviewer",
        decision="approved_by_human",
        confidence=None,
        order_value=None,
        reasoning="Manually approved by human operator via web interface.",
        outcome="approved_by_human",
    )
    print(f"[WEB] Decision {decision_id} approved by human.")
    return jsonify({
        "status": "approved_by_human",
        "decision_id": decision_id,
        "timestamp": entry["timestamp"],
    })


@app.route("/api/reject/<decision_id>", methods=["POST"])
def reject_decision(decision_id):
    """Mark a pending decision as rejected_by_human."""
    entry = log_agent_decision(
        decision_id=decision_id,
        agent_name="Human Reviewer",
        decision="rejected_by_human",
        confidence=None,
        order_value=None,
        reasoning="Manually rejected by human operator via web interface.",
        outcome="rejected_by_human",
    )
    print(f"[WEB] Decision {decision_id} rejected by human.")
    return jsonify({
        "status": "rejected_by_human",
        "decision_id": decision_id,
        "timestamp": entry["timestamp"],
    })


@app.route("/api/decision-log", methods=["GET"])
def get_decision_log():
    """Return the full decision log, most recent first."""
    with _log_lock:
        log_copy = list(reversed(decision_log))
    return jsonify(log_copy)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print()
    print("=" * 60)
    print("  LOGISTRIA Web Server")
    print("  http://localhost:5000")
    print("=" * 60)
    print()
    app.run(debug=False, host="0.0.0.0", port=5000)
