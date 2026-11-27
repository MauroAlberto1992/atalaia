# Phase 16: user-drawn areas

## Done
- **Draw an area on the map:** "✎ Draw area" (under "⌂ Whole area"). Click points, then double-click or click the first point to close; Esc cancels. Name it and pick a kind: `watch` (purple) or `restricted` (red). Both alert on entry.
- **API:** `POST /zones` validates and creates; `DELETE /zones/{name}` removes drawn areas only (config zones and ports: 409); `GET /zones` now has `source` (`config`, `port`, `user`).
- **Validation (backend, message shown in the UI as is):** 3-50 points, at least 3 different points, no crossing edges, every point inside the monitored area, unique name.
- **State:** the API validates and stores, then puts `ZoneAdded` / `ZoneRemoved` on the event queue; the state task (still the only writer) updates the alert engine and tells `/live` clients `{"type": "zones"}` so they refetch.
- **Ships already inside a new area are not alerted;** only real entries are. Removing an area raises no exit alerts.
- **Dark contacts:** a confirmed dark contact (not one an AIS ship could explain) inside an area raises `dark_in_zone` once per visit (◆, Zones group).
- **Persistence:** table `user_zones` (migration `003_user_zones.sql`), loaded at start once the recorder has connected (it runs the migrations). Without a database the area works but the UI says it is lost on restart.
- **The last demo zone ("Algarve exercise area (demo)") was removed** from `config/zones.toml`, as the developer asked: operators draw their own.

## Decisions
- **The API checks names under a lock, against a set it keeps,** instead of asking the state task: the state task applies events in order but the API must answer at once. Two simultaneous "create X" requests cannot both succeed.
- **The database write happens before the event:** if saving fails, the area is not created (503), so the live picture never has an area the database lost.
- **Flat geometry for crossing checks:** areas are a few nm across; lat/lon distortion does not change whether two edges cross.
- **`watch` and `restricted` behave the same;** the kind is the operator's meaning, shown by colour.

## Verified
- Backend: 192 tests (13 new), mypy strict, ruff. The "already inside" test fails when `add_zone` stops recording ships inside (checked by replacing the method in memory).
- Integration against the real TimescaleDB image: migrations 001-003 apply once; save, load, duplicate name refused, delete.
- Frontend: 41 tests, tsc, eslint.
- **Browser, against the full Docker stack:** drew a 4-point area, saved it (notice shown, area drawn with its label); a crossing area was refused with the backend's message; Esc cancelled; the popup's "Delete area" removed it; no console errors.
- **Restart:** created an area, `docker compose restart backend`, the area was still there.
- **Not verified:** a real AIS ship entering a drawn area in the browser (no AIS key in this environment); covered by the API test with a position event.

## What the agent got wrong
| Problem | How it was caught | What changed |
|---|---|---|
| The dark-contact test called the queue inside a lambda in a loop, capturing the loop variable late (every call would use the last `k`). | ruff (B023). | An async helper that takes `k` as an argument. |

## How to run
No new dependencies.
```bash
git pull
docker compose up --build    # http://localhost:8080
```
Areas you draw are kept in the database (`user_zones`).
