from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy.sql import func
from typing import List, Optional
from uuid import UUID
from datetime import datetime
import math
from app.core.dependencies import get_db, get_current_driver
from app.core.config import settings
from app.schemas.ride_enhanced import RideEnhancedResponse, VerifyOTPRequest
from app.models.ride_enhanced import RideEnhanced
from app.models.driver import Driver
from app.models.user import User
from app.models.ride_cancellation import RideCancellation
from app.services.realtime import hub
from app.services.driver_stats import get_driver_public_stats

router = APIRouter()


def redact_otp_for_driver(ride_dict: dict) -> dict:
    """Drivers must never receive the ride OTP — customer provides it verbally."""
    ride_dict = dict(ride_dict)
    ride_dict["ride_otp"] = None
    return ride_dict


def enrich_ride_response(ride: RideEnhanced, db: Session, current_driver: Driver = None) -> dict:
    """Add driver and customer details to ride response"""
    ride_dict = {c.name: getattr(ride, c.name) for c in ride.__table__.columns}
    ride_dict['driver_name'] = None
    ride_dict['driver_phone'] = None
    ride_dict['driver_vehicle_number'] = None
    ride_dict['driver_vehicle_type'] = None
    ride_dict['driver_vehicle_image'] = None
    ride_dict['driver_total_rides'] = 0
    ride_dict['driver_average_rating'] = None
    ride_dict['driver_rating_count'] = 0
    ride_dict['customer_name'] = None
    ride_dict['customer_phone'] = None

    if ride.driver_id:
        driver = current_driver if (current_driver and current_driver.id == ride.driver_id) else db.query(Driver).filter(Driver.id == ride.driver_id).first()
        if driver:
            ride_dict['driver_name'] = driver.name
            ride_dict['driver_phone'] = driver.phone
            ride_dict['driver_vehicle_number'] = driver.vehicle_number
            ride_dict['driver_vehicle_type'] = driver.vehicle_type
            ride_dict['driver_vehicle_image'] = driver.vehicle_image
            ride_dict.update(get_driver_public_stats(db, driver.id))

    if ride.user_id:
        customer = db.query(User).filter(User.id == ride.user_id).first()
        if customer:
            ride_dict['customer_name'] = customer.name
            ride_dict['customer_phone'] = customer.phone

    return redact_otp_for_driver(ride_dict)


async def _emit_ride(ride: RideEnhanced, event: str, extra: Optional[dict] = None):
    data = {
        "ride_id": str(ride.id),
        "status": ride.status,
        "user_id": str(ride.user_id),
        "driver_id": str(ride.driver_id) if ride.driver_id else None,
    }
    if extra:
        data.update(extra)
    await hub.publish_ride(str(ride.id), event, data)
    await hub.publish_user(str(ride.user_id), event, data)
    if ride.driver_id:
        await hub.publish_driver(str(ride.driver_id), event, data)


class LocationUpdate(BaseModel):
    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)
    accuracy: Optional[float] = None
    heading: Optional[float] = None
    speed: Optional[float] = None
    recorded_at: Optional[datetime] = None
    sequence: Optional[int] = None
    ride_id: Optional[UUID] = None


class CancelRideRequest(BaseModel):
    reason: str
    custom_reason: Optional[str] = None


