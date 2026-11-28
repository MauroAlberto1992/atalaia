"""Ingestion: keep a connection to aisstream open and push PositionEvents and
StaticEvents (phase 17a) to the state task's queue."""

import asyncio
import json
import logging
import random
import time
from collections.abc import Callable
from datetime import UTC, datetime

from websockets.asyncio.client import connect

from minicop.config import Settings
from minicop.events import AnyEvent, PositionEvent
from minicop.parsing import POSITION_TYPES, STATIC_TYPES, parse_event, parse_static

log = logging.getLogger(__name__)

AISSTREAM_URL = "wss://stream.aisstream.io/v0/stream"
SILENCE_TIMEOUT_S = 120  # no message for this long = dead connection, reconnect
STABLE_AFTER_S = 60  # a connection that lasted this long resets the backoff


class Backoff:
    """Exponential backoff with jitter: ~1, 2, 4, ... capped at `cap` seconds.

    Each delay is randomised between 50% and 100% of the nominal value, so
    many clients (or many restarts) don't all retry at the same instant.
    `rand` is injectable so tests are deterministic.
    """

    def __init__(
        self, base: float = 1, cap: float = 60, rand: Callable[[], float] = random.random
    ) -> None:
        self.base: float = base
        self.cap: float = cap
        self._rand = rand
        self._attempt = 0

    def next(self) -> float:
        nominal = min(self.cap, self.base * 2.0**self._attempt)  # float base: int**int is typed Any
        self._attempt += 1
        return nominal * (0.5 + 0.5 * self._rand())

    def reset(self) -> None:
        self._attempt = 0


class IngestStatus:
    """Read by /health. Only the ingestion task writes it."""

    def __init__(self) -> None:
        self.connected = False
        self.last_message_at: datetime | None = None
        self.reconnects = 0
        # Pipeline counters, to tell "the feed sends little" from "we lose data":
        self.frames = 0  # every frame received from aisstream
        self.positions = 0  # frames that parsed into a usable position
        self.positions_by_class: dict[str, int] = {"A": 0, "B": 0}
        self.statics = 0  # static data frames with a ship type or draught (phase 17a)


async def run_ingestion(
    settings: Settings,
    events: "asyncio.Queue[AnyEvent]",
    status: IngestStatus,
) -> None:
    subscription = json.dumps(
        {
            "APIKey": settings.api_key,
            "BoundingBoxes": settings.area.boxes,
            # Class A and Class B positions (phase 13), and static data:
            # ship type and draught (phase 17a).
            "FilterMessageTypes": [*POSITION_TYPES, *STATIC_TYPES],
        }
    )
    backoff = Backoff()
    while True:  # runs until the task is cancelled at shutdown
        connected_at: float | None = None
        try:
            # See phase-1.md for compression and open_timeout.
            async with connect(AISSTREAM_URL, compression="deflate", open_timeout=30) as ws:
                await ws.send(subscription)  # within 3 s of connecting
                connected_at = time.monotonic()
                status.connected = True
                log.info("Connected to aisstream, area '%s'", settings.area.name)
                while True:
                    # Watchdog: a connection can stay "open" while nothing
                    # arrives (e.g. a dead NAT mapping). Treat silence as failure.
                    frame = await asyncio.wait_for(ws.recv(), SILENCE_TIMEOUT_S)
                    status.last_message_at = datetime.now(UTC)
                    status.frames += 1
                    if isinstance(frame, bytes):
                        frame = frame.decode()
                    if frame.startswith('{"error"'):
                        log.error("aisstream error: %s", frame)
                        break  # aisstream closes after an error; reconnect below
                    event: PositionEvent | None = parse_event(frame)
                    if event:
                        status.positions += 1
                        status.positions_by_class[event.ais_class] += 1
                        await events.put(event)
                        continue
                    # Only frames of a static type: an invalid frame was already
                    # logged by parse_event, and must not be logged twice.
                    if not any(f'"{t}"' in frame for t in STATIC_TYPES):
                        continue
                    static = parse_static(frame)
                    if static:
                        status.statics += 1
                        await events.put(static)
        except asyncio.CancelledError:
            raise  # shutdown: don't swallow it
        except TimeoutError:
            log.warning("No data from aisstream for %s s (or handshake timeout)", SILENCE_TIMEOUT_S)
        except Exception as exc:  # network errors, closed connections...
            log.warning("aisstream connection failed: %r", exc)
        finally:
            status.connected = False

        # Only a connection that stayed up for a while proves the service is
        # healthy again; a connect-then-drop loop must keep backing off.
        if connected_at is not None and time.monotonic() - connected_at >= STABLE_AFTER_S:
            backoff.reset()
        delay = backoff.next()
        status.reconnects += 1
        log.info("Reconnecting in %.1f s", delay)
        await asyncio.sleep(delay)
