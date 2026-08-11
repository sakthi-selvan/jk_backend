"""Geocoding / place search for mobile apps (preview builds often lack a client Mapbox token)."""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.config import settings
from app.core.dependencies import get_current_mobile_actor, get_current_user
from app.models.user import User
from app.services.rate_limit import check_rate_limit
from app.services.routing import get_driving_route

router = APIRouter()

_USER_AGENT = "JKTaxi/1.0 (geo; contact=support@jktaxitamilnadu.com)"


def _http_get_json(url: str, timeout: float = 8.0) -> Dict[str, Any]:
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _map_mapbox_features(features: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for feature in features or []:
        center = feature.get("center") or []
        if len(center) < 2:
            continue
        out.append(
            {
                "name": feature.get("text") or (feature.get("place_name") or "").split(",")[0],
                "address": feature.get("place_name") or "",
                "latitude": float(center[1]),
                "longitude": float(center[0]),
            }
        )
    return out


def _search_mapbox(
    query: str,
    *,
    limit: int,
    proximity: Optional[str],
    country: str = "IN",
) -> List[Dict[str, Any]]:
    token = (settings.MAPBOX_ACCESS_TOKEN or "").strip()
    if not token:
        return []
    params: Dict[str, str] = {
        "access_token": token,
        "limit": str(limit),
        "country": country,
        # Broader than client-only filter so TN localities / areas resolve
        "types": "place,locality,neighborhood,address,poi,district,region",
        "language": "en",
    }
    if proximity:
        params["proximity"] = proximity
    qs = urllib.parse.urlencode(params)
    encoded = urllib.parse.quote(query)
    url = f"https://api.mapbox.com/geocoding/v5/mapbox.places/{encoded}.json?{qs}"
    data = _http_get_json(url)
    if data.get("message"):
        raise HTTPException(status_code=502, detail=f"Mapbox: {data.get('message')}")
    return _map_mapbox_features(data.get("features") or [])


def _search_nominatim(query: str, *, limit: int) -> List[Dict[str, Any]]:
    params = {
        "q": query,
        "format": "json",
        "addressdetails": "0",
        "limit": str(limit),
        "countrycodes": "in",
    }
    url = "https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode(params)
    data = _http_get_json(url)
    out: List[Dict[str, Any]] = []
    for item in data or []:
        try:
            display = item.get("display_name") or ""
            name = display.split(",")[0].strip() or display
            out.append(
                {
                    "name": name,
                    "address": display,
                    "latitude": float(item["lat"]),
                    "longitude": float(item["lon"]),
                }
            )
        except (KeyError, TypeError, ValueError):
            continue
    return out


def _reverse_mapbox(lat: float, lng: float) -> Optional[Dict[str, Any]]:
    token = (settings.MAPBOX_ACCESS_TOKEN or "").strip()
    if not token:
        return None
    params = {"access_token": token, "limit": "1", "language": "en"}
    qs = urllib.parse.urlencode(params)
    url = f"https://api.mapbox.com/geocoding/v5/mapbox.places/{lng},{lat}.json?{qs}"
    data = _http_get_json(url)
    mapped = _map_mapbox_features(data.get("features") or [])
    return mapped[0] if mapped else None


def _reverse_nominatim(lat: float, lng: float) -> Optional[Dict[str, Any]]:
    params = {"lat": str(lat), "lon": str(lng), "format": "json"}
    url = "https://nominatim.openstreetmap.org/reverse?" + urllib.parse.urlencode(params)
    data = _http_get_json(url)
    display = (data or {}).get("display_name")
    if not display:
        return None
    return {
        "name": display.split(",")[0].strip() or display,
        "address": display,
        "latitude": lat,
        "longitude": lng,
    }


@router.get("/search")
async def search_places(
    q: str = Query(..., min_length=2, max_length=200),
    limit: int = Query(5, ge=1, le=10),
    proximity: Optional[str] = Query(
        None, description="lng,lat bias for ranking (Mapbox)"
    ),
    current_user: User = Depends(get_current_user),
):
    """Forward geocode — used by customer app when the preview APK has no Mapbox public token."""
    ok, msg = check_rate_limit(f"geo:search:{current_user.id}", limit=40, window_seconds=60)
    if not ok:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=msg)

    query = q.strip()
    if len(query) < 2:
        return {"results": [], "source": "none"}

    try:
        results = _search_mapbox(query, limit=limit, proximity=proximity)
        if results:
            return {"results": results, "source": "mapbox"}
    except HTTPException:
        raise
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError) as exc:
        # Fall through to Nominatim
        print(f"[geo] mapbox search failed: {exc}")

    try:
        results = _search_nominatim(query, limit=limit)
        return {"results": results, "source": "nominatim" if results else "none"}
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError) as exc:
        raise HTTPException(status_code=502, detail=f"Place search failed: {exc}") from exc


@router.get("/reverse")
async def reverse_geocode(
    lat: float = Query(..., ge=-90, le=90),
    lng: float = Query(..., ge=-180, le=180),
    current_user: User = Depends(get_current_user),
):
    ok, msg = check_rate_limit(f"geo:reverse:{current_user.id}", limit=40, window_seconds=60)
    if not ok:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=msg)

    try:
        result = _reverse_mapbox(lat, lng)
        if result:
            return {"result": result, "source": "mapbox"}
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError) as exc:
        print(f"[geo] mapbox reverse failed: {exc}")

    try:
        result = _reverse_nominatim(lat, lng)
        if result:
            return {"result": result, "source": "nominatim"}
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError) as exc:
        raise HTTPException(status_code=502, detail=f"Reverse geocode failed: {exc}") from exc

    return {"result": None, "source": "none"}


@router.get("/mapbox-token")
async def get_mapbox_client_token(
    actor: dict = Depends(get_current_mobile_actor),
):
    """
    Return a public Mapbox token (pk.) after login so preview APKs can load tiles
    and client Directions without baking EXPO_PUBLIC_MAPBOX_ACCESS_TOKEN into the binary.
    """
    ok, msg = check_rate_limit(f"geo:token:{actor['role']}:{actor['id']}", limit=20, window_seconds=60)
    if not ok:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=msg)

    token = settings.client_mapbox_token()
    if not token:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Mapbox public token is not configured on the server (need a pk. token)",
        )
    return {"access_token": token, "style_url": "mapbox://styles/mapbox/streets-v12"}


@router.get("/directions")
async def get_directions(
    from_lat: float = Query(..., ge=-90, le=90),
    from_lng: float = Query(..., ge=-180, le=180),
    to_lat: float = Query(..., ge=-90, le=90),
    to_lng: float = Query(..., ge=-180, le=180),
    profile: Optional[str] = Query(None, description="driving-traffic | driving"),
    actor: dict = Depends(get_current_mobile_actor),
):
    """Road route for live maps (searching / navigation). Uses server Mapbox token."""
    ok, msg = check_rate_limit(f"geo:directions:{actor['role']}:{actor['id']}", limit=60, window_seconds=60)
    if not ok:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=msg)

    route = get_driving_route(from_lat, from_lng, to_lat, to_lng, profile=profile)
    return {
        "coordinates": route.coordinates,
        "distance_m": round(route.distance_km * 1000.0, 1),
        "duration_s": route.duration_seconds,
        "source": route.source,
    }
