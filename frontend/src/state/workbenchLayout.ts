export interface PanelPreferences {
  historyOpen: boolean;
  inspectorOpen: boolean;
  logsOpen: boolean;
}

export const DEFAULT_PANEL_PREFERENCES: PanelPreferences = {
  historyOpen: false,
  inspectorOpen: true,
  logsOpen: false,
};

const STORAGE_KEY = "map-llm:workbench-layout:v2";
const LEGACY_STORAGE_KEY = "map-llm:workbench-layout:v1";

function storageOrNull(storage?: Storage): Storage | null {
  if (storage) return storage;
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

function isPanelPreferences(value: unknown): value is PanelPreferences {
  if (!value || typeof value !== "object") return false;
  const candidate = value as Record<string, unknown>;
  return typeof candidate.historyOpen === "boolean"
    && typeof candidate.inspectorOpen === "boolean"
    && typeof candidate.logsOpen === "boolean";
}

export function loadPanelPreferences(storage?: Storage): PanelPreferences {
  const target = storageOrNull(storage);
  if (!target) return DEFAULT_PANEL_PREFERENCES;
  try {
    const raw = target.getItem(STORAGE_KEY);
    if (raw) {
      const parsed: unknown = JSON.parse(raw);
      return isPanelPreferences(parsed) ? parsed : DEFAULT_PANEL_PREFERENCES;
    }

    const legacyRaw = target.getItem(LEGACY_STORAGE_KEY);
    if (!legacyRaw) return DEFAULT_PANEL_PREFERENCES;
    const legacyParsed: unknown = JSON.parse(legacyRaw);
    if (!isPanelPreferences(legacyParsed)) return DEFAULT_PANEL_PREFERENCES;
    const migrated = { ...legacyParsed, historyOpen: false };
    target.setItem(STORAGE_KEY, JSON.stringify(migrated));
    return migrated;
  } catch {
    return DEFAULT_PANEL_PREFERENCES;
  }
}

export function savePanelPreferences(preferences: PanelPreferences, storage?: Storage): void {
  const target = storageOrNull(storage);
  if (!target) return;
  try {
    target.setItem(STORAGE_KEY, JSON.stringify(preferences));
  } catch {
    // A full or disabled browser storage should not block the workbench.
  }
}
