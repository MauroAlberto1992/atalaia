import { useEffect, useState } from "react";
import { useTrackStore } from "./store";
import type { HistoryWindow } from "./types";

// AIS navigational status codes (ITU-R M.1371).
const NAV_STATUS: Record<number, string> = {
  0: "Under way (engine)", 1: "At anchor", 2: "Not under command", 3: "Restricted manoeuvrability",
  4: "Constrained by draught", 5: "Moored", 6: "Aground", 7: "Fishing", 8: "Under way (sailing)",
  14: "AIS-SART", 15: "Not defined",
};

export function useNow(intervalMs = 1000): number {
  // Lazy initialiser: Date.now() runs once, not on every render.
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), intervalMs);
    return () => clearInterval(id);
  }, [intervalMs]);
  return now;
}

export function ago(iso: string, now: number): string {
  const s = Math.max(0, Math.round((now - Date.parse(iso)) / 1000));
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ${s % 60}s ago`;
  return `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m ago`;
}

function duration(seconds: number): string {
  const m = Math.round(seconds / 60);
  return m >= 60 ? `${Math.floor(m / 60)} h ${m % 60} min` : `${m} min`;
}

const WINDOWS: { value: HistoryWindow; label: string }[] = [
  { value: "live", label: "Live" },
  { value: 1, label: "1 h" },
  { value: 6, label: "6 h" },
  { value: 24, label: "24 h" },
  { value: 168, label: "7 d" },
];

export function ShipPanel() {
  const track = useTrackStore((s) => (s.selected === null ? undefined : s.tracks[s.selected]));
  const historyShip = useTrackStore((s) => s.historyShip);
  const window = useTrackStore((s) => s.window);
  const dbRoute = useTrackStore((s) => s.dbRoute);
  const dbError = useTrackStore((s) => s.dbError);
  const select = useTrackStore((s) => s.select);
  const setWindow = useTrackStore((s) => s.setWindow);
  const now = useNow();
  if (!track && !historyShip) return null;

  const rows: [string, string][] = track
    ? [
        ["MMSI", String(track.mmsi)],
        ["AIS class", track.ais_class === "B" ? "B (small craft)" : "A"],
        ["Position", `${track.latitude.toFixed(5)}, ${track.longitude.toFixed(5)}`],
        ["Speed", `${track.sog.toFixed(1)} kn`],
        ["Course", track.cog < 360 ? `${track.cog.toFixed(1)}°` : "n/a"],
        ["Heading", track.true_heading === 511 ? "n/a" : `${track.true_heading}°`],
        ["Status", NAV_STATUS[track.navigational_status] ?? `Code ${track.navigational_status}`],
        ["Last seen", ago(track.last_seen, now) + (track.stale ? " (stale)" : "")],
      ]
    : historyShip
      ? [
          // Not on the live map: only what the database knows.
          ["MMSI", String(historyShip.mmsi)],
          ["AIS class", historyShip.ais_class === "B" ? "B (small craft)" : "A"],
          ["Last seen", `${ago(historyShip.last_seen, now)} (not live)`],
        ]
      : [];

  if (window === "live" && track) {
    rows.push(["Distance", `${track.distance_nm.toFixed(2)} nm`]);
    rows.push(["Avg speed", `${track.avg_speed_kn.toFixed(1)} kn`]);
  } else if (dbRoute) {
    const st = dbRoute.stats;
    rows.push(["Points", `${st.points}${dbRoute.thinned ? " (thinned)" : ""}`]);
    rows.push(["Distance", `${st.distance_nm.toFixed(1)} nm`]);
    rows.push(["Avg speed", `${st.avg_speed_kn.toFixed(1)} kn (moving)`]);
    rows.push(["Longest gap", st.longest_gap_s > 0 ? duration(st.longest_gap_s) : "none"]);
  }

  const name = track?.ship_name || historyShip?.name || "Unknown";
  return (
    <aside className="panel">
      <header>
        <h2>{name}</h2>
        <button onClick={() => select(null)} aria-label="Close">×</button>
      </header>
      <div className="windows" role="group" aria-label="Route window">
        {WINDOWS.map((w) => (
          <button
            key={w.label}
            className="chip"
            aria-pressed={window === w.value}
            onClick={() => setWindow(w.value)}
          >
            {w.label}
          </button>
        ))}
      </div>
      {window !== "live" && !dbRoute && !dbError && <p className="note">Loading route…</p>}
      {dbError && <p className="note error">{dbError}</p>}
      <dl>
        {rows.map(([k, v]) => (
          <div key={k}><dt>{k}</dt><dd>{v}</dd></div>
        ))}
      </dl>
    </aside>
  );
}
