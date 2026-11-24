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

## What the agent got wrong

| Problem | How it was caught | What changed |
|---|---|---|
| Picked TOML via stdlib `tomllib`, which needs Python 3.11, without checking the user's machine. | Phase 1: the user's Mac had Python 3.10 and setup failed. | Rule: check the user's runtime versions when choosing dependencies, and state minimum versions in the plan. |
