import { Circle, Fill, Stroke, Style, Text } from "ol/style";
import type { FeatureLike } from "ol/Feature";
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

export function styleColorForValue(
  layer: Pick<LayerPayload, "style" | "render_spec">,
  value: unknown,
): string {
  const spec = layer.render_spec;
  if (!spec?.enabled) return stringValue(layer.style?.color) || "#2563eb";
  if (value === null || value === undefined || value === "") return spec.no_data_color;
  if (spec.kind === "categorical") {
    return spec.value_colors?.[String(value)] || spec.no_data_color;
  }
  const breaks = spec.breaks || [];
  const colors = spec.colors || [];
  const number = Number(value);
  if (!Number.isFinite(number) || breaks.length < 2 || colors.length === 0) return spec.no_data_color;
  let index = 0;
  while (index < breaks.length - 2 && number > breaks[index + 1]) index += 1;
  return colors[Math.min(index, colors.length - 1)] || spec.no_data_color;
}

export function styleForFeature(layer: LayerPayload, feature: FeatureLike) {
  const attribute = layer.render_spec?.attribute;
  const value = attribute ? feature.get(attribute) : undefined;
  const color = styleColorForValue(layer, value);
  const style = layer.style || {};
  const isPolygon = layer.geometry_type === "Polygon" || layer.geometry_type === "MultiPolygon";
  const alpha = numberValue(style.alpha, 1);
  const edgeColor = stringValue(style.edgecolor) || (isPolygon ? "#334155" : color);
  return new Style({
    fill: new Fill({ color: withAlpha(color, alpha) }),
    stroke: new Stroke({ color: edgeColor, width: isPolygon ? Math.max(numberValue(style.linewidth, 1), 1.1) : Math.max(numberValue(style.linewidth, 1), 0.8) }),
    image: new Circle({ radius: 5, fill: new Fill({ color: withAlpha(color, alpha) }), stroke: new Stroke({ color: edgeColor, width: 1 }) }),
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