def calculate_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate distance between two points in kilometers using Haversine formula"""
    R = 6371  # Earth's radius in kilometers

    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    delta_lat = math.radians(lat2 - lat1)
    delta_lon = math.radians(lon2 - lon1)

    a = math.sin(delta_lat / 2) ** 2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(delta_lon / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    distance = R * c
    return distance


def estimate_eta_minutes(distance_km: float) -> float:
    """Estimate ETA in minutes based on distance. Assumes average city speed of 30 km/h"""
    AVERAGE_SPEED_KMH = 30
    eta_hours = distance_km / AVERAGE_SPEED_KMH
    return eta_hours * 60


@router.post("/location")
async def update_driver_location(
    location: LocationUpdate,
    current_driver: Driver = Depends(get_current_driver),
    db: Session = Depends(get_db)
):
    """Update driver's current GPS location and broadcast to active ride subscribers."""
    current_driver.current_lat = location.latitude
    current_driver.current_lng = location.longitude
    current_driver.location_updated_at = func.now()
    db.commit()

    # Resolve active ride (explicit ride_id preferred)
    active_ride = None
    if location.ride_id:
        active_ride = db.query(RideEnhanced).filter(
            RideEnhanced.id == location.ride_id,
            RideEnhanced.driver_id == current_driver.id,
            RideEnhanced.status.in_(["accepted", "started"]),
        ).first()
    if not active_ride:
        active_ride = db.query(RideEnhanced).filter(
            RideEnhanced.driver_id == current_driver.id,
            RideEnhanced.status.in_(["accepted", "started"]),
        ).first()

    payload = {
        "driver_id": str(current_driver.id),
        "latitude": location.latitude,
        "longitude": location.longitude,
        "accuracy": location.accuracy,
        "heading": location.heading,
        "speed": location.speed,
        "sequence": location.sequence,
        "recorded_at": (location.recorded_at or datetime.utcnow()).isoformat(),
        "ride_id": str(active_ride.id) if active_ride else None,
        "status": active_ride.status if active_ride else None,
    }

    if active_ride:
        if hub.remember_location(str(active_ride.id), payload):
            await hub.publish_ride(str(active_ride.id), "driver_location", payload)
            await hub.publish_user(str(active_ride.user_id), "driver_location", payload)
    elif current_driver.is_online:
        # Driver just refreshed GPS while idle — try to claim a waiting ride immediately
        # instead of waiting for the background sweep (was up to 10s).
        from app.services.dispatch import (
            try_assign_waiting_ride,
            emit_ride_offer,
            scheduled_ready_for_dispatch,
        )
        waiting_ids = [
            row[0]
            for row in (
                db.query(RideEnhanced.id)
                .filter(
                    RideEnhanced.status == "pending",
                    RideEnhanced.driver_id.is_(None),
                    RideEnhanced.offered_driver_id.is_(None),
                )
                .order_by(RideEnhanced.created_at.asc())
                .limit(5)
                .all()
            )
        ]
        for ride_id in waiting_ids:
            peek = db.query(RideEnhanced).filter(RideEnhanced.id == ride_id).first()
            if peek and not scheduled_ready_for_dispatch(peek):
                continue
            assigned = try_assign_waiting_ride(db, ride_id)
            if assigned:
                ride, offered = assigned
                db.commit()
                db.refresh(ride)
                await emit_ride_offer(ride, offered)
                break

    return {"status": "ok", "sequence": location.sequence}


