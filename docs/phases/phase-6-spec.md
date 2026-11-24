# Phase 6 spec — Zones and alerts

> Reconstructed after the fact from the approved plan in the working session. From phase 7 on, specs are written and approved before any code.

## Goal
Turn the picture into something an operator can act on.

## Scope
- Polygon zones from config.
- Enter/exit, speeding (once per visit) and dark-ship alerts.
- `/zones`, `/alerts`, alerts on `/live`.
- Zones and an alert panel on the map.

## Out of scope
Alert persistence and acknowledgement, editing zones.

## Acceptance
- Tests for the polygon check and every rule.
- Live run: a real alert fires.
