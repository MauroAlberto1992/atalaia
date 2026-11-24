"""Fan-out of live updates to WebSocket clients.

Each client gets its own bounded queue. publish() never awaits, so one slow
client can never stall the state task or the other clients: if a client's
queue is full, it is dropped (its socket handler sees None and closes).
"""

import asyncio
import logging
from typing import Any

log = logging.getLogger(__name__)

CLIENT_QUEUE_SIZE = 1000


class Hub:
    def __init__(self) -> None:
        self._clients: set[asyncio.Queue[Any]] = set()

    def subscribe(self) -> asyncio.Queue[Any]:
        queue: asyncio.Queue[Any] = asyncio.Queue(maxsize=CLIENT_QUEUE_SIZE)
        self._clients.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[Any]) -> None:
        self._clients.discard(queue)

    def publish(self, message: Any) -> None:
        for queue in list(self._clients):
            try:
                queue.put_nowait(message)
            except asyncio.QueueFull:
                log.warning("Dropping slow WebSocket client")
                self.unsubscribe(queue)
                # Make room for the None sentinel that tells the handler to close.
                while not queue.empty():
                    queue.get_nowait()
                queue.put_nowait(None)

    def __len__(self) -> int:
        return len(self._clients)
