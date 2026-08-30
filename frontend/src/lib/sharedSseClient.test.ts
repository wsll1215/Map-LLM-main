import { describe, expect, it } from "vitest";
import { selectLeader } from "./sharedSseClient";
import { subscriptionNeedsRefresh } from "./sseSubscription";

describe("SSE fallback leader election", () => {
  it("selects one deterministic leader across tabs", () => {
    expect(selectLeader("tab-c", ["tab-b", "tab-a"])).toBe("tab-a");
    expect(selectLeader("tab-c", [])).toBe("tab-c");
  });

  it("detects when a live multiplex connection has a stale request set", () => {
    expect(subscriptionNeedsRefresh(new Set([1, 2]), [1, 2])).toBe(false);
    expect(subscriptionNeedsRefresh(new Set([1]), [1, 2])).toBe(true);
    expect(subscriptionNeedsRefresh(new Set([1, 2]), [2])).toBe(true);
  });
});
