# Phase 3 — React map

## Done
- `frontend/`: Vite + React 19 + TypeScript, Zustand, MapLibre GL 6, Vitest.
- `types.ts`: `Track` (mirrors the backend) and the `/live` message types.
- `store.ts`: Zustand store (`tracks` by MMSI, connection state, selected ship).
  The logic is in a pure `reduceLive()` function, which is unit-tested.
- `live.ts`: opens WS `/live` and feeds the store. Reconnects every 3 s; the snapshot sent on each connect rebuilds the state.
- `MapView.tsx`: MapLibre map with the OpenFreeMap dark style.
  - Ships are one GeoJSON source and one symbol layer.
  - The arrow is rotated by COG. A circle is shown when SOG < 0.5 kn or COG is 360 ("not available").
  - A click selects a ship, which gets a yellow ring.
- `ShipPanel.tsx`: details of the selected ship. "Last seen" updates every second.
- `StatusBar.tsx`: connection state and ship count.
- Backend: new `GET /area` returns the configured area, so the map frames it without hard-coding coordinates.
  This was not in the plan; it was needed to respect the "area only in config" rule.

## Decisions
- **Same origin in dev.** The Vite dev server proxies `/api/*` -> `localhost:8000/*` and `/live` (WebSocket), so FastAPI needs no CORS.
- **The map updates outside React.** `useTrackStore.subscribe()` calls `setData()` on the map source directly. React re-renders only the small status bar and panel.
- **One source, no DOM markers.** One `setData()` per change scales to hundreds of ships; one DOM marker per ship does not.
- **Icons drawn on a canvas.** There are no image files. They are drawn at pixel ratio 2 so they stay sharp on retina screens.
- **`icon-allow-overlap`.** Ships are never hidden, even when crowded in port.
- **`optimizeDeps.exclude: ["maplibre-gl"]`.** MapLibre 6 loads its web worker relative to its own module file. Vite's pre-bundling moved the module and the worker failed to load, so no ships were drawn.
- **StrictMode in dev.** Effects mount twice, so a "WebSocket is closed before the connection is established" warning appears once in the console. It is harmless and does not happen in a production build.

## Verified
- 3 frontend tests (store) and 25 backend tests pass; `tsc` and `vite build` are clean.
- Checked in headless Chromium with a fake backend that sends 15 ships:
  - the ships are drawn and the arrows are rotated;
  - a click opens the panel and draws the ring;
  - the status bar shows "Live | 15 ships".
- Not seen from the dev container: the OpenFreeMap basemap (blocked there; a plain background was used) and real aisstream data.

## How to run
Terminal 1 (backend):
```bash
cd backend && source .venv/bin/activate
pip install -e ".[dev]"
uvicorn minicop.api:app
```
Terminal 2 (frontend, Node 20+):
```bash
cd frontend
npm install
npm run dev        # open http://localhost:5173
npm test
```
