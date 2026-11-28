"""Impossible positions on the recorded real AIS (phase 17a evaluation).

Run inside the backend container (it has DATABASE_URL and the bathymetry):
    docker compose exec backend python -m minicop.evaluate_context --hours 24

For every recorded position in the window that the bathymetry covers, applies
the same rule as the live ContextMonitor (context.impossible_reason) with each
ship's declared draught from the ships table, and reports:
- how many positions were judged, and why the others were skipped
  (port, coastal band, no draught);
- how many are impossible: on land, or shallower than draught + margin;
- the ships involved, with examples (depth, draught, position).
"""

import argparse
import asyncio
import os
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta

import asyncpg

from minicop.bathymetry import load_bathymetry
from minicop.context import impossible_reason, load_context_config
from minicop.events import Track
from minicop.ports import PORT_MARGIN_NM, load_ports


async def main(hours: int, area: str) -> None:
    dsn = os.environ["DATABASE_URL"]
    bathy = load_bathymetry(area)
    if bathy is None:
        raise SystemExit(
            f"No bathymetry for '{area}': run scripts/fetch_bathymetry.py --area {area}"
        )
    cfg = load_context_config()
    ports = load_ports()
    conn = await asyncpg.connect(dsn)
    try:
        rows = await conn.fetch(
            """
            SELECT p.time, p.mmsi, p.lat, p.lon, s.name, s.ship_type, s.draught_m
            FROM positions p LEFT JOIN ships s ON s.mmsi = p.mmsi
            WHERE p.time >= $1
            """,
            datetime.now(UTC) - timedelta(hours=hours),
        )
    finally:
        await conn.close()

    counts: Counter[str] = Counter()
    by_ship: dict[int, list[str]] = defaultdict(list)
    names: dict[int, str] = {}
    for r in rows:
        lat, lon = r["lat"], r["lon"]
        if not bathy.covers(lat, lon):
            counts["outside the bathymetry"] += 1
            continue
        if any(p.near(lat, lon, PORT_MARGIN_NM) for p in ports):
            counts["skipped: in or near a port"] += 1
            continue
        land, sea = bathy.surroundings(lat, lon, cfg.coast_margin_m)
        if land and sea:
            counts["skipped: coastal band"] += 1
            continue
        track = Track(
            mmsi=r["mmsi"],
            ship_name=r["name"] or "",
            latitude=lat,
            longitude=lon,
            sog=0,
            cog=360,
            true_heading=511,
            navigational_status=0,
            last_seen=r["time"],
            draught_m=r["draught_m"],
        )
        counts["judged"] += 1
        if r["draught_m"] is None and sea:
            counts["judged, no declared draught (only 'on land' can fire)"] += 1
        reason = impossible_reason(track, bathy, cfg, [])
        if reason:
            counts["IMPOSSIBLE: on land" if "on land" in reason else "IMPOSSIBLE: too shallow"] += 1
            by_ship[r["mmsi"]].append(f"{r['time']:%Y-%m-%d %H:%M} {lat:.5f},{lon:.5f} {reason}")
            names[r["mmsi"]] = r["name"] or ""

    print(f"Recorded positions in the last {hours} h: {len(rows)}")
    for key, n in sorted(counts.items()):
        print(f"  {key:55} {n}")
    print(f"Ships with impossible positions: {len(by_ship)}")
    for mmsi, items in sorted(by_ship.items(), key=lambda kv: -len(kv[1]))[:15]:
        print(f"  {mmsi} {names[mmsi]!r}: {len(items)} positions, e.g. {items[0]}")
    print("Bathymetry: EMODnet DTM 2024 (CC BY 4.0). Not for navigation.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Impossible positions on recorded AIS.")
    parser.add_argument("--hours", type=int, default=24)
    parser.add_argument("--area", default=os.getenv("MINICOP_AREA", "algarve"))
    args = parser.parse_args()
    asyncio.run(main(args.hours, args.area))
