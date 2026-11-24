# Phase 2 — Service: in-memory state + API

## Done
- `events.py`: internal types. `PositionEvent` is one report; `Track` is the latest state of a ship.
- `parsing.py`: `parse_aisstream_time()` turns aisstream's Go-style timestamp into a UTC datetime.
  `parse_event()` turns a frame into a `PositionEvent`.
- `ingest.py`: always-on connection to aisstream. On any failure it reconnects after 5 s.
  `IngestStatus` tells `/health` whether it is connected.
- `state.py`: `TrackStore`, the only owner of `MMSI -> Track`. Pure logic.
- `hub.py`: fan-out of updates to WebSocket clients. Each client has a bounded queue.
- `api.py`: FastAPI app with the lifespan that starts the ingestion and state tasks, and:
  - `GET /tracks`: snapshot (list of tracks).
  - `WS /live`: first `{"type":"snapshot","tracks":[...]}`, then one `{"type":"track","track":{...}}` per change.
  - `GET /health`: `aisstream_connected`, `tracks`, `live_clients`.
- Script: a missing API key now prints a one-line error instead of a traceback.
- Tests: 24 in total (time parsing, events, state, hub, API with fake events).

## Architecture (final for v1)
```
aisstream ─► ingestion task ─► asyncio.Queue[PositionEvent] ─► state task ─► TrackStore
                                                                   │
                                                                   └─► Hub ─► one queue per /live client
GET /tracks reads TrackStore directly.
```
- **One task writes the store (the state task).** Everything runs in one event loop, so no locks are needed.
- **The store has no asyncio.** It is plain Python, so it can be tested without an event loop.

## Decisions
- **Out-of-order reports are ignored.** An event with `received_at <= last_seen` is dropped. Time comes from aisstream's `time_utc`, not from our clock.
- **Name fallback.** An empty ship name keeps the last known name.
- **Snapshot-first WebSocket.** `/live` subscribes to the hub and takes the snapshot with no `await` in between. In single-threaded asyncio that is atomic, so no update falls between the two.
- **Slow clients are dropped, not waited for.** `publish()` never awaits. A full client queue (1000) means the client is disconnected with code 1013 ("try again later"), so it never delays the others.
- **Bounded event queue (10 000).** If the state task falls behind, ingestion waits, which gives back-pressure instead of unbounded memory.
- **Simple reconnection.** Fixed 5 s delay on any failure, including an `{"error": ...}` frame from aisstream. Backoff is phase 5.
- **`create_app(ingest=False)`.** Tests run the real app without aisstream. They inject events through `app.state.events` and wait with `queue.join()`.
- **Deferred.** Stale-track flagging moves to phase 5, as in the phase list.

## Verified
- All tests pass.
- The service starts. `/health` and `/tracks` answer. With aisstream unreachable, ingestion logs the failure and keeps retrying every 5 s.
- The live aisstream connection was not tested from the dev container, whose network blocks aisstream; run it locally.

## How to run
```bash
cd backend
source .venv/bin/activate
pip install -e ".[dev]"            # new deps: fastapi, uvicorn, httpx
uvicorn minicop.api:app
# other terminal:
curl localhost:8000/health
curl localhost:8000/tracks
pytest
```
To watch `/live`: `python -m websockets ws://localhost:8000/live`.

## What the agent got wrong

| Problem | How it was caught | What changed |
|---|---|---|
| A state test moved a ship 6 nm in 10 s. That passed then, but is physically impossible. | Phase 4: the new jump filter rejected it and the test failed. | Test data must be physically plausible (speeds, distances, times). |
