import { describe, expect, it } from "vitest";
import { eventFeedReducer } from "./eventFeed";
import type { EventItem } from "./types";
const event = (id: number, text: string): EventItem => ({ id, run_id: "run-1", sender: "A", receiver: "B", type: "info", payload_json: {}, human_text: text, severity: "info", ts: "2026-01-01T00:00:00Z" });
describe("event feed reducer", () => {
  it("appends new frames and ignores duplicate replay", () => { const first = eventFeedReducer([], event(1, "one")); expect(eventFeedReducer(first, event(1, "one"))).toHaveLength(1); expect(eventFeedReducer(first, event(2, "two"))).toHaveLength(2); });
  it("replaces narration when event_updated arrives", () => { const updated = event(1, "upgraded"); expect(eventFeedReducer([event(1, "template")], { type: "event_updated", event: updated })[0].human_text).toBe("upgraded"); });
});
