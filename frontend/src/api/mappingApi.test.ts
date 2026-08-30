import { afterEach, describe, expect, it, vi } from "vitest";
import { mappingApi } from "./mappingApi";

describe("mapping operation idempotency", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("reuses the caller operation key for a deliberate process retry", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValue(new Response(JSON.stringify({ success: true, request_id: 7 }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    await mappingApi.process(7, "run-operation-1");

    const request = fetchMock.mock.calls[0][1] as RequestInit;
    expect(new Headers(request.headers).get("Idempotency-Key")).toBe("run-operation-1");
  });

  it("keeps a message id stable across an explicit message retry", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValue(new Response(JSON.stringify({ success: true, request_id: 7 }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    await mappingApi.continue(7, "补充道路", "message-operation-1", "message-1");

    const headers = new Headers((fetchMock.mock.calls[0][1] as RequestInit).headers);
    expect(headers.get("Idempotency-Key")).toBe("message-operation-1");
    expect(headers.get("X-Message-Id")).toBe("message-1");
  });
});