@router.get("/rides/available")
async def get_available_rides(
    current_driver: Driver = Depends(get_current_driver),
    db: Session = Depends(get_db)
):
    """Exclusive offers only — sequential one-by-one dispatch."""
    from app.core.config import settings
    from app.services.dispatch import (
        driver_docs_ready,
        driver_location_fresh,
        vehicle_matches,
        scheduled_ready_for_dispatch,
        expire_stale_pending_rides,
        offer_remaining_seconds,
        driver_offer_remaining_seconds,
        offer_is_for_driver,
    )
    from app.services.routing import estimate_pickup_eta_minutes, haversine_km

    expire_stale_pending_rides(db)

    ok, reason = driver_docs_ready(current_driver)
    if not ok:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=reason)

    if not current_driver.is_online:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Driver must be online to see available rides"
        )

    gps_fresh = driver_location_fresh(current_driver)
    # Exclusive offers must still be visible even if GPS is briefly stale.
    # Non-sequential mode still requires fresh GPS to browse open rides.
    if not settings.SEQUENTIAL_DISPATCH and not gps_fresh:
        return []

    if settings.SEQUENTIAL_DISPATCH:
        query = db.query(RideEnhanced).filter(
            RideEnhanced.status == "pending",
            RideEnhanced.driver_id.is_(None),
            RideEnhanced.offered_driver_id == current_driver.id,
        )
    else:
        cancelled_ride_ids = db.query(RideCancellation.ride_id).filter(
            RideCancellation.canceller_id == current_driver.id
        ).all()
        excluded_ids = [r[0] for r in cancelled_ride_ids]
        query = db.query(RideEnhanced).filter(
            RideEnhanced.status == "pending",
            RideEnhanced.driver_id.is_(None),
        )
        if excluded_ids:
            query = query.filter(RideEnhanced.id.notin_(excluded_ids))

    all_pending_rides = query.all()

    nearby_rides = []
    MAX_ETA_MINUTES = settings.MAX_PICKUP_ETA_MINUTES

    for ride in all_pending_rides:
        if not scheduled_ready_for_dispatch(ride):
            continue
        if settings.SEQUENTIAL_DISPATCH and not offer_is_for_driver(ride, current_driver.id):
            continue
        if settings.SEQUENTIAL_DISPATCH and driver_offer_remaining_seconds(ride) <= 0:
            continue
        if not vehicle_matches(current_driver, ride.vehicle_category):
            continue

        exclusive = settings.SEQUENTIAL_DISPATCH and offer_is_for_driver(ride, current_driver.id)

        # Prefer live driver coords; fall back to ride trip distance for exclusive offers
        # so a brief GPS glitch does not hide the Accept card.
        distance_to_pickup = None
        eta_to_pickup = None
        if (
            current_driver.current_lat is not None
            and current_driver.current_lng is not None
            and ride.pickup_lat is not None
            and ride.pickup_lng is not None
        ):
            distance_to_pickup = haversine_km(
                current_driver.current_lat,
                current_driver.current_lng,
                ride.pickup_lat,
                ride.pickup_lng
            )
            eta_to_pickup = estimate_pickup_eta_minutes(distance_to_pickup)

        if not exclusive:
            if distance_to_pickup is None or eta_to_pickup is None:
                continue
            if eta_to_pickup > MAX_ETA_MINUTES:
                continue
        else:
            if distance_to_pickup is None:
                distance_to_pickup = float(ride.distance_km or 0)
            if eta_to_pickup is None:
                eta_to_pickup = float(ride.eta_minutes or 0)

        offer_remaining = (
            driver_offer_remaining_seconds(ride)
            if settings.SEQUENTIAL_DISPATCH
            else offer_remaining_seconds(ride)
        )

        ride_dict = {
            "id": str(ride.id),
            "user_id": str(ride.user_id),
            "driver_id": str(ride.driver_id) if ride.driver_id else None,
            "trip_type": ride.trip_type,
            "vehicle_category": ride.vehicle_category,
            "pickup_location": ride.pickup_location,
            "dropoff_location": ride.dropoff_location,
            "pickup_lat": ride.pickup_lat,
            "pickup_lng": ride.pickup_lng,
            "dropoff_lat": ride.dropoff_lat,
            "dropoff_lng": ride.dropoff_lng,
            "stops": ride.stops or [],
            "is_scheduled": ride.is_scheduled,
            "scheduled_datetime": ride.scheduled_datetime,
            "booking_for_self": ride.booking_for_self,
            "passenger_name": ride.passenger_name,
            "passenger_phone": ride.passenger_phone,
            "passenger_notes": ride.passenger_notes,
            "preferences": ride.preferences or {},
            "driver_notes": ride.driver_notes,
            "ride_otp": None,
            "otp_verified": ride.otp_verified,
            "status": ride.status,
            "rejection_count": ride.rejection_count,
            "cancellation_reason": ride.cancellation_reason,
            "base_fare": ride.base_fare,
            "distance_fare": ride.distance_fare,
            "platform_fee": ride.platform_fee,
            "gst": ride.gst,
            "toll_charges": ride.toll_charges,
            "night_charges": ride.night_charges,
            "waiting_charges": ride.waiting_charges,
            "fare": ride.fare,
            "payment_status": ride.payment_status,
            "payment_method": ride.payment_method,
            "transaction_id": ride.transaction_id,
            "distance_km": round(distance_to_pickup, 2),
            "eta_minutes": round(eta_to_pickup),
            "trip_distance_km": ride.distance_km,
            "route_source": getattr(ride, "route_source", None),
            "offer_ttl_seconds": settings.DRIVER_OFFER_SECONDS if settings.SEQUENTIAL_DISPATCH else settings.OFFER_TTL_SECONDS,
            "offer_remaining_seconds": offer_remaining,
            "search_remaining_seconds": offer_remaining_seconds(ride),
            "driver_name": None,
            "driver_phone": None,
            "driver_vehicle_number": None,
            "driver_vehicle_type": None,
            "created_at": ride.created_at,
            "updated_at": ride.updated_at,
        }
        nearby_rides.append(ride_dict)

    nearby_rides.sort(key=lambda r: r["distance_km"])
    return nearby_rides[:10]


