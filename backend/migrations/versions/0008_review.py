"""0008_review: see migrations/sql/0008_review.sql"""
from migrations.sqlfile import forbid_in_production, run_sql, run_sql_file

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql_file("0008_review.sql")


def downgrade() -> None:
    forbid_in_production(revision)
    run_sql("DROP TABLE review.review_notes, review.review_items;")
