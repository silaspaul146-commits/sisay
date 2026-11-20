"""GET /public/app-config: settings the app picks up at start, so some fixes need no new release.

Today it carries the map tile provider. The app keeps the last answer and falls back to its
built-in default, so this endpoint being slow or down never blanks the map.
"""
from typing import Annotated

from fastapi import APIRouter, Depends, Response

from app.core.config import Settings, get_settings

router = APIRouter(prefix="/public", tags=["public map"])


@router.get("/app-config")
def app_config(settings: Annotated[Settings, Depends(get_settings)], response: Response) -> dict:
    response.headers["Cache-Control"] = "public, max-age=300"
    return {
        "map": {
            "tile_url": settings.map_tile_url,
            "fallback_url": settings.map_fallback_url or None,
            "subdomains": [s.strip() for s in settings.map_subdomains.split(",") if s.strip()],
            "attribution": settings.map_attribution,
            "max_zoom": settings.map_max_zoom,
            "saturation": settings.map_saturation,
        }
    }
