import type { Approval, ChatPlan, EventItem, InventoryItem, Product, RouteOutput, RunDetail, RunSummary, SupplierItem } from "./types";

const API_URL = (import.meta.env.VITE_API_URL || "http://localhost:8000").replace(/\/$/, "");
export const WS_URL = (import.meta.env.VITE_WS_URL || API_URL.replace(/^http/, "ws") + "/ws/events").replace(/\/$/, "");
const headers = (adminKey?: string): Record<string, string> => adminKey ? { "X-Admin-Key": adminKey, "Content-Type": "application/json" } : { "Content-Type": "application/json" };

async function request<T>(path: string, init: RequestInit = {}, adminKey?: string): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, { ...init, headers: { ...headers(adminKey), ...(init.headers || {}) } });
  if (!response.ok) throw new Error((await response.json().catch(() => null))?.detail || `Request failed (${response.status})`);
  return response.json() as Promise<T>;
}
export const api = {
  runs: (status?: string) => request<RunSummary[]>(`/api/runs${status ? `?status=${encodeURIComponent(status)}` : ""}`),
  run: (id: string) => request<RunDetail>(`/api/runs/${id}`),
  route: (id: string) => request<RouteOutput>(`/api/runs/${id}/route`),
  events: (params = "") => request<EventItem[]>(`/api/events${params}`),
  audit: (filters: { runId?: string; severity?: string; type?: string; limit?: number } = {}) => {
    const params = new URLSearchParams();
    if (filters.runId) params.set("run_id", filters.runId);
    if (filters.severity) params.set("severity", filters.severity);
    if (filters.type) params.set("type", filters.type);
    params.set("limit", String(filters.limit ?? 500));
    return request<EventItem[]>(`/api/events?${params.toString()}`);
  },
  approvals: () => request<Approval[]>("/api/approvals"),
  alerts: () => request<EventItem[]>("/api/alerts"),
  products: () => request<Product[]>("/api/products"),
  inventory: () => request<InventoryItem[]>("/api/inventory"),
  suppliers: () => request<SupplierItem[]>("/api/suppliers"),
  start: (body: object, key: string) => request<Record<string, unknown>>("/api/runs", { method: "POST", body: JSON.stringify(body) }, key),
  approve: async (id: string, key: string, approved = true, supplier_name?: string) => {
    const url = `${API_URL}/api/runs/${id}/approve`;
    const body = { approved, supplier_name };
    const response = await fetch(url, { method: "POST", headers: headers(key), body: JSON.stringify(body) });
    const result = await response.json().catch(() => ({}));
    console.log("[Logistria] approve request", { url, body, response: result });
    if (!response.ok) throw Object.assign(new Error(result?.detail || `Request failed (${response.status})`), { status: response.status });
    return result;
  },
  reject: (id: string, key: string) => api.approve(id, key, false),
  override: (id: string, supplier_id: number, key: string) => request(`/api/runs/${id}/override`, { method: "POST", body: JSON.stringify({ supplier_id }) }, key),
  chat: (message: string, key: string) => request<ChatPlan>("/api/chat", { method: "POST", body: JSON.stringify({ message }) }, key),
  confirm: (plan: ChatPlan, key: string) => request("/api/chat/confirm", { method: "POST", body: JSON.stringify({ plan_id: plan.plan_id, ...plan.proposed_plan }) }, key),
};
