import { describe, expect, it } from "vitest";
import { consumeSseChunk } from "./sse";

describe("consumeSseChunk", () => {
  it("parses complete events and keeps an incomplete frame", () => {
    const first = consumeSseChunk(
      "",
      "id: 1\nevent: request_started\ndata: {\"ok\":true}\n\n"
    );
    const second = consumeSseChunk(first.remainder, "id: 2\nevent: done\ndata: {");

    expect(first.events).toEqual([
      { id: "1", event: "request_started", data: '{"ok":true}' },
    ]);
    expect(second.events).toEqual([]);
    expect(second.remainder).toBe("id: 2\nevent: done\ndata: {");
  });

  it("joins multiline data fields in the SSE-defined way", () => {
    const result = consumeSseChunk(
      "",
      "event: message\ndata: first\ndata: second\n\n"
    );

    expect(result.events[0]).toEqual({
      id: "",
      event: "message",
      data: "first\nsecond",
    });
  });
});
