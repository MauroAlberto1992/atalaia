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
  ais_class: "A" | "B"; // A = ships, B = small craft (fishing, leisure)
  sensor_seen?: string | null; // last (simulated) sensor confirmation, ISO 8601
  // Phase 17a: declared static data and the sea depth here (EMODnet); absent/null when unknown.
  ship_type?: number | null;
  ship_type_label?: string;
  draught_m?: number | null;
  depth_m?: number | null;
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
  kind: string; // "restricted" | "watch" | "protected" | "speed" | "port"; others get a default colour
  source: "config" | "port" | "user"; // "user" = drawn on the map (phase 16), can be deleted
  alert_on_entry: boolean;
  max_speed_kn: number | null;
  polygon: Corner[];
  bbox: [Corner, Corner];
}

// Mirrors backend/src/minicop/alerts.py::Alert.
export interface Alert {
  id: number;
  kind: "enter" | "exit" | "speeding" | "dark" | "loitering" | "rendezvous" | "reappeared" | "spoofing"
    | "coverage_lost" | "coverage_restored" | "dark_vessel" | "dark_in_zone"
    | "impossible_position";
  mmsi: number;
  ship_name: string;
  zone: string | null; // null for behavioural anomalies
  at: string; // ISO 8601, UTC
  message: string; // includes the reason and the numbers behind it
  other_mmsi: number | null; // second ship, for rendezvous
  lat?: number | null; // where, for alerts with no AIS ship (dark vessels)
  lon?: number | null;
}

export type LiveMessage =
  | { type: "snapshot"; tracks: Track[]; alerts: Alert[]; sensor?: SensorSweep | null; dark?: DarkTrack[] }
  | { type: "sensor"; sweep: SensorSweep }
  | { type: "dark"; tracks: DarkTrack[] }
  | { type: "zones" } // drawn areas changed: refetch GET /zones
  | { type: "alert"; alert: Alert }
  | { type: "track"; track: Track }
  | { type: "stale"; mmsi: number }
  | { type: "remove"; mmsi: number };

export type ConnectionState = "connecting" | "open" | "closed";

// Phase 14: recorded history from the database.
export interface RoutePoint {
  time: string; // ISO 8601
  lat: number;
  lon: number;
  sog: number;
  cog: number;
}

export interface RouteStats {
  points: number;
  distance_nm: number; // within segments only
  moving_time_s: number;
  avg_speed_kn: number;
  longest_gap_s: number;
}

// Mirrors backend RouteResponse: the route split where points are > 30 min apart.
export interface RouteResponse {
  mmsi: number;
  hours: number;
  thinned: boolean;
  segments: RoutePoint[][];
  stats: RouteStats;
}

// Mirrors backend history_db.ShipSeen.
export interface ShipSeen {
  mmsi: number;
  name: string;
  ais_class: "A" | "B";
  last_seen: string;
  points: number;
}

// The route window: live (in-memory, as before) or N hours from the database.
export type HistoryWindow = "live" | 1 | 6 | 24 | 168;

// Phase 15: SIMULATED non-cooperative sensor and AIS + sensor fusion.
export interface SensorSweep {
  simulated: true;
  time: string;
  sensor_id: string;
  lat: number; // drone position
  lon: number;
  footprint_nm: number;
  detections: { time: string; lat: number; lon: number; sigma_m: number }[];
}

// A sensor contact that no AIS track explains.
export interface DarkTrack {
  id: string;
  lat: number;
  lon: number;
  sog: number | null; // null until its detections span 3 min (too noisy before)
  cog: number | null;
  detections: number;
  first_seen: string;
  last_seen: string;
  confirmed: boolean;
  // Set when an AIS ship seen in the last hour could be there: not dark, no alert.
  possible_mmsi: number | null;
  possible_name: string;
  possible_ais_age_min: number | null;
}
