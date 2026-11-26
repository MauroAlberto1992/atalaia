"""Connect to aisstream and print MMSI, latitude, longitude (phase 1),
or capture real frames as test fixtures (phase 13).

Run from backend/:
    python scripts/watch_positions.py              # print positions (Ctrl+C to stop)
    python scripts/watch_positions.py --save 5     # save 5 real frames per message type

--save writes raw frames to tests/fixtures/captured/<MessageType>_<n>.json and
stops when every type has N frames, or after --minutes (default 20). Parsers
are then tested against these real frames, not only against documentation.

No reconnection on purpose: if the connection drops, the script exits.
"""

import argparse
import asyncio
import json
import logging
import time
from pathlib import Path

from websockets.asyncio.client import connect

from minicop.config import ConfigError, load_settings
from minicop.parsing import parse_position

AISSTREAM_URL = "wss://stream.aisstream.io/v0/stream"
CAPTURE_TYPES = ["PositionReport", "StandardClassBPositionReport", "ExtendedClassBPositionReport"]
CAPTURE_DIR = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "captured"


async def main(save: int, minutes: float) -> None:
    settings = load_settings()
    subscription = {
        "APIKey": settings.api_key,
        "BoundingBoxes": settings.area.boxes,
        "FilterMessageTypes": CAPTURE_TYPES if save else ["PositionReport"],
    }
    saved: dict[str, int] = dict.fromkeys(CAPTURE_TYPES, 0)
    deadline = time.monotonic() + minutes * 60
    if save:
        CAPTURE_DIR.mkdir(parents=True, exist_ok=True)

    # compression="deflate" is websockets' default; set explicitly because
    # aisstream limits uncompressed connections.
    # open_timeout: aisstream's handshake can take >10 s (websockets' default).
    async with connect(AISSTREAM_URL, compression="deflate", open_timeout=30) as ws:
        # Must be the first thing sent, within 3 s of connecting.
        await ws.send(json.dumps(subscription))
        print(f"Subscribed to area '{settings.area.name}'. Waiting for ships...")
        if not save:
            print(f"{'MMSI':>9}  {'LAT':>9}  {'LON':>10}")

        async for frame in ws:
            # aisstream sends JSON as binary frames; decode to text first.
            if isinstance(frame, bytes):
                frame = frame.decode()
            # aisstream reports problems (e.g. bad API key) as {"error": "..."}.
            if frame.startswith('{"error"'):
                print(f"aisstream error: {frame}")
                return
            if save:
                kind = json.loads(frame).get("MessageType", "")
                if kind in saved and saved[kind] < save:
                    saved[kind] += 1
                    path = CAPTURE_DIR / f"{kind}_{saved[kind]}.json"
                    path.write_text(json.dumps(json.loads(frame), indent=1) + "\n")
                    print(f"saved {path.name}   progress: {saved}")
                if all(n >= save for n in saved.values()) or time.monotonic() > deadline:
                    print(f"Done. Captured: {saved}")
                    return
                continue
            report = parse_position(frame)
            if report:
                print(f"{report.mmsi:>9}  {report.latitude:>9.5f}  {report.longitude:>10.5f}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--save", type=int, default=0, help="frames to capture per message type")
    parser.add_argument("--minutes", type=float, default=20, help="stop capturing after this long")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    try:
        asyncio.run(main(args.save, args.minutes))
    except KeyboardInterrupt:
        pass
    except ConfigError as exc:
        raise SystemExit(f"Config error: {exc}") from None  # one line, no traceback
