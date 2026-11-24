# Phase 6 — Zones and alerts

## Done
- `config/zones.toml`: 5 demo zones, each a polygon in `[lat, lon]`:
  - Portimão approach (6 kn limit);
  - Ria Formosa (protected, entry alerts);
  - Algarve exercise area (restricted);
  - Tagus bar (12 kn limit);
  - Ponta Delgada exercise area (restricted).
- `geo.point_in_polygon()`: ray casting, about 10 lines, no shapely.
- `zones.py`: `Zone` model with a precomputed bounding box, and `load_zones()`.
- `alerts.py`: `AlertEngine` with four alert kinds:
  - **enter / exit**: only zones with `alert_on_entry`;
  - **speeding**: SOG above `max_speed_kn`, once per visit;
  - **dark**: the ship goes stale while inside any zone.
- API:
  - `GET /zones`;
  - `GET /alerts`: the last 200, newest first;
  - `/live` sends `{"type":"alert","alert":…}`, and the snapshot now includes `alerts`.
- Frontend:
  - zones drawn on the map (fill, dashed outline, label; colour by kind);
  - alert panel at the bottom left; a click selects the ship and flies to it;
  - "N new alerts" badge in the status bar, cleared when the panel is hovered or touched.
- Tests: 81 backend tests and 12 frontend tests.

## Decisions
- **The alert engine runs in the state task.** It is called after each accepted track update and each stale or removal, so there is still one writer and no locks. The track message is published before its alerts, so a client always knows the ship an alert is about.
- **Bounding box before the polygon test.** Most ships are far from most zones, so a cheap rectangle check rejects them before the ray casting runs.
- **Flat lon/lat geometry.** This is fine for zones tens of km wide away from the poles and the antimeridian. Points exactly on an edge can go either way, which doesn't matter for alerting.
- **First sighting inside a zone counts as "enter".** After a restart, ships already inside a restricted zone are still reported.
- **Speeding once per visit.** Otherwise a fast ship would raise an alert on every report (every 2–10 s).
- **Removal is not an exit.** A ship that vanished didn't leave, so the engine forgets it silently. Its "dark" alert was already raised when it went stale.
- **Tagus bar without entry alerts.** It is a busy port entrance and entry alerts would be noise; this was a small change from the plan.
- **Alerts in the snapshot.** A browser that connects late, or reconnects, sees the recent alerts.
  Only alerts received live count towards the "new" badge.
- **Zones are demo data.** They are plausible locations, not official boundaries, and the file header says so.
- **`@maplibre/maplibre-gl-style-spec` is a dev dependency.** It is used only for the `ExpressionSpecification` type; it is declared explicitly instead of relying on a transitive install.

## Verified
- All tests pass.
- Headless Chromium with a fake backend of ships crossing zones:
  - zones are drawn;
  - enter and speeding alerts appear live with the badge;
  - clicking an alert selects the ship, flies to it and shows its route.

## How to run
As in phase 3. Zones are in `backend/config/zones.toml`; restart the backend after editing them.
