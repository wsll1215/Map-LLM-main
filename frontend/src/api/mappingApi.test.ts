import { afterEach, describe, expect, it, vi } from "vitest";
import { mappingApi } from "./mappingApi";

describe("mappingApi trace loading", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("loads the full desktop trace page by default", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ items: [], next_cursor: null, total_count: 0 }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await mappingApi.traceEvents(141, 194);

    expect(fetchMock.mock.calls[0][0]).toContain("/events/?limit=100");
  });

  it("scopes historical logs to the selected run", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ logs: [] }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await mappingApi.logs(142, 197);

    expect(fetchMock.mock.calls[0][0]).toBe("/mapping/api/process-logs/142/?run_id=197");
  });
});
