import type { FeatureCollection } from "geojson";
import type { DarkTrack, SensorSweep } from "./types";

export interface SensorGeo {
  footprint: FeatureCollection;
  drone: FeatureCollection;
  detections: FeatureCollection;
  dark: FeatureCollection;
}

// Circle of `radiusNm` around (lat, lon) as a polygon ring [lon, lat], closed.
export function circleRing(lat: number, lon: number, radiusNm: number, sides = 64): [number, number][] {
  const dLat = radiusNm / 60;
  const dLon = radiusNm / (60 * Math.cos((lat * Math.PI) / 180));
  const ring: [number, number][] = [];
  for (let i = 0; i <= sides; i++) {
    const a = (2 * Math.PI * i) / sides;
    ring.push([lon + dLon * Math.cos(a), lat + dLat * Math.sin(a)]);
  }
  return ring;
}

export function darkInfo(d: DarkTrack): string {
  if (d.possible_mmsi !== null) {
    const who = d.possible_name || `MMSI ${d.possible_mmsi}`;
    const age = (d.possible_ais_age_min ?? 0).toFixed(0);
    return `${d.id}: possibly ${who} (MMSI ${d.possible_mmsi}, AIS ${age} min old): no alert. SIMULATED sensor.`;
  }
  const motion =
    d.sog !== null && d.cog !== null
      ? `~${d.sog.toFixed(0)} kn heading ${d.cog.toFixed(0)}°`
      : "speed not yet known";
  return `${d.id}: non-cooperative contact (no AIS), ${d.detections} detections, ${motion}. SIMULATED sensor.`;
}

export function sensorToGeo(sweep: SensorSweep | null, dark: DarkTrack[]): SensorGeo {
  const empty: FeatureCollection = { type: "FeatureCollection", features: [] };
  return {
    footprint: sweep
      ? { type: "FeatureCollection", features: [{ type: "Feature", properties: {},
          geometry: { type: "Polygon", coordinates: [circleRing(sweep.lat, sweep.lon, sweep.footprint_nm)] } }] }
      : empty,
    drone: sweep
      ? { type: "FeatureCollection", features: [{ type: "Feature", properties: { id: sweep.sensor_id },
          geometry: { type: "Point", coordinates: [sweep.lon, sweep.lat] } }] }
      : empty,
    detections: sweep
      ? { type: "FeatureCollection", features: sweep.detections.map((d) => ({ type: "Feature" as const,
          properties: {}, geometry: { type: "Point" as const, coordinates: [d.lon, d.lat] } })) }
      : empty,
    dark: {
      type: "FeatureCollection",
      features: dark.filter((d) => d.confirmed).map((d) => ({ type: "Feature" as const,
        properties: { id: d.id, info: darkInfo(d), possible: d.possible_mmsi !== null },
        geometry: { type: "Point" as const, coordinates: [d.lon, d.lat] } })),
    },
  };
}
