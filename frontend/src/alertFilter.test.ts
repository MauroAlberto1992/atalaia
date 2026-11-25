import { describe, expect, it } from "vitest";
import { countByGroup, filterAlerts, type AlertGroup } from "./alertFilter";
import type { Alert } from "./types";

const alert = (id: number, kind: Alert["kind"]): Alert => ({
  id, kind, mmsi: 1, ship_name: "T", zone: null, at: "2026-11-25T08:00:00Z", message: "m",
  other_mmsi: null,
});

const ALL: Alert[] = [
  alert(1, "enter"), alert(2, "dark"), alert(3, "loitering"), alert(4, "spoofing"), alert(5, "speeding"),
];

describe("alert filter", () => {
  it("counts alerts per group", () => {
    expect(countByGroup(ALL)).toEqual({ zones: 3, behaviour: 2 });
  });

  it("shows only the selected groups, keeping order", () => {
    const behaviour = new Set<AlertGroup>(["behaviour"]);
    expect(filterAlerts(ALL, behaviour).map((a) => a.id)).toEqual([3, 4]);
  });

  it("shows nothing when no group is selected", () => {
    expect(filterAlerts(ALL, new Set())).toEqual([]);
  });
});
