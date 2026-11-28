# Phase 17a spec: static AIS data, depth, impossible positions

Part 1 of phase 17 (split at the developer's request). Goal, data and sources
are shared with 17b; see the end of this file.

## Goal
Use the seabed to say what matters, not just to draw it. Three questions an
operator asks, answered with open, sourced data:
1. **Is this position even possible?** A ship reported where the sea is
   shallower than its draught (or on land) is aground, or its position is wrong
   or spoofed.
2. **Is this vessel behaving like a fishing vessel, and is that what it says it is?**
   Fishing has a signature (slow, many turns, typical depths); a vessel that
   fishes but declares itself as cargo, or fishes in a no-fishing area, is of interest.
3. **What should I look at first?** A priority for dark contacts and anomalies,
   from their context (depth, behaviour, areas), so the operator has a short,
   ordered list instead of a flat feed.

## Data (checked, see "Sources and licences")
- **EMODnet Bathymetry DTM 2024**: ~115 m grid (1/16 arc minute), CC BY 4.0.
  Only the cells covering the configured area are kept in the repository
  (a small file), with the required acknowledgement and "not for navigation".
- **Global Fishing Watch apparent fishing effort v3.0 (Zenodo)**, CC BY-NC 4.0,
  0.01 degree cells, 2012-2024: used **only to evaluate** our fishing detector.
  Not stored in the repository: a script downloads it and keeps the configured
  area locally. The GFW API is not used (its terms require registering on
  behalf of an organisation).

## Scope (17a)
1. **Static AIS data (ingestion):** also subscribe to the static messages
   (Class A ship static data; Class B static data report) and keep, per MMSI,
   the declared ship type and draught. Field names and units are taken from
   **captured real messages first** (lesson from phases 1 and 11), not from docs:
   a capture script saves a sample, and the tests are built from it.
   `Track` gains `ship_type` (code + label) and `draught_m` (None if unknown).
   Shown in the ship panel.
2. **Bathymetry for the configured area:** a script cuts the EMODnet DTM tile(s)
   to the configured area into a small file in `backend/config/`, with the
   acknowledgement. A `Bathymetry` class loads it once and answers
   `depth_m(lat, lon)` (nearest cell; None outside the grid).
   Shown in the ship panel ("Depth ~45 m, EMODnet").
3. **Impossible position alert** (`impossible_position`): depth and draught
   known and depth < draught + margin, or the position on land. Not raised in or
   near ports (existing list, phase-11 margin), nor closer to the coast than a
   configurable distance where the ~115 m grid can't tell. Once per ship per episode.
4. **Evaluation on recorded real AIS:** how many impossible positions, how many
   filtered by the port/coast rules, examples with depth and draught.
5. **Map:** optional depth shading (toggle, off by default), EMODnet in the
   map's attribution; README acknowledgement.

## Out of scope (17a)
Fishing behaviour, type mismatch, priority, GFW evaluation (all 17b); seabed
type, protected areas, tides.

## Acceptance (17a)
- Static data parsed from captured real messages; tests built from them.
- `depth_m` correct on test points checked against the source file, None outside.
- `impossible_position` raised for a test ship with draught > depth, not in a
  port or near the coast; real-data results recorded in `phase-17a.md`.
- EMODnet acknowledgement in README and map; "not for navigation" stated.
- Guardrails pass; verified in a real browser and in the Docker image.

## Sources and licences
- EMODnet Terms of Use: products "owned by the EU and therefore licensed under
  Creative Commons CC-BY 4.0"; acknowledgement: "This data product was created
  by EMODnet (https://emodnet.ec.europa.eu/en/), and is owned by the EU and
  licensed under the Creative Commons Attribution 4.0 International (CC BY 4.0)
  license." Catalogue records also state "DO NOT USE FOR NAVIGATION".
- Global Fishing Watch, Global AIS-based Apparent Fishing Effort Dataset v3.0.0,
  Zenodo, licence CC BY-NC 4.0, https://doi.org/10.5281/zenodo.14982712.
  Citation: "Global Fishing Watch. (2025). Global AIS-based Apparent Fishing
  Effort Dataset (Version 3.0.0) [Dataset]. Global Fishing Watch."
- GFW API terms (not used): accounts are "on behalf of an organization or
  entity that supports the sustainable use of ocean resources".
