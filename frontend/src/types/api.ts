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

export interface MapStreamEvent {
  id: string;
  event: string;
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
  status: "pending" | "processing" | "completed" | "failed";
  created_at?: string;
  updated_at?: string;
  maps?: GeneratedMap[];
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
