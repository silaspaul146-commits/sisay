"""Operational commands. Run with the owner/migration connection (MIGRATION_DATABASE_URL).

  python -m app.manage db-check              PostgreSQL/PostGIS versions, migration revision, roles
  python -m app.manage db-roles [--rotate]   create runtime roles, apply grants, print their URLs

Runtime roles (DB spec 9.2): the API uses app_citizen, public map routes use app_public, the worker
uses app_worker. Passwords are generated here and printed ONCE; put them in the host's secret
settings (Render environment), never in the repository.
"""
import argparse
import os
import secrets
import sys
from pathlib import Path

import psycopg
from psycopg import sql
from sqlalchemy.engine import make_url

from app.core.config import libpq_url, normalize_database_url

ROLES = {
    "app_citizen": "API DATABASE_URL",
    "app_public": "API PUBLIC_DATABASE_URL",
    "app_worker": "worker DATABASE_URL",
    "app_dashboard": "dashboard API (later phase)",
    "app_analytics": "analytics / BI (later phase)",
}
GRANTS_SQL = Path(__file__).resolve().parents[1] / "migrations" / "sql" / "grants.sql"


def _owner_url() -> str:
    url = os.environ.get("MIGRATION_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not url:
        sys.exit("Set MIGRATION_DATABASE_URL (owner role, direct connection)")
    return normalize_database_url(url)


def db_check() -> None:
    with psycopg.connect(libpq_url(_owner_url())) as conn:
        print("server     :", conn.execute("SHOW server_version").fetchone()[0])
        ext = conn.execute("SELECT extname, extversion FROM pg_extension ORDER BY 1").fetchall()
        print("extensions :", ", ".join(f"{n} {v}" for n, v in ext) or "none")
        avail = conn.execute("SELECT default_version FROM pg_available_extensions WHERE name='postgis'").fetchone()
        print("postgis    :", avail[0] if avail else "NOT AVAILABLE")
        try:
            print("migration  :", conn.execute("SELECT version_num FROM alembic_version").fetchone()[0])
        except psycopg.errors.UndefinedTable:
            print("migration  : none (run `alembic upgrade head`)")
            conn.rollback()
        roles = conn.execute("SELECT rolname FROM pg_roles WHERE rolname = ANY(%s)", (list(ROLES),)).fetchall()
        print("roles      :", ", ".join(sorted(r[0] for r in roles)) or "none")


def db_roles(rotate: bool) -> None:
    owner = make_url(_owner_url())
    created: dict[str, str] = {}
    with psycopg.connect(libpq_url(owner.render_as_string(hide_password=False)), autocommit=True) as conn:
        for role in ROLES:
            exists = conn.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,)).fetchone()
            if exists and not rotate:
                continue
            password = secrets.token_urlsafe(32)
            stmt = "ALTER ROLE {} WITH LOGIN PASSWORD {}" if exists else "CREATE ROLE {} WITH LOGIN PASSWORD {}"
            conn.execute(sql.SQL(stmt).format(sql.Identifier(role), sql.Literal(password)))
            created[role] = password
        conn.execute(GRANTS_SQL.read_text(encoding="utf-8"))

    print("Grants applied.")
    if not created:
        print("All roles already existed; passwords unchanged (use --rotate to set new ones).")
        return
    print("\nNew credentials. They are shown only once: store them in your host's secret settings.\n")
    for role, password in created.items():
        url = owner.set(username=role, password=password)
        print(f"# {ROLES[role]}")
        print(f"{role}: {url.render_as_string(hide_password=False)}\n")


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.manage")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("db-check")
    roles = sub.add_parser("db-roles")
    roles.add_argument("--rotate", action="store_true", help="set new passwords for existing roles")
    args = parser.parse_args()
    if args.cmd == "db-check":
        db_check()
    else:
        db_roles(args.rotate)


if __name__ == "__main__":
    main()
