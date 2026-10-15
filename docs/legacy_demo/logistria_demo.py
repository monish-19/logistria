"""
LOGISTRIA - Live Agent Reasoning Demo
Two-agent handoff proof-of-concept using the Groq API.

Usage:
    set GROQ_API_KEY=your_key_here
    python logistria_demo.py
"""

import os
import sys
import json
import re
import time
import textwrap

# Force UTF-8 output on Windows so unicode box-drawing chars work in any terminal
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from groq import Groq

# ==============================================================================
# HARDCODED DATA
# ==============================================================================

PRODUCT = {
    "name": "Product X",
    "current_stock": 40,
    "reorder_threshold": 100,
    "quantity_needed": 200,  # units to order
}

SUPPLIERS = [
    {
        "name": "Apex Industrial Supplies",
        "unit_price": 6.20,
        "lead_time_days": 7,
        "minimum_order_qty": 50,
        "performance_history": {
            "past_orders": 12,
            "on_time_delivery_rate": 0.97,
            "defect_rate": 0.01,
        },
    },
    {
        "name": "Meridian Components Co.",
        "unit_price": 5.85,
        "lead_time_days": 10,
        "minimum_order_qty": 100,
        "performance_history": {
            "past_orders": 8,
            "on_time_delivery_rate": 0.88,
            "defect_rate": 0.04,
        },
    },
    {
        "name": "NovaTrade Logistics",
        "unit_price": 5.50,
        "lead_time_days": 9,
        "minimum_order_qty": 150,
        "performance_history": {
            "past_orders": 0,
            "on_time_delivery_rate": None,
            "defect_rate": None,
        },
    },
    {
        "name": "SwiftSource Global",
        "unit_price": 6.80,
        "lead_time_days": 5,
        "minimum_order_qty": 50,
        "performance_history": {
            "past_orders": 0,
            "on_time_delivery_rate": None,
            "defect_rate": None,
        },
    },
]

# ==============================================================================
# GROQ SETUP
# ==============================================================================

API_KEY = os.environ.get("GROQ_API_KEY")
MODEL_NAME = "openai/gpt-oss-120b"  # Groq-hosted OpenAI-compatible model

TIMEOUT_SECONDS = 30


def configure_groq():
    if not API_KEY:
        raise EnvironmentError(
            "GROQ_API_KEY environment variable is not set. "
            "Please set it before running this script."
        )
    client = Groq(api_key=API_KEY)
    return client


# ==============================================================================
# FORMATTING HELPERS
# ==============================================================================

DIVIDER = "-" * 70


def section(title: str):
    print(f"\n{DIVIDER}")
    print(f"  {title}")
    print(DIVIDER)


def wrap_print(label: str, text: str, width: int = 68):
    """Print a labelled block of wrapped text."""
    print(f"\n  {label}")
    for line in text.splitlines():
        wrapped = textwrap.fill(
            line, width=width, initial_indent="    ", subsequent_indent="    "
        )
        print(wrapped if wrapped.strip() else "")


def print_kv(key: str, value):
    print(f"  {key:<26} {value}")


def extract_json(raw: str) -> dict:
    """
    Robustly extract the first top-level JSON object from a raw LLM response.

    Strategy (applied in order until one succeeds):
      1. Strip markdown fences, then try a bracket-depth scanner to find the
         exact outermost { ... } span — handles nested objects correctly.
      2. Fall back to a simple greedy regex on the stripped text.
      3. Try parsing the entire stripped text as-is (model returned bare JSON).

    Raises ValueError if all three strategies fail.
    """
    # Step 1: strip all markdown code fences
    cleaned = re.sub(r"```(?:json)?", "", raw, flags=re.IGNORECASE)
    cleaned = cleaned.replace("```", "").strip()

    # Strategy A: bracket-depth scanner — finds the true outermost { }
    def _bracket_scan(text: str):
        start = text.find("{")
        if start == -1:
            return None
        depth = 0
        in_string = False
        escape_next = False
        for i, ch in enumerate(text[start:], start=start):
            if escape_next:
                escape_next = False
                continue
            if ch == "\\" and in_string:
                escape_next = True
                continue
            if ch == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return text[start : i + 1]
        return None

    candidate = _bracket_scan(cleaned)
    if candidate:
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass  # fall through to next strategy

    # Strategy B: greedy regex fallback
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass

    # Strategy C: parse the whole cleaned string as bare JSON
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    raise ValueError("No JSON object found in response")


