import { useState } from "react";
import {
  ALERT_GROUPS,
  type AlertGroup,
  countByGroup,
  filterAlerts,
  loadShownGroups,
  saveShownGroups,
} from "./alertFilter";
import { useTrackStore } from "./store";
import type { Alert } from "./types";

const ICON: Record<Alert["kind"], string> = {
  enter: "▶",
  exit: "◀",
  speeding: "⚡",
  dark: "◼",
  loitering: "↻",
  rendezvous: "⇄",
  reappeared: "◉",
  spoofing: "⚠",
  coverage_lost: "⊘",
  coverage_restored: "⊕",
  dark_vessel: "◆",
  dark_in_zone: "◆",
  impossible_position: "⛔",
};

const GROUP_LABEL: Record<AlertGroup, string> = { zones: "Zones", behaviour: "Behaviour", system: "System" };

function hhmm(iso: string): string {
  // 24h clock: compact and unambiguous in an operations view.
  return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });
}

export function AlertPanel() {
  const alerts = useTrackStore((s) => s.alerts);
  const focusAlert = useTrackStore((s) => s.focusAlert);
  const markSeen = useTrackStore((s) => s.markSeen);
  // Lazy initialiser: read storage once, not on every render.
  const [shown, setShown] = useState<Set<AlertGroup>>(() => loadShownGroups());
  if (alerts.length === 0) return null;

  const update = (next: Set<AlertGroup>) => {
    setShown(next);
    saveShownGroups(next);
  };
  const toggle = (g: AlertGroup) => {
    const next = new Set(shown);
    if (next.has(g)) next.delete(g);
    else next.add(g);
    update(next);
  };
  const counts = countByGroup(alerts);
  const visible = filterAlerts(alerts, shown);
  const allShown = shown.size === ALERT_GROUPS.length;

  return (
    // Hovering or touching the panel counts as "seen". The filter only affects
    // this list: the "new alerts" badge still counts everything.
    <section className="alerts" onMouseEnter={markSeen} onTouchStart={markSeen}>
      <header>
        <h3>Alerts</h3>
        <div className="filters" role="group" aria-label="Filter alerts">
          {ALERT_GROUPS.map((g) => (
            <button
              key={g}
              className={`chip ${g}`}
              aria-pressed={shown.has(g)}
              onClick={() => toggle(g)}
            >
              {GROUP_LABEL[g]} {counts[g]}
            </button>
          ))}
          {!allShown && (
            <button className="chip all" onClick={() => update(new Set(ALERT_GROUPS))}>
              All
            </button>
          )}
        </div>
      </header>
      <ul>
        {visible.map((a) => (
          <li key={a.id}>
            <button className={`alert ${a.kind}`} onClick={() => focusAlert(a)}>
              <span className="icon">{ICON[a.kind]}</span>
              <span className="time">{hhmm(a.at)}</span>
              <span className="msg">{a.message}</span>
            </button>
          </li>
        ))}
        {visible.length === 0 && <li className="empty">No alerts in the selected groups</li>}
      </ul>
    </section>
  );
}
