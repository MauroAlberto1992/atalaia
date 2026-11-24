import { create } from "zustand";
import type { ConnectionState, LiveMessage, LngLat, Track } from "./types";

export interface TrackState {
  tracks: Record<number, Track>; // keyed by MMSI
  connection: ConnectionState;
  selected: number | null;
  route: LngLat[]; // route of the selected ship only
}

// Pure reducer: given a /live message, return the new tracks map.
// Kept outside the store so it can be unit-tested without React or Zustand.
export function reduceLive(tracks: Record<number, Track>, msg: LiveMessage): Record<number, Track> {
  if (msg.type === "snapshot") {
    // A snapshot replaces everything (also after a reconnect).
    return Object.fromEntries(msg.tracks.map((t) => [t.mmsi, t]));
  }
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
}

export const useTrackStore = create<TrackState & TrackActions>()((set, get) => ({
  tracks: {},
  connection: "connecting",
  selected: null,
  route: [],

  applyLive: (msg) =>
    set((s) => {
      const tracks = reduceLive(s.tracks, msg);
      // The selected ship may be gone (removed, or missing from a new snapshot).
      if (s.selected !== null && !(s.selected in tracks)) return { tracks, selected: null, route: [] };
      return {
        tracks,
        route:
          msg.type === "track" && msg.track.mmsi === s.selected ? appendRoute(s.route, msg.track) : s.route,
      };
    }),

  setConnection: (connection) => set({ connection }),

  select: (mmsi) => {
    set({ selected: mmsi, route: [] });
    if (mmsi === null) return;
    fetch(`/api/tracks/${mmsi}/history`)
      .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
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
