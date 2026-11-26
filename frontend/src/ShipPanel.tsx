import { useEffect, useState } from "react";
import { useTrackStore } from "./store";

// AIS navigational status codes (ITU-R M.1371).
const NAV_STATUS: Record<number, string> = {
  0: "Under way (engine)", 1: "At anchor", 2: "Not under command", 3: "Restricted manoeuvrability",
  4: "Constrained by draught", 5: "Moored", 6: "Aground", 7: "Fishing", 8: "Under way (sailing)",
  14: "AIS-SART", 15: "Not defined",
};

function useNow(intervalMs = 1000): number {
  // Lazy initialiser: Date.now() runs once, not on every render.
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), intervalMs);
    return () => clearInterval(id);
  }, [intervalMs]);
  return now;
}

function ago(iso: string, now: number): string {
  const s = Math.max(0, Math.round((now - Date.parse(iso)) / 1000));
  return s < 60 ? `${s}s ago` : `${Math.floor(s / 60)}m ${s % 60}s ago`;
}

export function ShipPanel() {
  const track = useTrackStore((s) => (s.selected === null ? undefined : s.tracks[s.selected]));
  const select = useTrackStore((s) => s.select);
  const now = useNow();
  if (!track) return null;

  const rows: [string, string][] = [
    ["MMSI", String(track.mmsi)],
    ["AIS class", track.ais_class === "B" ? "B (small craft)" : "A"],
    ["Position", `${track.latitude.toFixed(5)}, ${track.longitude.toFixed(5)}`],
    ["Speed", `${track.sog.toFixed(1)} kn`],
    ["Course", track.cog < 360 ? `${track.cog.toFixed(1)}°` : "n/a"],
    ["Heading", track.true_heading === 511 ? "n/a" : `${track.true_heading}°`],
    ["Status", NAV_STATUS[track.navigational_status] ?? `Code ${track.navigational_status}`],
    ["Last seen", ago(track.last_seen, now) + (track.stale ? " (stale)" : "")],
    ["Distance", `${track.distance_nm.toFixed(2)} nm`],
    ["Avg speed", `${track.avg_speed_kn.toFixed(1)} kn`],
  ];

  return (
    <aside className="panel">
      <header>
        <h2>{track.ship_name || "Unknown"}</h2>
        <button onClick={() => select(null)} aria-label="Close">×</button>
      </header>
      <dl>
        {rows.map(([k, v]) => (
          <div key={k}><dt>{k}</dt><dd>{v}</dd></div>
        ))}
      </dl>
    </aside>
  );
}
