import { describe, expect, it } from "vitest";
import { sortShips } from "./shipSort";
import type { ShipSeen } from "./types";

const ship = (mmsi: number, minutesAgo: number, points: number): ShipSeen => ({
  mmsi, name: `S${mmsi}`, ais_class: "A", points,
  last_seen: new Date(Date.UTC(2026, 10, 27, 8, 0) - minutesAgo * 60000).toISOString(),
});

// 1: seen 1 min ago, 10 pts, live. 2: 30 min ago, 500 pts. 3: 5 min ago, 50 pts, live. 4: 2 min ago, 50 pts.
const SHIPS = [ship(2, 30, 500), ship(1, 1, 10), ship(4, 2, 50), ship(3, 5, 50)];
const live = (m: number) => m === 1 || m === 3;
const order = (s: ShipSeen[]) => s.map((x) => x.mmsi);

describe("sortShips", () => {
  it("recent: last seen first", () => {
    expect(order(sortShips(SHIPS, "recent", live))).toEqual([1, 4, 3, 2]);
  });

  it("live first, then recent within each group", () => {
    expect(order(sortShips(SHIPS, "live", live))).toEqual([1, 3, 4, 2]);
  });

  it("points: most first, ties broken by recency", () => {
    expect(order(sortShips(SHIPS, "points", live))).toEqual([2, 4, 3, 1]);
  });

  it("does not mutate the input", () => {
    const copy = [...SHIPS];
    sortShips(SHIPS, "points", live);
    expect(SHIPS).toEqual(copy);
  });
});
