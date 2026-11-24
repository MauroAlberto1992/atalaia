# atalaia — Mini-COP

A small "Common Operational Picture": a live map of ships off the Portuguese
coast (AIS via aisstream.io), with zones and alerts.

**Status:** phase 1 (raw AIS positions in the terminal). See `CLAUDE.md` for scope and phases, and
`docs/phases/` for per-phase notes.

## Setup
```bash
cp .env.example .env   # add your aisstream.io API key
```
Then, from `backend/`:
```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
python scripts/watch_positions.py   # prints MMSI, lat, lon; Ctrl+C to stop
pytest
```
