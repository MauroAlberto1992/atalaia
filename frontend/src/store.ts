import { create } from "zustand";
import type { ConnectionState, LiveMessage, Track } from "./types";

export interface TrackState {
  tracks: Record<number, Track>; // keyed by MMSI
  connection: ConnectionState;
  selected: number | null;
}

// Pure reducer: given a /live message, return the new tracks map.
// Kept outside the store so it can be unit-tested without React or Zustand.
export function reduceLive(tracks: Record<number, Track>, msg: LiveMessage): Record<number, Track> {
  if (msg.type === "snapshot") {
    // A snapshot replaces everything (also after a reconnect).
    return Object.fromEntries(msg.tracks.map((t) => [t.mmsi, t]));
  }
  // New object so React/Zustand see a change.
  return { ...tracks, [msg.track.mmsi]: msg.track };
}

interface TrackActions {
  applyLive: (msg: LiveMessage) => void;
  setConnection: (c: ConnectionState) => void;
  select: (mmsi: number | null) => void;
}

export const useTrackStore = create<TrackState & TrackActions>()((set) => ({
  tracks: {},
  connection: "connecting",
  selected: null,
  applyLive: (msg) => set((s) => ({ tracks: reduceLive(s.tracks, msg) })),
  setConnection: (connection) => set({ connection }),
  select: (selected) => set({ selected }),
}));
