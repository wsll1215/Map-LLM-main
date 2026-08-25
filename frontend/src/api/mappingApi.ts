import { apiFetch } from "./client";
import type { ChatMessage, GeneratedMap, MapRequestSummary } from "../types/api";

export const mappingApi = {
  async create(prompt: string) { const result = await apiFetch<{ request_id: number }>("/mapping/api/create-request/", { method: "POST", body: JSON.stringify({ request_text: prompt }) }); return { request_id: result.request_id, title: prompt, status: "pending" as const }; },
  process: (id: number) => apiFetch<{ request_id: number }>("/mapping/api/process-request/", { method: "POST", body: JSON.stringify({ request_id: id }) }),
  continue: (id: number, message: string) => apiFetch<{ request_id: number; stream_after_id?: string }>("/mapping/api/continue-conversation/", { method: "POST", body: JSON.stringify({ request_id: id, message }) }),
  status: (id: number) => apiFetch<MapRequestSummary>(`/mapping/api/map-requests/${id}/`),
  async history() { const result = await apiFetch<{ sessions: MapRequestSummary[] }>("/mapping/api/history-maps/"); return result.sessions ?? []; },
  async messages(id: number) { const result = await apiFetch<{ messages: ChatMessage[] }>(`/mapping/api/chat-messages/${id}/`); return result.messages ?? []; },
  async generated(id: number) { const result = await apiFetch<{ maps: GeneratedMap[] }>(`/mapping/api/generated-maps/${id}/`); return result.maps ?? []; },
};
