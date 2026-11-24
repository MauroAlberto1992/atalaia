# Phase 2 spec — Service

> Reconstructed after the fact from the approved plan in the working session. From phase 7 on, specs are written and approved before any code.

## Goal
An always-on service holding the latest state of every ship.

## Scope
- Ingestion task with simple reconnection.
- Single-writer state task.
- Hub for fan-out to clients.
- `GET /tracks`, `WS /live` (snapshot, then deltas), `GET /health`.
- Out-of-order reports are ignored.

## Out of scope
Stale flagging (phase 5), history (phase 4), UI.

## Acceptance
- Tests for state and API with fake events.
- Live run: `/tracks` and `/live` show real ships.
