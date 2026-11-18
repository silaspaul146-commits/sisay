"""Database engines and per-request transactions.

All transactions run at READ COMMITTED (DB spec 8). SQL is written explicitly with SQLAlchemy Core
`text()`: the spatial queries are PostGIS-specific and are kept readable next to the spec.
"""
from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Connection, Engine, create_engine

from app.core.config import get_settings


def make_engine(url: str, pool_size: int) -> Engine:
    connect_args = {}
    if "-pooler." in url:
        # Neon's pooled endpoint runs PgBouncer in transaction mode: no server-side prepared statements.
        connect_args["prepare_threshold"] = None
    # pool_pre_ping also covers Neon computes that were suspended while idle.
    return create_engine(url, pool_pre_ping=True, pool_size=pool_size, max_overflow=pool_size,
                         pool_recycle=300, connect_args=connect_args)


@lru_cache
def get_engine() -> Engine:
    return make_engine(get_settings().database_url, 5)


@lru_cache
def get_public_engine() -> Engine:
    return make_engine(get_settings().effective_public_database_url, 5)


@lru_cache
def get_dashboard_engine() -> Engine:
    return make_engine(get_settings().effective_dashboard_database_url, 5)


def transaction() -> Iterator[Connection]:
    """FastAPI dependency: one transaction per request, committed on success."""
    with get_engine().begin() as conn:
        yield conn


def public_connection() -> Iterator[Connection]:
    """FastAPI dependency for public routes: read-only access through the public role."""
    with get_public_engine().connect() as conn:
        yield conn
