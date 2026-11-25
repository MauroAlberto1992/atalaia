"""End-to-end smoke test of the Docker stack, through nginx.

Usage: python scripts/smoke_test.py [base_url]   (default http://localhost:8080)
Needs the `websockets` package. Exits non-zero on the first failure.
"""

import asyncio
import json
import re
import sys
import urllib.error
import urllib.request

from websockets.asyncio.client import connect


def get(url: str) -> tuple[int, bytes]:
    with urllib.request.urlopen(url, timeout=10) as r:
        return r.status, r.read()


async def main(base: str) -> None:
    status, body = get(f"{base}/")
    assert status == 200 and b'<div id="root">' in body, "app page not served"
    print("ok  /  serves the app")

    # Every built asset the app references (in index.html and inside the JS
    # bundles, e.g. the MapLibre web worker) must exist and must not be HTML.
    # A missing asset once came back as index.html with status 200.
    assets = set(re.findall(r"/?assets/[\w.-]+\.(?:js|mjs|css)", body.decode()))
    for bundle in [a for a in assets if a.endswith(".js")]:
        _, js = get(f"{base}/{bundle.lstrip('/')}")
        assets |= set(re.findall(r"assets/[\w.-]+\.(?:js|mjs|css)", js.decode()))
    for asset in sorted(assets):
        path = asset.lstrip("/")
        with urllib.request.urlopen(f"{base}/{path}", timeout=10) as r:
            ctype = r.headers.get("Content-Type", "")
        assert "text/html" not in ctype, f"{path} served as HTML (missing file?)"
    print(f"ok  {len(assets)} assets served with the right type")

    try:
        get(f"{base}/assets/does-not-exist.js")
        raise AssertionError("missing asset did not return 404")
    except urllib.error.HTTPError as e:
        assert e.code == 404, f"missing asset returned {e.code}"
    print("ok  missing asset -> 404")

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
