import { describe, expect, it } from "vitest";
import { appendRoute, reduceAlerts, reduceLive } from "./store";
import type { Alert, Track } from "./types";

const track = (mmsi: number, latitude = 37): Track => ({
  mmsi, ship_name: "T", latitude, longitude: -8, sog: 0, cog: 0,
  true_heading: 511, navigational_status: 0, last_seen: "2026-11-24T12:00:00Z", ais_class: "A",
  stale: false, distance_nm: 0, avg_speed_kn: 0,
});

describe("reduceLive", () => {
  it("snapshot replaces all tracks", () => {
    const before = { 1: track(1), 2: track(2) };
    const after = reduceLive(before, { type: "snapshot", tracks: [track(3)], alerts: [] });
    expect(Object.keys(after)).toEqual(["3"]);
  });

  it("track message adds a new ship", () => {
    const after = reduceLive({ 1: track(1) }, { type: "track", track: track(2) });
    expect(Object.keys(after).sort()).toEqual(["1", "2"]);
  });

  it("track message updates an existing ship without mutating the old state", () => {
    const before = { 1: track(1, 37) };
    const after = reduceLive(before, { type: "track", track: track(1, 38) });
    expect(after[1]?.latitude).toBe(38);
    expect(before[1].latitude).toBe(37);
  });
});

describe("appendRoute", () => {
  it("adds the new position in [lon, lat] order", () => {
    expect(appendRoute([], track(1, 37))).toEqual([[-8, 37]]);
  });

  it("skips a position identical to the last one", () => {
    const route: [number, number][] = [[-8, 37]];
    expect(appendRoute(route, track(1, 37))).toBe(route);
  });
});

describe("reduceLive stale/remove", () => {
  it("marks a ship stale", () => {
    const after = reduceLive({ 1: track(1) }, { type: "stale", mmsi: 1 });
    expect(after[1]?.stale).toBe(true);
  });

  it("removes a ship", () => {
    const after = reduceLive({ 1: track(1), 2: track(2) }, { type: "remove", mmsi: 1 });
    expect(Object.keys(after)).toEqual(["2"]);
  });

  it("ignores unknown MMSIs", () => {
    const before = { 1: track(1) };
    expect(reduceLive(before, { type: "stale", mmsi: 9 })).toBe(before);
    expect(reduceLive(before, { type: "remove", mmsi: 9 })).toBe(before);
  });
});

const alert = (id: number): Alert => ({
  id, kind: "enter", mmsi: 1, ship_name: "T", zone: "Z", at: "2026-11-24T12:00:00Z", message: "m",
  other_mmsi: null,
});

describe("reduceAlerts", () => {
  it("snapshot replaces the list", () => {
    expect(reduceAlerts([alert(1)], { type: "snapshot", tracks: [], alerts: [alert(7)] })).toEqual([alert(7)]);
  });

  it("new alert goes first", () => {
    const after = reduceAlerts([alert(1)], { type: "alert", alert: alert(2) });
    expect(after.map((a) => a.id)).toEqual([2, 1]);
  });

  it("is bounded to 200", () => {
    const many = Array.from({ length: 200 }, (_, i) => alert(i));
    expect(reduceAlerts(many, { type: "alert", alert: alert(999) })).toHaveLength(200);
  });

  it("alert messages don't change tracks", () => {
    const before = { 1: track(1) };
    expect(reduceLive(before, { type: "alert", alert: alert(1) })).toBe(before);
  });
});
