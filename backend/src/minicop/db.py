"""Database setup: numbered SQL migrations and the retention policy.

Migrations are plain SQL files in backend/migrations, applied in name order
inside a transaction each, and recorded in schema_migrations so they run once.
No ORM: the schema is visible as SQL.
"""

import logging
from pathlib import Path

import asyncpg

from minicop.config import BACKEND_DIR

log = logging.getLogger(__name__)

MIGRATIONS_DIR = BACKEND_DIR / "migrations"


def load_migrations(directory: Path = MIGRATIONS_DIR) -> list[tuple[str, str]]:
    """(name, sql) of every migration file, in name order. Plain blocking file
    reads: they run once at startup and the files are tiny."""
    return [(p.name, p.read_text()) for p in sorted(directory.glob("*.sql"))]


async def migrate(conn: asyncpg.Connection, directory: Path = MIGRATIONS_DIR) -> list[str]:
    """Apply pending migrations. Returns the names applied this time."""
    await conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        " name text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())"
    )
    done = {r["name"] for r in await conn.fetch("SELECT name FROM schema_migrations")}
    applied = []
    for name, sql in load_migrations(directory):
        if name in done:
            continue
        async with conn.transaction():
            await conn.execute(sql)
            await conn.execute("INSERT INTO schema_migrations (name) VALUES ($1)", name)
        log.info("Applied migration %s", name)
        applied.append(name)
    return applied


async def set_retention(conn: asyncpg.Connection, days: int) -> None:
    """(Re)apply the retention policy, so changing the setting takes effect."""
    await conn.execute("SELECT remove_retention_policy('positions', if_exists => true)")
    await conn.execute("SELECT add_retention_policy('positions', make_interval(days => $1))", days)
