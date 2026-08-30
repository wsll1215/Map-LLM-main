import { describe, expect, it } from "vitest";
import { shouldPollTaskStatus } from "./useTaskStatus";

describe("task status polling", () => {
  it("polls only while the stream is not connected", () => {
    expect(shouldPollTaskStatus(true, "connecting")).toBe(true);
    expect(shouldPollTaskStatus(true, "reconnecting")).toBe(true);
    expect(shouldPollTaskStatus(true, "polling")).toBe(true);
    expect(shouldPollTaskStatus(true, "connected")).toBe(false);
    expect(shouldPollTaskStatus(false, "polling")).toBe(false);
  });
});
