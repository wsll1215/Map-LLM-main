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
  /** Client-side identity for a viewport-limited Worker response. */
  data_bbox?: [number, number, number, number] | null;
  render_mode?: "geojson" | "geojson-worker" | "mvt" | "pmtiles";
  data_url?: string | null;
  data_source_meta?: DataSourceMeta | null;
  render_spec?: RenderSpec | null;
}

export interface DataSourceMeta {
  dataset_id?: string | null;
  source_type: "local" | "remote" | "upload" | string;
  provider?: string | null;
  source_url?: string | null;
  attribution?: string | null;
  cache_path?: string | null;
  status?: "available" | "pending" | "failed" | string;
  error?: string | null;
}

export interface PreviewMeta {
  image_url?: string | null;
  version?: number | null;
  iteration?: number | null;
  tool_name?: string | null;
  created_at_ms?: number | null;
  is_final?: boolean;
  fallback?: boolean;
}

export interface RenderSpec {
  enabled: boolean;
  attribute?: string | null;
  kind?: "numeric" | "categorical";
  method?: "quantile" | "equal_interval" | "natural_breaks" | "categorical";
  classes?: number;
  breaks?: number[];
  labels?: string[];
  values?: string[];
  colors: string[];
  value_colors?: Record<string, string>;
  no_data_color: string;
  warning_code?: string;
  warning?: string;
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

export type MapStreamEventName = "request_started" | "trace_event" | "tool_started" | "tool_finished" | "llm_started" | "llm_finished" | "data_fetch_started" | "data_fetch_finished" | "render_started" | "render_finished" | "map_initialized" | "layer_upserted" | "map_element_updated" | "process_log" | "assistant_started" | "assistant_delta" | "assistant_message" | "request_completed" | "request_partial" | "request_failed" | "request_needs_clarification" | "done";

export interface MapStreamEvent {
  id: string;
  event: MapStreamEventName | string;
  data: Record<string, unknown>;
}

export type TraceEventType = "run" | "intent_parse" | "validation" | "llm_generation" | "tool_call" | "source_plan" | "data_fetch" | "layer_process" | "render" | "preview_update" | "warning" | "retry" | "error" | "run_finished" | "process_log";

export interface TraceError {
  error_code?: string;
  user_message?: string;
  retryable?: boolean;
  next_action?: string;
  [key: string]: unknown;
}

export interface TraceEvent {
  event_id: string;
  event_seq: number;
  trace_id?: string | null;
  request_id?: number | null;
  run_id?: number | null;
  parent_event_id?: string | null;
  event_type: TraceEventType | string;
  phase?: string;
  actor?: string;
  status: "running" | "success" | "warning" | "error" | "cancelled" | string;
  started_at?: string | null;
  finished_at?: string | null;
  duration_ms?: number | null;
  summary: string;
  has_details?: boolean;
  input?: unknown;
  output?: unknown;
  attributes?: Record<string, unknown>;
  error?: TraceError | null;
}

export interface TraceEventPage {
  items: TraceEvent[];
  next_cursor: number | null;
  total_count?: number;
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
  status: "pending" | "processing" | "needs_clarification" | "completed" | "partial" | "failed";
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
  completion_report?: Record<string, unknown>;
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
