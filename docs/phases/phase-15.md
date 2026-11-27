# Phase 15 — Sensor fusion: finding "dark" vessels

## Done
- **SIMULATED sensor** (`sensors.py`, `config/sensors.toml`): a patrol drone flies a loop offshore Algarve with a 5 nm footprint and one sweep every 30 s. Each sweep detects:
  - real AIS ships (Pd 0.9, 150 m position error);
  - two scripted **dark targets** that never transmit AIS;
  - Poisson clutter.

  Each detection carries its ground truth, which is used **only** by the evaluation and never published.
- **Fusion** (`fusion.py`, pure):
  - dead reckoning of AIS tracks to the sweep time;
  - a gate that grows with AIS age;
  - **greedy global nearest neighbour** assignment;
  - unassociated detections feed candidates, confirmed as **dark tracks** after **3 detections in the last 5 sweeps**, with a plausible speed between consecutive detections.
- **State task integration:** a `SensorTick` on the same queue. The state task (still the only writer) runs the sweep and the fusion, marks AIS tracks "AIS + sensor" (`sensor_seen`), publishes `sensor` and `dark` on `/live` and in the snapshot, and raises **`dark_vessel`** alerts, which carry a position because there is no MMSI.
- **Off by default** (`MINICOP_SIMULATED_SENSOR=1` turns it on). Docker Compose turns it on for the demo; tests and other runs leave it off.
- **Map:**
  - footprint and drone;
  - confirmed dark tracks as red diamonds, with a popup on click;
  - a cyan ring on AIS ships the sensor confirmed in the last 2 min;
  - raw detections as a toggle;
  - "Source: AIS / AIS + sensor (SIMULATED)" in the ship panel;
  - **"SIMULATED sensor" always shown in the status bar**;
  - `dark_vessel` alerts in the "System" filter group, with ◆.
- **`scripts/evaluate_fusion.py`**: hours of simulated time in seconds, scored against the ground truth.
- **Tests:** 18 fusion and simulator tests, 2 end-to-end API tests and 5 frontend tests. Totals: 172 backend, 35 frontend.

## Evaluation (6 simulated hours, 40 synthetic AIS ships, seed 42)
| Scenario | Dark targets | Time to confirm | False dark (clutter) | AIS ships reported dark | AIS detections → right MMSI / unassociated |
|---|---|---|---|---|---|
| Default (Pd 0.9, 0.5 clutter/sweep, AIS ≤ 3 min old) | 2/2 | 1.0 min | 0 | 0 | 99.9% / 0.0% |
| Harder (Pd 0.7, 2 clutter/sweep) | 2/2 | 1.0 / 4.5 min | **3** | 0 | 99.6% / 0.2% |
| **Sparse AIS (reports up to 15 min old)** | 2/2 | 1.0 min | 0 | **38** | 70.4% / **29.3%** |

### After the "could a recent AIS ship be there?" check (spec addendum)
Before a confirmed contact is reported dark, every AIS ship seen in the last 60 min (stale ones too) is tested for reachability: distance from its last report ≤ 0.5 nm + (SOG × 1.5 + 2 kn) × time since that report. If one fits, the contact is shown grey as "possibly <ship> (AIS N min old)", with no alert; it is re-checked every sweep.

| Scenario | Dark targets | Time to confirm | AIS ships reported dark | Explained by recent AIS |
|---|---|---|---|---|
| Default | 2/2 | 1.0 / 1.0 min | 0 | 1 dark contact, briefly (no delay) |
| Harder | 2/2 | 1.0 / 4.5 min | 0 | 1 dark contact, briefly (no delay) |
| Sparse AIS | 2/2 | 1.0 / **147.5 min** | **4** (was 38) | 36 right MMSI, 2 wrong MMSI, **2 dark contacts** |

**The cost is real:** in the sparse scenario DARK-2 (3 kn, loitering among ships) was explained for a whole drone pass, at one point by a ship whose AIS was only 2.4 min old, and was only reported on the drone's next pass, 146 min later. Close to AIS ships, a dark vessel cannot be told apart from them with this rule. Tried and measured: excluding ships the sensor matched elsewhere in the same sweep. It did not help DARK-2 and raised AIS ships reported dark from 4 to 5 (10 in a cruder version), so it was reverted.

### After moving the dark targets next to the drone's route
Tested on the developer's Mac, the dark targets were rarely seen: the drone flies the perimeter of its patrol box and they sailed in the middle, inside the footprint only 9% (DARK-1) and 6% (DARK-2) of the time. They now sail ~2 nm inside the north leg and loiter near the south-east corner: 13% and 18%, i.e. seen on every loop. Same evaluation, new paths:

| Scenario | Dark targets | Time to confirm | False dark (clutter) | AIS ships reported dark | Explained by recent AIS |
|---|---|---|---|---|---|
| Default | 2/2 | 1.0 / 1.0 min | 0 | 0 | 1 dark contact, briefly |
| Harder | 2/2 | 1.0 / 2.5 min | 1 | 0 | 1 dark contact, briefly |
| Sparse AIS | 2/2 | 1.0 / 1.0 min | 0 | **6** (39 without the check) | 37 right MMSI, 2 wrong MMSI, **5 dark contacts** |

