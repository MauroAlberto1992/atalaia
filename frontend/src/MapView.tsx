import type { FeatureCollection } from "geojson";
import { MapLibreMap, type GeoJSONSource, type MapLayerMouseEvent } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { useEffect, useRef } from "react";
import { ICON_PIXEL_RATIO, movingIcon, stoppedIcon } from "./shipIcons";
import { useTrackStore } from "./store";
import type { Track } from "./types";

const STYLE_URL = "https://tiles.openfreemap.org/styles/dark"; // free, no API key
const STOPPED_KNOTS = 0.5; // below this, show a circle instead of an arrow

// Area corners from GET /area, in aisstream order: [[lat, lon], [lat, lon]].
type BBox = [[number, number], [number, number]];

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
      properties: { mmsi: t.mmsi, icon: isMoving(t) ? "ship-moving" : "ship-stopped", cog: t.cog },
    })),
  };
}

export function MapView() {
  const container = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MapLibreMap | null>(null);

  // Create the map once.
  useEffect(() => {
    const map = new MapLibreMap({
      container: container.current!,
      style: STYLE_URL,
      center: [-8.0, 38.5], // replaced by the configured area below
      zoom: 6,
    });
    mapRef.current = map;

    fetch("/api/area")
      .then((r) => r.json())
      .then((area: { bbox: BBox }) => {
        const [[latMin, lonMin], [latMax, lonMax]] = area.bbox;
        map.fitBounds([[lonMin, latMin], [lonMax, latMax]], { padding: 20, animate: false });
      })
      .catch(() => {}); // keep the default view if the backend is down

    map.on("load", () => {
      map.addImage("ship-moving", movingIcon(), { pixelRatio: ICON_PIXEL_RATIO });
      map.addImage("ship-stopped", stoppedIcon(), { pixelRatio: ICON_PIXEL_RATIO });
      map.addSource("ships", { type: "geojson", data: toGeoJSON(useTrackStore.getState().tracks) });
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
        },
      });
      map.on("click", "ships", (e: MapLayerMouseEvent) => {
        const mmsi = e.features?.[0]?.properties?.mmsi as number | undefined;
        if (mmsi !== undefined) useTrackStore.getState().select(mmsi);
      });
      map.on("mouseenter", "ships", () => (map.getCanvas().style.cursor = "pointer"));
      map.on("mouseleave", "ships", () => (map.getCanvas().style.cursor = ""));

      // Push store changes into the map. subscribe() runs outside React's
      // render cycle: the map is updated directly, nothing re-renders.
      const sync = () => {
        const { tracks, selected } = useTrackStore.getState();
        (map.getSource("ships") as GeoJSONSource).setData(toGeoJSON(tracks));
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
