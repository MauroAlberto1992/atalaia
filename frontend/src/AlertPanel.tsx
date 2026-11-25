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
};

function hhmm(iso: string): string {
  // 24h clock: compact and unambiguous in an operations view.
  return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });
}

export function AlertPanel() {
  const alerts = useTrackStore((s) => s.alerts);
  const focusAlert = useTrackStore((s) => s.focusAlert);
  const markSeen = useTrackStore((s) => s.markSeen);
  if (alerts.length === 0) return null;

  return (
    // Hovering or touching the panel counts as "seen".
    <section className="alerts" onMouseEnter={markSeen} onTouchStart={markSeen}>
      <h3>Alerts</h3>
      <ul>
        {alerts.map((a) => (
          <li key={a.id}>
            <button className={`alert ${a.kind}`} onClick={() => focusAlert(a)}>
              <span className="icon">{ICON[a.kind]}</span>
              <span className="time">{hhmm(a.at)}</span>
              <span className="msg">{a.message}</span>
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}
