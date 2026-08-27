import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const css = readFileSync(resolve(process.cwd(), "src/styles/app.css"), "utf8");

describe("live preview layout", () => {
  it("keeps the data error below the mode badge", () => {
    expect(css).toMatch(/\.map-data-error, \.map-data-loading\s*\{[^}]*top:\s*56px/s);
  });

  it("keeps the normal PNG preview below the mode badge", () => {
    expect(css).toMatch(/\.map-live-preview-wrap\s*\{[^}]*top:\s*56px/s);
  });

  it("turns the PNG fallback into a full canvas preview", () => {
    expect(css).toMatch(
      /\.map-live-preview-fallback\s*\{[^}]*left:\s*14px[^}]*right:\s*14px[^}]*top:\s*116px[^}]*bottom:\s*64px/s,
    );
    expect(css).toMatch(
      /\.map-live-preview-fallback \.map-live-preview\s*\{[^}]*width:\s*min\(100%,\s*760px\)/s,
    );
  });
});
