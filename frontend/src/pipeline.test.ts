import { describe, expect, it } from "vitest";
import { deriveNodes } from "./pipeline";
import type { EventItem, RunDetail } from "./types";

const run = (run_id: string, status: string): RunDetail => ({
  run_id,
  product_name: "Widget Pro",
  quantity: 5,
  status,
  approval_required: status === "pending_human_review",
  urgency: "normal",
  nodes: { inventory: "done", ranking: "done", procurement: "paused", manufacturing: "pending", logistics: "pending", monitor: "active" },
  materials: [],
  purchase_orders: [],
});

const event = (run_id: string, sender: string, payload_json: Record<string, unknown> = {}): EventItem => ({
  id: Math.random(),
  run_id,
  sender,
  receiver: "system",
  type: "response",
  payload_json,
  human_text: null,
  severity: "info",
  ts: "2026-01-01T00:00:00Z",
});

describe("run-scoped pipeline state", () => {
  it("does not borrow completion events from another same-product run", () => {
    const pending = run("run-pending", "pending_human_review");
    const complete = run("run-complete", "completed");
    const events = [
      event(complete.run_id, "ManufacturingStep", { progress_pct: 100 }),
      event(complete.run_id, "LogisticsAgent", { route: {} }),
    ];
    expect(deriveNodes(pending, events).manufacturing).toBe("pending");
    expect(deriveNodes(pending, events).logistics).toBe("pending");
    expect(deriveNodes(complete, events).manufacturing).toBe("done");
  });
});
