# Phase 0 — Setup

## Done
- `CLAUDE.md` with context, scope, rules and phases.
- Structure: `backend/` (package `minicop`, `tests/`, `config/areas.toml`), `docs/phases/`.
- `.gitignore` (ignores `.env`), `.env.example`, basic README.

## Decisions
- Area config in TOML: read with stdlib `tomllib` (Python 3.11+), no extra dependency.
- Bbox stored in aisstream's `[lat, lon]` order so it can be sent as-is.
- Frontend folder deferred to phase 3.

## How to run
Nothing to run yet.
