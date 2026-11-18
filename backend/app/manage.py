"""Operational commands. Run with the owner/migration connection (MIGRATION_DATABASE_URL).

  python -m app.manage db-check              PostgreSQL/PostGIS versions, migration revision, roles
  python -m app.manage db-roles [--rotate]   create runtime roles, apply grants, print their URLs
  python -m app.manage grant --subject SUB --email E PERMISSION...    provision a staff user
  python -m app.manage grant --subject SUB --revoke PERMISSION...     revoke permissions

Staff sign in at the OIDC provider (U-1). `--subject` is the provider's `sub` claim for that person
(shown in the provider's user list, e.g. "auth0|65f..." or a UUID). Users are never created
automatically on first sign-in.

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


PERMISSIONS = ("incident.view", "incident.assess", "incident.verify", "incident.correct", "incident.merge",
               "report.review", "reporter_identity.view", "evidence.view_restricted", "alert.issue",
               "alert.withdraw", "disclosure_policy.manage", "platform.admin")
REVIEWER_BUNDLE = ("incident.view", "incident.assess", "incident.verify", "incident.merge", "report.review")


def grant(subject: str, email: str | None, permissions: list[str], revoke: bool) -> None:
    unknown = [p for p in permissions if p not in PERMISSIONS and p != "reviewer"]
    if unknown:
        sys.exit(f"Unknown permission(s): {', '.join(unknown)}. Valid: reviewer (bundle), {', '.join(PERMISSIONS)}")
    codes = sorted({c for p in permissions for c in (REVIEWER_BUNDLE if p == "reviewer" else (p,))})
    with psycopg.connect(libpq_url(_owner_url())) as conn:
        user = conn.execute("SELECT id FROM identity.users WHERE auth_subject = %s", (subject,)).fetchone()
        if revoke:
            if not user:
                sys.exit("No user with that subject.")
            n = conn.execute("""UPDATE identity.platform_permissions SET revoked_at = now()
                                WHERE user_id = %s AND permission_code = ANY(%s) AND revoked_at IS NULL""",
                             (user[0], codes)).rowcount
            print(f"Revoked {n} permission(s).")
            return
        if not user:
            if not email:
                sys.exit("New user: --email is required.")
            user = conn.execute("""INSERT INTO identity.users (email, auth_subject, status)
                                   VALUES (%s, %s, 'active') RETURNING id""", (email, subject)).fetchone()
            print(f"Created user {user[0]}")
        else:
            conn.execute("UPDATE identity.users SET status = 'active' WHERE id = %s AND status <> 'active'", (user[0],))
        for code in codes:
            conn.execute("""INSERT INTO identity.platform_permissions (user_id, permission_code)
                            VALUES (%s, %s) ON CONFLICT DO NOTHING""", (user[0], code))
        conn.execute("""INSERT INTO ops.audit_logs (actor_type, action, resource_type, resource_id, metadata)
                        VALUES ('system', 'permission.grant', 'user', %s, jsonb_build_object('codes', %s::text[]))""",
                     (user[0], codes))
        active = conn.execute("""SELECT permission_code FROM identity.platform_permissions
                                 WHERE user_id = %s AND revoked_at IS NULL ORDER BY 1""", (user[0],)).fetchall()
        print("Active permissions:", ", ".join(r[0] for r in active))


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.manage")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("db-check")
    roles = sub.add_parser("db-roles")
    roles.add_argument("--rotate", action="store_true", help="set new passwords for existing roles")
    g = sub.add_parser("grant", help="provision a staff user and grant (or --revoke) platform permissions")
    g.add_argument("--subject", required=True, help="the OIDC provider's `sub` for this person")
    g.add_argument("--email")
    g.add_argument("--revoke", action="store_true")
    g.add_argument("permissions", nargs="+", help="permission codes, or `reviewer` for the reviewer bundle")
    args = parser.parse_args()
    if args.cmd == "db-check":
        db_check()
    elif args.cmd == "grant":
        grant(args.subject, args.email, args.permissions, args.revoke)
    else:
        db_roles(args.rotate)


if __name__ == "__main__":
    main()
