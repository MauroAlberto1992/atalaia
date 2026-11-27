import type { ExpressionSpecification } from "@maplibre/maplibre-gl-style-spec";
import type { FeatureCollection } from "geojson";
import {
  MapLibreMap,
  Popup,
  setWorkerUrl,
  type GeoJSONSource,
  type MapLayerMouseEvent,
} from "maplibre-gl";
// MapLibre 6 loads its web worker from a file next to its own module. The dev
// server serves it from node_modules, but `vite build` does not copy it, so in
// production the request fell through to index.html and no map was drawn.
// Importing it with ?url makes Vite emit the file and gives us its final URL.
import workerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?url";
import "maplibre-gl/dist/maplibre-gl.css";
import { useEffect, useRef } from "react";
import { routeBounds, routeToGeo } from "./routeGeo";
import { chevronIcon, ICON_PIXEL_RATIO, movingIcon, stoppedIcon } from "./shipIcons";
import { useTrackStore } from "./store";
import type { LngLat, Track, Zone } from "./types";

setWorkerUrl(workerUrl);

const STYLE_URL = "https://tiles.openfreemap.org/styles/dark"; // free, no API key
const STOPPED_KNOTS = 0.5; // below this, show a circle instead of an arrow

// Area boxes from GET /area, in aisstream order: [[lat, lon], [lat, lon]].
type Box = [[number, number], [number, number]];

function isMoving(t: Track): boolean {
  // AIS uses COG 360 for "not available": no direction to show.
  return t.sog >= STOPPED_KNOTS && t.cog < 360;
}

// All ships go into one GeoJSON source. Updating one source per change is far
// cheaper than one DOM marker per ship once there are hundreds of ships.
function toGeoJSON(tracks: Record<number, Track>): FeatureCollection {
  return {
    type: "FeatureCollection",
    features: Object.values(tracks).map((t) => ({
      type: "Feature",
      geometry: { type: "Point", coordinates: [t.longitude, t.latitude] }, // GeoJSON: lon first!
      properties: {
        mmsi: t.mmsi,
        icon:
          (isMoving(t) ? "ship-moving" : "ship-stopped") +
          (t.ais_class === "B" ? "-b" : "") +
          (t.stale ? "-stale" : ""),
        cog: t.cog,
        stale: t.stale,
        aisClass: t.ais_class,
      },
    })),
  };
}

// Zone colours by kind; unknown kinds fall back to grey.
const ZONE_COLOR: ExpressionSpecification = ["match", ["get", "kind"], "restricted", "#ef4444", "protected", "#22c55e", "speed", "#f59e0b", "port", "#64748b", "#94a3b8"];
// Ports are context (where stopping is normal), not alert areas: draw them faintly.
const IS_PORT: ExpressionSpecification = ["==", ["get", "kind"], "port"];

function zonesGeoJSON(zones: Zone[]): FeatureCollection {
  return {
    type: "FeatureCollection",
    features: zones.map((z) => ({
      type: "Feature",
      geometry: {
        type: "Polygon",
        // Config is [lat, lon]; GeoJSON is [lon, lat] and wants the ring
        // closed (first vertex repeated at the end). The backend guarantees
        // at least 3 vertices.
        coordinates: [[...z.polygon, ...z.polygon.slice(0, 1)].map(([lat, lon]) => [lon, lat])],
      },
      properties: { name: z.name, kind: z.kind },
    })),
  };
}

function routeGeoJSON(route: LngLat[]): FeatureCollection {
  // A line needs at least two points; an empty collection draws nothing.
  if (route.length < 2) return { type: "FeatureCollection", features: [] };
  return {
    type: "FeatureCollection",
    features: [{ type: "Feature", geometry: { type: "LineString", coordinates: route }, properties: {} }],
  };
}

