import { describe, expect, it } from "vitest";
import { styleForLayer, styleColorForValue } from "./styles";

describe("styleForLayer", () => {
  it("uses polygon face and edge colors from the realtime payload", () => {
    const style = styleForLayer({
      name: "北京边界",
      geometry_type: "Polygon",
      style: {
        color: "#000000",
        facecolor: "#f4dfaa",
        edgecolor: "#6b4f2a",
        linewidth: 2.5,
        alpha: 0.8,
      },
    });

    expect(style.getFill()?.getColor()).toBe("rgba(244,223,170,0.8)");
    expect(style.getStroke()?.getColor()).toBe("#6b4f2a");
    expect(style.getStroke()?.getWidth()).toBe(2.5);
  });

  it("keeps polygon boundaries visible when the payload omits an edge style", () => {
    const style = styleForLayer({ name: "北京边界", geometry_type: "Polygon", style: { color: "#8B7355", linewidth: 0.4 } });

    expect(style.getStroke()?.getColor()).toBe("#334155");
    expect(style.getStroke()?.getWidth()).toBe(1.1);
  });

  it("keeps dense line layers readable in the realtime preview", () => {
    const style = styleForLayer({ name: "北京道路", geometry_type: "LineString", style: { color: "#8B7355", linewidth: 0.4 } });

    expect(style.getStroke()?.getColor()).toBe("#8B7355");
    expect(style.getStroke()?.getWidth()).toBe(0.8);
  });
});

describe("render spec colors", () => {
  const layer = {
    geometry_type: "Polygon",
    style: { color: "#000000", facecolor: "#000000" },
    render_spec: {
      enabled: true,
      kind: "numeric" as const,
      breaks: [0, 10, 20, 30],
      colors: ["#111111", "#222222", "#333333"],
      no_data_color: "#999999",
    },
  };

  it("uses the shared numeric breaks", () => {
    expect(styleColorForValue(layer, 1)).toBe("#111111");
    expect(styleColorForValue(layer, 10)).toBe("#111111");
    expect(styleColorForValue(layer, 11)).toBe("#222222");
    expect(styleColorForValue(layer, 30)).toBe("#333333");
  });

  it("uses categorical and no-data colors", () => {
    const categorical = {
      ...layer,
      render_spec: {
        enabled: true,
        kind: "categorical" as const,
        colors: ["#111111"],
        value_colors: { A: "#ABCDEF" },
        no_data_color: "#999999",
      },
    };
    expect(styleColorForValue(categorical, "A")).toBe("#ABCDEF");
    expect(styleColorForValue(categorical, null)).toBe("#999999");
  });
});
