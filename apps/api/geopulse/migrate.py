"""Versioned SQL migrations protected by a PostgreSQL advisory lock."""

import os
from pathlib import Path
import psycopg


def main():
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        conn.execute("SELECT pg_advisory_xact_lock(824131)")
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations (version text PRIMARY KEY, applied_at timestamptz DEFAULT now())"
        )
        for file in sorted((Path(__file__).parent.parent / "migrations").glob("*.sql")):
            if not conn.execute("SELECT 1 FROM schema_migrations WHERE version=%s", (file.name,)).fetchone():
                conn.execute(file.read_text())
                conn.execute("INSERT INTO schema_migrations(version) VALUES (%s)", (file.name,))
                print(f"Applied {file.name}")


if __name__ == "__main__":
    main()
