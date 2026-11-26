"""Integration tests against a real TimescaleDB + PostGIS.

Skipped unless TEST_DATABASE_URL is set (CI runs them with a service
container; locally: docker compose up db, then
TEST_DATABASE_URL=postgresql://postgres:<password>@localhost:5432/minicop_test).
The test database is wiped at the start of each test.
"""

import asyncio
import os
from datetime import UTC, datetime, timedelta

import asyncpg
import pytest

from minicop.db import migrate, set_retention
from minicop.events import Track
from minicop.recorder import Recorder

DSN = os.getenv("TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(not DSN, reason="TEST_DATABASE_URL not set")
T0 = datetime(2026, 11, 26, 12, 0, tzinfo=UTC)


async def fresh_connection() -> asyncpg.Connection:
    conn = await asyncpg.connect(DSN)
    await conn.execute(
        "DROP TABLE IF EXISTS positions CASCADE; DROP TABLE IF EXISTS ships CASCADE;"
        "DROP TABLE IF EXISTS schema_migrations;"
    )
    return conn


def run(coro):  # tiny helper: async tests without a pytest plugin
    return asyncio.run(coro)


def test_migrations_apply_once():
    async def body():
        conn = await fresh_connection()
        try:
            assert await migrate(conn) == ["001_positions.sql"]
            assert await migrate(conn) == []  # idempotent
            hypertables = await conn.fetchval(
                "SELECT count(*) FROM timescaledb_information.hypertables"
                " WHERE hypertable_name = 'positions'"
            )
            assert hypertables == 1
        finally:
            await conn.close()

    run(body())


def test_policies_are_in_place():
    async def body():
        conn = await fresh_connection()
        try:
            await migrate(conn)
            await set_retention(conn, 30)
            await set_retention(conn, 7)  # changing it replaces the policy
            jobs = await conn.fetch(
                "SELECT proc_name, config FROM timescaledb_information.jobs"
                " WHERE hypertable_name = 'positions'"
            )
            names = sorted(j["proc_name"] for j in jobs)
            assert names == ["policy_compression", "policy_retention"]
            retention = next(j for j in jobs if j["proc_name"] == "policy_retention")
            assert "7 days" in retention["config"]
        finally:
            await conn.close()

    run(body())


def test_recorder_writes_positions_and_ships():
    async def body():
        conn = await fresh_connection()
        recorder = Recorder(DSN, retention_days=30)
        for s in range(3):
            recorder.enqueue(
                Track(
                    mmsi=263000001,
                    ship_name="" if s == 2 else "TEST SHIP",
                    latitude=37.0 + s * 0.001,
                    longitude=-8.0,
                    sog=6,
                    cog=0,
                    true_heading=511,
                    navigational_status=0,
                    last_seen=T0 + timedelta(seconds=10 * s),
                )
            )
        task = asyncio.create_task(recorder.run())
        try:
            for _ in range(100):  # wait up to ~10 s for the batch
                if recorder.written == 3:
                    break
                await asyncio.sleep(0.1)
            assert recorder.written == 3
            rows = await conn.fetch(
                "SELECT lat, ST_Y(geom::geometry) AS geom_lat FROM positions ORDER BY time"
            )
            assert [round(r["lat"], 3) for r in rows] == [37.0, 37.001, 37.002]
            assert all(abs(r["lat"] - r["geom_lat"]) < 1e-9 for r in rows)  # geom derived
            ship = await conn.fetchrow("SELECT * FROM ships WHERE mmsi = 263000001")
            assert ship["name"] == "TEST SHIP"  # empty name didn't overwrite it
            assert ship["last_seen"] == T0 + timedelta(seconds=20)
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            await conn.close()

    run(body())
