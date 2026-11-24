# Phase 4 spec — Per-ship history

> Reconstructed after the fact from the approved plan in the working session. From phase 7 on, specs are written and approved before any code.

## Goal
Route, distance and average speed per ship.

## Scope
- Haversine in nautical miles.
- `ShipHistory` with a jitter filter (10 m), a jump filter (60 kn) and a bounded deque.
- `GET /tracks/{mmsi}/history`.
- The route of the selected ship is drawn and extended live.

## Out of scope
Persistence.

## Acceptance
- Tests with known distances.
- The route grows live on the map.
