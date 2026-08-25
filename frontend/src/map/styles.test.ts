import { describe, expect, it } from "vitest";
import { styleForLayer } from "./styles";

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
