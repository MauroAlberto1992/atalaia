import { describe, expect, it } from "vitest";
import { circleRing, darkInfo, sensorToGeo } from "./sensorGeo";
import type { DarkTrack, SensorSweep } from "./types";

const sweep: SensorSweep = {
  simulated: true, time: "2026-11-27T10:00:00Z", sensor_id: "SIM-DRONE-1", lat: 36.9, lon: -8.5,
  footprint_nm: 5, detections: [{ time: "2026-11-27T10:00:00Z", lat: 36.91, lon: -8.51, sigma_m: 150 }],
};
const dark = (id: string, confirmed: boolean): DarkTrack => ({
  id, lat: 36.88, lon: -8.45, sog: 6, cog: 210, detections: 4, confirmed,
  first_seen: "2026-11-27T09:58:00Z", last_seen: "2026-11-27T10:00:00Z",
  possible_mmsi: null, possible_name: "", possible_ais_age_min: null,
});

describe("sensorToGeo", () => {
  it("draws the footprint, the drone and the detections", () => {
    const geo = sensorToGeo(sweep, []);
    expect(geo.footprint.features).toHaveLength(1);
    expect(geo.drone.features).toHaveLength(1);
    expect(geo.detections.features).toHaveLength(1);
  });

  it("shows only confirmed dark tracks", () => {
    const geo = sensorToGeo(sweep, [dark("D-1", true), dark("D-2", false)]);
    expect(geo.dark.features.map((f) => String(f.properties?.id))).toEqual(["D-1"]);
    expect(String(geo.dark.features[0]?.properties?.info)).toContain("SIMULATED");
  });

  it("is empty without a sensor", () => {
    const geo = sensorToGeo(null, []);
    expect(geo.footprint.features).toHaveLength(0);
  });
});

describe("dark info", () => {
  it("says when the speed is not known yet", () => {
    const fresh = { ...dark("D-3", true), sog: null, cog: null };
    expect(darkInfo(fresh).lines.join(" ")).toContain("speed not yet known");
  });

  it("names the AIS ship that could explain a contact, and marks it grey", () => {
    const maybe = { ...dark("D-4", true), possible_mmsi: 263000001, possible_name: "MAR AZUL", possible_ais_age_min: 12.4 };
    const info = darkInfo(maybe);
    expect(info.title).toBe("D-4: possibly an AIS ship");
    expect(info.lines[0]).toBe("MAR AZUL (MMSI 263000001), last AIS 12 min ago, could be here.");
    expect(info.mmsi).toBe(263000001);
    expect(sensorToGeo(sweep, [maybe]).dark.features[0]?.properties?.possible).toBe(true);
  });

  it("does not repeat the MMSI when the ship has no name", () => {
    const maybe = { ...dark("D-5", true), possible_mmsi: 211392060, possible_ais_age_min: 14 };
    expect(darkInfo(maybe).lines[0]).toBe("unnamed (MMSI 211392060), last AIS 14 min ago, could be here.");
  });
});

describe("circleRing", () => {
  it("is closed and has the right radius north-south", () => {
    const ring = circleRing(36.9, -8.5, 5);
    expect(ring[0]).toEqual(ring[ring.length - 1]);
    const maxLat = Math.max(...ring.map((p) => p[1]));
    expect((maxLat - 36.9) * 60).toBeCloseTo(5, 1);
  });
});
