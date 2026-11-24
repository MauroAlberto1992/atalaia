# Phase 5 — Resilience and the whole coast

## Done
- **Stale tracks.**
  - A ship silent for 10 min is marked `stale` (grey and translucent on the map, "(stale)" in the panel, counted in the status bar).
  - After 60 min it is removed together with its history.
  - `/live` has two new messages: `{"type":"stale","mmsi":…}` and `{"type":"remove","mmsi":…}`.
  - A stale ship that reports again is fresh again.
- **Robust reconnection.**
  - Exponential backoff with jitter: 1, 2, 4, … up to 60 s, each delay randomised between 50% and 100%.
  - The backoff is reset only after a connection that stayed up for 60 s.
  - Watchdog: 120 s without any message forces a reconnect.
  - `/health` adds `last_message_at` and `reconnects`.
- **Whole coast.**
  - An area is now a list of boxes.
  - `portugal` = mainland coast band + Madeira/Porto Santo + Azores.
  - `/area` returns all boxes and the map frames their union.
- Tests: 67 backend tests and 8 frontend tests.

## Decisions
- **Expiry goes through the event queue.** A clock task puts a `Tick` on the same queue as positions every 30 s.
  The state task stays the single writer of the store (no locks), and the order relative to positions is well defined.
- **Thresholds.** Class A ships report every 2–10 s under way and every 3 min when moored, so 10 min of silence is abnormal.
  Removal at 60 min bounds memory as ships pass through the area.
- **Stale is reported once.** The sweep only reports changes, so the hub isn't flooded every 30 s.
- **Backoff reset only after a stable connection.** A connect-then-drop loop (e.g. a bad API key, or aisstream overloaded) keeps backing off instead of retrying every second.
- **Watchdog.** A TCP connection can look open while nothing arrives, for example after a dead NAT mapping. `asyncio.wait_for(ws.recv(), 120)` turns silence into an error.
- **Several boxes, not one.** One box covering mainland + Azores would subscribe to about 20° of open Atlantic and its traffic.
- **Selected ship removed.** If the selected ship is removed, the selection and route are cleared.
- **Stale ships drawn under live ones.** `symbol-sort-key` puts them below.

## Verified
- All tests pass.
- Headless Chromium with a fake backend of 30 ships across the mainland, Madeira and the Azores (6 of them stale):
  - the map frames all three regions;
  - the status bar shows "30 ships (6 stale)".
- Not verified from the dev container: real traffic volume for the whole coast, and real reconnections.

## How to run
In `.env`, set `MINICOP_AREA=portugal`, then run the backend and frontend as in phase 3.
`curl localhost:8000/health` shows `reconnects` and `last_message_at`.
