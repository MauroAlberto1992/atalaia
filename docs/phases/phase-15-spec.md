# Phase 15 spec — Sensor fusion: finding "dark" vessels

Status: approved.

(User-drawn areas move to phase 16.)

## Goal
AIS only shows ships that *choose* to transmit. Add a second, **non-cooperative**
sensor whose detections don't depend on the ship, fuse its detections with the
AIS tracks, and raise an alert when something is detected that **no AIS track
explains**: a dark vessel. This is the "data fusion" part of a Common
Operational Picture, and the second priority in the README.

## The sensor: simulated, and labelled as such
There is no free real radar, SAR or drone feed. The sensor is a **simulator**:
- A **patrol drone** flies a configured loop. Its sensor footprint is a circle of about 5 nm radius.
- **Each sweep** (every 30 s) it detects:
  - **real AIS ships** inside the footprint, with probability of detection Pd = 0.9 and position error of about 150 m (1σ);
  - **scripted dark targets**: simulated ships that move but never transmit AIS (for example a slow boat crossing to a rendezvous). They are inside the footprint only part of the time;
  - **false alarms** (clutter): a few random detections per sweep.
- **Everything is configurable** in `backend/config/sensors.toml`, and **labelled "SIMULATED"** in the code, the API, the UI and the docs.
- Because the simulator knows the ground truth, **the fusion can be measured honestly** (see Acceptance).

## Scope
1. **`Detection` event**: time, position, position error and sensor id. It is produced by the simulator task and put **on the same event queue** as AIS positions. The state task stays the single writer; the architecture doesn't change, it gains a source.
2. **Association** (`fusion.py`, pure):
   - **Predict** each AIS track to the detection time (dead reckoning from its last position, SOG and COG; tracks older than 10 min are not used).
   - **Gate** at about 0.5 nm, widened by the time since the last AIS report.
   - **Assign** with global nearest neighbour inside the gate, so one detection goes to at most one track and one track gets at most one detection per sweep.
3. **Results:**
   - **Fused**: a detection associated with an AIS track. The track is marked "AIS + sensor", with the time it was last confirmed by the sensor.
   - **Unassociated**: the detection starts or updates a **candidate non-cooperative track**.
   - **Confirmation (M-of-N)**: a candidate becomes a **dark vessel track** after **3 detections in 5 sweeps** that are consistent in position and speed. Single clutter detections never confirm. A track with no detection for 10 min is dropped.
   - A confirmed dark track raises a **`dark_vessel` alert** (System group): "Non-cooperative contact: 4 detections, no AIS, ~6 kn heading 210°".
4. **API and map:**
   - The live picture includes **dark tracks**, with a distinct icon (a red diamond) and source "sensor only";
   - fused AIS tracks show a small "sensor" badge;
   - **the drone and its footprint** are drawn;
   - **raw detections** can be shown as faint dots (a toggle);
   - the ship panel shows the **source**: AIS / sensor / AIS + sensor.
5. **Evaluation script** (`scripts/evaluate_fusion.py`): runs the simulator with recorded AIS positions from the database (or synthetic ones) for N simulated hours, faster than real time, and reports, against the ground truth:
   - dark targets found;
   - time to confirmation;
   - false dark alerts (from clutter or association errors);
   - real ships wrongly reported as dark.

## Out of scope
- Real sensor data; several sensors at once.
- Kalman or IMM filtering and JPDA association. The simple predict / gate / nearest-neighbour approach is the explainable baseline, and the evaluation numbers show where it falls short.
- A message broker (only worth it with several real sources).

## Tests
- **Dead reckoning:** a known course and speed give a known position.
- **Gating:** inside and outside the gate; the gate widens with track age.
- **Association:** two ships and two detections give the right pairs; a detection between two ships goes to the nearer one; no detection is used twice.
- **Confirmation:**
  - a dark target crossing the footprint is confirmed after 3 of 5 sweeps;
  - random clutter (seeded) is not confirmed over many sweeps;
  - a real AIS ship is fused, never reported as dark.
- **End to end** through the state task: detections in, then a `dark_vessel` alert and a dark track on `/live`.
- **Browser:** the drone footprint, a dark track and a fused badge are drawn.

## Acceptance
- All guardrails and CI pass.
- The evaluation report (in the phase summary) gives the numbers above for the default configuration, plus at least one harder setting (lower Pd or more clutter). **The weaknesses are stated, not hidden.**
- A live run on the developer's Mac shows the drone patrolling over real AIS traffic: real ships fused, and a scripted dark target confirmed and alerted.