@router.post("/rides/{ride_id}/accept", response_model=RideEnhancedResponse)
async def accept_ride(
    ride_id: UUID,
    current_driver: Driver = Depends(get_current_driver),
    db: Session = Depends(get_db)
):
    """Accept exclusive offer — FOR UPDATE prevents double accept."""
    from app.core.config import settings
    from app.services.dispatch import (
        driver_docs_ready,
        driver_location_fresh,
        vehicle_matches,
        scheduled_ready_for_dispatch,
        offer_remaining_seconds,
        driver_offer_remaining_seconds,
        offer_is_for_driver,
        driver_has_active_ride,
        declined_driver_ids,
    )

    ok, reason = driver_docs_ready(current_driver)
    if not ok:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=reason)

    if not current_driver.is_online:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Driver must be online to accept rides"
        )

    # Idempotent: already accepted by this driver
    already = (
        db.query(RideEnhanced)
        .filter(
            RideEnhanced.id == ride_id,
            RideEnhanced.driver_id == current_driver.id,
            RideEnhanced.status.in_(["accepted", "started"]),
        )
        .first()
    )
    if already:
        return enrich_ride_response(already, db, current_driver)

    has_coords = current_driver.current_lat is not None and current_driver.current_lng is not None
    # Exclusive offers stay visible with briefly stale GPS — allow accept the same way
    # so the 40s window is not burned on a GPS freshness check after the card is shown.
    if settings.SEQUENTIAL_DISPATCH:
        if not has_coords:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Location required. Enable GPS before accepting.",
            )
    elif not driver_location_fresh(current_driver):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Location is stale. Enable GPS and update location before accepting.",
        )

    if driver_has_active_ride(db, current_driver.id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Complete your current ride before accepting another",
        )

    if current_driver.id in declined_driver_ids(db, ride_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You already declined this ride",
        )

    # SELECT FOR UPDATE - locks the row to prevent race condition
    ride = db.query(RideEnhanced).filter(
        RideEnhanced.id == ride_id,
        RideEnhanced.status == "pending",
        RideEnhanced.driver_id.is_(None)
    ).with_for_update().first()

    if not ride:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ride already accepted by another driver"
        )

    if settings.SEQUENTIAL_DISPATCH and not offer_is_for_driver(ride, current_driver.id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This offer is not assigned to you",
        )

    if settings.SEQUENTIAL_DISPATCH and driver_offer_remaining_seconds(ride) <= 0:
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="Offer window expired")

    if offer_remaining_seconds(ride) <= 0:
        ride.status = "cancelled"
        ride.cancellation_reason = "Offer expired before accept"
        ride.offered_driver_id = None
        ride.offer_started_at = None
        db.commit()
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="Ride offer expired")

    if not scheduled_ready_for_dispatch(ride):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Scheduled ride is not open for dispatch yet",
        )

    if not vehicle_matches(current_driver, ride.vehicle_category):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Vehicle type does not match ride category ({ride.vehicle_category})",
        )

    prefs = ride.preferences or {}
    if prefs.get("women_driver") and (getattr(current_driver, "gender", None) or "").lower() != "female":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This ride prefers a women captain",
        )

    ride.driver_id = current_driver.id
    ride.status = "accepted"
    ride.offered_driver_id = None
    ride.offer_started_at = None
    db.commit()
    db.refresh(ride)

    await _emit_ride(ride, "ride_accepted")
    # Tell other drivers immediately so UI drops any stale offer
    await hub.publish(hub.drivers_online_channel(), "ride_taken", {
        "ride_id": str(ride.id),
        "driver_id": str(current_driver.id),
        "status": "accepted",
    })
    return enrich_ride_response(ride, db, current_driver)


