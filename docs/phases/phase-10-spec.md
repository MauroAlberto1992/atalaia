# Phase 10 spec — Coverage gaps vs. ships going dark

Status: proposed, waiting for approval.

## Problem (found on live data)
In the phase 9 live run, several ships in the Tagus bar went "dark" in the same
second, with 31 ships stale at once. That is almost certainly a reception gap
(the AIS receiver or aisstream's coverage of that area), not ships switching
AIS off. The result:
- **false "dark" alerts**, one per ship;
- after the gap, a burst of **false "reappeared" alerts** once the ships report again 30 min or more later.

An operator needs the system to tell "we lost coverage" apart from "this ship
went silent". The second is a possible threat; the first is an
infrastructure problem.

## Goal
Detect coverage gaps, report each as **one** alert, and stop the per-ship
alerts it would otherwise cause.

## Scope
1. **Coverage-gap detection** (pure logic, run by the state task at each sweep).
   - The ships that went stale in this sweep are grouped by region, on a coarse grid of 0.5° (about 30 nm).
   - In a region, if at least **4 ships** went stale with their last reports within **2 minutes** of each other, that is a **coverage gap**.
   - Rationale: independent ships don't fall silent in the same 2 minutes; a receiver does.
2. **One alert per gap**, of a new kind `coverage_lost`.
   - Example: "Coverage lost near 38.7N 9.3W: 7 ships went silent within 40 s".
   - Its map position is the centroid of those ships, so clicking it flies there.
3. **Suppression.**
   - Ships in a coverage gap raise no "dark" alert.
   - When they report again, they raise no "reappeared" alert either.
   - A ship going silent on its own still alerts as before.
4. **Coverage restored.** When at least half of a gap's ships have reported again, raise `coverage_restored` with the gap's duration. After 2 hours the gap is closed without that alert, so memory stays bounded.
5. **Thresholds in config:** a new `[coverage]` section in `anomalies.toml` (min ships, max spread, region size).
6. **Frontend.**
   - The new kinds get icons.
   - A third filter group, **"System"**: coverage is about our sensors, not about ships.

## Out of scope
- Modelling real receiver positions or coverage maps.
- A feed-level outage alert based on the ingestion connection. A full outage already shows up as every region going silent together, and the status bar shows the connection.
- Changing how ships are marked stale on the map. Those ships really are unseen; only the alerts change.

## Known limitation
Four or more ships that deliberately switch AIS off within the same 2 minutes, in the same area, would be classified as a coverage gap. That is unlikely, but it is exactly the kind of coordinated behaviour an operator would care about.
Mitigation: the coverage alert lists the ships, so a human can judge. This will be stated in the docs.

## Tests
- 5 ships in one region going silent within 30 s: one `coverage_lost`, no "dark" alerts.
- 1 ship going silent alone in a zone: "dark" as before.
- 5 ships going silent spread over 10 min: individual alerts, no coverage gap.
- 5 ships going silent within 30 s, but in different regions: no coverage gap.
- After a gap: ships reporting again raise no "reappeared"; `coverage_restored` fires once half are back.
- A gap is closed after 2 h without restoration (bounded memory).

## Acceptance
- All guardrails and CI pass.
- Verified in the browser with a replayed scenario.
- Live run: when gaps like the Tagus one happen again, they show as a single coverage alert.
