# Phase 14 spec — Routes from the database

Status: proposed, waiting for approval.

## Goal
See where a ship has been over hours or days, from the recorded history, not
only since the service last started. Includes ships that are no longer on the
live map.

## What the data looks like (overnight live run, 22:19–07:19 UTC)
- 11 178 positions from 381 ships (252 Class A, 129 Class B).
- 1 200–1 450 positions per hour, with no gaps.
- **About 30 positions per ship per hour, unevenly spread.** A moving ship can report every few seconds, then go silent for many minutes. **Routes will have gaps**, and the UI must show them honestly instead of drawing a confident straight line across missing data.

## Scope
### Backend
1. **`GET /tracks/{mmsi}/route?hours=N`** (default 24, maximum 168 = 7 days).
   - Ordered points from `positions` (time, lat, lon, sog, cog), using the `(mmsi, time DESC)` index.
   - **Segments**: the route is split wherever two consecutive points are more than 30 min apart. Each segment is drawn on its own, so a gap never becomes a straight line.
   - **Stats over the window**: number of points, distance (haversine, with the same jitter and jump filters as the live history), time covered, average speed, and the longest gap.
   - **Size cap**: at most 5 000 points per request. If there are more, evenly thinned by time, and the response says so.
2. **`GET /ships?hours=N`**: ships seen in the window, from the database, including ships no longer live. For each: MMSI, name, AIS class, last seen, number of points. Default 24 h; ordered by last seen.
3. **Without a database** (`DATABASE_URL` unset): both endpoints answer `503` with a clear message, and the live history (phase 4) keeps working as before.
4. **The database queries live in a small `history_db.py` module** (asyncpg, plain SQL), separate from the recorder: reading never touches the write path.

### Frontend
5. **Window selector in the ship panel**: Live (as today) / 1 h / 6 h / 24 h / 7 d. Choosing a window draws the route from the database.
6. **Honest drawing:**
   - each segment is a solid line;
   - **gaps** between segments are a faint dashed line, with the gap duration on hover;
   - **every actual reported point** is a small dot, so it is clear where the data really is.
7. **Stats in the panel** for the chosen window: points, distance, average speed, longest gap.
8. **"Recent ships" list**: a collapsible list from `/ships` that includes ships no longer on the live map. Clicking one shows its route.

## Out of scope
- Time-slider or animated playback (possible later).
- Area queries ("who crossed this area"): phase 15.
- Server-side simplification such as Douglas–Peucker: thinning by time is enough for now.

## Tests
- **Pure:** splitting into segments at gaps; stats (distance, average speed, longest gap); thinning keeps the first and last points and respects the cap.
- **Integration (real TimescaleDB):** the route query returns ordered points within the window, only for that ship; `/ships` lists ships seen in the window, including ones not in the live state.
- **API:** `503` without a database; a valid request with a database.
- **Frontend:** the reducer/state for the chosen window; a browser check with a fake backend, where one route has a gap and must show as two segments plus a dashed link.

## Acceptance
- All guardrails and CI pass.
- On the developer's Mac, with the overnight data:
  - the 24 h route of a ship that left the live map is visible;
  - gaps are shown as gaps;
  - the panel stats are plausible.
