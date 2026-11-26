# Phase 11 spec — Real port list from OpenStreetMap

Status: proposed, waiting for approval.

## Problem
The port areas used to suppress loitering, rendezvous and "dark" alerts are 7
hand-drawn demo rectangles. On live data, two fishing boats moored in a port
that isn't in that list raised a false rendezvous alert. The NGA World Port
Index (first choice) was unavailable: the site is under maintenance.

## Goal
Replace the demo ports with a sourced, much more complete list: commercial
ports, fishing harbours and marinas in mainland Portugal, Madeira and the Azores.

## Source
**OpenStreetMap**, via the Overpass API.
- Licence: ODbL. Attribution "© OpenStreetMap contributors" is required. The basemap already shows it, and it will also go in the README and in the generated file.
- Features queried, inside the configured area boxes:
  - `landuse=harbour` (port areas, with real polygons);
  - `seamark:type=harbour` (nautical harbour points, including fishing harbours);
  - `leisure=marina`.

## Scope
1. **`backend/scripts/fetch_ports.py`**: one-off script that runs the Overpass query and writes **`backend/config/ports.json`**.
   - Each port has a name, a kind (harbour, fishing, marina), a position, and a polygon when OSM has one (otherwise a circle of about 0.5 nm around the point, as a polygon).
   - The file header records the source, licence, query and fetch date.
   - Overlapping entries for the same place are merged into one, by distance.
2. **The backend loads port zones from `ports.json`** instead of the `kind = "port"` entries in `zones.toml`; those demo entries are removed. The other demo zones (restricted, protected, speed) stay.
3. **The file is committed to the repository.** The service never calls Overpass at runtime: no extra dependency, no network need, reproducible. To refresh it, re-run the script.
4. **Frontend:** no change; port zones are drawn as now, just more of them.
5. **Performance:** there will be a few hundred port polygons. The bounding-box pre-check already rejects most of them cheaply. If profiling shows a cost, a coarse grid index is added, as was done for rendezvous.

## Out of scope
- Live updates from OSM.
- Other countries.
- Using port data for anything except alert suppression (e.g. port-call detection, a README idea).

## Tests
- Parsing a small **real** Overpass response, captured and saved as a fixture: polygon, point and marina cases, plus de-duplication.
- Loading `ports.json`: every port has a source, a valid polygon and coordinates inside Portugal's areas.
- Regression: a ship moored at Ericeira, the live false positive, is inside a port (if OSM has it, which the fetch will show).
- The existing tests still pass with the real port list.

## Acceptance
- All guardrails and CI pass.
- The phase summary reports how many ports were found per region and whether the Ericeira case is covered.
- A live run on the developer's machine shows fewer false rendezvous and loitering alerts in ports.