export function MapView() {
  const container = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MapLibreMap | null>(null);

  // Create the map once.
  useEffect(() => {
    // The div is rendered before effects run, so this only fails on a bug.
    if (!container.current) throw new Error("map container not mounted");
    const map = new MapLibreMap({
      container: container.current,
      style: STYLE_URL,
      center: [-8.0, 38.5], // replaced by the configured area below
      zoom: 6,
    });
    mapRef.current = map;

    fetch("/api/area")
      .then((r) => r.json())
      .then((area: { boxes: Box[] }) => {
        // Frame the union of all boxes (e.g. mainland + Madeira + Azores).
        const lats = area.boxes.flatMap(([[a], [b]]) => [a, b]);
        const lons = area.boxes.flatMap(([[, a], [, b]]) => [a, b]);
        map.fitBounds(
          [[Math.min(...lons), Math.min(...lats)], [Math.max(...lons), Math.max(...lats)]],
          { padding: 20, animate: false },
        );
      })
      .catch(() => {}); // keep the default view if the backend is down

    map.on("load", () => {
      // One image per combination: moving/stopped x Class A/B x live/stale.
      for (const classB of [false, true]) {
        for (const stale of [false, true]) {
          const suffix = (classB ? "-b" : "") + (stale ? "-stale" : "");
          const opts = { pixelRatio: ICON_PIXEL_RATIO };
          map.addImage(`ship-moving${suffix}`, movingIcon(stale, classB), opts);
          map.addImage(`ship-stopped${suffix}`, stoppedIcon(stale, classB), opts);
        }
      }
      map.addSource("ships", { type: "geojson", data: toGeoJSON(useTrackStore.getState().tracks) });
      // Zones, drawn first so they sit under routes and ships.
      map.addSource("zones", { type: "geojson", data: zonesGeoJSON([]) });
      map.addLayer({ id: "zones-fill", type: "fill", source: "zones", paint: { "fill-color": ZONE_COLOR, "fill-opacity": ["case", IS_PORT, 0.05, 0.12] } });
      map.addLayer({ id: "zones-line", type: "line", source: "zones", paint: { "line-color": ZONE_COLOR, "line-width": 1.5, "line-dasharray": [3, 2], "line-opacity": ["case", IS_PORT, 0.4, 1] } });
      map.addLayer({
        id: "zones-label", type: "symbol", source: "zones",
        filter: ["!", IS_PORT],
        layout: { "text-field": ["get", "name"], "text-size": 11 },
        paint: { "text-color": ZONE_COLOR, "text-halo-color": "#0c1220", "text-halo-width": 1.5 },
      });
      // Port names (hundreds, from OpenStreetMap) only when zoomed in.
      map.addLayer({
        id: "ports-label", type: "symbol", source: "zones", minzoom: 12,
        filter: IS_PORT,
        layout: { "text-field": ["get", "name"], "text-size": 10 },
        paint: { "text-color": ZONE_COLOR, "text-halo-color": "#0c1220", "text-halo-width": 1.5 },
      });
      fetch("/api/zones")
        .then((r) => r.json())
        .then((zones: Zone[]) => (map.getSource("zones") as GeoJSONSource).setData(zonesGeoJSON(zones)))
        .catch(() => {});

      // Route of the selected ship, drawn under the ship icons.
      map.addSource("route", { type: "geojson", data: routeGeoJSON([]) });
      map.addLayer({
        id: "route",
        type: "line",
        source: "route",
        layout: { "line-join": "round", "line-cap": "round" },
        paint: { "line-color": "#facc15", "line-width": 2, "line-opacity": 0.8 },
      });
      // Recorded route from the database (phase 14): segments, gaps, points.
      const emptyGeo = routeToGeo(null);
      map.addSource("db-segments", { type: "geojson", data: emptyGeo.segments });
      map.addSource("db-gaps", { type: "geojson", data: emptyGeo.gaps });
      map.addSource("db-points", { type: "geojson", data: emptyGeo.points });
      map.addLayer({
        id: "db-gaps", type: "line", source: "db-gaps",
        // A gap is not a track: faint and dashed, never a confident line.
        paint: { "line-color": "#facc15", "line-width": 1.5, "line-opacity": 0.4, "line-dasharray": [2, 3] },
      });
      map.addLayer({
        id: "db-segments", type: "line", source: "db-segments",
        layout: { "line-join": "round", "line-cap": "round" },
        paint: { "line-color": "#facc15", "line-width": 2, "line-opacity": 0.85 },
      });
      // Each received report: a chevron pointing the way the ship went next;
      // a lone report (no neighbour, no direction) stays a dot.
      map.addImage("route-chevron", chevronIcon(), { pixelRatio: ICON_PIXEL_RATIO });
      map.addLayer({
        id: "db-points", type: "symbol", source: "db-points",
        filter: ["!", ["get", "single"]],
        layout: {
          "icon-image": "route-chevron",
          "icon-rotate": ["get", "bearing"],
          "icon-rotation-alignment": "map", // relative to north, like ship arrows
          "icon-allow-overlap": true,
          "icon-size": 0.8,
        },
      });
      map.addLayer({
        id: "db-points-single", type: "circle", source: "db-points",
        filter: ["get", "single"],
        paint: { "circle-radius": 2.5, "circle-color": "#facc15", "circle-stroke-color": "#0c1220", "circle-stroke-width": 1 },
      });
      // Hovering a gap says how long there was no data.
      const gapPopup = new Popup({ closeButton: false, closeOnClick: false });
      map.on("mousemove", "db-gaps", (e: MapLayerMouseEvent) => {
        const minutes = e.features?.[0]?.properties.minutes as number | undefined;
        if (minutes === undefined) return;
        const text = minutes >= 60 ? `${Math.floor(minutes / 60)} h ${minutes % 60} min` : `${minutes} min`;
        gapPopup.setLngLat(e.lngLat).setText(`No data for ${text}`).addTo(map);
      });
      map.on("mouseleave", "db-gaps", () => gapPopup.remove());

      map.addLayer({
        id: "selected-ring",
        type: "circle",
        source: "ships",
        filter: ["==", ["get", "mmsi"], -1],
        paint: { "circle-radius": 14, "circle-color": "transparent", "circle-stroke-color": "#facc15", "circle-stroke-width": 2 },
      });
      map.addLayer({
        id: "ships",
        type: "symbol",
        source: "ships",
        layout: {
          "icon-image": ["get", "icon"],
          "icon-rotate": ["get", "cog"],
          "icon-rotation-alignment": "map", // rotate relative to north, not the screen
          "icon-allow-overlap": true, // never hide ships, even when crowded in port
          // Class B (small craft) drawn smaller, so they read differently at a glance.
          "icon-size": ["case", ["==", ["get", "aisClass"], "B"], 0.7, 1],
          // Draw live ships on top of stale ones.
          "symbol-sort-key": ["case", ["get", "stale"], 0, 1],
        },
        paint: { "icon-opacity": ["case", ["get", "stale"], 0.6, 1] },
      });
      map.on("click", "ships", (e: MapLayerMouseEvent) => {
        const mmsi = e.features?.[0]?.properties.mmsi as number | undefined;
        if (mmsi !== undefined) useTrackStore.getState().select(mmsi);
      });
      map.on("mouseenter", "ships", () => (map.getCanvas().style.cursor = "pointer"));
      map.on("mouseleave", "ships", () => (map.getCanvas().style.cursor = ""));

      // Push store changes into the map. subscribe() runs outside React's
      // render cycle: the map is updated directly, nothing re-renders.
      let lastFocus: LngLat | null = null;
      let lastDbRoute: unknown = null;
      const sync = () => {
        const { tracks, selected, route, focus, window, dbRoute } = useTrackStore.getState();
        if (focus && focus !== lastFocus) {
          // Same reference = same request; a click on an alert creates a new array.
          lastFocus = focus;
          map.flyTo({ center: focus, zoom: Math.max(map.getZoom(), 11) });
        }
        // setData returns a promise in MapLibre 6; we don't need to wait for it.
        void (map.getSource("ships") as GeoJSONSource).setData(toGeoJSON(tracks));
        // Live route only in "live" mode; a recorded window replaces it.
        void (map.getSource("route") as GeoJSONSource).setData(
          routeGeoJSON(window === "live" ? route : []),
        );
        if (dbRoute !== lastDbRoute) {
          lastDbRoute = dbRoute;
          const geo = routeToGeo(dbRoute);
          void (map.getSource("db-segments") as GeoJSONSource).setData(geo.segments);
          void (map.getSource("db-gaps") as GeoJSONSource).setData(geo.gaps);
          void (map.getSource("db-points") as GeoJSONSource).setData(geo.points);
          const bounds = dbRoute ? routeBounds(dbRoute) : null;
          if (bounds) map.fitBounds(bounds, { padding: 80, maxZoom: 13 });
        }
        map.setFilter("selected-ring", ["==", ["get", "mmsi"], selected ?? -1]);
      };
      sync();
      const unsubscribe = useTrackStore.subscribe(sync);
      map.once("remove", unsubscribe);
    });

    return () => map.remove();
  }, []);

  return <div ref={container} className="map" />;
}
