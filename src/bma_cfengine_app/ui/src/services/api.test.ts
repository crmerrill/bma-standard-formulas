import { afterEach, describe, expect, it, vi } from "vitest";
import * as api from "./api";

describe("api request handling", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.clearAllMocks();
  });

  it("uses /api base path and returns JSON payload", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          run_id: "run_1",
          status: "completed",
          created_at: "2026-01-01T00:00:00Z",
          sections: [],
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    const run = await api.getRun("run_1");
    expect(fetchMock).toHaveBeenCalledWith("/api/runs/run_1", undefined);
    expect(run.run_id).toBe("run_1");
  });

  it("normalizes network fetch failures to a startup hint", async () => {
    const fetchMock = vi.fn().mockRejectedValue(new Error("Failed to fetch"));
    vi.stubGlobal("fetch", fetchMock);

    await expect(api.getRun("run_2")).rejects.toThrow(
      "Cannot reach the API. Start the engine server",
    );
  });

  it("surfaces string detail errors with status code", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ detail: "Bad mapping request" }), {
        status: 400,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      api.saveMapping({ upload_id: "u1", mappings: [] }),
    ).rejects.toThrow("400: Bad mapping request");
  });

  it("surfaces array detail errors with joined messages", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ detail: [{ msg: "field required" }, { msg: "wrong type" }] }), {
        status: 422,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      api.validateMapping({ upload_id: "u1", mappings: [] }),
    ).rejects.toThrow("422: field required; wrong type");
  });
});
