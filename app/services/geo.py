"""Service-area and coordinate validation helpers."""
from __future__ import annotations

from typing import Optional, Tuple

from app.core.config import settings


def parse_bbox(raw: str) -> Tuple[float, float, float, float]:
    """Parse 'min_lng,min_lat,max_lng,max_lat'."""
    parts = [float(x.strip()) for x in raw.split(",")]
    if len(parts) != 4:
        raise ValueError("SERVICE_AREA_BBOX must be min_lng,min_lat,max_lng,max_lat")
    min_lng, min_lat, max_lng, max_lat = parts
    return min_lng, min_lat, max_lng, max_lat


def point_in_service_area(lat: float, lng: float) -> bool:
    if not settings.SERVICE_AREA_ENABLED:
        return True
    try:
        min_lng, min_lat, max_lng, max_lat = parse_bbox(settings.SERVICE_AREA_BBOX)
    except ValueError:
        return True
    return min_lat <= lat <= max_lat and min_lng <= lng <= max_lng


def assert_service_area(lat: float, lng: float, label: str = "Location") -> Optional[str]:
    """Return error message if outside area, else None."""
    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        return f"{label} coordinates are invalid"
    if not point_in_service_area(lat, lng):
        return f"{label} is outside our service area"
    return None
