"""DB spec 10.2: CI runs upgrade head -> downgrade base -> upgrade head, then checks reference data."""
import pytest
from sqlalchemy import text

from tests.integration.conftest import alembic_config

pytestmark = pytest.mark.integration


def test_downgrade_and_upgrade_cycle(engine):
    from alembic import command
    cfg = alembic_config()
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    with engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM ref.incident_categories")).scalar() == 15
        assert conn.execute(text("SELECT count(*) FROM ref.disclosure_policies WHERE status = 'active'")).scalar() == 4
        # Category compatibility is stored in both directions.
        assert conn.execute(text("""
            SELECT count(*) FROM ref.category_compatibility a
            WHERE NOT EXISTS (SELECT 1 FROM ref.category_compatibility b
                              WHERE b.category_id = a.compatible_category_id
                                AND b.compatible_category_id = a.category_id AND b.weight = a.weight)
        """)).scalar() == 0


def test_snap_is_deterministic(engine):
    with engine.connect() as conn:
        a, b = conn.execute(text("""
            SELECT ST_AsText(disclosure.snap_public_point(ST_SetSRID(ST_MakePoint(10.1591, 5.9631), 4326)::geography, 500)),
                   ST_AsText(disclosure.snap_public_point(ST_SetSRID(ST_MakePoint(10.1591, 5.9631), 4326)::geography, 500))
        """)).one()
        assert a == b
