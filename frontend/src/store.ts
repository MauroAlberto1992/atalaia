import { create } from "zustand";
import type { Alert, ConnectionState, LiveMessage, LngLat, Track } from "./types";

const MAX_ALERTS = 200; // same bound as the backend

export interface TrackState {
  tracks: Record<number, Track>; // keyed by MMSI
  connection: ConnectionState;
  selected: number | null;
  route: LngLat[]; // route of the selected ship only
  alerts: Alert[]; // newest first
  unseen: number; // alerts received live since the user last looked
  focus: LngLat | null; // map flies here when this changes (new array = new request)
}

// Pure reducer: given a /live message, return the new tracks map.
// Kept outside the store so it can be unit-tested without React or Zustand.
export function reduceLive(tracks: Record<number, Track>, msg: LiveMessage): Record<number, Track> {
  if (msg.type === "snapshot") {
    // A snapshot replaces everything (also after a reconnect).
    return Object.fromEntries(msg.tracks.map((t) => [t.mmsi, t]));
  }
  if (msg.type === "alert") return tracks;
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
  markSeen: () => void;
}

export const useTrackStore = create<TrackState & TrackActions>()((set, get) => ({
  tracks: {},
  connection: "connecting",
  selected: null,
  route: [],
  alerts: [],
  unseen: 0,
  focus: null,

  applyLive: (msg) =>
    set((s) => {
      const tracks = reduceLive(s.tracks, msg);
      const alerts = reduceAlerts(s.alerts, msg);
      const unseen = msg.type === "alert" ? s.unseen + 1 : s.unseen;
      // The selected ship may be gone (removed, or missing from a new snapshot).
      if (s.selected !== null && !(s.selected in tracks))
        return { tracks, alerts, unseen, selected: null, route: [] };
      return {
        tracks,
        alerts,
        unseen,
        route:
          msg.type === "track" && msg.track.mmsi === s.selected ? appendRoute(s.route, msg.track) : s.route,
      };
    }),

  setConnection: (connection) => set({ connection }),

  markSeen: () => set({ unseen: 0 }),

  focusAlert: (alert) => {
    const t = get().tracks[alert.mmsi];
    if (!t) return; // ship already removed: nothing to show
    get().select(alert.mmsi);
    set({ focus: [t.longitude, t.latitude] });
  },

  select: (mmsi) => {
    set({ selected: mmsi, route: [] });
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
}));
