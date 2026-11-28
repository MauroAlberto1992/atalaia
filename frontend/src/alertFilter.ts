import type { Alert } from "./types";

// A few groups instead of one toggle per kind: ten toggles don't fit in the
// panel header (especially on a phone), and an operator thinks in these terms:
// "where" (zone rules), "how it behaves" (anomalies), and "our own sensors"
// (coverage), which is about reception, not about any ship.
export type AlertGroup = "zones" | "behaviour" | "system";
export const ALERT_GROUPS: AlertGroup[] = ["zones", "behaviour", "system"];

const GROUP_OF: Record<Alert["kind"], AlertGroup> = {
  enter: "zones",
  exit: "zones",
  speeding: "zones",
  dark: "zones",
  loitering: "behaviour",
  rendezvous: "behaviour",
  reappeared: "behaviour",
  spoofing: "behaviour",
  coverage_lost: "system",
  coverage_restored: "system",
  dark_vessel: "system",
  dark_in_zone: "zones",
  impossible_position: "behaviour",
};

export function groupOf(alert: Alert): AlertGroup {
  return GROUP_OF[alert.kind];
}

export function countByGroup(alerts: Alert[]): Record<AlertGroup, number> {
  const counts: Record<AlertGroup, number> = { zones: 0, behaviour: 0, system: 0 };
  for (const a of alerts) counts[groupOf(a)] += 1;
  return counts;
}

export function filterAlerts(alerts: Alert[], shown: ReadonlySet<AlertGroup>): Alert[] {
  return alerts.filter((a) => shown.has(groupOf(a)));
}

// Remembered per browser so a reload keeps the operator's view. Storage can
// be unavailable (private mode, blocked site data): fall back to "show all".
const STORAGE_KEY = "minicop.alertGroups";

export function loadShownGroups(): Set<AlertGroup> {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) {
      const parsed = JSON.parse(raw) as unknown;
      if (Array.isArray(parsed)) {
        return new Set(ALERT_GROUPS.filter((g) => parsed.includes(g)));
      }
    }
  } catch {
    // ignore: use the default below
  }
  return new Set(ALERT_GROUPS);
}

export function saveShownGroups(shown: ReadonlySet<AlertGroup>): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify([...shown]));
  } catch {
    // ignore: the filter still works for this session
  }
}