The earlier 147-minute delay for DARK-2 depended on its old path among the synthetic ships; the risk itself (a dark target near AIS ships is "explained") remains: 5 dark contacts were explained at some point.

Demo speed: `MINICOP_SENSOR_SWEEP_S=1` and `MINICOP_DRONE_SPEED_KN=600` in `.env` give one patrol loop in ~8 min (drone only; dark targets keep their real speed).

### Position noise in the plausibility check
In the fast demo (sweeps 1 s apart) no contact was ever confirmed: 150 m of position noise between fixes 1 s apart reads as ~300 kn, so the per-hop speed check rejected everything. Each hop may now be up to `max_speed x time + 3 sigma` of the difference of two noisy fixes. Measured: in 30 min of fast demo, 6 confirmations (every pass of each dark target); 2 sigma kept only 4. Cost: in the harder scenario, clutter false darks went from 1 to 4 in 6 h; the other scenarios are unchanged.

### Weaknesses (stated, not hidden)
1. **Sparse AIS was the big one** (now mitigated, see above; the cost is a dark vessel hiding next to AIS ships). AIS tracks older than 10 minutes are not used for association, so a real ship whose last report is 10–15 minutes old looks like a non-cooperative contact: **38 false dark alerts in 6 hours**. The real feed measured in phase 12 averages about 2 minutes between reports per ship, with longer silences, so this would happen in practice. Fix candidates:
   - before declaring "dark", check older AIS tracks with a gate that grows with possible travel;
   - report "possibly MMSI X" instead of "dark".
2. **Clutter can confirm by chance:** M-of-N has a non-zero false-alarm rate. 3 in 6 hours at 2 clutter per sweep; 1 in 5 hours in the unit test at 1 per sweep.
3. **Speed is noisy over short spans.** 3 detections in 1 minute with 150 m error gave "16 kn" for a 6 kn target (seen in the browser). Speed is now only reported once a contact's detections span 3 minutes; before that the UI says "speed not yet known".
4. **The ground truth for real ships is their last AIS position.** The simulator cannot know where a real ship really is between reports.
5. **Greedy assignment**, not optimal (Hungarian), and no Kalman filtering. Fine at this density; it would matter in crowded ports.

## Decisions
- **The simulator runs inside the state task.** It needs the real ships' positions, which only the state holds. A real sensor would be a separate ingestion task producing the same `Detection` objects; the fusion would not change.
- **Ground truth never leaves the backend.** It is excluded from `/live`, and a test asserts it.
- **Simulation is off by default** and labelled everywhere, so simulated contacts are never mixed into a real picture by accident.

## Verified
- All tests and guardrails pass. End to end: a scripted dark target is confirmed, the alert is raised, and `/live` carries a sweep marked simulated, without ground truth.
- **Browser**, with sensor time accelerated (one sweep every 0.15 s):
  - footprint and drone drawn;
  - two AIS ships with the cyan "sensor" ring;
  - a `dark_vessel` alert;
  - "SIMULATED sensor" in the status bar;
  - no console errors.
- **Pending:** a live run on the developer's Mac, where the drone flies over real AIS traffic in real time.

## What the agent got wrong
| Problem | How it was caught | What changed |
|---|---|---|
| **Diagnosed a design flaw without measuring it.** When the clutter test failed, the agent blamed old candidates with a growing radius, added a "confirmation window" check, and told the developer it was "a real design flaw". Measured afterwards with and without the check: **1 false confirmation in both**. The failure was a genuine chance coincidence of 3 clutter points. | Measuring both variants in memory. The first attempt to measure "before" was itself invalid: `git stash` doesn't stash new untracked files, so it measured the fixed code. | The check stays, with an honest comment (it keeps stale candidates from taking new contacts' detections), and the test now bounds the false-alarm rate instead of demanding zero. The developer was told the earlier claim was wrong. |
| The speed shown for a fresh dark contact (16 kn for a 6 kn target) came from too short a span. | The browser screenshot. | No speed until the detections span 3 minutes. |
| The first "exclude ships seen elsewhere" variant was expected to help; it made things worse (4 → 10 AIS ships reported dark). | Running the evaluation after each change. | Reverted; the result is recorded above instead of tuning until the numbers looked good. |
| The scripted dark targets were placed inside the patrol box, where the perimeter-flying drone rarely sees them (9% / 6% of the time). | The developer, waiting in the live demo. | Measured, then moved next to the drone's route (13% / 18%). |
| The per-hop speed check ignored position noise, so with 1 s sweeps nothing ever confirmed; the fast-demo option was shipped after checking only that the drone moved. | The developer could not find a single dark contact in the live demo. | Noise term added (3 sigma), regression test that fails on the old rule, fast demo measured end to end. |
| Two scripted edits failed on text that `ruff format` had already reflowed, and one put a constant above the imports. | ruff (E402) and the edit script's own assertion. | Re-read the current text before scripted edits. |

## How to run
`docker compose up --build`: the simulated sensor is on by default. The drone patrols offshore Algarve: look south of Portimão. `python scripts/evaluate_fusion.py` (from `backend/`) runs the evaluation.
