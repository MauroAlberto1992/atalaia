import type { FeatureCollection } from "geojson";
import type { RoutePoint, RouteResponse } from "./types";

// GeoJSON for a recorded route, drawn honestly (phase 14):
// - segments: solid lines where reports are close in time;
// - gaps: a dashed link between the end of one segment and the start of the
//   next, carrying the gap length, so a silence is never drawn as a track;
// - points: every report actually received, as a chevron pointing the way the
//   ship went next (the bearing to the next report; the last point of a
//   segment uses the bearing from the previous one). Not the reported COG,
//   which is often "not available" (360) or noise when slow.
export interface RouteGeo {
  segments: FeatureCollection;
  gaps: FeatureCollection;
  points: FeatureCollection;
}

// Initial bearing from a to b in degrees clockwise from north. Flat
// approximation (longitude scaled by cos(lat)), fine between nearby reports.
export function bearing(a: RoutePoint, b: RoutePoint): number {
  const dx = (b.lon - a.lon) * Math.cos((a.lat * Math.PI) / 180);
  const dy = b.lat - a.lat;
  return ((Math.atan2(dx, dy) * 180) / Math.PI + 360) % 360;
}

function bearingsOf(seg: RoutePoint[]): number[] {
  return seg.map((p, i) => {
    const next = seg[i + 1];
    const prev = seg[i - 1];
    if (next) return bearing(p, next);
    if (prev) return bearing(prev, p);
    return 0; // a single report: no direction known
  });
}

export function routeToGeo(route: RouteResponse | null): RouteGeo {
  const empty: FeatureCollection = { type: "FeatureCollection", features: [] };
  if (!route) return { segments: empty, gaps: empty, points: empty };
  const segs = route.segments.filter((s) => s.length > 0);
  return {
    segments: {
      type: "FeatureCollection",
      features: segs
        .filter((s) => s.length >= 2) // a single point is shown as a dot only
        .map((s) => ({
          type: "Feature",
          geometry: { type: "LineString", coordinates: s.map((p) => [p.lon, p.lat]) },
          properties: {},
        })),
    },
    gaps: {
      type: "FeatureCollection",
      features: segs.slice(1).flatMap((next, i) => {
        const prev = segs[i];
        const a = prev?.[prev.length - 1];
        const b = next[0];
        if (!a || !b) return [];
        const minutes = Math.round((Date.parse(b.time) - Date.parse(a.time)) / 60000);
        return [{
          type: "Feature" as const,
          geometry: { type: "LineString" as const, coordinates: [[a.lon, a.lat], [b.lon, b.lat]] },
          properties: { minutes },
        }];
      }),
    },
    points: {
      type: "FeatureCollection",
      features: segs.flatMap((seg) => {
        const bearings = bearingsOf(seg);
        return seg.map((p, i) => ({
          type: "Feature" as const,
          geometry: { type: "Point" as const, coordinates: [p.lon, p.lat] },
          // single: no neighbour, so no direction: drawn as a dot, not a chevron
          properties: { time: p.time, bearing: bearings[i] ?? 0, single: seg.length === 1 },
        }));
      }),
    },
  };
}

// [[west, south], [east, north]] of all points, for framing the route.
export function routeBounds(route: RouteResponse): [[number, number], [number, number]] | null {
  const pts = route.segments.flat();
  if (pts.length === 0) return null;
  const lons = pts.map((p) => p.lon);
  const lats = pts.map((p) => p.lat);
  return [[Math.min(...lons), Math.min(...lats)], [Math.max(...lons), Math.max(...lats)]];
}
