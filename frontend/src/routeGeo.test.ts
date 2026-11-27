import { describe, expect, it } from "vitest";
import { routeBounds, routeToGeo } from "./routeGeo";
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
