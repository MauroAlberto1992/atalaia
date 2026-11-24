"""Phase 1: connect to aisstream and print MMSI, latitude, longitude.

Run from backend/:  python scripts/watch_positions.py   (Ctrl+C to stop)
No reconnection on purpose: if the connection drops, the script exits.
"""

import asyncio
import json
import logging

from websockets.asyncio.client import connect

from minicop.config import ConfigError, load_settings
from minicop.parsing import parse_position

AISSTREAM_URL = "wss://stream.aisstream.io/v0/stream"


async def main() -> None:
    settings = load_settings()
    subscription = {
        "APIKey": settings.api_key,
        "BoundingBoxes": settings.area.boxes,
        "FilterMessageTypes": ["PositionReport"],
    }

    # compression="deflate" is websockets' default; set explicitly because
    # aisstream limits uncompressed connections.
    # open_timeout: aisstream's handshake can take >10 s (websockets' default).
    async with connect(AISSTREAM_URL, compression="deflate", open_timeout=30) as ws:
        # Must be the first thing sent, within 3 s of connecting.
        await ws.send(json.dumps(subscription))
        print(f"Subscribed to area '{settings.area.name}'. Waiting for ships...")
        print(f"{'MMSI':>9}  {'LAT':>9}  {'LON':>10}")

        async for frame in ws:
            # aisstream sends JSON as binary frames; decode to text first.
            if isinstance(frame, bytes):
                frame = frame.decode()
            # aisstream reports problems (e.g. bad API key) as {"error": "..."}.
            if frame.startswith('{"error"'):
                print(f"aisstream error: {frame}")
                return
            report = parse_position(frame)
            if report:
                print(f"{report.mmsi:>9}  {report.latitude:>9.5f}  {report.longitude:>10.5f}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
    except ConfigError as exc:
        raise SystemExit(f"Config error: {exc}")
