import { describe, expect, it } from "vitest";
import { bearing, routeBounds, routeToGeo } from "./routeGeo";
import type { RouteResponse } from "./types";

const p = (minute: number, lat: number) => ({
  time: new Date(Date.UTC(2026, 10, 27, 2, minute)).toISOString(), lat, lon: -8.5, sog: 6, cog: 0,
});

const route: RouteResponse = {
  mmsi: 1, hours: 24, thinned: false,
  // two segments with a 45-minute silence between them
  segments: [[p(0, 37.0), p(5, 37.01), p(10, 37.02)], [p(55, 37.08), p(59, 37.09)]],
  stats: { points: 5, distance_nm: 1.8, moving_time_s: 840, avg_speed_kn: 7.7, longest_gap_s: 2700 },
};

describe("routeToGeo", () => {
  it("draws one line per segment", () => {
    expect(routeToGeo(route).segments.features).toHaveLength(2);
  });

  it("links segments with a gap carrying its length", () => {
    const gaps = routeToGeo(route).gaps.features;
    expect(gaps).toHaveLength(1);
    expect(gaps[0]?.properties).toEqual({ minutes: 45 });
  });

  it("shows every received point", () => {
    expect(routeToGeo(route).points.features).toHaveLength(5);
  });

  it("a single-point segment is a dot, not a line", () => {
    const lone: RouteResponse = { ...route, segments: [[p(0, 37.0)]] };
    const geo = routeToGeo(lone);
    expect(geo.segments.features).toHaveLength(0);
    expect(geo.points.features).toHaveLength(1);
  });

  it("is empty without a route", () => {
    const geo = routeToGeo(null);
    expect(geo.points.features).toHaveLength(0);
  });
});

describe("routeBounds", () => {
  it("covers all points", () => {
    expect(routeBounds(route)).toEqual([[-8.5, 37.0], [-8.5, 37.09]]);
  });
});

describe("direction of travel", () => {
  it("bearing is clockwise from north", () => {
    const a = p(0, 37.0);
    expect(bearing(a, { ...a, lat: 37.1 })).toBeCloseTo(0);
    expect(bearing(a, { ...a, lon: -8.4 })).toBeCloseTo(90);
    expect(bearing(a, { ...a, lat: 36.9 })).toBeCloseTo(180);
    expect(bearing(a, { ...a, lon: -8.6 })).toBeCloseTo(270);
  });

  it("each point points to the next, the last one keeps the previous direction", () => {
    const pts = routeToGeo(route).points.features.map((f) => f.properties?.bearing as number);
    // both segments head north: every chevron ~0 degrees, including segment ends
    expect(pts.every((b) => b < 1 || b > 359)).toBe(true);
  });

  it("a ferry going and coming back points both ways", () => {
    const ferry: RouteResponse = {
      ...route, segments: [[p(0, 37.0), p(5, 37.05), p(10, 37.0)]],
    };
    const b = routeToGeo(ferry).points.features.map((f) => Math.round(f.properties?.bearing as number));
    expect(b).toEqual([0, 180, 180]);
  });

  it("a lone report is marked as having no direction", () => {
    const lone: RouteResponse = { ...route, segments: [[p(0, 37.0)]] };
    expect(routeToGeo(lone).points.features[0]?.properties?.single).toBe(true);
  });
});
