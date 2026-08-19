import { useCallback, useEffect, useState } from "react";
import { mappingApi } from "../api/mappingApi";
import type { MapRequestSummary } from "../types/api";

export function useSessionHistory() {
  const [history, setHistory] = useState<MapRequestSummary[]>([]);
  const [loading, setLoading] = useState(false);
  const refresh = useCallback(async () => {
    setLoading(true);
    try { setHistory(await mappingApi.history()); } finally { setLoading(false); }
  }, []);
  useEffect(() => { void refresh(); }, [refresh]);
  return { history, loading, refresh };
}
