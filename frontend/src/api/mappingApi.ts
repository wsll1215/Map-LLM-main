import { apiFetch } from "./client";
import type { ChatMessage, GeneratedMap, MapRequestSummary, TraceEvent, TraceEventPage } from "../types/api";

export const mappingApi = {
  async create(prompt: string) { const result = await apiFetch<{ request_id: number }>("/mapping/api/create-request/", { method: "POST", body: JSON.stringify({ request_text: prompt }) }); return { request_id: result.request_id, title: prompt, status: "pending" as const }; },
  process: (id: number) => apiFetch<{ request_id: number }>("/mapping/api/process-request/", { method: "POST", body: JSON.stringify({ request_id: id }) }),
  continue: (id: number, message: string) => apiFetch<{ request_id: number; stream_after_id?: string }>("/mapping/api/continue-conversation/", { method: "POST", body: JSON.stringify({ request_id: id, message }) }),
  status: (id: number) => apiFetch<MapRequestSummary>(`/mapping/api/map-requests/${id}/`),
  async history() { const result = await apiFetch<{ sessions: MapRequestSummary[] }>("/mapping/api/history-maps/"); return result.sessions ?? []; },
  async messages(id: number) { const result = await apiFetch<{ messages: ChatMessage[] }>(`/mapping/api/chat-messages/${id}/`); return result.messages ?? []; },
  async logs(id: number, runId?: number | null) {
    const query = runId == null ? "" : `?run_id=${encodeURIComponent(runId)}`;
    const result = await apiFetch<{ logs: Array<Record<string, unknown>> }>(`/mapping/api/process-logs/${id}/${query}`);
    return result.logs ?? [];
  },
  async generated(id: number) { const result = await apiFetch<{ maps: GeneratedMap[] }>(`/mapping/api/generated-maps/${id}/`); return result.maps ?? []; },
  async latestPreview(id: number) { return apiFetch<{ preview?: { image_url?: string; created_at_ms?: number } | null }>(`/mapping/api/realtime-preview/${id}/`); },
  async traceEvents(requestId: number, runId: number, params = "limit=100") { return apiFetch<TraceEventPage>(`/mapping/api/map-requests/${requestId}/runs/${runId}/events/${params ? `?${params}` : ""}`); },
  async traceEvent(requestId: number, runId: number, eventId: string) { return apiFetch<TraceEvent>(`/mapping/api/map-requests/${requestId}/runs/${runId}/events/${encodeURIComponent(eventId)}/`); },
};
