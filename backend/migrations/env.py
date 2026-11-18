"""Alembic environment. Migrations are hand-written SQL files (migrations/sql); see DB spec 10.2."""
import os

from alembic import context
from sqlalchemy import create_engine, pool

from app.core.config import normalize_database_url

url = os.environ.get("MIGRATION_DATABASE_URL") or os.environ.get("DATABASE_URL")
if not url:
    raise SystemExit("Set MIGRATION_DATABASE_URL or DATABASE_URL")
if "-pooler." in url:
    raise SystemExit("Run migrations over a direct (non-pooled) connection: remove '-pooler' from the host")
url = normalize_database_url(url)


def run_migrations_online() -> None:
    engine = create_engine(url, poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=None, transaction_per_migration=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    raise SystemExit("Offline mode is not supported: migrations execute SQL files directly.")
run_migrations_online()
