"""POST /public/place-search: find a town, neighbourhood or road to move the map to. No account."""
from functools import lru_cache
from typing import Literal

from fastapi import APIRouter, Response
from pydantic import BaseModel, ConfigDict, Field

from app.core.config import get_settings
from app.core.errors import ApiError, validation_error
from app.modules.places.geocoder import NominatimGeocoder, SearchUnavailable

router = APIRouter(prefix="/public", tags=["public map"])
ATTRIBUTION = "© OpenStreetMap contributors"


class PlaceSearchIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(min_length=2, max_length=100)
    lang: Literal["en", "fr"] = "en"
    limit: int = Field(default=8, ge=1, le=10)


@lru_cache
def geocoder() -> NominatimGeocoder:
    s = get_settings()
    return NominatimGeocoder(user_agent=s.geocoder_user_agent, url=s.geocoder_url)


@router.post("/place-search")
def place_search(body: PlaceSearchIn, response: Response) -> dict:
    if len(body.query.strip()) < 2:
        raise validation_error("query", "Type at least two letters.")
    try:
        places = geocoder().search(body.query, body.lang, body.limit)
    except SearchUnavailable:
        raise ApiError(503, "search_unavailable", "Place search is not available right now. Move the map instead.")
    response.headers["Cache-Control"] = "no-store"
    return {"items": [p.as_dict() for p in places], "attribution": ATTRIBUTION}