@router.post("/rides/{ride_id}/verify-otp", response_model=RideEnhancedResponse)
async def verify_ride_otp(
    ride_id: UUID,
    otp_request: VerifyOTPRequest,
    current_driver: Driver = Depends(get_current_driver),
    db: Session = Depends(get_db)
):
    """Verify OTP before starting ride"""
    ride = db.query(RideEnhanced).filter(
        RideEnhanced.id == ride_id,
        RideEnhanced.driver_id == current_driver.id,
        RideEnhanced.status == "accepted"
    ).first()

    if not ride:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ride not found or not assigned to you"
        )

    if ride.otp_verified:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="OTP already verified"
        )

    if ride.ride_otp != otp_request.otp:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid OTP"
        )

    ride.otp_verified = True
    db.commit()
    db.refresh(ride)

    await _emit_ride(ride, "otp_verified")
    return enrich_ride_response(ride, db, current_driver)


@router.post("/rides/{ride_id}/start", response_model=RideEnhancedResponse)
async def start_ride(
    ride_id: UUID,
    current_driver: Driver = Depends(get_current_driver),
    db: Session = Depends(get_db)
):
    """Start a ride (requires OTP verification)"""
    ride = db.query(RideEnhanced).filter(
        RideEnhanced.id == ride_id,
        RideEnhanced.driver_id == current_driver.id
    ).first()

    if not ride:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ride not found"
        )

    # Idempotent: already in progress — return current ride (avoids double-tap 400s)
    if ride.status == "started":
        return enrich_ride_response(ride, db, current_driver)

    if ride.status != "accepted":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot start ride with status: {ride.status}"
        )

    if not ride.otp_verified:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Please verify OTP before starting the ride"
        )

    ride.status = "started"
    db.commit()
    db.refresh(ride)

    await _emit_ride(ride, "ride_started")
    return enrich_ride_response(ride, db, current_driver)


