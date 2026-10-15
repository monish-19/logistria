import type { EventItem, NodeStatus, RunDetail, RouteOutput } from "./types";

export const PIPELINE_NODES = ["inventory", "ranking", "procurement", "manufacturing", "logistics", "monitor"] as const;
export type PipelineNode = typeof PIPELINE_NODES[number];

const senderNode: Record<string, PipelineNode> = {
  InventoryAgent: "inventory",
  SupplierRankingAgent: "ranking",
  ProcurementAgent: "procurement",
  ManufacturingStep: "manufacturing",
  LogisticsAgent: "logistics",
  MonitorAgent: "monitor",
};

export function eventNode(event: EventItem): PipelineNode | undefined {
  return senderNode[event.sender];
}

export function deriveNodes(run: RunDetail | undefined, events: EventItem[]): Record<PipelineNode, NodeStatus> {
  const nodes = Object.fromEntries(PIPELINE_NODES.map((node) => [node, run?.nodes[node] || "pending"])) as Record<PipelineNode, NodeStatus>;
  if (run?.status === "completed") {
    return Object.fromEntries(PIPELINE_NODES.map((node) => [node, "done"])) as Record<PipelineNode, NodeStatus>;
  }
  if (run?.status === "rejected") {
    return Object.fromEntries(PIPELINE_NODES.map((node) => [node, node === "procurement" ? "failed" : PIPELINE_NODES.indexOf(node) > 2 ? "pending" : "done"])) as Record<PipelineNode, NodeStatus>;
  }
  for (const event of events.filter((event) => event.run_id === run?.run_id)) {
    const node = eventNode(event);
    if (!node) continue;
    const payload = event.payload_json;
    if (event.sender === "Admin" && event.payload_json.approved === true) {
      nodes.procurement = "done";
    } else if (node === "procurement" && event.type === "human_action") {
      nodes.procurement = "paused";
    } else if (node === "manufacturing" && Number(payload.progress_pct || 0) < 100) {
      nodes.manufacturing = "active";
    } else if (node === "manufacturing" && Number(payload.progress_pct || 0) >= 100) {
      nodes.manufacturing = "done";
    } else if (node === "logistics" && payload.route) {
      nodes.logistics = "done";
    } else {
      nodes[node] = event.severity === "alert" || event.severity === "escalation" ? "failed" : "done";
    }
  }
  const firstOpen = PIPELINE_NODES.findIndex((node) => nodes[node] === "pending");
  if (firstOpen >= 0 && !PIPELINE_NODES.some((node) => nodes[node] === "active" || nodes[node] === "paused")) {
    nodes[PIPELINE_NODES[firstOpen]] = "active";
  }
  return nodes;
}

export function routeFromEvents(events: EventItem[]): RouteOutput | undefined {
  for (const event of events.slice().reverse()) {
    const route = event.payload_json.route;
    if (route && typeof route === "object") return route as RouteOutput;
  }
  return undefined;
}

export function runLabel(events: EventItem[]): { product: string; quantity: string; status: string } {
  const start = events.find((event) => event.sender === "Admin" && event.payload_json.product_name);
  const product = String(start?.payload_json.product_name || "Demo production run");
  const quantity = String(start?.payload_json.quantity || "50");
  const review = events.some((event) => event.type === "human_action");
  const complete = events.some((event) => event.sender === "LogisticsAgent" && event.payload_json.status === "completed");
  return { product, quantity, status: complete ? "Completed" : review ? "Needs review" : "Running" };
}
