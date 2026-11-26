# Phase 13 — Class B vessels (small boats)

## Done
- **Captured real frames first.** `scripts/watch_positions.py --save N` saves raw frames per message type. The developer ran it on 2026-11-26: 5 `PositionReport` (Class A) and 5 `StandardClassBPositionReport` (message 18) are committed in `backend/tests/fixtures/captured/`. **No `ExtendedClassBPositionReport` (message 19) appeared in 20 minutes**, so it has no real fixture; it uses the same parsing path, written from the documentation.
- **Subscription and parser** cover messages 1/2/3, 18 and 19 (`POSITION_TYPES` in `parsing.py`). Class B carries no navigational status, so it is set to 15 ("not defined").
- **`ais_class` ("A"/"B")** on `PositionReport`, `PositionEvent`, `Track`, in `/live`, and in the database: migration `002_ais_class.sql` adds `ais_class char(1) NOT NULL DEFAULT 'A'`, and existing rows were all Class A.
- **`/health`**: `positions_class_a` and `positions_class_b`.
- **Map:** Class B is drawn **green** (`#4ade80`, lighter than the protected-zone green) and at 70% icon size; stale ships of either class stay grey. The panel shows "AIS class: B (small craft)".
- **Coastal demo zones removed** (requested by the developer): Portimão approach, Ria Formosa, Tagus bar and the Ponta Delgada exercise area overlapped real ports and the coast. Only the offshore "Algarve exercise area (demo)" remains.
- **Detectors and alerts:** unchanged. Class B boats are subject to every rule.
- **Tests:** 12 new, plus the integration test extended, for 150 in total (including 3 against a real TimescaleDB).
  - Every captured frame parses, with the right class and status.
  - `ais_class` round-trips into the database.
  - Migrations 001 and 002 apply in order.

## Deviations from the spec
- The green colour for Class B and the removal of the coastal demo zones were not in the spec. Both were requested by the developer after the live run.

## Findings from the real frames
- **Class B position reports carry no ship name**: `MetaData.ShipName` is empty. Class B names come in a separate message (type 24, `StaticDataReport`), which we don't subscribe to. Small craft therefore show their MMSI instead of a name. Subscribing to type 24 is a natural follow-up.
- **No navigational status**, as the spec expected.

## Verified
- All tests and guardrails pass.
- **Migration 002 on a compressed chunk:** on a real TimescaleDB, a row 3 days old was inserted, its chunk compressed, then 002 applied. The old row reads `A` and new rows can be `B`. This matters because the developer's database will have compressed chunks.
- **Browser** (fake backend, 4 Class A and 4 Class B ships side by side): Class B is drawn visibly smaller.
- **Live run** (developer's Mac, area `portugal`, about 6.5 min at night, 23:47–23:54 UTC):

  | | Count |
  |---|---|
  | positions parsed | 143 |
  | Class A | 110 (77%) |
  | **Class B** | **33 (23%)** |
  | ships on the map | 92 |

  - **Class B adds about 30% more positions** on top of Class A alone, at night, when few small craft are out. A daytime run should show more.
  - The overall rate was about 0.37 positions/s, against 0.24 in the phase 12 run. Different times, so only indicative.
  - `db_written` 141 vs `positions_accepted` 143 with 0 queued and 0 dropped: two rows were mid-write when `/health` was read (`take()` removes rows from the buffer before the write completes). That is not a loss. A possible refinement: count in-flight rows separately.

## What the agent got wrong
| Problem | How it was caught | What changed |
|---|---|---|
| Edits made by string replacement went wrong twice: a field was inserted between a line and its comment (`events.py`), and an edit to a test silently didn't apply (the Track in the DB test never got `ais_class="B"`). | ruff's line-length error, and the integration test failing on the expected class. | Re-read the affected lines after scripted edits. The failing integration test was a test bug, not a recorder bug, and was confirmed by reading the code before changing anything. |
| Phase 12 added a dependency (`asyncpg`) without telling the developer to reinstall locally. The pre-commit hooks then failed on their Mac. | The developer's commit of the captured frames. | Rule in `CLAUDE.md`: any dependency change comes with the explicit reinstall command in the run instructions. |

## How to run
No new dependencies in this phase. `docker compose up --build`: migration 002 is applied automatically on start.
