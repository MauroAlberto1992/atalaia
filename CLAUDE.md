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
- Out of v1: login, aircraft, satellites, hosting. (Docker since phase 8, database since phase 12.)

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
   AlertEngine (zones from `backend/config/zones.toml`) and AnomalyDetector
   (thresholds in `backend/config/anomalies.toml`) and CoverageMonitor run in the same state task.
4. Recorder (phase 12): accepted positions -> bounded in-process buffer -> batched COPY into
   PostgreSQL + TimescaleDB + PostGIS (`db` service; migrations in `backend/migrations`).
   Never blocks the live path; optional (off without `DATABASE_URL`).
3. API: `GET /tracks` (current snapshot) and `WS /live` (real-time changes),
   plus `/tracks/{mmsi}/history`, `/tracks/{mmsi}/route`, `/ships`, `/zones`, `/alerts`,
   `/area`, `/health`.
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
- Plan before code: write `docs/phases/phase-N-spec.md` (goal, scope, out of
  scope, acceptance) and wait for the user's OK.
- Guardrails must pass before every commit (`pre-commit`); never use `--no-verify`.
- Any deviation from an approved spec is stated explicitly, with the reason.
- Small steps. Do not add anything outside the current phase.
- The user reads all the code: explain anything non-obvious.
- Tests for the core logic (parsing, state).
- At the end of each phase, write `docs/phases/phase-N.md` with what was done,
  decisions taken, how to run it, and "What the agent got wrong" (problem,
  how it was caught, what changed). Add each lesson to "Lessons learned" below.
- Code, comments and documentation in English (chat with the user in Portuguese).
- When a change adds or changes a dependency (backend/pyproject.toml, frontend/package.json),
  say so explicitly in the run instructions for the user, with the reinstall command:
  `cd backend && pip install -e ".[dev]"` and/or `cd frontend && npm install`.
  Docker rebuilds install everything; the user's local venv does not (phase 12: the
  pre-commit hooks failed on the user's Mac because asyncpg was missing).

## Phases
0. Setup: project structure and CLAUDE.md.
1. See the data: script that connects to aisstream, parses PositionReport into
   Pydantic models and prints MMSI, latitude and longitude.
2. Service: in-memory state + API.
3. React map.
4. Per-ship history: route, distance (haversine), average speed.
5. Resilience (stale tracks, reconnection) and the whole coast.
6. Zones and alerts.
7. AI workflow and guardrails (see docs/ai-workflow.md).
8. Docker: `docker compose up --build` -> http://localhost:8080.
9. Anomaly detection: loitering, rendezvous, reappearance after AIS gaps, spoofing.
10. Coverage gaps: many ships silent together = one coverage alert, not many "dark" alerts.
11. Real port list from OpenStreetMap (config/ports.json, 359 ports, ODbL).
12. Record every position in TimescaleDB/PostGIS.
13. Class B vessels (small craft): messages 18/19, ais_class everywhere, smaller icon.
14. Routes from the database: window 1 h-7 d, segments split at gaps, honest drawing, recent ships.
15. Sensor fusion (SIMULATED drone sensor): AIS association, dark-vessel tracks and alerts, evaluation.
Next: 16 user-drawn areas. (Sparse-AIS false darks: mitigated, 38 -> 4; a dark vessel next to AIS ships can hide, see phase-15.md.)

## Layout
```
backend/
  config/areas.toml   # named bounding boxes
  src/minicop/        # Python package
  tests/              # pytest
docs/phases/          # one file per finished phase
frontend/             # React + Zustand + MapLibre (phase 3+)
docker-compose.yml    # backend + nginx frontend (phase 8)

Status: v1 complete (phases 0-6); phase 7 adds guardrails and the AI workflow docs.
```

## Lessons learned (from "What the agent got wrong")
- Check the user's runtime versions (Python, Node) before choosing dependencies;
  read the `engines` field of key packages and declare minimums, and enforce
  them (npm `engine-strict`); a declaration that only warns is not a guardrail.
- Don't default to the newest major version; prefer what the tooling around it supports.
- Measure external services before trusting library defaults (timeouts, first messages).
- Build test fixtures from real captured data, not only from documentation.
- Test data must be physically plausible (speeds, distances, times).
- Verify UI changes in a real browser; passing tests and builds are not enough.
  Verify the artefact that ships (production build / Docker image), not only the dev server.
- Test a new guardrail against the old, broken version: if it doesn't fail there, it isn't a guardrail.
- SPA fallbacks (`try_files ... /index.html`) can hide missing files behind a 200; assets must 404.
- Logs for dropped data say where and include a truncated sample.
- Geographic or domain data needs a source, or is labelled as demo in the UI itself.
  Memory is not a reference, not even for test coordinates (they were 66-560 m off).
- Inspect real exported data before trusting a parser written from docs (Overpass relations had no centre).
- Claims in docs (e.g. "precomputed") are checked against the code in review.
- Declare every package the code imports; no reliance on transitive dependencies.
- Kill old dev servers before testing; use strict ports.
- "What the agent got wrong" entries must be real events from the session; never write a
  plausible-sounding one. An empty section is better than an invented one.
- Test a diagnosis before applying the fix (e.g. pg_isready socket vs TCP turned out to make no difference).
- Integration tests against the real dependency catch what unit tests with assumptions miss.
- `git stash` does not stash new untracked files: to compare before/after for a new file, patch in memory.
- A probabilistic rule (M-of-N) has a non-zero false-alarm rate: test that it is bounded, not zero.
- Keep test data clearly on one side of a threshold (e.g. chord vs arc made 4 kn fall just under 2 nm).
- A demo/speed option is verified by its end result (contacts confirmed), not only by its inputs (drone moving).
- In a simulated scenario, measure that the sensor actually sees the targets before handing it over.
