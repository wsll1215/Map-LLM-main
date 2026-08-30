import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const css = readFileSync(resolve(process.cwd(), "src/styles/app.css"), "utf8");

describe("live preview layout", () => {
  it("keeps the empty-state prompt in a compact corner status area", () => {
    expect(css).toMatch(/\.map-empty\s*\{[^}]*top:\s*52px[^}]*left:\s*14px[^}]*transform:\s*none/s);
    expect(css).not.toMatch(/\.map-empty\s*\{[^}]*top:\s*50%[^}]*left:\s*50%/s);
  });

  it("keeps the data error below the mode badge", () => {
    expect(css).toMatch(/\.map-data-error, \.map-data-loading\s*\{[^}]*top:\s*56px/s);
  });

  it("does not reserve a fake minimum page width", () => {
    expect(css).toMatch(/body\s*\{[^}]*min-width:\s*0(?:px)?/s);
  });

  it("keeps the intermediate PNG out of the map canvas", () => {
    expect(css).not.toMatch(/\.map-live-preview(?:-wrap|-fallback)?\b/);
  });
});
