"""Audit log writes (DB spec 4.11). Records who/what/when; never copies sensitive values."""
import json
import uuid
from typing import Any

from sqlalchemy import Connection, text

from app.core.errors import request_id_var


def audit(conn: Connection, *, action: str, resource_type: str, resource_id: uuid.UUID,
          actor_type: str, actor_id: uuid.UUID | None = None, organization_id: uuid.UUID | None = None,
          metadata: dict[str, Any] | None = None) -> None:
    rid = request_id_var.get() or None
    conn.execute(
        text("""
            INSERT INTO ops.audit_logs (actor_id, actor_type, organization_id, action, resource_type,
                                        resource_id, request_id, metadata)
            VALUES (:actor_id, :actor_type, :organization_id, :action, :resource_type, :resource_id,
                    CAST(:request_id AS uuid), CAST(:metadata AS jsonb))
        """),
        {"actor_id": actor_id, "actor_type": actor_type, "organization_id": organization_id,
         "action": action, "resource_type": resource_type, "resource_id": resource_id,
         "request_id": rid, "metadata": json.dumps(metadata or {}, default=str)},
    )
