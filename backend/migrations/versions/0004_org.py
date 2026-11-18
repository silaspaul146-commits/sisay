"""0004_org: see migrations/sql/0004_org.sql"""
from migrations.sqlfile import forbid_in_production, run_sql, run_sql_file

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql_file("0004_org.sql")


def downgrade() -> None:
    forbid_in_production(revision)
    run_sql("DROP TABLE org.membership_permissions, org.organization_memberships, org.organizations;")
