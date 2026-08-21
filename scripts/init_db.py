"""One-time database setup: applies db/schema.sql to the configured database.

Run manually after creating a Neon project (with the pgvector extension
available) and setting DATABASE_URL in .env:

    python scripts/init_db.py

Only meant to run once per fresh database — the schema has no "IF NOT
EXISTS" guards on its tables, so re-running against an already-initialized
database fails cleanly with an explanation instead of partially applying
changes.
"""

from __future__ import annotations

import sys
from pathlib import Path

import psycopg

from app.config import get_settings

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "db" / "schema.sql"


def apply_schema(database_url: str, schema_path: Path = SCHEMA_PATH) -> None:
    """Apply a SQL schema file to a database in a single transaction.

    Args:
        database_url: Postgres connection string to apply the schema to.
        schema_path: Path to the .sql file containing the schema DDL.

    Raises:
        psycopg.Error: If any statement in the schema fails (e.g. because it
            was already applied). The transaction is rolled back before the
            error propagates, so no partial schema is left behind.
    """
    schema_sql = schema_path.read_text(encoding="utf-8")
    with psycopg.connect(database_url) as conn, conn.cursor() as cur:
        cur.execute(schema_sql)


def main() -> None:
    """Load settings from the environment and apply db/schema.sql."""
    settings = get_settings()

    print(f"Applying {SCHEMA_PATH} to the configured database...")
    try:
        apply_schema(settings.database_url)
    except psycopg.Error as exc:
        print(
            "Failed to apply schema. If this database was already "
            "initialized, this is expected — the schema only needs to be "
            "applied once.\n"
            f"Database error: {exc}",
            file=sys.stderr,
        )
        sys.exit(1)

    print("Schema applied successfully.")


if __name__ == "__main__":
    main()
