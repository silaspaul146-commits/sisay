"""Helpers shared by the revision scripts."""
import os
from pathlib import Path

from alembic import op

SQL_DIR = Path(__file__).parent / "sql"


def run_sql_file(name: str) -> None:
    """Execute a multi-statement SQL file on the migration connection.

    Uses the raw psycopg connection (simple query protocol) so that dollar-quoted function
    bodies and multiple statements run as written, inside Alembic's transaction.
    """
    sql = (SQL_DIR / name).read_text(encoding="utf-8")
    op.get_bind().connection.driver_connection.execute(sql)


def run_sql(sql: str) -> None:
    op.get_bind().connection.driver_connection.execute(sql)


def forbid_in_production(revision: str) -> None:
    """DB spec 12.1: production schema changes only move forward."""
    if os.environ.get("APP_ENV", "development") == "production":
        raise NotImplementedError(f"Downgrade of {revision} is not allowed in production; write a forward migration.")
