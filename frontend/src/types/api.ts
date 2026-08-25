import { z } from "zod";

export type GeometryType = "Point" | "MultiPoint" | "LineString" | "MultiLineString" | "Polygon" | "MultiPolygon" | "GeometryCollection";

export interface GeoJsonFeatureCollection {
  type: "FeatureCollection";
  features: Array<{
    type: "Feature";
    geometry: { type: GeometryType; coordinates?: unknown } | null;
    properties?: Record<string, unknown> | null;
    id?: string | number;
  }>;
  truncated?: boolean;
  feature_count?: number;
}

export interface LayerPayload {
  id?: string | null;
  name?: string | null;
  geometry_type?: GeometryType | string | null;
  visible?: boolean;
  z_order?: number;
  data_source?: string | null;
  style?: Record<string, unknown>;
  geojson?: GeoJsonFeatureCollection | null;
  version?: number;
  data_hash?: string | null;
  feature_count?: number;
  extent?: [number, number, number, number] | null;
  render_mode?: "geojson" | "geojson-worker" | "mvt" | "pmtiles";
  data_url?: string | null;
}

export interface ViewStatePayload {
  map?: {
    title?: string | null;
    extent?: [number, number, number, number] | null;
    crs?: string | null;
    background_color?: string;
    layer_count?: number;
  };
  layers?: LayerPayload[];
  annotations?: Array<Record<string, unknown>>;
  elements?: Record<string, unknown>;
  output_path?: string | null;
}

export type MapStreamEventName = "request_started" | "tool_finished" | "map_initialized" | "layer_upserted" | "map_element_updated" | "process_log" | "assistant_message" | "request_completed" | "request_failed" | "request_needs_clarification" | "done";

export interface MapStreamEvent {
  id: string;
  event: MapStreamEventName | string;
  data: Record<string, unknown>;
}

export interface ChatMessage {
  id?: number;
  type: "user" | "assistant" | "system" | "log";
  content: string;
  created_at?: string;
  extra_data?: Record<string, unknown>;
}

export interface MapRequestSummary {
  request_id: number;
  title: string;
  request_text?: string;
  status: "pending" | "processing" | "needs_clarification" | "completed" | "failed";
  created_at?: string;
  updated_at?: string;
  maps?: GeneratedMap[];
  view_state?: ViewStatePayload | null;
  result_message?: string;
  error_message?: string;
  latest_run?: {
    id: number;
    status: string;
    trace_id?: string;
    error_code?: string;
    error_message?: string;
    map_version?: number | null;
  } | null;
  latest_successful_run?: MapRequestSummary["latest_run"];
  has_available_result?: boolean;
  latest_map_version?: number | null;
  clarification?: ClarificationData | null;
}

export interface ClarificationData {
  question?: string;
  missing_fields?: string[];
  suggestions?: string[];
  reason?: string;
}

export interface GeneratedMap {
  id: number;
  request_id: number;
  filename: string;
  version: number;
  file_path: string;
  file_size?: number;
  file_exists?: boolean;
  created_at?: string;
}

export const apiErrorSchema = z.object({
  success: z.boolean().optional(),
  message: z.string().optional(),
  error: z.string().optional(),
});
