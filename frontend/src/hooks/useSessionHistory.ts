import { useCallback, useEffect, useState } from "react";
import { mappingApi } from "../api/mappingApi";
import type { MapRequestSummary } from "../types/api";

export function useSessionHistory() {
  const [history, setHistory] = useState<MapRequestSummary[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try { setHistory(await mappingApi.history()); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "历史成果读取失败"); }
    finally { setLoading(false); }
  }, []);
  useEffect(() => { void refresh(); }, [refresh]);
  return { history, loading, error, refresh };
}
