import type { ShipSeen } from "./types";

export type ShipSort = "recent" | "live" | "points";

export const SHIP_SORTS: { value: ShipSort; label: string }[] = [
  { value: "recent", label: "Recent" },
  { value: "live", label: "Live first" },
  { value: "points", label: "Points" },
];

// Pure: returns a new array, never mutates the input.
// - recent: last seen first;
// - live: ships on the live map first, then the rest; most recent first within each;
// - points: most recorded points first (ties: most recent first).
export function sortShips(ships: ShipSeen[], sort: ShipSort, isLive: (mmsi: number) => boolean): ShipSeen[] {
  const byRecent = (a: ShipSeen, b: ShipSeen) => Date.parse(b.last_seen) - Date.parse(a.last_seen);
  const sorted = [...ships];
  if (sort === "recent") return sorted.sort(byRecent);
  if (sort === "points") return sorted.sort((a, b) => b.points - a.points || byRecent(a, b));
  return sorted.sort((a, b) => Number(isLive(b.mmsi)) - Number(isLive(a.mmsi)) || byRecent(a, b));
}

// Remembered per browser; storage may be unavailable (private mode).
const KEY = "minicop.shipSort";
export function loadShipSort(): ShipSort {
  try {
    const v = localStorage.getItem(KEY);
    if (v === "recent" || v === "live" || v === "points") return v;
  } catch {
    // ignore: default below
  }
  return "recent";
}
export function saveShipSort(v: ShipSort): void {
  try {
    localStorage.setItem(KEY, v);
  } catch {
    // ignore: the choice still works for this session
  }
}
