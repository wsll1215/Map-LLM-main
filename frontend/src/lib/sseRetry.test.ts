import { describe, expect, it } from "vitest";
import { sseResponseErrorCode } from "./sseRetry";

describe("sseResponseErrorCode", () => {
  it("preserves a structured authentication error from a 401 response", () => {
    expect(sseResponseErrorCode(401, "access_token_expired")).toBe("access_token_expired");
  });

  it("normalizes a connection-limit fallback for an unstructured 429", () => {
    expect(sseResponseErrorCode(429, undefined)).toBe("sse_connection_limit");
  });

  it("does not invent an error code for unrelated responses", () => {
    expect(sseResponseErrorCode(503, undefined)).toBeUndefined();
  });
});
