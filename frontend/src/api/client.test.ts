import { afterEach, describe, expect, it, vi } from "vitest";
import { apiFetch } from "./client";

describe("apiFetch", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("surfaces a backend message for a non-success response", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ success: false, message: "缺少请求ID" }), {
          status: 400,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );

    await expect(apiFetch("/mapping/api/process-request/", { method: "POST" })).rejects.toThrow(
      "缺少请求ID",
    );
  });

  it("surfaces a backend message when a 200 response reports success false", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ success: false, message: "地图服务暂不可用" }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );

    await expect(apiFetch("/mapping/api/process-request/", { method: "POST" })).rejects.toThrow(
      "地图服务暂不可用",
    );
  });
});
