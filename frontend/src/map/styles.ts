import { Circle, Fill, Stroke, Style, Text } from "ol/style";
import type { LayerPayload } from "../types/api";

export function styleForLayer(layer: LayerPayload) {
  const style = layer.style || {};
  const color = stringValue(style.color) || "#2563eb";
  const faceColor = stringValue(style.facecolor) || color;
  const isPolygon = layer.geometry_type === "Polygon" || layer.geometry_type === "MultiPolygon";
  const edgeColor = stringValue(style.edgecolor) || (isPolygon ? "#334155" : color);
  const alpha = numberValue(style.alpha, 1);
  const lineWidth = isPolygon ? Math.max(numberValue(style.linewidth ?? style.width, 1), 1.1) : Math.max(numberValue(style.linewidth ?? style.width, 1), 0.8);
  const labelField = stringValue(style.label_column ?? style.label_field);

  return new Style({
    // Match Matplotlib: facecolor fills polygons and edgecolor draws borders.
    fill: new Fill({ color: withAlpha(faceColor, alpha) }),
    stroke: new Stroke({ color: edgeColor, width: lineWidth }),
    image: new Circle({ radius: 5, fill: new Fill({ color: withAlpha(color, alpha) }), stroke: new Stroke({ color: edgeColor, width: 1 }) }),
    text: labelField ? new Text({ text: labelField, fill: new Fill({ color: "#172033" }), stroke: new Stroke({ color: "#fff", width: 3 }) }) : undefined,
  });
}

function stringValue(value: unknown): string | undefined {
  return typeof value === "string" && value.trim() ? value : undefined;
}

function numberValue(value: unknown, fallback: number): number {
  const number = typeof value === "number" ? value : Number(value);
  return Number.isFinite(number) ? Math.max(0, number) : fallback;
}

function withAlpha(color: string, alpha: number): string {
  if (alpha >= 1) return color;
  const hex = color.match(/^#([0-9a-f]{3}|[0-9a-f]{6})$/i)?.[1];
  if (!hex) return color;
  const fullHex = hex.length === 3 ? hex.split("").map((value) => value + value).join("") : hex;
  const channels = [0, 2, 4].map((offset) => Number.parseInt(fullHex.slice(offset, offset + 2), 16));
  return `rgba(${channels.join(",")},${Math.min(1, Math.max(0, alpha))})`;
}
