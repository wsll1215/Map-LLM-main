import { Circle, Fill, Stroke, Style, Text } from "ol/style";
import type { LayerPayload } from "../types/api";

export function styleForLayer(layer: LayerPayload) {
  const color = layer.style?.color ?? "#2563eb";
  return new Style({
    fill: new Fill({ color: `${color}55` }),
    stroke: new Stroke({ color, width: Number(layer.style?.width ?? 2) }),
    image: new Circle({ radius: 5, fill: new Fill({ color }), stroke: new Stroke({ color: "#fff", width: 1 }) }),
    text: layer.style?.label_field ? new Text({ text: String(layer.style.label_field), fill: new Fill({ color: "#172033" }), stroke: new Stroke({ color: "#fff", width: 3 }) }) : undefined,
  });
}