@router.post("/rides/{ride_id}/complete", response_model=RideEnhancedResponse)
async def complete_ride(
    ride_id: UUID,
    force: bool = False,
    latitude: Optional[float] = None,
    longitude: Optional[float] = None,
    current_driver: Driver = Depends(get_current_driver),
    db: Session = Depends(get_db)
):
    """Complete a ride — driver must be near drop-off unless force is allowed."""
    ride = db.query(RideEnhanced).filter(
        RideEnhanced.id == ride_id,
        RideEnhanced.driver_id == current_driver.id
    ).first()

    if not ride:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ride not found"
        )

    # Idempotent: already completed
    if ride.status == "completed":
        return enrich_ride_response(ride, db, current_driver)

    if ride.status != "started":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Can only complete rides that are started"
        )

    force_allowed = bool(settings.ALLOW_FORCE_COMPLETE)
    if force and not force_allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Force complete is disabled. Reach the drop-off to complete the ride.",
        )

    # Prefer freshly reported phone GPS; fall back to last stored driver location
    check_lat = latitude if latitude is not None else current_driver.current_lat
    check_lng = longitude if longitude is not None else current_driver.current_lng
    if latitude is not None and longitude is not None:
        current_driver.current_lat = latitude
        current_driver.current_lng = longitude
        db.add(current_driver)

    radius_km = float(settings.COMPLETE_DROP_OFF_RADIUS_KM or 1.5)

    if not force:
        if check_lat is None or check_lng is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Current location required to complete ride. Enable GPS and try again.",
            )
        if ride.dropoff_lat and ride.dropoff_lng:
            distance_to_dropoff = calculate_distance(
                check_lat,
                check_lng,
                ride.dropoff_lat,
                ride.dropoff_lng
            )
            if distance_to_dropoff > radius_km:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        f"You are {distance_to_dropoff:.1f} km away from drop-off. "
                        f"Please reach within {radius_km:.1f} km to complete the ride."
                    ),
                )

    ride.status = "completed"
    ride.payment_status = "pending"
    db.commit()
    db.refresh(ride)

    await _emit_ride(ride, "ride_completed")
    return enrich_ride_response(ride, db, current_driver)


@router.post("/rides/{ride_id}/cancel")
async def cancel_ride(
    ride_id: UUID,
    cancel_request: CancelRideRequest,
    current_driver: Driver = Depends(get_current_driver),
    db: Session = Depends(get_db)
):
    """
    Driver cancel:
    - accepted + OTP not verified → reassign to next driver (no overlap kill)
    - started / OTP verified → permanently cancel
    """
    from app.services.dispatch import (
        begin_dispatch,
        assign_next_offer,
        emit_ride_offer,
        record_driver_pass,
    )

    ride = db.query(RideEnhanced).filter(
        RideEnhanced.id == ride_id,
        RideEnhanced.driver_id == current_driver.id,
        RideEnhanced.status.in_(["accepted", "started"])
    ).with_for_update().first()

    if not ride:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ride not found or not assigned to you"
        )

    # Soft cancel → next driver (before trip actually starts)
    if ride.status == "accepted" and not ride.otp_verified:
        record_driver_pass(db, ride, current_driver.id, cancel_request.reason or "driver_cancelled")
        ride.driver_id = None
        ride.status = "pending"
        ride.otp_verified = False
        begin_dispatch(ride)
        next_driver = assign_next_offer(db, ride)
        db.commit()
        db.refresh(ride)

        await _emit_ride(ride, "ride_reassigned", {
            "rejection_count": ride.rejection_count,
            "reason": cancel_request.reason,
        })
        if next_driver:
            await emit_ride_offer(ride, next_driver)
        return {
            "message": "Ride returned to dispatch for next driver",
            "reason": cancel_request.reason,
            "reassigned": True,
        }

    # Hard cancel after trip started
    try:
        cancellation = RideCancellation(
            ride_id=ride_id,
            cancelled_by="driver",
            canceller_id=current_driver.id,
            reason=cancel_request.reason,
            custom_reason=cancel_request.custom_reason
        )
        db.add(cancellation)
    except Exception as e:
        print(f"Warning: Could not create cancellation record: {e}")

    previous_driver_id = ride.driver_id
    ride.status = "cancelled"
    ride.driver_id = None
    ride.offered_driver_id = None
    ride.offer_started_at = None
    ride.cancellation_reason = f"{cancel_request.reason}: {cancel_request.custom_reason or ''}"

    db.commit()

    data = {
        "ride_id": str(ride.id),
        "status": "cancelled",
        "user_id": str(ride.user_id),
        "driver_id": str(previous_driver_id) if previous_driver_id else None,
        "reason": cancel_request.reason,
    }
    await hub.publish_ride(str(ride.id), "ride_cancelled", data)
    await hub.publish_user(str(ride.user_id), "ride_cancelled", data)
    if previous_driver_id:
        await hub.publish_driver(str(previous_driver_id), "ride_cancelled", data)

    return {
        "message": "Ride cancelled successfully",
        "reason": cancel_request.reason,
        "reassigned": False,
    }


