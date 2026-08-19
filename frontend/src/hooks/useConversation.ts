import { useCallback } from "react";
import { mappingApi } from "../api/mappingApi";

export function useConversation(requestId: number | null) {
  const loadMessages = useCallback(async () => requestId ? mappingApi.messages(requestId) : [], [requestId]);
  const send = useCallback((message: string) => requestId ? mappingApi.continue(requestId, message) : Promise.reject(new Error("尚未创建地图任务")), [requestId]);
  return { loadMessages, send };
}
