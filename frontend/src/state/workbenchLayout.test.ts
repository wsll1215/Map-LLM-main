import { describe, expect, it } from "vitest";
import {
  DEFAULT_PANEL_PREFERENCES,
  loadPanelPreferences,
  savePanelPreferences,
  type PanelPreferences,
} from "./workbenchLayout";

function createStorage(initial: Record<string, string> = {}): Storage {
  const values = new Map(Object.entries(initial));
  return {
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, value),
    removeItem: (key) => values.delete(key),
    clear: () => values.clear(),
    key: (index) => [...values.keys()][index] ?? null,
    get length() { return values.size; },
  };
}

describe("workbench panel preferences", () => {
  it("defaults to a collapsed history rail, open inspector, and collapsed log strip", () => {
    expect(DEFAULT_PANEL_PREFERENCES).toEqual({ historyOpen: false, inspectorOpen: true, logsOpen: false });
    expect(loadPanelPreferences(createStorage())).toEqual(DEFAULT_PANEL_PREFERENCES);
  });

  it("migrates the previous layout without keeping history permanently open", () => {
    const storage = createStorage({
      "map-llm:workbench-layout:v1": JSON.stringify({ historyOpen: true, inspectorOpen: false, logsOpen: true }),
    });

    expect(loadPanelPreferences(storage)).toEqual({ historyOpen: false, inspectorOpen: false, logsOpen: true });
  });

  it("restores only valid panel state from storage", () => {
    const storage = createStorage({
      "map-llm:workbench-layout:v1": JSON.stringify({ historyOpen: false, inspectorOpen: true, logsOpen: true }),
    });

    expect(loadPanelPreferences(storage)).toEqual({ historyOpen: false, inspectorOpen: true, logsOpen: true });
  });

  it("ignores malformed or partial preferences", () => {
    const storage = createStorage({
      "map-llm:workbench-layout:v1": JSON.stringify({ historyOpen: false, unexpected: true }),
    });

    expect(loadPanelPreferences(storage)).toEqual(DEFAULT_PANEL_PREFERENCES);
  });

  it("persists the complete panel state as one versioned record", () => {
    const storage = createStorage();
    const preferences: PanelPreferences = { historyOpen: false, inspectorOpen: false, logsOpen: true };

    savePanelPreferences(preferences, storage);

    expect(loadPanelPreferences(storage)).toEqual(preferences);
  });
});