@router.get("/rides/active")
async def get_active_ride(
    current_driver: Driver = Depends(get_current_driver),
    db: Session = Depends(get_db)
):
    """Get driver's active ride with customer info"""
    active_ride = db.query(RideEnhanced).filter(
        RideEnhanced.driver_id == current_driver.id,
        RideEnhanced.status.in_(["accepted", "started"])
    ).first()

    if not active_ride:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active ride found"
        )

    return enrich_ride_response(active_ride, db, current_driver)


@router.get("/rides/history", response_model=List[RideEnhancedResponse])
async def get_driver_ride_history(
    current_driver: Driver = Depends(get_current_driver),
    db: Session = Depends(get_db)
):
    """Get driver's ride history (completed + cancelled) with full ride details"""
    rides = db.query(RideEnhanced).filter(
        RideEnhanced.driver_id == current_driver.id,
        RideEnhanced.status.in_(["completed", "cancelled"]),
    ).order_by(RideEnhanced.created_at.desc()).limit(100).all()

    return [enrich_ride_response(ride, db, current_driver) for ride in rides]


@router.get("/rides/{ride_id}", response_model=RideEnhancedResponse)
async def get_driver_ride_details(
    ride_id: UUID,
    current_driver: Driver = Depends(get_current_driver),
    db: Session = Depends(get_db),
):
    """Get a ride assigned to this driver, or a pending exclusive offer for them."""
    ride = db.query(RideEnhanced).filter(RideEnhanced.id == ride_id).first()

    if not ride:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ride not found",
        )

    is_assignee = ride.driver_id == current_driver.id
    is_offer = (
        ride.status == "pending"
        and ride.driver_id is None
        and ride.offered_driver_id == current_driver.id
    )
    if not is_assignee and not is_offer:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ride not found",
        )

    return enrich_ride_response(ride, db, current_driver)


@router.get("/earnings")
async def get_driver_earnings(
    current_driver: Driver = Depends(get_current_driver),
    db: Session = Depends(get_db)
):
    """Get driver's earnings breakdown - today, weekly, monthly, total"""
    from datetime import datetime, timedelta

    now = datetime.utcnow()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = today_start - timedelta(days=now.weekday())
    month_start = today_start.replace(day=1)

    all_completed = db.query(RideEnhanced).filter(
        RideEnhanced.driver_id == current_driver.id,
        RideEnhanced.status == "completed"
    ).all()

    today_rides = [r for r in all_completed if r.created_at and r.created_at.replace(tzinfo=None) >= today_start]
    week_rides = [r for r in all_completed if r.created_at and r.created_at.replace(tzinfo=None) >= week_start]
    month_rides = [r for r in all_completed if r.created_at and r.created_at.replace(tzinfo=None) >= month_start]

    total_earnings = sum(r.fare for r in all_completed)
    today_earnings = sum(r.fare for r in today_rides)
    week_earnings = sum(r.fare for r in week_rides)
    month_earnings = sum(r.fare for r in month_rides)

    return {
        "today": {
            "earnings": round(today_earnings, 2),
            "rides": len(today_rides),
        },
        "week": {
            "earnings": round(week_earnings, 2),
            "rides": len(week_rides),
        },
        "month": {
            "earnings": round(month_earnings, 2),
            "rides": len(month_rides),
        },
        "total": {
            "earnings": round(total_earnings, 2),
            "rides": len(all_completed),
            "average_fare": round(total_earnings / len(all_completed), 2) if all_completed else 0,
        },
    }


