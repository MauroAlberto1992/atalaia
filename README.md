# atalaia — Mini-COP

[![CI](https://github.com/MauroAlberto1992/atalaia/actions/workflows/ci.yml/badge.svg)](https://github.com/MauroAlberto1992/atalaia/actions/workflows/ci.yml)

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
- **Anomaly detection**, with each alert explaining why:
  - loitering;
  - two ships meeting at sea (possible transfer);
  - reappearance after an AIS gap, with the distance and implied speed;
  - possible spoofing (repeated impossible jumps).
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
- **Tests:** pytest (104) and Vitest (12), plus a browser check of the production images.

## Run it
You need an API key from https://aisstream.io.

### With Docker (simplest)
```bash
cp .env.example .env        # set AISSTREAM_API_KEY
docker compose up --build   # open http://localhost:8080
```

### For development

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

Areas are configured in `backend/config/areas.toml`, zones in
`backend/config/zones.toml`, and port areas come from OpenStreetMap in
`backend/config/ports.json` (© OpenStreetMap contributors, ODbL). Coordinates there are `[lat, lon]`, latitude first.

## Ideas for next steps
Not planned yet; candidates for a v2. The first two come first: they are
what maritime surveillance work (maritime domain awareness) is actually about.

### Priority 1: anomaly detection (first version done in phase 9)
Loitering, rendezvous, reappearance and spoofing are implemented as explainable rules. Next:
- tune them against real traffic;
- add the ideas below that are not built yet.

Full list of ideas:
- **Loitering:** a ship circling or drifting in one place far from port or fishing grounds.
- **Rendezvous:** two ships meeting at sea at low speed, a possible ship-to-ship transfer (smuggling, sanctions evasion).
- **Going dark:** AIS switched off repeatedly, or in the same places; gaps scored by where and how long.
- **Spoofing:** positions or speeds that are physically inconsistent, or identities (MMSI) seen in two places at once.
- **Illegal fishing:** a fishing pattern inside protected or closed areas.

Start with explainable rules and scores. Each alert says *why*, which an operator can act on.
Add learned models where rules fall short.

### Priority 2: fusion with non-cooperative sensors
AIS only shows ships that *choose* to transmit.
The real value is correlating it with detections that don't depend on the ship: radar, SAR satellite images, or EO/IR cameras on drones.
- Add a second (initially simulated) source: e.g. "drone detections" with position, time and uncertainty.
- **Correlate** each detection with AIS tracks (gating by distance and time, then assignment).
  A detection with no matching AIS track is a **dark vessel**: the most valuable alert of all.
- Show source and confidence per track on the map: AIS only, sensor only, or both.
- **Tasking:** suggest where to send a drone to check an anomaly, ranked by priority and time to reach it.

This is the "data fusion" part of a real Common Operational Picture, and it reuses the architecture as is: one more ingestion task feeding the same queue.

### Persistence: a database
- **PostgreSQL + PostGIS** (or TimescaleDB) for positions, tracks and alerts.
- History survives restarts and is no longer capped at 2000 points per ship.
- Replay a past time window on the map ("what happened here last night?").
- Zone checks can move to SQL (`ST_Contains`) once there are many zones.

### Analytics without AI
- **Fishing hotspots.** Use a grid heatmap of positions from ships reporting status 7 ("fishing"), or moving slowly in a fishing pattern, aggregated by season and time of day.
  This is plain counting, with no model needed.
- **Traffic density and lanes.** The same kind of heatmap over all ships shows the shipping lanes.
- **Port calls.** Moored or anchored periods near ports give arrival and departure times and dwell times.

### Ideas using AI / ML
- **Route prediction.** Start with a baseline that extrapolates the current course and speed (dead reckoning).
  A model trained on past tracks could then predict where a ship will be in 30–60 minutes, and its likely destination.
- **Anomaly detection.** Flag behaviour that doesn't fit the ship's usual pattern:
  - loitering;
  - two ships meeting at sea (possible ship-to-ship transfer);
  - repeated "going dark" in the same place;
  - positions that jump in ways that suggest AIS spoofing.
- **Vessel type from movement.** Classify a ship from how it moves (fishing vs. cargo vs. leisure) when its declared type is missing or doesn't match.
- **Natural-language operator assistant.** An LLM over the live picture and the alerts could answer questions like "which ships went dark near Sagres today?" or write a shift summary.

## Built with AI agents
Most of the code was written by an AI coding agent (Claude Code), directed through:
- written specs per phase;
- a shared context file (`CLAUDE.md`);
- review and live testing by the developer.

Guardrails run before every commit and in CI:
- ruff, mypy (strict) and pytest for the backend;
- eslint, tsc and vitest for the frontend;
- gitleaks for secrets;
- hadolint for the Dockerfiles, plus a CI job that starts the containers and smoke-tests them.

Every phase summary records what the agent got wrong and how it was caught.
See [`docs/ai-workflow.md`](docs/ai-workflow.md).

## How it was built
In phases, each with a plan, tests and a write-up of the decisions in
[`docs/phases/`](docs/phases): data exploration, service, map, history,
resilience, zones and alerts.
