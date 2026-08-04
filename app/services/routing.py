"""Server-side Mapbox Directions + haversine fallback for fare/ETA truth."""
from __future__ import annotations

import json
import math
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import List, Optional, Tuple

from app.core.config import settings


@dataclass
class RouteResult:
    distance_km: float
    duration_seconds: float
    coordinates: List[List[float]]  # [lng, lat] GeoJSON order
    source: str  # "mapbox" | "haversine"


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * r * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _haversine_route(lat1: float, lng1: float, lat2: float, lng2: float) -> RouteResult:
    distance_km = max(settings.MIN_FARE_DISTANCE_KM, haversine_km(lat1, lng1, lat2, lng2))
    # Assume average urban speed for fallback ETA
    duration_seconds = (distance_km / max(settings.FALLBACK_SPEED_KMH, 1.0)) * 3600
    return RouteResult(
        distance_km=round(distance_km, 3),
        duration_seconds=round(duration_seconds, 1),
        coordinates=[[lng1, lat1], [lng2, lat2]],
        source="haversine",
    )


def get_driving_route(
    pickup_lat: float,
    pickup_lng: float,
    dropoff_lat: float,
    dropoff_lng: float,
    profile: Optional[str] = None,
) -> RouteResult:
    """Return road-network route when Mapbox token is set; else haversine fallback."""
    profile = profile or settings.MAPBOX_ROUTING_PROFILE
    token = settings.MAPBOX_ACCESS_TOKEN
    if not token:
        return _haversine_route(pickup_lat, pickup_lng, dropoff_lat, dropoff_lng)

    coords = f"{pickup_lng},{pickup_lat};{dropoff_lng},{dropoff_lat}"
    qs = urllib.parse.urlencode({
        "geometries": "geojson",
        "overview": "full",
        "access_token": token,
    })
    url = f"https://api.mapbox.com/directions/v5/mapbox/{profile}/{coords}?{qs}"

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "jk-taxi-backend/2"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError, ValueError):
        return _haversine_route(pickup_lat, pickup_lng, dropoff_lat, dropoff_lng)

    routes = payload.get("routes") or []
    if not routes:
        return _haversine_route(pickup_lat, pickup_lng, dropoff_lat, dropoff_lng)

    route = routes[0]
    distance_m = float(route.get("distance") or 0)
    duration_s = float(route.get("duration") or 0)
    geometry = (route.get("geometry") or {}).get("coordinates") or []
    distance_km = max(settings.MIN_FARE_DISTANCE_KM, distance_m / 1000.0)

    return RouteResult(
        distance_km=round(distance_km, 3),
        duration_seconds=round(duration_s, 1),
        coordinates=geometry,
        source="mapbox",
    )


def estimate_pickup_eta_minutes(distance_km: float) -> float:
    return (distance_km / max(settings.FALLBACK_SPEED_KMH, 1.0)) * 60.0
