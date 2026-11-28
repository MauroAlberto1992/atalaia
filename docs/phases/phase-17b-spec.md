# Phase 17b spec: fishing behaviour, type mismatch, priority, GFW evaluation

Part 2 of phase 17; needs 17a (ship type, depth). Sources as in phase-17a-spec.md.

## Scope (17b)
1. **Fishing behaviour** (`fishing_behaviour` flag on the track, not an alert by
   itself): over a sliding window (e.g. 30-60 min) of the ship's own history,
   speed mostly in a fishing range and frequent course changes, at depths where
   fishing is plausible. Thresholds in `config/context.toml`, each with its
   reason. Wording everywhere: "behaviour compatible with fishing", never "is fishing".
2. **Declared type mismatch alert** (`type_mismatch`): fishing behaviour for a
   sustained period by a vessel declared as non-fishing (cargo, tanker...).
   Unknown type: no alert.
3. **Priority:** each dark contact and anomaly alert gets a score with its
   reasons listed (e.g. "+ fishing-speed pattern, + over 50-200 m depth,
   + inside a restricted area, - AIS ship could explain it"). An "Attention"
   list in the UI, highest first. Weights in config; never a black box.
4. **Evaluation (`scripts/evaluate_context.py`):** share of our "fishing
   behaviour" positions that fall in cells where GFW recorded fishing effort
   (2023-2024), against the share for all positions (baseline). GFW data
   downloaded and cut locally by a script, never committed; citation printed.

## Out of scope (17b)
Machine-learning classifier; live GFW comparison (data ends in 2024); GFW API.

## Acceptance (17b)
- Fishing behaviour and type mismatch tested with physically plausible tracks
  (trawler pattern vs transiting cargo ship).
- Priority reasons shown in the UI; "Attention" list ordered correctly.
- Evaluation numbers, with the baseline, recorded in `phase-17b.md`.
- GFW citation in the evaluation output and docs; no GFW data in the repository.
- Guardrails pass; verified in a real browser and in the Docker image.
