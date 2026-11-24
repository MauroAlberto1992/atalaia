# Phase 4 — Per-ship history

## Done
- `geo.py`: `haversine_nm()` gives the great-circle distance in nautical miles.
- `history.py`: `ShipHistory` stores a bounded route, a running distance, and stats (`distance_nm`, `duration_s`, `avg_speed_kn`).
- `TrackStore` keeps one `ShipHistory` per ship.
  `Track` now carries `distance_nm` and `avg_speed_kn`, so the stats reach the map through `/live` with no extra requests.
- `GET /tracks/{mmsi}/history` returns the route points and stats, or 404 for an unknown MMSI.
- Frontend:
  - Selecting a ship fetches its history and draws it as a yellow line.
  - Live updates for that ship extend the line.
  - The panel shows distance and average speed.
- Tests: 39 backend tests and 5 frontend tests.

## Decisions
- **Nautical miles.** They are the maritime unit, and 1 kn = 1 nm/h, so `distance / hours` is already in knots.
- **Haversine (spherical Earth).** The error is under 0.5% compared with the ellipsoid, which is fine at this scale.
- **Jitter filter (10 m).** A point less than 10 m from the last one is not added to the route or the distance.
  A moored ship's GPS wanders a few metres on every report; without the filter it would add up to kilometres while standing still.
  The track itself still updates (`last_seen`, speed, status).
- **Jump filter (60 kn).** A point that would need more than 60 kn since the last one is rejected as a GPS glitch.
  The track does not move to it.
  After 3 consecutive rejections the new position is accepted, because then the old position was probably the wrong one, or there was a long gap.
  The jump is not counted as distance.
- **Bounded history.** At most 2000 points per ship, kept in a `deque`.
  Each point stores its distance from the previous one, so when the oldest point is evicted, the first segment is subtracted in O(1) instead of recomputing everything.
- **Route only for the selected ship.** Sending every route on every `/live` message would be heavy.
  The route is fetched once on selection and then extended from `/live`.
  Live points that arrive while the fetch is in flight are kept, and appended after the history if it doesn't already contain them.
- **Memory only.** History is lost when the service restarts; a database is out of v1.
- **Known differences.**
  - The frontend extends the line with every live position. It skips only exact duplicates and does not apply the backend's 10 m filter, so the drawn line can include a few jitter points the backend ignores.
  - The average speed covers the stored window, including time spent stopped. It is "average over the window", not "average while moving".

## Verified
- All tests pass.
- Checked in headless Chromium with a fake backend sending moving ships:
  - clicking a ship draws its route;
  - the route grows live;
  - the panel shows distance and average speed.

## How to run
Same as phase 3: `uvicorn minicop.api:app` in `backend/`, `npm run dev` in `frontend/`. Click a ship to see its route.

## What the agent got wrong

| Problem | How it was caught | What changed |
|---|---|---|
| Put route stats on `Track`, a change from the plan. | Flagged by the agent. | Same rule as above: state deviations explicitly. |
| Debugging a screenshot for several minutes because an old fake server was still running on the port. | Agent noticed the API response didn't match the code. | Test servers run with `--strictPort` and earlier ones are killed first. |
