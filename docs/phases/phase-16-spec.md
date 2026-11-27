# Phase 16 spec: user-drawn areas

## Goal
An operator draws an area of interest on the map (e.g. "watch this bay tonight")
and gets alerts when a ship, or a dark sensor contact, enters it. Today zones
only come from `config/zones.toml` and need a restart. This is decision support:
the operator defines what matters now, without touching config files.

## Scope
1. **Drawing (frontend):** a "Draw area" button. Click points on the map, double
   click (or click the first point) to close; Esc cancels. Then give it a name
   and a kind: `restricted` (alert on entry) or `watch` (alert on entry, shown in
   a different colour). Minimum 3 points; self-crossing polygons are refused.
2. **API (backend):**
   - `POST /zones` creates a user area: `{name, kind, polygon}`; validated
     (3-50 vertices, inside the configured area, unique name, no self-crossing).
   - `DELETE /zones/{name}` removes a user area. Config zones and ports cannot
     be deleted (409).
   - `GET /zones` adds `source: "config" | "port" | "user"` to every zone.
3. **State:** user areas go through the event queue to the state task (single
   writer), which updates the AlertEngine's zones. A ship already inside a new
   area does **not** alert at creation (only real entries alert); this is stated
   in the UI ("ships already inside are not alerted").
4. **Dark contacts:** when a confirmed dark contact is inside, or enters, a
   `restricted`/`watch` area, one `dark_in_zone` alert per contact and area.
5. **Persistence:** in the database when `DATABASE_URL` is set (migration
   `003_user_zones.sql`, loaded at start); in memory otherwise, and the UI says
   "not saved: no database".
6. **UI:** user areas drawn dashed in their own colours, with a delete (×) in
   their popup; live updates to every open browser via `/live`.
7. **Tests:** polygon validation (self-crossing, too few points, outside the
   area), create/delete through the API, entry alerts after creation and none
   for ships already inside, dark contact entering an area, persistence round
   trip against the real database (integration test, skipped without it).

## Out of scope
- Editing an area's vertices (delete and redraw instead).
- Circles, corridors, or time-limited areas.
- Users, login, or per-user areas: every browser sees and can delete every area.
- Speed limits on user areas.

## Acceptance
- Draw an area in the browser, a ship entering it raises an alert within one
  position report; a dark contact entering it raises `dark_in_zone`.
- The area survives `docker compose restart backend` (with the database).
- Every open browser sees the area appear and disappear without reloading.
- Invalid polygons are refused with a clear message, in the UI.
- All guardrails pass; verified in a real browser and in the Docker image.
