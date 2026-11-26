# Phase 11 — Real port list from OpenStreetMap

## Done
- **`backend/config/ports.json`**: **359 port areas** from OpenStreetMap: 277 mainland, 21 Madeira, 61 Azores.
  - By kind: 180 marinas, 169 harbours, 10 fishing harbours.
  - **Source, licence (ODbL), OSM data timestamp (2026-11-26T23:18Z) and the exact query** are recorded in the file.
- **`minicop/ports.py`**: `ports_from_overpass()` turns an Overpass response into ports.
  - Mapped outlines become polygons. Points become 0.5 nm circles. Relations without geometry use the centre of their bounds.
  - **De-duplication:** a point inside a mapped outline, or within 0.5 nm of another kept point, is dropped.
  - `load_ports()` returns them as `kind = "port"` zones, which raise no alerts themselves and suppress loitering, rendezvous and "dark" alerts.
- **`scripts/fetch_ports.py`**: queries Overpass, or reads an export with `--from-file`. `--print-query` prints the query used.
- **"In port" = inside a port outline or within 0.3 nm (about 550 m) of it** (`Zone.near`, `PORT_MARGIN_NM`).
  - OSM outlines are mostly land (terminals, quays); ships sit in the water next to them.
  - The edge distance is computed in a local flat projection, after a bounding-box check widened by the margin.
  - It is used for loitering, rendezvous and "dark".
- **"Dark" alerts are now suppressed in or next to any port, even inside another zone.** Before, a ship in both a port and a restricted zone still went "dark" for the restricted zone; switching AIS off in port is normal either way.
- **The 7 hand-drawn demo ports were removed** from `zones.toml`. The other demo zones stay.
- **Map:** port names have their own layer, shown from zoom 12 only (there are hundreds).
- **Pre-commit:** `backend/data/` (raw exports) is excluded from the end-of-file and whitespace fixers, so exports are kept byte for byte.
- **Tests:** 11 new tests (including the Leixões basin case, rendezvous suppression in the basin, and polygon edge distance); first on a fixture of **3 genuine elements from the export** (a way, a node, a relation), plus validation of the committed file.

## Deviations from the spec
- **Overpass couldn't be reached from the development environment.** The host was allowed, but the connection was reset for about 2 h, while other newly allowed hosts worked within a minute. The developer ran the query on https://overpass-turbo.eu and committed the raw export (`backend/data/osm/ports-raw.json`). The script gained `--from-file` for this.
- **The first query was too narrow**, so the developer exported twice. It used only `landuse=harbour`, `seamark:type=harbour` and `leisure=marina`, and Peniche, for example, wasn't in it at all. The final query adds `industrial=port`, `harbour=*` and `seamark:type=harbour_basin`.
- **The Ericeira regression test from the spec was not written.** The developer said the two boats were "in the port" without saying which. Ericeira was the agent's assumption from a ship's name, and their position isn't known. The test now checks named major ports from the data instead.

## What the agent got wrong
| Problem | How it was caught | What changed |
|---|---|---|
| The parser silently dropped relations: Overpass `out geom` gives relations bounds but no centre. | Inspecting the real export before using it: 9 relations, none with a centre. | Use the centre of the bounds; a test on a real relation. |
| The first Overpass query missed major fishing and commercial ports (Peniche not present at all). | A coverage check against known ports. | Wider query; a test that named major ports are present. |
| **Coverage was checked with port coordinates written from memory**, 66–560 m off, so it reported 8 of 15 ports "missing". With the wider export, all 8 turned out to be present. | Measuring the distance from each "missing" point to the nearest port before concluding. | Coverage is tested by names from the data. Lesson: memory is not a reference, not even for test data (same root cause as the Ria Formosa polygon in phase 6). |
| Assumed the moored rendezvous pair was at Ericeira from a ship's name. | Rereading what the developer actually said. | The assumption is stated, and the test was not built on it. |
| Didn't anticipate that OSM port outlines are land (terminals, quays) and not water: a ship in Leixões basin was outside every port polygon, so in-port alerts were still possible. | **The developer's screenshot** of Leixões on live data. | A 0.3 nm "near port" margin; tests with a basin point derived from the OSM data (0.14 nm from the Porto de Pesca outline) and an open-sea control point. |
| A test assertion that could never fail (`x in (True, False)`). | Agent review before committing. | Replaced by a real check (the port polygon contains its centroid). |

## How to run
- Nothing changes for running.
- **To refresh the port list:**
  - with Overpass access: `python scripts/fetch_ports.py`;
  - without it: run `python scripts/fetch_ports.py --print-query`, run that query on overpass-turbo, export the "raw OSM data", then run `python scripts/fetch_ports.py --from-file <file>`.
