# Phase 14 — Routes from the database

## Done
- **`routes.py`** (pure):
  - `split_segments`: a new segment wherever reports are more than 30 min apart.
  - `route_stats`: points, distance, moving time, average speed and longest gap. Distance and time are counted **within segments only**, using the same jitter and jump filters as the live history.
  - `thin`: at most 5 000 points, evenly spread by index, keeping the first and last.
- **`history_db.py`**: the read side, with an asyncpg pool created lazily on the first request, separate from the recorder.
  - `route(mmsi, since)` uses the `(mmsi, time DESC)` index.
  - `ships(since)` lists ships with positions in the window, including ones no longer live, with name, AIS class, last seen and number of points.
- **API**:
  - `GET /tracks/{mmsi}/route?hours=1..168` returns the segments and the stats;
  - `GET /ships?hours=1..168` returns the ships seen in the window;
  - both answer `503` with a clear message without a database or when it is down.
- **Frontend**:
  - **Window selector** in the ship panel: Live / 1 h / 6 h / 24 h / 7 d.
  - The recorded route is **drawn honestly**: a solid line per segment, **a faint dashed link across gaps** (hover: "No data for 48 min"), and **a dot for every received report**. The map frames the route.
  - **Panel stats** for the window: points (and whether they were thinned), distance, average speed while moving, longest gap.
  - **"Recent ships (24 h)"**: a collapsible list from `/ships`, including ships no longer on the live map. Clicking one shows its 24 h route.
- **Tests**:
  - 6 pure route tests;
  - an API `503` test;
  - a real-TimescaleDB integration test for both queries (ordering, window, only that ship, ships not in the live state, empty names);
  - 6 frontend tests for the route GeoJSON.
  - Totals: 158 backend (4 against the database), 21 frontend.

## Addendum: direction of travel (requested after the live run)
On the developer's data, a Barreiro–Terreiro do Paço ferry went back and forth, and with plain dots it was impossible to tell which way it was going.
- **Each recorded point is now a chevron (›) pointing the way the ship went next.** The direction is the bearing to the next report; the last point of a segment uses the bearing from the previous one. A lone report, with no neighbour, stays a dot.
- **The reported COG is not used**, because it is often "not available" (360) or noise when the ship is slow.
- **Tests:** compass bearings, the "points to the next one" rule, a ferry going and coming back (0°, 180°, 180°), and lone points.
- **Verified in the browser** against the real backend and database, with an out-and-back route: the chevrons point north on the way out and south on the way back.

## Decisions
- **Gaps are shown, not hidden.** The overnight data showed about 30 reports per ship per hour, unevenly spread. A plain line through the points would claim knowledge we don't have.
- **Statistics exclude gaps.** Distance and average speed over a 45-minute silence are unknown, so they are not counted.
- **Thinning by time, not geometry simplification.** It keeps the time structure of the data, which matters for gaps. Douglas–Peucker can come later if routes get dense.
- **The read pool is lazy.** The API starts even if the database is still coming up, and a failed connection is retried on the next request.
- **A ship from the history list stays selected while not live.** The live-update logic used to clear any selection that wasn't on the live map.

## Verified
- All tests and guardrails pass.
- **Real backend + real TimescaleDB in the browser.** History was written straight into the database: a ship that is no longer live, with a 48-minute silence.
  - It appears in "Recent ships" ("3m ago, 45 pts").
  - Its route is drawn as 2 segments with a dashed gap and dots.
  - The panel shows 45 points, 15.6 nm, 7.2 kn while moving, longest gap 48 min.
  - No console errors.
- **Pending:** the developer's live data (9+ hours recorded overnight).

## What the agent got wrong
| Problem | How it was caught | What changed |
|---|---|---|
| A field was inserted into the wrong place by a scripted edit: the `run_state` signature instead of the `Runtime` class (both had a `recorder: Recorder \| None` line). | ruff syntax error. | Anchored the insertion on the exact `Runtime` line. Lesson again: re-read after scripted edits. |
| An integration-test assertion was written as `[...][::-1][::-1][::-1]`, which is correct but unreadable. | Self-review before running. | The expected list is written out in order, with a comment. |
| The new "select a ship from history" would have been cleared by the existing live-update rule ("selected ship not live, so clear it"). | Reading the store before testing in the browser. | The rule now keeps a selection that came from history. |
| `.panel button` (meant for the close button) made the new window buttons huge, so "7 d" wrapped. | The browser screenshot. | Scoped the rule to `.panel header button`. |

## How to run
No new dependencies (asyncpg came in phase 12). `docker compose up --build`, select a ship, and pick 1 h / 6 h / 24 h / 7 d, or open "Recent ships".