@router.post("/rides/{ride_id}/reject")
async def reject_ride(
    ride_id: UUID,
    current_driver: Driver = Depends(get_current_driver),
    db: Session = Depends(get_db)
):
    """Reject after accept → reassign to next driver with fresh search clock."""
    from app.services.dispatch import (
        begin_dispatch,
        assign_next_offer,
        emit_ride_offer,
        record_driver_pass,
    )

    ride = db.query(RideEnhanced).filter(RideEnhanced.id == ride_id).with_for_update().first()

    if not ride:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ride not found"
        )

    if ride.driver_id != current_driver.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This ride is not assigned to you"
        )

    if ride.status not in ["pending", "accepted"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot reject ride that has already started or completed"
        )

    if ride.otp_verified:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot reject ride after OTP verification. Ride has started."
        )

    record_driver_pass(db, ride, current_driver.id, "driver_rejected_after_accept")
    ride.driver_id = None
    ride.status = "pending"
    ride.otp_verified = False
    begin_dispatch(ride)
    next_driver = assign_next_offer(db, ride)

    db.commit()
    db.refresh(ride)

    await _emit_ride(ride, "ride_reassigned", {"rejection_count": ride.rejection_count})
    if next_driver:
        await emit_ride_offer(ride, next_driver)

    return {
        "message": "Ride rejected successfully",
        "rejection_count": ride.rejection_count,
        "ride_id": str(ride.id)
    }


@router.put("/status")
async def update_driver_status_v2(
    payload: dict,
    current_driver: Driver = Depends(get_current_driver),
    db: Session = Depends(get_db),
):
    """Go online/offline with docs + location gates."""
    from app.services.dispatch import (
        driver_docs_ready,
        driver_location_fresh,
        release_driver_exclusive_offers,
        emit_advance_events,
    )

    want_online = bool(payload.get("is_online"))
    if want_online:
        ok, reason = driver_docs_ready(current_driver)
        if not ok:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=reason)
        if not driver_location_fresh(current_driver):
            if current_driver.current_lat is None or current_driver.current_lng is None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Share your GPS location before going online",
                )

    was_online = bool(current_driver.is_online)
    current_driver.is_online = want_online
    db.commit()
    db.refresh(current_driver)

    # Going offline mid-offer: release exclusive window immediately and reassign
    if was_online and not want_online:
        events = await release_driver_exclusive_offers(db, current_driver.id)
        await emit_advance_events(events)

    return {
        "id": str(current_driver.id),
        "is_online": current_driver.is_online,
        "is_verified": current_driver.is_verified,
        "vehicle_type": current_driver.vehicle_type,
    }


@router.post("/rides/{ride_id}/decline")
async def decline_ride(
    ride_id: UUID,
    current_driver: Driver = Depends(get_current_driver),
    db: Session = Depends(get_db)
):
    """Decline exclusive pending offer → immediately offer next driver."""
    from app.services.dispatch import (
        record_driver_pass,
        assign_next_offer,
        emit_ride_offer,
        offer_is_for_driver,
    )
    from app.core.config import settings

    ride = db.query(RideEnhanced).filter(
        RideEnhanced.id == ride_id,
        RideEnhanced.status == "pending",
    ).with_for_update().first()
    if not ride:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pending ride not found")

    if settings.SEQUENTIAL_DISPATCH and not offer_is_for_driver(ride, current_driver.id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This offer is not assigned to you",
        )

    record_driver_pass(db, ride, current_driver.id, "driver_declined")
    ride.offered_driver_id = None
    ride.offer_started_at = None
    next_driver = assign_next_offer(db, ride)
    db.commit()
    db.refresh(ride)

    await hub.publish_driver(str(current_driver.id), "offer_expired", {
        "ride_id": str(ride_id),
    })
    if next_driver:
        await emit_ride_offer(ride, next_driver)

    return {"message": "Ride declined", "next_offered": bool(next_driver)}
