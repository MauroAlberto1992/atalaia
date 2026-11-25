"""End-to-end smoke test of the Docker stack, through nginx.

Usage: python scripts/smoke_test.py [base_url]   (default http://localhost:8080)
Needs the `websockets` package. Exits non-zero on the first failure.
"""

import asyncio
import json
import sys
import urllib.request

from websockets.asyncio.client import connect


def get(url: str) -> tuple[int, bytes]:
    with urllib.request.urlopen(url, timeout=10) as r:
        return r.status, r.read()


async def main(base: str) -> None:
    status, body = get(f"{base}/")
    assert status == 200 and b'<div id="root">' in body, "app page not served"
    print("ok  /  serves the app")

    status, body = get(f"{base}/api/health")
    health = json.loads(body)
    assert status == 200 and "tracks" in health, f"bad /api/health: {health}"
    print(f"ok  /api/health  {health}")

    ws_url = base.replace("http", "ws", 1) + "/live"
    async with connect(ws_url, open_timeout=10) as ws:
        first = json.loads(await asyncio.wait_for(ws.recv(), 10))
    assert first["type"] == "snapshot", f"expected snapshot, got {first['type']}"
    print(f"ok  /live  snapshot with {len(first['tracks'])} tracks")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8080"))
