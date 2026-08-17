from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from uuid import UUID
from typing import Optional
import secrets
import json

from app.core.dependencies import get_db, get_current_user
from app.models.user import User
from app.models.ride_enhanced import RideEnhanced
from app.models.rating import RideRating, SafetyEvent
from app.services.realtime import hub

router = APIRouter()


class RatingCreate(BaseModel):
    rating: int = Field(..., ge=1, le=5)
    comment: Optional[str] = Field(None, max_length=500)


class SOSRequest(BaseModel):
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    note: Optional[str] = None


class TripShareResponse(BaseModel):
    share_token: str
    share_path: str
    ride_id: str


@router.post("/rides/{ride_id}/rating")
async def submit_rating(
    ride_id: UUID,
    body: RatingCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ride = db.query(RideEnhanced).filter(
        RideEnhanced.id == ride_id,
        RideEnhanced.user_id == current_user.id,
    ).first()
    if not ride:
        raise HTTPException(status_code=404, detail="Ride not found")
    if ride.status != "completed":
        raise HTTPException(status_code=400, detail="Only completed rides can be rated")

    existing = db.query(RideRating).filter(RideRating.ride_id == ride_id).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This ride has already been rated",
        )

    row = RideRating(
        ride_id=ride_id,
        user_id=current_user.id,
        driver_id=ride.driver_id,
        rating=body.rating,
        comment=body.comment,
    )
    db.add(row)
    db.commit()
    return {"message": "Rating submitted", "rating": body.rating}


@router.post("/rides/{ride_id}/sos")
async def trigger_sos(
    ride_id: UUID,
    body: SOSRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ride = db.query(RideEnhanced).filter(
        RideEnhanced.id == ride_id,
        RideEnhanced.user_id == current_user.id,
        RideEnhanced.status.in_(["accepted", "started"]),
    ).first()
    if not ride:
        raise HTTPException(status_code=404, detail="No active ride for SOS")

    event = SafetyEvent(
        ride_id=ride_id,
        user_id=current_user.id,
        event_type="sos",
        latitude=body.latitude,
        longitude=body.longitude,
        meta=json.dumps({
            "note": body.note,
            "emergency_contact_name": current_user.emergency_contact_name,
            "emergency_contact_phone": current_user.emergency_contact_phone,
            "driver_id": str(ride.driver_id) if ride.driver_id else None,
        }),
    )
    db.add(event)
    db.commit()
    db.refresh(event)

    payload = {
        "ride_id": str(ride_id),
        "event_id": str(event.id),
        "user_id": str(current_user.id),
        "latitude": body.latitude,
        "longitude": body.longitude,
        "type": "sos",
    }
    await hub.publish_ride(str(ride_id), "safety_sos", payload)
    await hub.publish_user(str(current_user.id), "safety_sos", payload)
    if ride.driver_id:
        await hub.publish_driver(str(ride.driver_id), "safety_sos", payload)

    return {
        "message": "SOS recorded. Contacting emergency services and your emergency contact.",
        "event_id": str(event.id),
        "emergency_dial": "112",
        "emergency_contact_phone": current_user.emergency_contact_phone,
    }


@router.post("/rides/{ride_id}/trip-share", response_model=TripShareResponse)
async def create_trip_share(
    ride_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ride = db.query(RideEnhanced).filter(
        RideEnhanced.id == ride_id,
        RideEnhanced.user_id == current_user.id,
        RideEnhanced.status.in_(["accepted", "started"]),
    ).first()
    if not ride:
        raise HTTPException(status_code=404, detail="No active ride to share")

    token = secrets.token_urlsafe(16)
    event = SafetyEvent(
        ride_id=ride_id,
        user_id=current_user.id,
        event_type="trip_share",
        share_token=token,
    )
    db.add(event)
    db.commit()

    return TripShareResponse(
        share_token=token,
        share_path=f"/share/{token}",
        ride_id=str(ride_id),
    )


@router.get("/share/{token}")
async def public_trip_share(token: str, db: Session = Depends(get_db)):
    event = db.query(SafetyEvent).filter(
        SafetyEvent.share_token == token,
        SafetyEvent.event_type == "trip_share",
    ).order_by(SafetyEvent.created_at.desc()).first()
    if not event:
        raise HTTPException(status_code=404, detail="Share link not found")

    ride = db.query(RideEnhanced).filter(RideEnhanced.id == event.ride_id).first()
    if not ride or ride.status not in ("accepted", "started"):
        raise HTTPException(status_code=410, detail="Trip is no longer active")

    from app.services.realtime import hub as rt
    loc = rt.get_last_location(str(ride.id)) or {}

    return {
        "ride_id": str(ride.id),
        "status": ride.status,
        "pickup_location": ride.pickup_location,
        "dropoff_location": ride.dropoff_location,
        "driver_lat": loc.get("latitude"),
        "driver_lng": loc.get("longitude"),
        "updated_at": loc.get("recorded_at"),
    }
