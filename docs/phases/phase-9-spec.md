# Phase 9 spec — Anomaly detection

Status: proposed, waiting for approval.

## Goal
Go from "rules on zones" to "behaviour that doesn't fit", the top-priority
idea in the README. An operator should see *suspicious behaviour anywhere*,
not only inside predefined zones, and each alert must say **why** it fired.

## Scope
New detectors in `backend/src/minicop/anomalies.py`. Like the alert engine, it is pure logic and runs in the state task (still a single writer).
Each detector produces an `Alert` with a new `kind` and a human-readable reason with numbers.

1. **Loitering.** A ship that keeps moving but stays in a small area for a long time, away from ports.
   - Over the last 30 min, the ship travelled ≥ 2 nm, but every point is within 0.5 nm of the centroid.
   - Reason, for example: "moved 3.1 nm in 40 min but stayed within 0.4 nm".
   - Fires once per episode.
2. **Rendezvous.** Two ships close together and slow, away from ports, for a sustained time: a possible ship-to-ship transfer.
   - Distance < 0.3 nm, both under 2 kn, for ≥ 10 min.
   - Uses a coarse grid so we don't compare every pair of ships.
3. **AIS gap on reappearance.** It extends the existing "dark" alert, which only fires inside zones.
   - When a stale ship reports again *anywhere*, raise a "reappeared" alert with the gap duration, the distance between where it vanished and where it came back, and the implied speed.
   - Only gaps ≥ 30 min, so normal reception holes don't fire it.
   - Implied speed is computed for every gap but **not judged**; spoofing below is the detector for impossible speeds.
4. **Possible spoofing.** Positions that are physically impossible.
   - The history already rejects jumps above 60 kn. Repeated jumps (≥ 3 in 10 min) now raise an alert.
   - Typical causes: spoofing, or two transmitters using the same MMSI.

### Supporting changes
- **Port exclusion areas.** New `kind = "port"` entries in `zones.toml`, marked "(demo)": Portimão, Lagos, Faro/Olhão, Lisbon, Sines, Funchal and Ponta Delgada.
  Loitering and rendezvous are ignored inside them, so normal port behaviour doesn't fire.
  Port zones raise no alerts themselves.
- **Thresholds in config.** A new `[anomalies]` section in `backend/config/anomalies.toml`, so thresholds can be tuned without code changes.
- **Frontend.**
  - Icons and colours for the new kinds.
  - Clicking a rendezvous alert selects one of the two ships.
  - Port zones are drawn very faintly.

## Out of scope
- Machine-learning models. The rules here are the explainable baseline a model would later be compared against.
- Sensor fusion / dark-vessel detection from non-AIS sources (next candidate).
- Persisting anomalies, or replaying recorded data.

## Tests
- Synthetic, physically plausible tracks for each detector, covering both "fires" and "doesn't fire" cases.
  - Loitering: a ship circling at 3 kn offshore fires; a ship anchored and still doesn't; a ship circling inside a port zone doesn't.
  - Rendezvous: two ships side by side for 12 min fire; for 5 min they don't; a ship passing quickly doesn't.
  - Reappearance: a 45 min gap fires, with the right distance and implied speed; a 15 min gap doesn't.
  - Spoofing: 3 jumps in 10 min fire; a single jump doesn't.
- Every alert fires once per episode.
- The grid search for rendezvous gives the same result as the brute-force search.

## Acceptance
- All guardrails pass, including CI and the Docker smoke test.
- Verified in the browser with a fake backend replaying scenarios for each detector.
- A live run on the user's machine. Real loitering or rendezvous may be rare; that is expected and will be reported honestly.

## Risks
Thresholds are guesses until they have been watched against real traffic.
Fishing boats will often look like they are loitering.
The phase summary will report how noisy each detector is on live data.
