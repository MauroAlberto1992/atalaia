# atalaia — Mini-COP

A small "Common Operational Picture": a live map of ships off the Portuguese
coast (AIS via aisstream.io), with zones and alerts.

**Status:** phase 2 (backend service: live track state + API). See `CLAUDE.md` for scope and phases, and
`docs/phases/` for per-phase notes.

## Setup
```bash
cp .env.example .env   # add your aisstream.io API key
```
Then, from `backend/`:
```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
uvicorn minicop.api:app            # API on http://localhost:8000 (GET /tracks, WS /live, GET /health)
python scripts/watch_positions.py   # phase 1 debug script: prints MMSI, lat, lon
pytest
```
