# atalaia — Mini-COP

A small **Common Operational Picture**: a live map of ships off the Portuguese
coast (mainland, Madeira and Azores), built from real AIS data, with route
history, zones and alerts.

![Mini-COP](docs/screenshot.png)

## What it does
- **Live AIS ingestion** from aisstream.io over WebSocket.
  - Reconnects with backoff and jitter.
  - A watchdog reconnects after 2 minutes of silence.
- **Track state** for every ship.
  - Out-of-order reports are dropped.
  - Ships silent for 10 min are flagged stale and removed after 60 min.
- **Route history** per ship.
  - Haversine distance and average speed.
  - Filters GPS jitter and impossible jumps.
- **Zones and alerts.**
  - Entry and exit of restricted areas.
  - Speeding in speed-limited zones.
  - "Dark ship": a ship stops transmitting inside a zone.
- **Browser map** (React + MapLibre) that updates live: ships rotate with their course, stale ships fade, and clicking an alert flies to the ship.

## Architecture
```
aisstream ──► ingestion ──► asyncio.Queue ──► state task ──► TrackStore + AlertEngine
                               ▲                  │
                         clock Tick (30 s)        └──► Hub ──► WS /live ──► React + Zustand + MapLibre
                                                              GET /tracks, /tracks/{mmsi}/history,
                                                              /zones, /alerts, /area, /health
```
- **One process, event-driven, no broker.**
- **One task owns all state (single writer).** Positions and clock ticks share one queue, so no locks are needed.
- **The browser never talks to aisstream.** It gets a snapshot, then deltas, over a single WebSocket.

## Stack
- **Backend:** Python 3.11+, FastAPI, asyncio, Pydantic, websockets.
- **Frontend:** React 19, TypeScript, Zustand, MapLibre GL, Vite.
- **Tests:** pytest (81) and Vitest (12).

## Run it
You need an API key from https://aisstream.io.

```bash
cp .env.example .env        # set AISSTREAM_API_KEY; MINICOP_AREA=algarve or portugal

# backend (Python 3.11+)
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
uvicorn minicop.api:app     # http://localhost:8000
pytest

# frontend (Node 22.12+), in another terminal
cd frontend
npm install
npm run dev                 # http://localhost:5173
npm test
```

Areas are configured in `backend/config/areas.toml` and zones in
`backend/config/zones.toml`. Coordinates there are `[lat, lon]`, latitude first.

## How it was built
In phases, each with a plan, tests and a write-up of the decisions in
[`docs/phases/`](docs/phases): data exploration, service, map, history,
resilience, zones and alerts.
