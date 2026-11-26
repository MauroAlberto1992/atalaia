# Phase 13 spec — Class B vessels (small boats)

Status: proposed, waiting for approval.

(Renumbering: "routes from the database" moves to phase 14 and "user-drawn
areas" to phase 15.)

## Problem
Since phase 1 the subscription asks aisstream for `PositionReport` only: AIS
messages 1/2/3, sent by **Class A** transponders (ships over 300 GT, passenger
ships, EU fishing vessels over 15 m). **Class B** transponders, fitted on small
fishing boats, leisure craft and many coastal workboats, send different messages
and are not received at all. On a coast like Portugal's, that is a large share
of the traffic, and exactly the small craft that matter for coastal security.

The phase 12 live run also showed a sparse feed (0.31 positions/s for the whole
coast at night), so more sources of positions also help the routes of phase 14.

## Scope
1. **Capture real frames first** (lesson from phase 1: fixtures from real data).
   - `scripts/watch_positions.py --save N` saves N raw frames per message type to `backend/tests/fixtures/`.
   - The developer runs it on their Mac; the agent's environment can't reach aisstream.
   - The parser is written against those captured frames, not only against documentation.
2. **Subscribe to and parse Class B position messages:**
   - `StandardClassBPositionReport` (message 18);
   - `ExtendedClassBPositionReport` (message 19).

   Both become the same `PositionEvent` as Class A. They carry no navigational status, so the status is set to 15 ("not defined").
3. **`ais_class` ("A" / "B") on `PositionEvent`, `Track` and in the database.** This adds migration `002`, which adds a column to `positions`.
4. **Map:** Class B ships drawn with a **smaller icon**, so small craft are visually distinct. The panel shows "AIS class: B".
5. **Detectors and alerts:** unchanged. Class B boats are subject to the same zone rules and anomaly detection.
   - Class B reports less often (every 30 s under way, every 3 min when slow), well within the 10 min stale threshold.
6. **Counters:** `/health` counts positions per class, to see how much Class B adds.

## Out of scope
- Static and voyage data (`ShipStaticData`, `StaticDataReport`: ship type, size, destination). Useful later for "vessel type" ideas.
- Aids to navigation, base stations, SAR aircraft.

## Tests
- Parsing **captured real** Class B frames (18 and 19), plus the existing Class A tests.
- Status defaults to 15 for Class B.
- The `ais_class` round-trip: parser, then `Track`, then a database row (integration test).
- Migration 002 applies on top of 001, and is idempotent.

## Acceptance
- All guardrails and CI pass.
- A live run on the developer's Mac. The phase summary reports:
  - Class A vs Class B positions per second, and how many extra ships appear;
  - the effect on the overall positions/s measured in phase 12.
- Class B ships are visible on the map with the smaller icon.
