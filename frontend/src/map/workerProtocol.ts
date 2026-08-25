import type { GeoJsonFeature, GeoJsonFeatureCollection } from "./geojsonParser";

export type GeoJsonWorkerRequest =
  | {
      type: "parse";
      requestId: number;
      layerId: string;
      layerVersion: number;
      collection: GeoJsonFeatureCollection;
      batchSize?: number;
    }
  | { type: "cancel"; requestId: number };

export type GeoJsonWorkerResponse =
  | {
      type: "batch";
      requestId: number;
      layerId: string;
      layerVersion: number;
      features: GeoJsonFeature[];
      featureCount: number;
      extent: [number, number, number, number] | null;
      done: boolean;
    }
  | { type: "error"; requestId: number; layerId: string; layerVersion: number; message: string };
