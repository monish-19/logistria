import { beforeEach, describe, expect, it, vi } from "vitest";
import type { EventItem, RunSummary } from "./types";

const runs: RunSummary[] = [{ run_id: "run-1", product_name: "Widget", quantity: 10, status: "running" }];
const events: EventItem[] = [{ id: 1, run_id: "run-1", sender: "planner", receiver: "factory", type: "decision", payload_json: {}, human_text: "Started", severity: "info", ts: "2026-01-01T00:00:00Z" }];

vi.mock("./api", () => ({
  api: {
    runs: vi.fn(async () => runs),
    events: vi.fn(async () => events),
    run: vi.fn(),
  },
}));

describe("operation store", () => {
  beforeEach(async () => {
    const { useStore } = await import("./store");
    useStore.setState({ events: [], runs: [], activeRun: undefined, error: undefined });
  });

  it("loads runs and events together", async () => {
    const { useStore } = await import("./store");

    await useStore.getState().load();

    expect(useStore.getState().runs).toEqual(runs);
    expect(useStore.getState().events).toEqual(events);
    expect(useStore.getState().error).toBeUndefined();
  });

  it("deduplicates websocket event replays", async () => {
    const { useStore } = await import("./store");

    useStore.getState().ingest(events[0]);
    useStore.getState().ingest(events[0]);

    expect(useStore.getState().events).toHaveLength(1);
  });
});
