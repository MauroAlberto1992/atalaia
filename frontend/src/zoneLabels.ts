import type { FeatureCollection } from "geojson";
import type { Zone } from "./types";

// One label point per zone. Labelling the polygon itself repeats the name:
// MapLibre cuts GeoJSON into tiles and places a label in every tile the
// polygon crosses. The point is the mean of the vertices, fine for the
// small, convex zones in config (not a true centroid for odd shapes).
export function zoneLabelPoints(zones: Zone[]): FeatureCollection {
  return {
    type: "FeatureCollection",
    features: zones.map((z) => {
      const n = z.polygon.length;
      const lat = z.polygon.reduce((s, [la]) => s + la, 0) / n;
      const lon = z.polygon.reduce((s, [, lo]) => s + lo, 0) / n;
      return {
        type: "Feature" as const,
        geometry: { type: "Point" as const, coordinates: [lon, lat] },
        properties: { name: z.name, kind: z.kind },
      };
    }),
  };
}
