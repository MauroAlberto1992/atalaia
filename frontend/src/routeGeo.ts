import type { FeatureCollection } from "geojson";
import type { RouteResponse } from "./types";

// GeoJSON for a recorded route, drawn honestly (phase 14):
// - segments: solid lines where reports are close in time;
// - gaps: a dashed link between the end of one segment and the start of the
//   next, carrying the gap length, so a silence is never drawn as a track;
// - points: every report actually received.
export interface RouteGeo {
  segments: FeatureCollection;
  gaps: FeatureCollection;
  points: FeatureCollection;
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
      features: segs.flat().map((p) => ({
        type: "Feature",
        geometry: { type: "Point", coordinates: [p.lon, p.lat] },
        properties: { time: p.time },
      })),
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
