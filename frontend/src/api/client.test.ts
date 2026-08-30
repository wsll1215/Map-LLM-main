import { afterEach, describe, expect, it, vi } from "vitest";
import {
  apiFetch,
  ApiRequestError,
  bootstrapAuth,
  clearAccessToken,
  getAuthStatus,
  isRetryableRefreshError,
  isTerminalRefreshError,
  refreshAccessToken,
  refreshRecoveryDelayMs,
  refreshRetryDelayMs,
  revokeAllTokens,
} from "./client";

describe("apiFetch", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    clearAccessToken();
  });

  it("keeps the latest auth status for components mounted after bootstrap", () => {
    clearAccessToken("connection_recovering");

    expect(getAuthStatus()).toBe("connection_recovering");
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

  it("keeps refresh terminal errors out of the network recovery loop", () => {
    const response = new Response(null, { status: 401 });
    const expired = new ApiRequestError("登录状态已过期", response, {
      error_code: "refresh_token_expired",
      retryable: false,
    });
    const unavailable = new ApiRequestError("稍后重试", new Response(null, { status: 503 }), {
      error_code: "refresh_temporarily_unavailable",
      retryable: true,
    });

    expect(isTerminalRefreshError(expired)).toBe(true);
    expect(isRetryableRefreshError(expired)).toBe(false);
    expect(isRetryableRefreshError(unavailable)).toBe(true);
  });

  it("uses finite fast backoff and then a stable recovery interval", () => {
    expect([1, 2, 3, 4, 5, 6].map(refreshRecoveryDelayMs)).toEqual([
      500,
      1000,
      2000,
      4000,
      8000,
      15000,
    ]);
  });

  it("honors Retry-After for auth rate limiting without allowing unbounded waits", () => {
    const rateLimited = new ApiRequestError("请稍后重试", new Response(null, { status: 429 }), {
      error_code: "auth_rate_limited",
      retryable: true,
      retry_after: 12,
    });
    const tooLong = new ApiRequestError("请稍后重试", new Response(null, { status: 429 }), {
      error_code: "auth_rate_limited",
      retryable: true,
      retry_after: 120,
    });

    expect(refreshRetryDelayMs(rateLimited, 1)).toBe(12000);
    expect(refreshRetryDelayMs(tooLong, 1)).toBe(60000);
  });

  it("reuses one refresh request id across network retry attempts", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({
        success: false,
        error_code: "refresh_temporarily_unavailable",
        retryable: true,
        next_action: "retry_refresh",
      }), { status: 503 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({
        success: true,
        access_token: "access-after-retry",
        expires_in: 600,
        access_expires_at: new Date(Date.now() + 600000).toISOString(),
        refresh_expires_at: new Date(Date.now() + 86400000).toISOString(),
      }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(refreshAccessToken()).resolves.toBe("access-after-retry");
    const firstHeaders = new Headers((fetchMock.mock.calls[0][1] as RequestInit).headers);
    const secondHeaders = new Headers((fetchMock.mock.calls[1][1] as RequestInit).headers);
    expect(firstHeaders.get("X-Refresh-Request-Id")).toBe(secondHeaders.get("X-Refresh-Request-Id"));
  });

  it("schedules low-frequency recovery after fast refresh attempts are exhausted", async () => {
    const scheduledDelays: number[] = [];
    vi.spyOn(window, "setTimeout").mockImplementation(((handler: TimerHandler, timeout?: number) => {
      const delay = Number(timeout ?? 0);
      scheduledDelays.push(delay);
      if (delay !== 10000 && delay !== 15000 && typeof handler === "function") {
        queueMicrotask(() => handler());
      }
      return 1 as unknown as number;
    }) as typeof window.setTimeout);
    vi.spyOn(window, "clearTimeout").mockImplementation(() => undefined);
    try {
      vi.stubGlobal(
        "fetch",
        vi.fn().mockImplementation(() => Promise.resolve(new Response(JSON.stringify({
            success: false,
            error_code: "refresh_temporarily_unavailable",
            retryable: true,
            next_action: "retry_refresh",
          }), { status: 503 }))),
      );

      const refresh = refreshAccessToken();
      await expect(refresh).rejects.toMatchObject({ errorCode: "refresh_temporarily_unavailable" });
      expect(scheduledDelays).toContain(15000);
    } finally {
      vi.restoreAllMocks();
    }
  });

  it("does not replay a non-idempotent POST after a 401", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({
        success: true,
        access_token: "access-before-post",
        expires_in: 600,
        access_expires_at: new Date(Date.now() + 600000).toISOString(),
        refresh_expires_at: new Date(Date.now() + 86400000).toISOString(),
      }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({
        success: false,
        error_code: "access_token_expired",
        message: "访问凭据已过期",
      }), { status: 401 }));
    vi.stubGlobal("fetch", fetchMock);

    await bootstrapAuth();
    await expect(apiFetch("/mapping/api/process-request/", {
      method: "POST",
      body: JSON.stringify({ request_id: 1 }),
    })).rejects.toMatchObject({ errorCode: "access_token_expired" });
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("replays a POST after 401 only when it carries an idempotency key", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({
        success: true,
        access_token: "access-before-idempotent-post",
        expires_in: 600,
        access_expires_at: new Date(Date.now() + 600000).toISOString(),
        refresh_expires_at: new Date(Date.now() + 86400000).toISOString(),
      }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({
        success: false,
        error_code: "access_token_expired",
        message: "访问凭据已过期",
      }), { status: 401 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ success: true }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    await bootstrapAuth();
    await expect(apiFetch("/mapping/api/process-request/", {
      method: "POST",
      headers: { "Idempotency-Key": "process-once" },
      body: JSON.stringify({ request_id: 1 }),
    })).resolves.toEqual({ success: true });
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });

  it("sends a Bearer token when revoking all token families", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({
        success: true,
        access_token: "access-for-revoke",
        expires_in: 600,
        access_expires_at: new Date(Date.now() + 600000).toISOString(),
        refresh_expires_at: new Date(Date.now() + 86400000).toISOString(),
      }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ success: true }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    await bootstrapAuth();
    await expect(revokeAllTokens()).resolves.toBeUndefined();
    const headers = new Headers((fetchMock.mock.calls[1][1] as RequestInit).headers);
    expect(headers.get("Authorization")).toBe("Bearer access-for-revoke");
  });
});
