"""0010_subscription: see migrations/sql/0010_subscription.sql"""
from migrations.sqlfile import forbid_in_production, run_sql, run_sql_file

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql_file("0010_subscription.sql")


def downgrade() -> None:
    forbid_in_production(revision)
    run_sql("DROP TABLE subscription.journey_checks, subscription.alert_subscription_categories, subscription.alert_subscriptions, subscription.saved_routes, subscription.saved_locations, subscription.subscriber_principals;")