# ==============================================================================
# FALLBACK HELPERS  (rule-based, never crashes)
# ==============================================================================

def fallback_supplier_ranking(quantity_needed: int) -> dict:
    """Pick the cheapest supplier that can fulfil the order."""
    eligible = [s for s in SUPPLIERS if s["minimum_order_qty"] <= quantity_needed]
    candidates = eligible if eligible else SUPPLIERS
    best = min(candidates, key=lambda s: s["unit_price"])
    ranked = sorted(candidates, key=lambda s: s["unit_price"])
    return {
        "ranked_suppliers": [s["name"] for s in ranked],
        "top_pick": best["name"],
        "reasoning": (
            "Rule-based fallback: selected supplier with lowest unit price "
            "that meets the minimum order quantity requirement."
        ),
        "confidence": 0.60,
    }


def fallback_procurement_decision(top_pick: str, order_value: float) -> dict:
    return {
        "decision": "pending_human_approval",
        "reasoning": (
            "Rule-based fallback: Groq API unavailable. "
            "Flagging for human review as a safe default."
        ),
        "order_value": order_value,
    }


# ==============================================================================
# AGENT 1 - SupplierRankingAgent
# ==============================================================================

# System message: JSON-only mandate + exact schema (enforced at API level AND in prompt)
RANKING_SYSTEM_MSG = """You are SupplierRankingAgent, an intelligent procurement AI.

Respond with ONLY a valid JSON object matching this schema, with no other text before or after it:
{
  "ranked_suppliers": ["<name1>", "<name2>", "<name3>", "<name4>"],
  "top_pick": "<name of best supplier>",
  "reasoning": "<step-by-step reasoning covering both established and cold-start suppliers>",
  "confidence": <float 0.0-1.0>
}

Do not include markdown fences, preamble, explanation, or any text outside the JSON object.""".strip()

# User message: task data and ranking rules
RANKING_USER_TEMPLATE = """
TASK
A reorder has been triggered for "{product_name}".
Quantity needed: {quantity_needed} units.

SUPPLIER CANDIDATES
{supplier_json}

RANKING RULES (follow these exactly)

Established Suppliers (past_orders >= 5):
  Weight your ranking PRIMARILY on their performance history:
  - on_time_delivery_rate (higher is better)
  - defect_rate (lower is better)
  - Then consider lead time and unit price as tiebreakers.
  Explicitly state in your reasoning how each supplier's performance
  history drove their score.

New Suppliers (past_orders == 0 -- cold-start case):
  These have NO historical data. Do NOT penalise them unfairly.
  Instead weight them on:
  - unit_price (lower is better)
  - lead_time_days (lower is better)
  - minimum_order_qty fit (closer to {quantity_needed} without exceeding
    the order need is better)
  Explicitly state in your reasoning that you are applying cold-start
  logic for these suppliers and why.
{scenario_hint}""".strip()


