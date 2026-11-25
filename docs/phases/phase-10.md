# Phase 10 — Coverage gaps vs ships going dark

## Done
- **`backend/src/minicop/coverage.py`**: `CoverageMonitor`, pure logic run by the state task.
  - **Detection.** Ships that just became stale are held as *pending* for `max_spread_s` (120 s), so the rest of their cohort can arrive. Then, per region (0.5° grid, about 30 nm), the largest set of pending ships whose last reports fit within 120 s is found with a sliding window. **At least 4 ships means a coverage gap.**
  - **One `coverage_lost` alert per gap**, for example: "Coverage lost near 38.7N 9.3W: 6 ships went silent within 25 s (TAGUS 0, …)". It names the ships so a human can judge.
  - **Ships in a gap get no "dark" alert**, and **no "reappeared" alert** when they come back.
  - Ships that later go stale in the same region and time window join the open gap.
  - **`coverage_restored`** fires once half of the gap's ships have reported again, with the gap duration.
  - Gaps are forgotten after 2 h (bounded memory).
- **`[coverage]` thresholds** in `backend/config/anomalies.toml`.
- **Rendezvous ignores ships reporting AIS status "moored" (5).** "At anchor" (1) still counts.
- **Frontend**: icons ⊘ (coverage lost) and ⊕ (restored), and a third alert filter group, **"System"**.
- **Tests**: 13 new (117 backend, 15 frontend).
  - Gap, cohort split across sweeps, lone ship, spread over 10 min, different regions, restoration, memory.
  - Moored vs at anchor.
  - "Reappeared" suppression.
  - Two end-to-end tests through the state task (a gap gives one `coverage_lost` and no "dark"; a lone ship still goes "dark").

## Decisions
- **Hold, then decide.** Ships that fell silent within 120 s of each other become stale in sweeps up to 120 s apart. Deciding per sweep would split one gap into several small groups and leak "dark" alerts. The cost is that a genuine "dark" alert is about 2 min later, small next to the 10 min it takes to call a ship stale.
- **Region grid, not distance clustering.** It is simple and explainable. A gap that straddles a cell boundary can split into two groups, each of which still needs 4 ships. That is acceptable for a first version and noted here.
- **The map is unchanged.** Ships in a gap still turn grey: they really are unseen. Only the alerts change.
- **The coverage alert is attached to the first ship that went silent**, so clicking it flies to the area. The message carries the whole cohort.

## Known limitation
Four or more ships deliberately switching AIS off within the same 2 minutes, in the same ~30 nm area, would be classified as a coverage gap. The alert lists the ships, so an operator can spot a suspicious cohort, for example ships that are not normally together.

## Not done: real port list (spec addendum, point 1)
The NGA World Port Index could not be downloaded from the development environment. The host was allowed, but `msi.nga.mil` answered every request with a 503 "apology" page. The hand-drawn demo ports remain for now. Next step: the developer downloads the CSV in a browser and commits it; a small script then extracts the Portuguese ports, with the source and date recorded.

## Verified
- All guardrails pass.
- Real-time scenario in the browser with a fake backend (see the result below).

## What the agent got wrong
- **Nothing caught yet in this phase.** The live run is still pending; anything it finds goes here.
- **Nearly recorded a mistake that never happened.** While writing this summary, the agent first wrote a row describing a "per-sweep design" that a test had supposedly caught. That design never existed: the pending window was there from the start. The row was removed before committing.
  - Lesson: this section is only valuable if every entry is real.

## How to run
As before. Thresholds: `[coverage]` in `backend/config/anomalies.toml`.
