# CLAUDE.md — Mini-COP (atalaia)

## Context
Mini-COP: a live map of ships off the Portuguese coast, with zones and alerts.
A small version of a "Common Operational Picture", built as a portfolio piece to
show defence and security companies (e.g. TEKEVER, ATLAS platform) the ability to build
real-time systems with maps and data fusion.

## v1 scope
- Single source: ships via AIS, from aisstream.io (WebSocket).
- Configurable area: Algarve during development, whole Portuguese coast later.
  The area lives in a config file (`backend/config/areas.toml`, a list of boxes per area), never hard-coded.
- Out of v1: database, login, aircraft, satellites, deploy.

## Stack
- Backend: Python, FastAPI + asyncio, Pydantic.
- Frontend (from phase 3 only): React + Zustand + MapLibre.

## Architecture (finalised in phase 2, see docs/phases/phase-2.md)
One always-on process, event-driven internally (asyncio queues, no broker):
1. Ingestion: task connected to aisstream with automatic reconnection.
   Converts each message into an event.
2. State: sole owner of the MMSI -> Track map (single writer task).
   Flags ships that stopped transmitting (stale after 10 min, removed after 60 min),
   driven by a clock Tick on the same queue.
   Hub: fans out changes to WebSocket clients, dropping slow ones.
   AlertEngine (zones from `backend/config/zones.toml`) runs in the same state task.
3. API: `GET /tracks` (current snapshot) and `WS /live` (real-time changes),
   plus `/tracks/{mmsi}/history`, `/zones`, `/alerts`, `/area`, `/health`.
The browser never connects to aisstream directly.

## aisstream gotchas
- URL: `wss://stream.aisstream.io/v0/stream`
- The subscription message must be sent within 3 seconds of connecting.
- Coordinates are `[latitude, longitude]` — latitude first.
- Enable permessage-deflate (uncompressed connections are rate-limited).
- API key in `.env`, never in the repository.

## Target audience: keep it in mind
The point of this project is to be relevant to defence and security companies
(the user is applying to several; TEKEVER and its ATLAS platform is one example).
When proposing features or priorities, always ask: does this show something
these companies need? Common needs across the sector:
- maritime / situational awareness: a reliable live picture from several sources;
- detecting non-cooperative or "dark" targets;
- sensor and data fusion (AIS + radar, satellite SAR, drone EO/IR);
- anomaly detection (loitering, rendezvous, going dark, spoofing, illegal fishing);
- decision support: helping operators decide where to send assets;
- robustness: works with gaps, noise and bad data.
Prefer generic, sector-wide value over features tailored to one company.
Keep company names out of user-facing text (README, UI); they live here only.

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
frontend/             # React + Zustand + MapLibre (phase 3+)

Status: v1 complete (phases 0-6).
```