def agent1_supplier_ranking(client, product: dict, suppliers: list) -> dict:
    section("[SUPPLIER RANKING AGENT]")
    print(f"\n  Evaluating {len(suppliers)} suppliers for '{product['name']}'...")
    print(f"  Quantity needed: {product['quantity_needed']} units\n")

    result = None

    hint = product.get("scenario_hint", "")
    hint_block = f"\n\nADDITIONAL CONTEXT\n{hint}" if hint else ""
    user_msg = RANKING_USER_TEMPLATE.format(
        product_name=product["name"],
        quantity_needed=product["quantity_needed"],
        supplier_json=json.dumps(suppliers, indent=2),
        scenario_hint=hint_block,
    )
    messages = [
        {"role": "system", "content": RANKING_SYSTEM_MSG},
        {"role": "user",   "content": user_msg},
    ]

    for attempt in range(1, 3):  # up to 2 attempts
        try:
            print(f"  Calling Groq ({MODEL_NAME}) -- attempt {attempt}/2 ...")
            start = time.time()
            chat_response = client.chat.completions.create(
                model=MODEL_NAME,
                messages=messages,
                temperature=0.2,
                max_tokens=1024,
                timeout=TIMEOUT_SECONDS,
                response_format={"type": "json_object"},
                reasoning_effort="low",
            )
            elapsed = time.time() - start
            raw_response = chat_response.choices[0].message.content
            print(f"  Response received in {elapsed:.1f}s")
            result = extract_json(raw_response)
            break  # success
        except (json.JSONDecodeError, ValueError):
            # Catches both bare JSONDecodeError and the ValueError raised by
            # extract_json when all extraction strategies fail.
            if attempt == 1:
                print("  [!] JSON parse failed on attempt 1 -- retrying once ...")
                # continue to attempt 2
            else:
                print("  [!] JSON parse failed on attempt 2.")
                print("  FALLBACK TRIGGERED -- using lowest-price rule.")
                result = fallback_supplier_ranking(product["quantity_needed"])
        except Exception as e:
            print(f"  [FALLBACK] Groq call failed: {e}")
            print("  Using rule-based fallback for supplier ranking.")
            result = fallback_supplier_ranking(product["quantity_needed"])
            break

    if result is None:
        result = fallback_supplier_ranking(product["quantity_needed"])

    # Display results
    print()
    print_kv("Top Pick:", result.get("top_pick", "N/A"))
    print_kv("Confidence Score:", f"{result.get('confidence', 0.0):.2f}")
    print_kv("Ranked Order:", " > ".join(result.get("ranked_suppliers", [])))
    wrap_print("Agent Reasoning:", result.get("reasoning", ""))

    return result


# ==============================================================================
# AGENT 2 - ProcurementOrchestrator
# ==============================================================================

# System message: JSON-only mandate + exact schema
ORCHESTRATOR_SYSTEM_MSG = """You are ProcurementOrchestrator, the final decision-making AI in a procurement pipeline.

Respond with ONLY a valid JSON object matching this schema, with no other text before or after it:
{
  "decision": "auto_approved" or "pending_human_approval",
  "reasoning": "<clear explanation referencing the exact confidence and order value numbers>",
  "order_value": <number>
}

Do not include markdown fences, preamble, explanation, or any text outside the JSON object.""".strip()

# User message: handoff data and decision rule
ORCHESTRATOR_USER_TEMPLATE = """
INCOMING HANDOFF FROM SupplierRankingAgent

  Top Pick Supplier : {top_pick}
  Ranking Confidence: {confidence}
  Order Value       : ${order_value:.2f}  ({quantity_needed} units x ${unit_price:.2f} each)
  Agent Reasoning   : {ranking_reasoning}

DECISION RULE (apply this exactly -- reference the actual numbers in your reasoning)
  IF   confidence >= 0.80  AND  order_value < 5000.00  ->  decision = "auto_approved"
  OTHERWISE                                             ->  decision = "pending_human_approval"

State which branch was triggered and cite the exact confidence ({confidence}) and
order value (${order_value:.2f}) figures in your reasoning field.
""".strip()


