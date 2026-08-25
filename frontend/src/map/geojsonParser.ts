export interface GeoJsonGeometry {
  type: string;
  coordinates?: unknown;
}

export interface GeoJsonFeature {
  type: "Feature";
  geometry: GeoJsonGeometry | null;
  properties?: Record<string, unknown> | null;
  id?: string | number;
}

export interface GeoJsonFeatureCollection {
  type: "FeatureCollection";
  features: unknown;
}

export interface ParsedFeatureCollection {
  batches: GeoJsonFeature[][];
  featureCount: number;
  extent: [number, number, number, number] | null;
}

export function parseFeatureCollection(
  collection: GeoJsonFeatureCollection,
  batchSize = 500,
): ParsedFeatureCollection {
  if (!Array.isArray(collection.features)) {
    throw new Error("GeoJSON features must be an array");
  }
  if (!Number.isInteger(batchSize) || batchSize < 1) {
    throw new Error("batchSize must be a positive integer");
  }

  const features: GeoJsonFeature[] = [];
  const extent: [number, number, number, number] = [Infinity, Infinity, -Infinity, -Infinity];
  for (const candidate of collection.features) {
    if (!isFeature(candidate) || candidate.geometry === null) continue;
    features.push(candidate);
    extendExtent(extent, candidate.geometry.coordinates);
  }

  const batches: GeoJsonFeature[][] = [];
  for (let index = 0; index < features.length; index += batchSize) {
    batches.push(features.slice(index, index + batchSize));
  }
  return {
    batches,
    featureCount: features.length,
    extent: Number.isFinite(extent[0]) ? extent : null,
  };
}

function isFeature(value: unknown): value is GeoJsonFeature {
  if (!value || typeof value !== "object") return false;
  const feature = value as Partial<GeoJsonFeature>;
  return feature.type === "Feature" && feature.geometry !== undefined;
}

function extendExtent(extent: [number, number, number, number], coordinates: unknown): void {
  if (!Array.isArray(coordinates)) return;
  if (
    coordinates.length >= 2 &&
    typeof coordinates[0] === "number" &&
    typeof coordinates[1] === "number" &&
    Number.isFinite(coordinates[0]) &&
    Number.isFinite(coordinates[1])
  ) {
    extent[0] = Math.min(extent[0], coordinates[0]);
    extent[1] = Math.min(extent[1], coordinates[1]);
    extent[2] = Math.max(extent[2], coordinates[0]);
    extent[3] = Math.max(extent[3], coordinates[1]);
    return;
  }
  for (const child of coordinates) extendExtent(extent, child);
}
