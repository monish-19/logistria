import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "./api";

afterEach(() => vi.restoreAllMocks());

describe("api client", () => {
  it("serializes audit filters and returns event data", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify([{ id: 7 }]), { status: 200 }));

    await expect(api.audit({ runId: "run 1", severity: "warning", type: "alert" })).resolves.toEqual([{ id: 7 }]);
    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/api/events?run_id=run+1&severity=warning&type=alert&limit=500",
      expect.objectContaining({ headers: { "Content-Type": "application/json" } }),
    );
  });

  it("surfaces API error details", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({ detail: "Not authorized" }), { status: 403 }));

    await expect(api.products()).rejects.toThrow("Not authorized");
  });
});
