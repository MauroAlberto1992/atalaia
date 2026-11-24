// Mirrors backend/src/minicop/events.py::Track (JSON form: datetimes are ISO strings).
export interface Track {
  mmsi: number;
  ship_name: string;
  latitude: number;
  longitude: number;
  sog: number; // knots
  cog: number; // degrees
  true_heading: number; // 511 = not available
  navigational_status: number;
  last_seen: string; // ISO 8601, UTC
}

// Messages sent by WS /live.
export type LiveMessage =
  | { type: "snapshot"; tracks: Track[] }
  | { type: "track"; track: Track };

export type ConnectionState = "connecting" | "open" | "closed";
