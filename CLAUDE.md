# CLAUDE.md — Mini-COP (atalaia)

## Context
Mini-COP: a live map of ships off the Portuguese coast, with zones and alerts.
A small version of a "Common Operational Picture", built as a portfolio piece to
show defence companies (e.g. TEKEVER, ATLAS platform) the ability to build
real-time systems with maps and data fusion.

## v1 scope
- Single source: ships via AIS, from aisstream.io (WebSocket).
- Configurable area: Algarve during development, whole Portuguese coast later.
  The area lives in a config file (`backend/config/areas.toml`), never hard-coded.
- Out of v1: database, login, aircraft, satellites, deploy.

## Stack
- Backend: Python, FastAPI + asyncio, Pydantic.
- Frontend (from phase 3 only): React + Zustand + MapLibre.

## Architecture (proposal, finalised in phase 2)
One always-on process, event-driven internally (asyncio queues, no broker):
1. Ingestion: task connected to aisstream with automatic reconnection.
   Converts each message into an event.
2. State: sole owner of the MMSI -> Track map. Flags ships that stopped transmitting.
3. API: `GET /tracks` (current snapshot) and `WS /live` (real-time changes).
The browser never connects to aisstream directly.

## aisstream gotchas
- URL: `wss://stream.aisstream.io/v0/stream`
- The subscription message must be sent within 3 seconds of connecting.
- Coordinates are `[latitude, longitude]` — latitude first.
- Enable permessage-deflate (uncompressed connections are rate-limited).
- API key in `.env`, never in the repository.

## Working rules
- Plan before code: present the plan and wait for the user's OK.
- Small steps. Do not add anything outside the current phase.
- The user reads all the code: explain anything non-obvious.
- Tests for the core logic (parsing, state).
- At the end of each phase, write `docs/phases/phase-N.md` with what was done,
  decisions taken, and how to run it.
- Code, comments and documentation in English (chat with the user in Portuguese).

## Phases
0. Setup: project structure and CLAUDE.md.
1. See the data: script that connects to aisstream, parses PositionReport into
   Pydantic models and prints MMSI, latitude and longitude.
2. Service: in-memory state + API.
3. React map.
4. Per-ship history: route, distance (haversine), average speed.
5. Resilience (stale tracks, reconnection) and the whole coast.
6. Zones and alerts.

## Layout
```
backend/
  config/areas.toml   # named bounding boxes
  src/minicop/        # Python package
  tests/              # pytest
docs/phases/          # one file per finished phase
frontend/             # created in phase 3
```
