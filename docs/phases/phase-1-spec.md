# Phase 1 spec — See the data

> Reconstructed after the fact from the approved plan in the working session. From phase 7 on, specs are written and approved before any code.

## Goal
Prove we can receive and parse live AIS positions.

## Scope
- Script that connects to aisstream with permessage-deflate and sends the subscription within 3 s.
- Pydantic models for the envelope and `PositionReport`; `parse_position()` never raises.
- Prints MMSI, latitude and longitude.
- Tests for parsing and config.

## Out of scope
Reconnection, state, API.

## Acceptance
- Run against the live feed, real ships are printed.
- Invalid frames are dropped without stopping the stream.
