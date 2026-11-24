"""Ingestion: keep a connection to aisstream open and push PositionEvents to a queue."""

import asyncio
import json
import logging

from websockets.asyncio.client import connect

from minicop.config import Settings
from minicop.events import PositionEvent
from minicop.parsing import parse_event

log = logging.getLogger(__name__)

AISSTREAM_URL = "wss://stream.aisstream.io/v0/stream"
RECONNECT_DELAY_S = 5  # fixed delay; backoff comes in phase 5


class IngestStatus:
    """Read by /health. Only the ingestion task writes it."""

    def __init__(self) -> None:
        self.connected = False


async def run_ingestion(
    settings: Settings, events: asyncio.Queue[PositionEvent], status: IngestStatus
) -> None:
    subscription = json.dumps({
        "APIKey": settings.api_key,
        "BoundingBoxes": [settings.area.bbox],
        "FilterMessageTypes": ["PositionReport"],
    })
    while True:  # runs until the task is cancelled at shutdown
        try:
            # See phase-1.md for compression and open_timeout.
            async with connect(AISSTREAM_URL, compression="deflate", open_timeout=30) as ws:
                await ws.send(subscription)  # within 3 s of connecting
                status.connected = True
                log.info("Connected to aisstream, area '%s'", settings.area.name)
                async for frame in ws:
                    if isinstance(frame, bytes):
                        frame = frame.decode()
                    if frame.startswith('{"error"'):
                        log.error("aisstream error: %s", frame)
                        break  # aisstream closes after an error; reconnect below
                    event = parse_event(frame)
                    if event:
                        await events.put(event)
        except asyncio.CancelledError:
            raise  # shutdown: don't swallow it
        except Exception as exc:  # network errors, timeouts, closed connections...
            log.warning("aisstream connection failed: %r", exc)
        finally:
            status.connected = False
        log.info("Reconnecting in %s s", RECONNECT_DELAY_S)
        await asyncio.sleep(RECONNECT_DELAY_S)
