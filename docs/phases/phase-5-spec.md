# Phase 5 spec — Resilience and the whole coast

> Reconstructed after the fact from the approved plan in the working session. From phase 7 on, specs are written and approved before any code.

## Goal
Keep the picture trustworthy over hours, for the whole Portuguese area.

## Scope
- Stale after 10 min, removed after 60 min, driven by a clock tick on the state queue.
- Backoff with jitter; watchdog on silence.
- Multi-box areas: mainland, Madeira and the Azores.

## Out of scope
Persistence, more sources.

## Acceptance
- Tests for the stale/remove rules and the backoff sequence.
- Live run with `MINICOP_AREA=portugal`.
