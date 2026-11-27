import { useState } from "react";
import { ago, useNow } from "./ShipPanel";
import { loadShipSort, saveShipSort, SHIP_SORTS, sortShips, type ShipSort } from "./shipSort";
import { useTrackStore } from "./store";
import type { ShipSeen } from "./types";

// Ships recorded in the last 24 h, including ones no longer on the live map
// (phase 14). Collapsed by default; the list is fetched when opened.
export function RecentShips() {
  const [open, setOpen] = useState(false);
  const [ships, setShips] = useState<ShipSeen[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sort, setSort] = useState<ShipSort>(() => loadShipSort());
  const selectHistoric = useTrackStore((s) => s.selectHistoric);
  const live = useTrackStore((s) => s.tracks);
  const now = useNow(10_000); // "x min ago" only needs coarse updates

  const toggle = () => {
    const next = !open;
    setOpen(next);
    if (!next) return;
    setError(null);
    fetch("/api/ships?hours=24")
      .then(async (r) => {
        if (!r.ok) {
          const body = (await r.json().catch(() => null)) as { detail?: string } | null;
          throw new Error(body?.detail ?? `HTTP ${r.status}`);
        }
        return (await r.json()) as ShipSeen[];
      })
      .then(setShips)
      .catch((e: unknown) => setError(String(e)));
  };

  return (
    <section className="recent">
      <button className="recent-toggle" onClick={toggle} aria-expanded={open}>
        Recent ships (24 h) {open ? "▾" : "▸"}
      </button>
      {open && (
        <div className="recent-body">
          {error && <p className="note error">{error}</p>}
          {!error && !ships && <p className="note">Loading…</p>}
          <div className="sorts" role="group" aria-label="Sort ships">
            {SHIP_SORTS.map((o) => (
              <button
                key={o.value}
                className="chip"
                aria-pressed={sort === o.value}
                onClick={() => {
                  setSort(o.value);
                  saveShipSort(o.value);
                }}
              >
                {o.label}
              </button>
            ))}
          </div>
          <ul>
            {ships && sortShips(ships, sort, (m) => m in live).map((s) => (
              <li key={s.mmsi}>
                <button onClick={() => selectHistoric(s)}>
                  <span className={`dot class-${s.ais_class}`} />
                  <span className="name">{s.name || s.mmsi}</span>
                  <span className="meta">
                    {s.mmsi in live ? "live" : ago(s.last_seen, now)} · {s.points} pts
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}
