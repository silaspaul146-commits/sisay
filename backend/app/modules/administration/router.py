"""Reference data for clients (Engineering pack 5.2: GET /incident-categories)."""
from typing import Annotated

from fastapi import APIRouter, Depends, Response
from sqlalchemy import Connection, text

from app.core.db import transaction

router = APIRouter(tags=["reference data"])


@router.get("/incident-categories")
def list_incident_categories(response: Response, conn: Annotated[Connection, Depends(transaction)]) -> dict:
    rows = conn.execute(
        text("""SELECT code, name, is_sensitive FROM ref.incident_categories
                WHERE active ORDER BY name""")
    ).all()
    response.headers["Cache-Control"] = "public, max-age=3600"
    return {"items": [{"code": r.code, "name": r.name, "is_sensitive": r.is_sensitive} for r in rows],
            "next_cursor": None}
