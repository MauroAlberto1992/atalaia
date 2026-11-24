# Phase 1 — See the data

## Done
- `backend/pyproject.toml`: package `minicop` (Python >= 3.11), deps `websockets`, `pydantic`, `python-dotenv`; dev dep `pytest`.
- `minicop/config.py`: loads the API key and area name from `.env`, and the area's bbox from `config/areas.toml`.
- `minicop/models.py`: Pydantic models for the aisstream envelope (`AisEnvelope`, `MetaData`) and `PositionReport`, with snake_case fields mapped from aisstream's PascalCase keys.
- `minicop/parsing.py`: `parse_position(raw)` returns a `PositionReport` or `None`. It never raises.
- `scripts/watch_positions.py`: connects, subscribes, and prints `MMSI LAT LON`.
- Tests: 10 tests for parsing and config.

## Decisions
- **Parsing never raises.** Bad frames are logged and dropped so one broken message cannot stop the stream.
- **Two-step validation.** The envelope is validated first; the inner message is validated only if the type is `PositionReport`. This keeps the code easy to extend to other message types later.
- **Position validity.** Coordinates must be within the lat/lon range, which also rejects AIS "not available" values (91/181).
- **`time_utc` kept as a string.** aisstream uses a Go-style timestamp format; we will parse it in phase 2, when the state needs it.
- **`open_timeout=30`**: the aisstream handshake was observed taking ~13 s, over the 10 s websockets default.
- **Control messages.** The first frame after subscribing is `{"MessageType":"SubscriptionConfirmation","Message":{"CompressionEnabled":true}}`, which has no `MetaData`. `MetaData` is therefore optional on the envelope, and the message is ignored by the type check. It also confirms that compression is active.
- **No reconnection.** The script exits if the connection drops. Reconnection belongs to the service (phase 2/5).
- **Server-side filter.** `FilterMessageTypes: ["PositionReport"]` asks aisstream to send only positions, which saves bandwidth.
- **Compression.** `compression="deflate"` (permessage-deflate) is set explicitly, even though it is the websockets default.
- **aisstream errors.** An `{"error": ...}` frame, e.g. for a bad API key, is printed and the script stops.

## Not verified here
The development container's network blocks aisstream.io, so the live connection has not been tested.
Parsing is tested against a fixture that follows the documented message format.

## How to run
```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp ../.env.example ../.env          # put your AISSTREAM_API_KEY in it
python scripts/watch_positions.py   # Ctrl+C to stop
pytest
```
