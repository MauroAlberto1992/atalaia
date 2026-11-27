import { describe, expect, it } from "vitest";
import { zoneLabelPoints } from "./zoneLabels";
import type { Zone } from "./types";

const box: Zone = {
  name: "Box", kind: "restricted", alert_on_entry: true, max_speed_kn: null,
  polygon: [[36.7, -8.4], [36.7, -8.2], [36.8, -8.2], [36.8, -8.4]],
  bbox: [[36.7, -8.4], [36.8, -8.2]],
};

describe("zoneLabelPoints", () => {
  it("gives exactly one point per zone, in its middle, as [lon, lat]", () => {
    const geo = zoneLabelPoints([box]);
    expect(geo.features).toHaveLength(1);
    const g = geo.features[0]?.geometry;
    expect(g?.type).toBe("Point");
    const [lon, lat] = (g as { coordinates: number[] }).coordinates;
    expect(lon).toBeCloseTo(-8.3);
    expect(lat).toBeCloseTo(36.75);
    expect(geo.features[0]?.properties?.name).toBe("Box");
  });
});
