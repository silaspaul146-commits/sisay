"""0017_alerts_and_installations: see migrations/sql/0017_alerts_and_installations.sql"""
from migrations.sqlfile import forbid_in_production, run_sql, run_sql_file

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql_file("0017_alerts_and_installations.sql")
    run_sql_file("grants.sql")


def downgrade() -> None:
    forbid_in_production(revision)
    run_sql("""
        DROP FUNCTION identity.register_push_endpoint(uuid, text, text);
        ALTER TABLE alerting.alert_versions
          DROP CONSTRAINT ck_alert_versions_status,
          DROP COLUMN category_code, DROP COLUMN verification_status, DROP COLUMN severity,
          DROP COLUMN status, DROP COLUMN notify, DROP COLUMN public_point,
          DROP COLUMN public_precision_m, DROP COLUMN policy_version;
        ALTER TABLE alerting.alerts DROP COLUMN category_id;
        DROP TABLE alerting.alert_inbox;
        DROP INDEX identity.uq_installations_token_hash;
        ALTER TABLE identity.installations DROP CONSTRAINT ck_installations_token_pair,
          DROP COLUMN token_hash, DROP COLUMN token_pepper_version;
    """)