def agent2_procurement_orchestrator(
    client, ranking_result: dict, product: dict, suppliers: list
) -> tuple:
    section("[PROCUREMENT ORCHESTRATOR]")
    print("\n  Receiving handoff from SupplierRankingAgent ...")

    top_pick_name = ranking_result.get("top_pick", "")
    confidence = ranking_result.get("confidence", 0.0)
    ranking_reasoning = ranking_result.get("reasoning", "")

    # Look up the chosen supplier's unit price
    top_supplier = next(
        (s for s in suppliers if s["name"] == top_pick_name), None
    )
    unit_price = (
        top_supplier["unit_price"]
        if top_supplier
        else min(s["unit_price"] for s in suppliers)
    )
    quantity_needed = product["quantity_needed"]
    order_value = unit_price * quantity_needed

    print_kv("  Incoming Top Pick:", top_pick_name)
    print_kv("  Incoming Confidence:", f"{confidence:.2f}")
    print_kv("  Computed Order Value:", f"${order_value:,.2f}")
    print()

    user_msg = ORCHESTRATOR_USER_TEMPLATE.format(
        top_pick=top_pick_name,
        confidence=confidence,
        order_value=order_value,
        quantity_needed=quantity_needed,
        unit_price=unit_price,
        ranking_reasoning=ranking_reasoning,
    )
    messages = [
        {"role": "system", "content": ORCHESTRATOR_SYSTEM_MSG},
        {"role": "user",   "content": user_msg},
    ]

    result = None
    try:
        print(f"  Calling Groq ({MODEL_NAME}) for final decision ...")
        start = time.time()
        chat_response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=messages,
            temperature=0.1,
            max_tokens=512,
            timeout=TIMEOUT_SECONDS,
            response_format={"type": "json_object"},
            reasoning_effort="low",
        )
        elapsed = time.time() - start
        raw_response = chat_response.choices[0].message.content
        print(f"  Response received in {elapsed:.1f}s\n")
        result = extract_json(raw_response)
    except Exception as e:
        print(f"  [FALLBACK] Groq call failed: {e}")
        print("  Using rule-based fallback for procurement decision.")
        result = fallback_procurement_decision(top_pick_name, order_value)

    # Ensure order_value is present
    if "order_value" not in result:
        result["order_value"] = order_value

    decision_label = (
        "[AUTO-APPROVED]"
        if result.get("decision") == "auto_approved"
        else "[PENDING HUMAN APPROVAL]"
    )
    print_kv("Final Decision:", decision_label)
    print_kv("Order Value:", f"${result.get('order_value', order_value):,.2f}")
    wrap_print("Orchestrator Reasoning:", result.get("reasoning", ""))

    return result, order_value


# ==============================================================================
# MAIN
# ==============================================================================

def main():
    print()
    print("=" * 70)
    print("  LOGISTRIA -- Live Agent Reasoning Demo")
    print("  Multi-agent procurement pipeline  |  Powered by Groq AI")
    print("=" * 70)

    # Reorder trigger event
    section("REORDER TRIGGER")
    p = PRODUCT
    print()
    print_kv("Product:", p["name"])
    print_kv("Current Stock:", f"{p['current_stock']} units")
    print_kv("Reorder Threshold:", f"{p['reorder_threshold']} units")
    print_kv(
        "Stock Deficit:",
        f"{p['reorder_threshold'] - p['current_stock']} units below threshold",
    )
    print_kv("Quantity to Order:", f"{p['quantity_needed']} units")
    print(
        f"\n  [TRIGGER] {p['name']} stock: {p['current_stock']} units, "
        f"threshold: {p['reorder_threshold']} units -- reorder triggered"
    )

    # Configure Groq client
    try:
        client = configure_groq()
    except EnvironmentError as e:
        print(f"\n  ERROR: {e}")
        return

    # Agent 1: Supplier Ranking
    ranking_result = agent1_supplier_ranking(client, PRODUCT, SUPPLIERS)

    # Agent 2: Procurement Decision  (real handoff -- ranking_result passed directly)
    procurement_result, order_value = agent2_procurement_orchestrator(
        client, ranking_result, PRODUCT, SUPPLIERS
    )

    # Final Decision Chain Summary
    section("DECISION CHAIN SUMMARY")
    print()

    top_pick = ranking_result.get("top_pick", "Unknown Supplier")
    confidence = ranking_result.get("confidence", 0.0)
    decision = procurement_result.get("decision", "unknown")
    final_order_value = procurement_result.get("order_value", order_value)

    decision_str = (
        f"Auto-approved (order value ${final_order_value:,.2f})"
        if decision == "auto_approved"
        else f"Flagged for human approval (order value ${final_order_value:,.2f})"
    )

    chain = (
        f"Reorder triggered -> {top_pick} ranked #1 "
        f"(confidence {confidence:.2f}) -> {decision_str}"
    )
    print(f"  DECISION CHAIN: {chain}")
    print()
    print("=" * 70)
    print("  Demo complete.")
    print("=" * 70)
    print()


if __name__ == "__main__":
    main()
