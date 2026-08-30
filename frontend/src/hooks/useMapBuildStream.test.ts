import { describe, expect, it } from "vitest";
import {
  normalizeStreamCursor,
  isCurrentStreamGeneration,
  shouldStopStreamForStatus,
  isTransportTerminalStreamEvent,
  isNonRetryableSseStatus,
  sseRetryDelayForStatus,
  sseRetryDelayMs,
  shouldSuspendSseForError,
  shouldRefreshSseForAuthError,
  isTerminalSseAuthError,
} from "./useMapBuildStream";

describe("useMapBuildStream generation guard", () => {
  it("removes the request-id prefix from multiplex event ids", () => {
    expect(normalizeStreamCursor("11:12-0")).toBe("12-0");
    expect(normalizeStreamCursor("12-0")).toBe("12-0");
  });

  it("rejects updates from an older connection generation", () => {
    expect(isCurrentStreamGeneration(3, 3)).toBe(true);
    expect(isCurrentStreamGeneration(4, 3)).toBe(false);
  });

  it("uses five fast reconnect delays before switching to low-frequency recovery", () => {
    expect([1, 2, 3, 4, 5].map(sseRetryDelayMs)).toEqual([500, 1000, 2000, 4000, 8000]);
    expect(sseRetryDelayMs(6)).toBe(15000);
    expect(sseRetryDelayMs(20)).toBe(15000);
  });

  it("does not retry authentication or missing-resource responses", () => {
    expect([401, 403, 404].every(isNonRetryableSseStatus)).toBe(true);
    expect(isNonRetryableSseStatus(500)).toBe(false);
    expect(isNonRetryableSseStatus(429)).toBe(false);
  });

  it("uses low-frequency recovery immediately after an SSE connection limit", () => {
    expect([1, 2, 5].map((attempt) => sseRetryDelayForStatus(429, attempt))).toEqual([15000, 15000, 15000]);
    expect(sseRetryDelayForStatus(503, 1)).toBe(500);
  });

  it("suspends the shared connection when the server asks the client to poll", () => {
    expect(shouldSuspendSseForError("sse_connection_limit")).toBe(true);
    expect(shouldSuspendSseForError("sse_budget_unavailable")).toBe(true);
    expect(shouldSuspendSseForError("stream_disconnected")).toBe(false);
  });

  it("refreshes credentials for stream reauthentication but stops for terminal refresh errors", () => {
    expect(shouldRefreshSseForAuthError("stream_reauth_required")).toBe(true);
    expect(shouldRefreshSseForAuthError("access_token_expired")).toBe(true);
    expect(isTerminalSseAuthError("refresh_token_reuse_detected")).toBe(true);
    expect(isTerminalSseAuthError("refresh_temporarily_unavailable")).toBe(false);
  });

  it("stops transport recovery after every terminal task status", () => {
    expect(["completed", "partial", "failed", "needs_clarification"].every(shouldStopStreamForStatus)).toBe(true);
    expect(shouldStopStreamForStatus("processing")).toBe(false);
  });

  it("keeps the stream open after a compatibility status event until done", () => {
    expect(isTransportTerminalStreamEvent("request_completed")).toBe(false);
    expect(isTransportTerminalStreamEvent("request_partial")).toBe(false);
    expect(isTransportTerminalStreamEvent("request_failed")).toBe(false);
    expect(isTransportTerminalStreamEvent("done")).toBe(true);
  });
});
