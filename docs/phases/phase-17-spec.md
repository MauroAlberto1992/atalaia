# Phase 17 spec: environmental context (bathymetry) and fishing behaviour

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

## Scope
1. **Static AIS data (ingestion):** also subscribe to the static messages
   (Class A ship static data; Class B static data report) and keep, per MMSI,
   the declared ship type and draught. Field names and units are taken from
   **captured real messages first** (lesson from phases 1 and 11), not from docs.
   `Track` gains `ship_type` (code + label) and `draught_m` (None if unknown).
2. **Depth at each position:** a `Bathymetry` class loads the grid once and
   answers `depth_m(lat, lon)` (nearest cell; None outside the grid).
   Shown in the ship panel ("Depth ~45 m, EMODnet").
3. **Impossible position alert** (`impossible_position`): depth known, draught
   known, and depth < draught + margin, or the position is on land.
   Not raised in or near ports (existing port list, same margin as phase 11),
   nor where the grid is too coarse to tell (near the coast: a configurable
   distance). Once per ship per episode.
4. **Fishing behaviour** (`fishing_behaviour` flag on the track, not an alert by
   itself): over a sliding window (e.g. 30-60 min) of the ship's own history,
   speed mostly in a fishing range and frequent course changes, at depths
   where fishing is plausible. Thresholds in `config/context.toml`, each with
   its reason. Wording everywhere: "behaviour compatible with fishing", never
   "is fishing".
5. **Declared type mismatch alert** (`type_mismatch`): fishing behaviour for a
   sustained period by a vessel whose declared type is not fishing (e.g. cargo,
   tanker). Unknown type: no alert.
6. **Priority:** each dark contact and each anomaly alert gets a score with its
   reasons listed (e.g. "+ fishing-speed pattern, + over 50-200 m depth,
   + inside a restricted area, - AIS ship could explain it"). An "Attention"
   list in the UI, highest first. Weights in config; the score is explained,
   never a black box.
7. **Evaluation (`scripts/evaluate_context.py`):**
   - impossible positions on the recorded real AIS: how many, how many in or
     near ports (filtered), examples with depth and draught;
   - fishing detector vs GFW: share of our "fishing behaviour" positions that
     fall in cells where GFW recorded fishing effort (2023-2024), against the
     share for all positions (a baseline, so the number means something);
   - results in `phase-17.md`, good or bad.
8. **Map:** optional depth shading layer (toggle, off by default), with the
   EMODnet acknowledgement in the map's attribution.

## Out of scope
- Seabed type, protected-area or fishing-regulation layers (later, if useful).
- A machine-learning fishing classifier (rules first; measured).
- Live comparison with GFW (its data ends in 2024).
- Tides (depth is relative to the grid's datum; covered by the margin).

## Acceptance
- Static data parsed from captured real messages; tests built from them.
- `depth_m` correct on test points with a known source (not memory), and None
  outside the grid.
- `impossible_position` raised for a test ship with draught > depth, not raised
  in a port or near the coast; false positives on real recorded data reported.
- Fishing behaviour and type mismatch tested with physically plausible tracks
  (a trawler pattern vs a transiting cargo ship).
- The priority shows its reasons in the UI; the "Attention" list orders correctly.
- Evaluation numbers recorded, with the baseline.
- Licences: EMODnet acknowledgement in the README and the map; GFW citation in
  the evaluation output and docs; no GFW data in the repository.
- All guardrails pass; verified in a real browser and in the Docker image.

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
