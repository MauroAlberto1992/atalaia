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
  stale: boolean; // silent for 10+ min
  distance_nm: number; // over the backend's stored history
  avg_speed_kn: number;
}

// GeoJSON order: longitude first.
export type LngLat = [number, number];

// Messages sent by WS /live.
export type Corner = [number, number]; // [lat, lon], backend/config order

// Mirrors backend/src/minicop/zones.py::Zone.
export interface Zone {
  name: string;
  kind: string; // "restricted" | "protected" | "speed"; other values get a default colour
  alert_on_entry: boolean;
  max_speed_kn: number | null;
  polygon: Corner[];
  bbox: [Corner, Corner];
}

// Mirrors backend/src/minicop/alerts.py::Alert.
export interface Alert {
  id: number;
  kind: "enter" | "exit" | "speeding" | "dark";
  mmsi: number;
  ship_name: string;
  zone: string;
  at: string; // ISO 8601, UTC
  message: string;
}

export type LiveMessage =
  | { type: "snapshot"; tracks: Track[]; alerts: Alert[] }
  | { type: "alert"; alert: Alert }
  | { type: "track"; track: Track }
  | { type: "stale"; mmsi: number }
  | { type: "remove"; mmsi: number };

export type ConnectionState = "connecting" | "open" | "closed";
