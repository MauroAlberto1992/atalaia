import { create } from "zustand";
import type {
  Alert,
  ConnectionState,
  Corner,
  DarkTrack,
  HistoryWindow,
  SensorSweep,
  LiveMessage,
  LngLat,
  RouteResponse,
  ShipSeen,
  Track,
} from "./types";

const MAX_ALERTS = 200; // same bound as the backend

export interface TrackState {
  tracks: Record<number, Track>; // keyed by MMSI
  connection: ConnectionState;
  selected: number | null;
  route: LngLat[]; // route of the selected ship only
  alerts: Alert[]; // newest first
  unseen: number; // alerts received live since the user last looked
  homeRequests: number;
  zonesVersion: number; // bumped when /live says the drawn areas changed: refetch
  drawing: boolean; // the operator is drawing an area (phase 16)
  draft: Corner[]; // its points so far, [lat, lon]
  draftClosed: boolean; // closed: waiting for a name and a kind // incremented by the "whole area" button; the map frames the area
  focus: LngLat | null; // map flies here when this changes (new array = new request)
  // Phase 14: recorded history for the selected ship.
  window: HistoryWindow; // "live" = in-memory route (as before), else hours from the DB
  dbRoute: RouteResponse | null;
  dbError: string | null; // shown in the panel, e.g. "No database configured"
  historyShip: ShipSeen | null; // selected ship that is no longer on the live map
  // Phase 15: SIMULATED sensor picture.
  sensor: SensorSweep | null;
  dark: DarkTrack[];
  showDetections: boolean;
}

// Pure reducer: given a /live message, return the new tracks map.
// Kept outside the store so it can be unit-tested without React or Zustand.
export function reduceLive(tracks: Record<number, Track>, msg: LiveMessage): Record<number, Track> {
  if (msg.type === "snapshot") {
    // A snapshot replaces everything (also after a reconnect).
    return Object.fromEntries(msg.tracks.map((t) => [t.mmsi, t]));
  }
  if (msg.type === "alert" || msg.type === "sensor" || msg.type === "dark" || msg.type === "zones") return tracks;
  if (msg.type === "stale") {
    const t = tracks[msg.mmsi];
    return t ? { ...tracks, [msg.mmsi]: { ...t, stale: true } } : tracks;
  }
  if (msg.type === "remove") {
    if (!(msg.mmsi in tracks)) return tracks;
    const { [msg.mmsi]: _removed, ...rest } = tracks;
    return rest;
  }
  // New object so React/Zustand see a change.
  return { ...tracks, [msg.track.mmsi]: msg.track };
}

// Pure: alerts list after a /live message (newest first, bounded).
export function reduceAlerts(alerts: Alert[], msg: LiveMessage): Alert[] {
  if (msg.type === "snapshot") return msg.alerts;
  if (msg.type === "alert") return [msg.alert, ...alerts].slice(0, MAX_ALERTS);
  return alerts;
}

// Pure: extend a route with a ship's latest position, unless it hasn't moved.
// (The backend filters GPS jitter more strictly; this only avoids exact duplicates.)
export function appendRoute(route: LngLat[], track: Track): LngLat[] {
  const last = route[route.length - 1];
  if (last && last[0] === track.longitude && last[1] === track.latitude) return route;
  return [...route, [track.longitude, track.latitude]];
}

interface TrackActions {
  applyLive: (msg: LiveMessage) => void;
  setConnection: (c: ConnectionState) => void;
  select: (mmsi: number | null) => void;
  focusAlert: (alert: Alert) => void;
  setWindow: (w: HistoryWindow) => void;
  toggleDetections: () => void;
  selectHistoric: (ship: ShipSeen) => void;
  markSeen: () => void;
  goHome: () => void;
  startDraw: () => void;
  addDraftPoint: (p: Corner) => void;
  closeDraft: () => void;
  cancelDraw: () => void;
  zonesChanged: () => void;
}

