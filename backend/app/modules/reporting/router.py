"""Reporting routes (API contract 3). Anonymous: no account is ever required to report (BR-01)."""
import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, Response

from app.core.config import Settings, get_settings
from app.core.db import get_engine
from app.modules.reporting.schemas import ReportCreate, ReportCreated, ReportStatus
from app.modules.reporting.service import SubmitContext, get_report_status, submit_report

router = APIRouter(prefix="/reports", tags=["reporting"])


@router.post(
    "",
    response_model=ReportCreated,
    response_model_exclude_none=True,
    status_code=201,
    responses={200: {"description": "Idempotent replay of an earlier submission (never includes the token)"},
               409: {"description": "Idempotency-Key reused with a different payload"}},
)
def create_report(
    payload: ReportCreate,
    response: Response,
    idempotency_key: Annotated[uuid.UUID, Header(alias="Idempotency-Key")],
    settings: Annotated[Settings, Depends(get_settings)],
    installation_id: Annotated[uuid.UUID | None, Header(alias="X-Installation-ID")] = None,
    client_platform: Annotated[Literal["android", "ios", "web"], Header(alias="X-Client-Platform")] = "android",
    access_token: Annotated[str | None, Header(alias="X-Report-Access-Token")] = None,
) -> ReportCreated:
    """Submit a report. Clients should generate the access token on the device and send it here,
    so that a lost response never loses the token (DB spec F-01)."""
    # Commit inside the endpoint, before responding: a 201/200 must mean the report is persisted
    # (BR-23). A yield-dependency teardown may run after the response has been sent.
    with get_engine().begin() as conn:
        status, body = submit_report(
            conn, payload,
            SubmitContext(idempotency_key=idempotency_key, installation_id=installation_id,
                          client_platform=client_platform, client_token=access_token),
            settings,
        )
    response.status_code = status
    response.headers["Cache-Control"] = "no-store"
    return body


@router.get("/{report_id}/status", response_model=ReportStatus)
def report_status(
    report_id: uuid.UUID,
    response: Response,
    settings: Annotated[Settings, Depends(get_settings)],
    access_token: Annotated[str | None, Header(alias="X-Report-Access-Token")] = None,
) -> ReportStatus:
    response.headers["Cache-Control"] = "no-store"
    with get_engine().begin() as conn:
        return get_report_status(conn, report_id, access_token, settings)
