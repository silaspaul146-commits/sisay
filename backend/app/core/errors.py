"""Standard error envelope (API contract 1.4, 20).

{"error": {"code": "...", "message": "...", "details": [...], "request_id": "..."}}
Messages are generic: errors must not reveal whether private resources exist.
"""
import logging
import uuid
from contextvars import ContextVar

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger(__name__)

request_id_var: ContextVar[str] = ContextVar("request_id", default="")


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, details: list[dict] | None = None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.details = details or []


def validation_error(field: str, message: str, code: str = "validation_error") -> ApiError:
    return ApiError(422, code, "The submitted request is invalid.", [{"field": field, "message": message}])


def _body(code: str, message: str, details: list[dict]) -> dict:
    return {"error": {"code": code, "message": message, "details": details, "request_id": request_id_var.get()}}


_STATUS_CODES = {
    400: "bad_request",
    401: "authentication_required",
    403: "insufficient_permission",
    404: "resource_not_found",
    405: "method_not_allowed",
    409: "invalid_state_transition",
    429: "rate_limit_exceeded",
}


def install_error_handlers(app: FastAPI) -> None:
    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next):
        rid = request.headers.get("X-Request-ID")
        try:
            rid = str(uuid.UUID(rid)) if rid else str(uuid.uuid4())
        except ValueError:
            rid = str(uuid.uuid4())
        token = request_id_var.set(rid)
        try:
            response = await call_next(request)
        except Exception:
            # Handled here, not by the app-level Exception handler: that one runs in Starlette's
            # outermost middleware, after this context has been reset, so the 500 would carry no
            # request id in the body or the X-Request-ID header.
            log.exception("unhandled error", extra={"request_id": rid})
            response = JSONResponse(_body("internal_error", "An unexpected error occurred.", []), status_code=500)
        finally:
            request_id_var.reset(token)
        response.headers["X-Request-ID"] = rid
        return response

    @app.exception_handler(ApiError)
    async def api_error(_: Request, exc: ApiError):
        return JSONResponse(_body(exc.code, exc.message, exc.details), status_code=exc.status)

    @app.exception_handler(RequestValidationError)
    async def request_validation(_: Request, exc: RequestValidationError):
        details = []
        for err in exc.errors():
            loc = [str(p) for p in err.get("loc", ()) if p not in ("body", "query", "header", "path")]
            # Never echo submitted values back: they may contain coordinates or tokens.
            details.append({"field": ".".join(loc) or None, "message": err.get("msg", "Invalid value.")})
        return JSONResponse(_body("validation_error", "The submitted request is invalid.", details), status_code=422)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(_: Request, exc: StarletteHTTPException):
        code = _STATUS_CODES.get(exc.status_code, "error")
        return JSONResponse(_body(code, "The request could not be processed.", []), status_code=exc.status_code)

    @app.exception_handler(Exception)
    async def unexpected(_: Request, exc: Exception):
        log.exception("unhandled error", extra={"request_id": request_id_var.get()})
        return JSONResponse(_body("internal_error", "An unexpected error occurred.", []), status_code=500)