export const useTrackStore = create<TrackState & TrackActions>()((set, get) => ({
  tracks: {},
  connection: "connecting",
  selected: null,
  route: [],
  alerts: [],
  unseen: 0,
  focus: null,
  homeRequests: 0,
  zonesVersion: 0,
  drawing: false,
  draft: [],
  draftClosed: false,
  window: "live",
  dbRoute: null,
  dbError: null,
  historyShip: null,
  sensor: null,
  dark: [],
  showDetections: false,

  applyLive: (msg) =>
    set((s) => {
      const tracks = reduceLive(s.tracks, msg);
      const sensorPart =
        msg.type === "snapshot"
          ? { sensor: msg.sensor ?? null, dark: msg.dark ?? [] }
          : msg.type === "sensor"
            ? { sensor: msg.sweep }
            : msg.type === "dark"
              ? { dark: msg.tracks }
              : {};
      const alerts = reduceAlerts(s.alerts, msg);
      const unseen = msg.type === "alert" ? s.unseen + 1 : s.unseen;
      // Drawn areas changed, or (re)connected and possibly missed a change.
      const zonesPart =
        msg.type === "zones" || msg.type === "snapshot" ? { zonesVersion: s.zonesVersion + 1 } : {};
      // The selected ship may be gone (removed, or missing from a new snapshot).
      // A ship picked from the recorded history is meant to be off the live map.
      if (s.selected !== null && !(s.selected in tracks) && s.historyShip === null)
        return { tracks, alerts, unseen, ...sensorPart, ...zonesPart, selected: null, route: [] };
      return {
        tracks,
        alerts,
        unseen,
        ...sensorPart,
        ...zonesPart,
        route:
          msg.type === "track" && msg.track.mmsi === s.selected ? appendRoute(s.route, msg.track) : s.route,
      };
    }),

  setConnection: (connection) => set({ connection }),

  markSeen: () => set({ unseen: 0 }),

  toggleDetections: () => set((s) => ({ showDetections: !s.showDetections })),

  focusAlert: (alert) => {
    const t = get().tracks[alert.mmsi];
    if (!t) {
      // No AIS ship (e.g. a dark vessel): fly to where the alert happened.
      if (alert.lat != null && alert.lon != null) set({ focus: [alert.lon, alert.lat] });
      return;
    }
    get().select(alert.mmsi);
    set({ focus: [t.longitude, t.latitude] });
  },

  setWindow: (w) => {
    const mmsi = get().selected;
    set({ window: w, dbRoute: null, dbError: null });
    if (w === "live" || mmsi === null) return;
    fetch(`/api/tracks/${mmsi}/route?hours=${w}`)
      .then(async (r) => {
        if (!r.ok) {
          const body = (await r.json().catch(() => null)) as { detail?: string } | null;
          throw new Error(body?.detail ?? `HTTP ${r.status}`);
        }
        return (await r.json()) as RouteResponse;
      })
      .then((route) => {
        // Ignore a late answer for another ship or window.
        if (get().selected === mmsi && get().window === w) set({ dbRoute: route });
      })
      .catch((e: unknown) => {
        if (get().selected === mmsi && get().window === w) set({ dbError: String(e) });
      });
  },

  selectHistoric: (ship) => {
    // A ship from the database list, possibly no longer live: show 24 h.
    get().select(ship.mmsi);
    set({ historyShip: ship });
    get().setWindow(24);
  },

  select: (mmsi) => {
    set({ selected: mmsi, route: [], window: "live", dbRoute: null, dbError: null, historyShip: null });
    if (mmsi === null) return;
    fetch(`/api/tracks/${mmsi}/history`)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then((h: { points: { latitude: number; longitude: number }[] }) => {
        // The user may have clicked another ship while this was loading.
        if (get().selected !== mmsi) return;
        const fetched: LngLat[] = h.points.map((p) => [p.longitude, p.latitude]);
        // Live points that arrived during the fetch go after the history,
        // unless the history already contains them.
        const same = (a: LngLat, b: LngLat) => a[0] === b[0] && a[1] === b[1];
        const live = get().route.filter((p) => !fetched.some((f) => same(f, p)));
        set({ route: [...fetched, ...live] });
      })
      .catch(() => {}); // no history: the route just starts from live updates
  },
  goHome: () => set((s) => ({ homeRequests: s.homeRequests + 1 })),
  startDraw: () => set({ drawing: true, draft: [], draftClosed: false }),
  addDraftPoint: (p) => set((s) => (s.drawing && !s.draftClosed ? { draft: [...s.draft, p] } : {})),
  // Closing needs 3 points; the backend checks the rest (crossings, area).
  closeDraft: () => set((s) => (s.draft.length >= 3 ? { draftClosed: true } : {})),
  cancelDraw: () => set({ drawing: false, draft: [], draftClosed: false }),
  zonesChanged: () => set((s) => ({ zonesVersion: s.zonesVersion + 1 })),
}));
