"""FastAPI application: modular monolith, API under /api/v1 (Engineering pack 2, API contract 1.2)."""
import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.core.config import get_settings
from app.core.db import get_engine
from app.core.errors import install_error_handlers
from app.core.logging import configure_logging
from app.modules.administration.router import router as reference_router
from app.modules.disclosure.public_router import router as public_router
from app.modules.reporting.router import router as reporting_router


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Optionally run the outbox worker in this process (RUN_WORKER_IN_API, see config)."""
    settings = get_settings()
    worker = None
    if settings.run_worker_in_api:
        from app.core.db import make_engine
        from app.infrastructure.workers.runner import Worker
        worker = Worker(settings, engine=make_engine(settings.worker_database_url, 2))
        threading.Thread(target=worker.run_forever, kwargs={"install_signal_handlers": False},
                         name="outbox-worker", daemon=True).start()
    yield
    if worker:
        worker.stop()


def create_app() -> FastAPI:
    configure_logging()
    settings = get_settings()
    app = FastAPI(
        lifespan=lifespan,
        title="Crisis Safety and Humanitarian Intelligence Platform API",
        version="1.0.0",
        openapi_url="/api/v1/openapi.json",
        docs_url=None if settings.app_env == "production" else "/docs",
        redoc_url=None,
    )
    install_error_handlers(app)

    api = APIRouter(prefix="/api/v1")
    api.include_router(reference_router)
    api.include_router(reporting_router)
    api.include_router(public_router)
    app.include_router(api)

    @app.get("/health", tags=["operations"], include_in_schema=False)
    def health() -> dict:
        return {"status": "ok"}

    @app.get("/ready", tags=["operations"], include_in_schema=False)
    def ready():
        try:
            with get_engine().connect() as conn:
                conn.execute(text("SELECT 1 FROM ref.incident_categories LIMIT 1"))
        except Exception:
            return JSONResponse({"status": "unavailable"}, status_code=503)
        return {"status": "ready"}

    return app


app = create_app()
