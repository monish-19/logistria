export type Severity = "info" | "warning" | "success" | "alert" | "escalation";
export type EventType = "info" | "request" | "response" | "decision" | "alert" | "escalation" | "human_action";
export type NodeStatus = "pending" | "active" | "done" | "failed" | "paused";

export interface EventItem {
  id: number;
  run_id: string | null;
  sender: string;
  receiver: string;
  type: EventType | string;
  payload_json: Record<string, unknown>;
  human_text: string | null;
  severity: Severity | string;
  ts: string;
}
export interface RunSummary { run_id: string; product_name: string; quantity: number; status: string; decision?: unknown; created_at?: string; }
export interface RunDetail extends RunSummary {
  approval_required: boolean; due_date?: string; urgency: string; nodes: Record<string, NodeStatus>;
  materials: Record<string, unknown>[]; selected_supplier?: Record<string, unknown> | null;
  purchase_orders: Record<string, unknown>[]; route?: RouteOutput | null; distance_km?: number; eta_minutes?: number; delivery_cost?: number;
}
export interface RouteOutput {
  geometry?: { type: string; coordinates: [number, number][] } | [number, number][] | null;
  stops?: { name: string; lat: number; lon: number; eta_minutes: number }[];
  distance_km?: number; eta_minutes?: number; delivery_cost?: number; method?: string; ordered_stops?: string[];
}
export interface Product { id: number; name: string; sku?: string; reorder_threshold: number; }
export interface InventoryItem { id: number; material: string; sku?: string; available_qty: number; reserved_qty: number; }
export interface SupplierItem { id: number; name: string; is_cold_start: boolean; materials: { material_id: number; unit_price: number; lead_time_days: number; }[]; }
export interface Approval { id: number; run_id: string | null; status: string; comments?: string; approved_by?: string; }
export interface ChatPlan {
  message: string; plan_id?: string; requires_confirmation?: boolean; shortfall_table?: Record<string, unknown>[];
  proposed_plan?: { product_name: string; quantity: number; due_date?: string | null; urgency: string };
}
