"""0003_identity: see migrations/sql/0003_identity.sql"""
from migrations.sqlfile import forbid_in_production, run_sql, run_sql_file

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql_file("0003_identity.sql")


def downgrade() -> None:
    forbid_in_production(revision)
    run_sql("DROP TABLE identity.platform_permissions, identity.push_endpoints, identity.installations, identity.users;")
