# Phase 9 — Anomaly detection

## Done
- **`backend/src/minicop/anomalies.py`**: the `AnomalyDetector`, pure logic run by the state task (still a single writer). It shares the alert engine's id sequence and recent-alerts list. Four detectors, each firing once per episode with the numbers in the message:
  - **loitering**: within the last 30 min the ship moved ≥ 2 nm but stayed within 0.5 nm of the centroid, outside ports. Example: "moved 2.2 nm in 27 min but stayed within 0.21 nm".
  - **rendezvous**: two ships < 0.3 nm apart, both < 2 kn, for ≥ 10 min, outside ports. The partner must have reported in the last 5 min.
  - **reappeared**: a ship reports again after ≥ 30 min without AIS, with the gap, the distance and the implied speed. It works even after the ship was removed from the state, because the last position is remembered for 24 h, with a bounded memory.
  - **spoofing**: ≥ 3 rejected impossible jumps in 10 min (spoofing, or two transmitters with one MMSI).
- **Thresholds in `backend/config/anomalies.toml`.**
- **Port areas (demo)** in `zones.toml`, with `kind = "port"`. Loitering, rendezvous and "dark" alerts are ignored inside them, and ports raise no alerts themselves.
- **`Alert`**: `zone` is optional, and `other_mmsi` is new (for rendezvous). `AlertEngine.record()` is public.
- **`TrackStore`**: records rejected jumps (`jumps_since`), and `SweepResult.removed_tracks` gives the last known state of removed ships.
- **`ShipHistory.recent(since)`**: walks from the newest end, so loitering costs only the window size, not all 2000 points.
- **Frontend**: icons and colours for the new kinds; port zones drawn faintly.
- **Alert filter** (spec addendum): "Zones" / "Behaviour" toggles with counts in the alert panel header, plus "All".
  - It is remembered in `localStorage`, guarded with try/catch so private mode just falls back to showing everything.
  - It filters the list only, not the "new alerts" badge.
  - The filter functions in `alertFilter.ts` are pure and unit-tested.
- **Tests**: 23 new (104 backend in total), all on synthetic, physically plausible tracks:
  - "fires" and "doesn't fire" cases for every detector;
  - once per episode, and re-arming;
  - the grid neighbour search matches brute force on 300 ships;
  - spoofing driven through the real `TrackStore` with alternating reports 60 nm apart.

## Decisions
- **Explainable rules, not ML.** Each alert says why it fired, so an operator can judge it. These rules are the baseline any learned model would have to beat.
- **Grid for rendezvous.** Ships are bucketed in 0.01° cells, at least 0.45 nm in both directions up to 42°N, which is at least the 0.3 nm threshold. Only the 3×3 neighbouring cells are checked, so no close pair is missed and there is no O(n²) scan.
- **Loitering needs a covered window.** The history must span at least 90% of the 30 min window, otherwise a ship we just started seeing would look like it hasn't gone far.
- **Reappearance uses the detector's own last-seen memory**, not the store's stale state. That way gaps longer than the 60 min removal still count.
- **Spoofing counts rejections, not accepted positions.** The history accepts a position after 3 consecutive "jumps"; that one is not counted.
- **Ports exclude dark alerts too.** Switching AIS off in port is normal.

## Verified
- All tests and guardrails pass.
- In a headless browser with a fake backend replaying 50 minutes of scenarios in a few seconds (event times drive the detectors, not the wall clock), all four alerts fired with sensible numbers. Clicking the rendezvous alert selects one of the two ships and flies to them.
- **First live run (developer's machine, area `portugal`, about 107 ships):**
  - port zones visible;
  - a real `reappeared` alert: "TREPADEIRA AZUL reappeared after 30 min without AIS, 1.2 nm from where it vanished (implied 2.3 kn)".
  - **Noise found:** several ships in the Tagus bar went "dark" in the same second (08:19:19), with 31 ships stale at once. That is almost certainly a coverage or feed gap, not ships switching AIS off, so the "dark" alerts were false. Proposed as the next fix.
- **Not yet verified on live data:** The phase spec requires a live run on the developer's machine. How noisy each detector is on real traffic (fishing boats will look like loitering) is still to be reported.

## What the agent got wrong
| Problem | How it was caught | What changed |
|---|---|---|
| The loitering test circled at 4 kn. 30 min of reports sum to 1.99 nm of chords, just under the 2 nm threshold (a chord is shorter than its arc), so the test failed. The detector was right; the test data sat on the edge. | The test itself. | 5 kn (2.48 nm), with a comment. Lesson: keep test data clearly on one side of a threshold. |

## How to run
As before (`docker compose up --build`, or uvicorn + `npm run dev`). Tune the thresholds in `backend/config/anomalies.toml` and restart the backend.
