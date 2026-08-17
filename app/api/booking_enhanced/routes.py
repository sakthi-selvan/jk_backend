from typing import List, Optional
from uuid import UUID
from datetime import datetime, time
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session
from app.core.dependencies import get_db, get_current_user, get_current_driver
from app.schemas.ride_enhanced import (
    BookingCreate, RideEnhancedResponse, VerifyOTPRequest,
    VehicleCategoryResponse, FareBreakdown
)
from app.models.ride_enhanced import RideEnhanced, generate_ride_otp
from app.models.vehicle_category import VehicleCategoryConfig
from app.models.user import User
from app.models.driver import Driver
from app.services.realtime import hub
from app.services.driver_stats import get_driver_public_stats
from app.core.config import settings

router = APIRouter()


async def _emit_ride(ride: RideEnhanced, event: str, extra=None):
    data = {
        "ride_id": str(ride.id),
        "status": ride.status,
        "user_id": str(ride.user_id),
        "driver_id": str(ride.driver_id) if ride.driver_id else None,
        "updated_at": ride.updated_at.isoformat() if ride.updated_at else None,
    }
    if extra:
        data.update(extra)
    await hub.publish_ride(str(ride.id), event, data)
    await hub.publish_user(str(ride.user_id), event, data)
    if ride.driver_id:
        await hub.publish_driver(str(ride.driver_id), event, data)
    # Do NOT blast ride_created to all drivers — sequential dispatch uses ride_offer


def calculate_fare(
    distance_km: float,
    vehicle_category: VehicleCategoryConfig,
    is_night: bool = False,
    toll_charges: float = 0.0,
    trip_type: str = "one_way",
    rental_hours: int = 1,
    surge_multiplier: float = 1.0,
    waiting_minutes: float = 0.0,
) -> dict:
    """Calculate detailed fare breakdown from admin-configured category rates."""
    platform_fee = float(getattr(vehicle_category, "platform_fee", None) or 40.0)
    hourly_rate = float(getattr(vehicle_category, "hourly_rate", None) or 280.0)
    night_pct = float(getattr(vehicle_category, "night_surcharge_percent", None) or 15.0) / 100.0
    gst_pct = float(getattr(vehicle_category, "gst_percent", None) or 5.0) / 100.0
    waiting_per_min = float(getattr(vehicle_category, "waiting_charge_per_min", None) or 0.0)
    surge_multiplier = max(1.0, float(surge_multiplier or 1.0))

    if trip_type == "rental":
        hours = max(1, int(rental_hours or 1))
        # Market package (Uber/Ola style): ₹/hr · includes ~10 km per hour.
        # hourly_rate is the GST-inclusive package price customers see.
        package_total = hourly_rate * hours
        gst_pct_safe = max(0.0, gst_pct)
        if gst_pct_safe > 0:
            subtotal_pkg = package_total / (1.0 + gst_pct_safe)
            gst = package_total - subtotal_pkg
        else:
            subtotal_pkg = package_total
            gst = 0.0
        return {
            "base_fare": round(subtotal_pkg, 2),
            "distance_fare": 0.0,
            "platform_fee": 0.0,
            "gst": round(gst, 2),
            "toll_charges": round(float(toll_charges or 0.0), 2),
            "night_charges": 0.0,
            "waiting_charges": 0.0,
            "total": round(package_total + float(toll_charges or 0.0), 2),
            "surge_multiplier": 1.0,
            "rental_hours": hours,
            "included_km": float(10 * hours),
        }
    else:
        # Always compute one-way first; round_trip doubles the full fare below
        base_fare = vehicle_category.base_fare
        distance_fare = distance_km * vehicle_category.per_km_rate

    # Apply surge to distance+base (not platform fee)
    base_fare = base_fare * surge_multiplier
    distance_fare = distance_fare * surge_multiplier

    night_charges = (base_fare + distance_fare) * night_pct if is_night else 0.0
    waiting_charges = max(0.0, float(waiting_minutes or 0.0)) * waiting_per_min

    subtotal = (
        base_fare
        + distance_fare
        + platform_fee
        + toll_charges
        + night_charges
        + waiting_charges
    )
    gst = subtotal * gst_pct

    total = subtotal + gst

    # Round trip = exact 2× one-way fare (outbound + return)
    if trip_type == "round_trip":
        base_fare *= 2.0
        distance_fare *= 2.0
        platform_fee *= 2.0
        toll_charges = float(toll_charges or 0.0) * 2.0
        night_charges *= 2.0
        waiting_charges *= 2.0
        gst *= 2.0
        total *= 2.0

    return {
        "base_fare": round(base_fare, 2),
        "distance_fare": round(distance_fare, 2),
        "platform_fee": round(platform_fee, 2),
        "gst": round(gst, 2),
        "toll_charges": round(toll_charges, 2),
        "night_charges": round(night_charges, 2),
        "waiting_charges": round(waiting_charges, 2),
        "total": round(total, 2),
        "surge_multiplier": surge_multiplier,
    }


def current_surge_multiplier(now=None) -> float:
    """Simple peak-hour surge (P5 starter). Replace with supply/demand later."""
    now = now or datetime.now()
    hour = now.hour
    if 8 <= hour < 11 or 17 <= hour < 21:
        return float(getattr(settings, "SURGE_PEAK_MULTIPLIER", 1.2))
    return 1.0


def cancellation_fee_for_status(status_value: str) -> float:
    if status_value == "pending":
        return 0.0
    if status_value == "accepted":
        return float(getattr(settings, "CANCEL_FEE_ACCEPTED", 30.0))
    if status_value == "started":
        return float(getattr(settings, "CANCEL_FEE_STARTED", 50.0))
    return 0.0


@router.get("/vehicle-categories", response_model=List[VehicleCategoryResponse])
async def get_vehicle_categories(db: Session = Depends(get_db)):
    """Get all active vehicle categories (premium removed from product)."""
    categories = db.query(VehicleCategoryConfig).filter(
        VehicleCategoryConfig.is_active == True,
        VehicleCategoryConfig.name != "premium",
    ).order_by(VehicleCategoryConfig.display_order).all()

    return categories


@router.post("/calculate-fare", response_model=FareBreakdown)
async def calculate_fare_estimate(
    pickup_lat: float,
    pickup_lng: float,
    dropoff_lat: float,
    dropoff_lng: float,
    vehicle_category: str,
    trip_type: str = "one_way",
    rental_hours: int = 1,
    scheduled_datetime: datetime = None,
    db: Session = Depends(get_db)
):
    """Calculate fare estimate using road-network distance when Mapbox is configured."""
    from app.services.geo import assert_service_area
    from app.services.routing import get_driving_route

    for label, lat, lng in (
        ("Pickup", pickup_lat, pickup_lng),
        ("Dropoff", dropoff_lat, dropoff_lng),
    ):
        err = assert_service_area(lat, lng, label)
        if err:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=err)

    if (vehicle_category or "").strip().lower() == "premium":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Premium category is no longer available",
        )

    cat_name = (vehicle_category or "").strip().lower()
    category_config = db.query(VehicleCategoryConfig).filter(
        VehicleCategoryConfig.name == cat_name
    ).first()

    if not category_config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Vehicle category '{cat_name}' not found. Restart API to seed default categories.",
        )

    route = get_driving_route(pickup_lat, pickup_lng, dropoff_lat, dropoff_lng)
    distance_km = route.distance_km

    ride_time = scheduled_datetime or datetime.now()
    is_night = ride_time.hour >= 22 or ride_time.hour < 6
    surge = current_surge_multiplier(ride_time)

    fare_breakdown = calculate_fare(
        distance_km, category_config, is_night, trip_type=trip_type, rental_hours=rental_hours,
        surge_multiplier=surge,
    )
    fare_breakdown["distance_km"] = round(distance_km, 2)
    fare_breakdown["duration_minutes"] = round(route.duration_seconds / 60.0, 1)
    fare_breakdown["route_source"] = route.source
    fare_breakdown["surge_multiplier"] = surge

    return FareBreakdown(**fare_breakdown)


@router.post("/", response_model=RideEnhancedResponse, status_code=status.HTTP_201_CREATED)
@router.post("", response_model=RideEnhancedResponse, status_code=status.HTTP_201_CREATED, include_in_schema=False)
async def create_booking_enhanced(
    booking: BookingCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create a new enhanced ride booking and start sequential one-by-one offers."""
    from app.services.geo import assert_service_area
    from app.services.routing import get_driving_route
    from app.services.dispatch import (
        user_has_active_ride,
        begin_dispatch,
        emit_ride_offer,
        scheduled_ready_for_dispatch,
        try_assign_waiting_ride,
    )

    if user_has_active_ride(db, current_user.id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You already have an active ride. Complete or cancel it before booking again.",
        )

    # Get vehicle category config
    category_config = db.query(VehicleCategoryConfig).filter(
        VehicleCategoryConfig.name == booking.vehicle_category.value
    ).first()

    if not category_config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Vehicle category not found"
        )

    # Bike rental not allowed
    if booking.trip_type.value == "rental" and booking.vehicle_category.value == "bike":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Rental is not available for Bike category"
        )

    pickup_err = assert_service_area(booking.pickup_lat, booking.pickup_lng, "Pickup")
    if pickup_err:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=pickup_err)

    route_geometry = None
    route_duration_seconds = None
    route_source = None
    eta_minutes = 5

    # Calculate distance via road network when dropoff exists
    if booking.dropoff_lat and booking.dropoff_lng:
        drop_err = assert_service_area(booking.dropoff_lat, booking.dropoff_lng, "Dropoff")
        if drop_err:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=drop_err)
        route = get_driving_route(
            booking.pickup_lat, booking.pickup_lng,
            booking.dropoff_lat, booking.dropoff_lng,
        )
        distance_km = route.distance_km
        route_geometry = route.coordinates
        route_duration_seconds = route.duration_seconds
        route_source = route.source
        eta_minutes = max(1, int(round(route.duration_seconds / 60.0)))
    else:
        # For rental, use package included km (10 km / hour — Uber/Ola style)
        hours = max(1, int(getattr(booking, "rental_hours", None) or 1))
        distance_km = 10.0 * hours

    # Check if night time
    ride_time = booking.scheduled_datetime or datetime.now()
    is_night = ride_time.hour >= 22 or ride_time.hour < 6
    surge = current_surge_multiplier(ride_time)

    # Calculate fare breakdown
    fare_breakdown = calculate_fare(
        distance_km, category_config, is_night, trip_type=booking.trip_type.value,
        rental_hours=max(1, int(getattr(booking, "rental_hours", None) or 1)),
        surge_multiplier=surge,
    )

    # Convert stops to dict format
    stops_data = [stop.model_dump() for stop in booking.stops]

    new_ride = RideEnhanced(
        user_id=current_user.id,
        trip_type=booking.trip_type.value,
        vehicle_category=booking.vehicle_category.value,
        pickup_location=booking.pickup_location,
        dropoff_location=booking.dropoff_location,
        pickup_lat=booking.pickup_lat,
        pickup_lng=booking.pickup_lng,
        dropoff_lat=booking.dropoff_lat,
        dropoff_lng=booking.dropoff_lng,
        stops=stops_data,
        is_scheduled=booking.is_scheduled,
        scheduled_datetime=booking.scheduled_datetime,
        booking_for_self=booking.booking_for_self,
        passenger_name=booking.passenger_name,
        passenger_phone=booking.passenger_phone,
        passenger_notes=booking.passenger_notes,
        preferences=booking.preferences.model_dump(),
        driver_notes=booking.driver_notes,
        # Rapido-style: same OTP for every ride of this user
        ride_otp=current_user.ride_otp or generate_ride_otp(),
        payment_method=booking.payment_method,
        distance_km=distance_km,
        eta_minutes=eta_minutes,
        route_geometry=route_geometry,
        route_duration_seconds=route_duration_seconds,
        route_source=route_source,
        surge_multiplier=surge,
        base_fare=fare_breakdown["base_fare"],
        distance_fare=fare_breakdown["distance_fare"],
        platform_fee=fare_breakdown["platform_fee"],
        gst=fare_breakdown["gst"],
        toll_charges=fare_breakdown["toll_charges"],
        night_charges=fare_breakdown["night_charges"],
        waiting_charges=fare_breakdown["waiting_charges"],
        fare=fare_breakdown["total"]
    )

    begin_dispatch(new_ride)
    db.add(new_ride)
    db.commit()
    db.refresh(new_ride)

    # Notify customer that search started (not a blast to all drivers)
    await _emit_ride(new_ride, "ride_created", {
        "vehicle_category": new_ride.vehicle_category,
        "is_scheduled": new_ride.is_scheduled,
        "offer_ttl_seconds": settings.OFFER_TTL_SECONDS,
        "sequential": settings.SEQUENTIAL_DISPATCH,
    })

    # First exclusive offer — only if ready for dispatch now (row-locked)
    if scheduled_ready_for_dispatch(new_ride):
        assigned = try_assign_waiting_ride(db, new_ride.id)
        if assigned:
            ride, offered = assigned
            db.commit()
            db.refresh(ride)
            await emit_ride_offer(ride, offered)
            return enrich_ride_with_driver(ride, db)

    return enrich_ride_with_driver(new_ride, db)


def enrich_ride_with_driver(ride: RideEnhanced, db: Session) -> dict:
    """Add driver details to ride response"""
    ride_dict = {c.name: getattr(ride, c.name) for c in ride.__table__.columns}
    ride_dict['driver_name'] = None
    ride_dict['driver_phone'] = None
    ride_dict['driver_vehicle_number'] = None
    ride_dict['driver_vehicle_type'] = None
    ride_dict['driver_vehicle_image'] = None
    ride_dict['driver_total_rides'] = 0
    ride_dict['driver_average_rating'] = None
    ride_dict['driver_rating_count'] = 0

    if ride.driver_id:
        driver = db.query(Driver).filter(Driver.id == ride.driver_id).first()
        if driver:
            ride_dict['driver_name'] = driver.name
            ride_dict['driver_phone'] = driver.phone
            ride_dict['driver_vehicle_number'] = driver.vehicle_number
            ride_dict['driver_vehicle_type'] = driver.vehicle_type
            ride_dict['driver_vehicle_image'] = driver.vehicle_image
            ride_dict.update(get_driver_public_stats(db, driver.id))

    return ride_dict


RIDE_TIMEOUT_MINUTES = max(1, settings.OFFER_TTL_SECONDS // 60)


@router.get("/active", response_model=RideEnhancedResponse, responses={204: {"description": "No active ride"}})
async def get_active_booking(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get user's active ride. Returns 204 when the user has no active booking (not an error)."""
    from app.services.dispatch import expire_stale_pending_rides

    expire_stale_pending_rides(db)

    active_ride = db.query(RideEnhanced).filter(
        RideEnhanced.user_id == current_user.id,
        RideEnhanced.status.in_(["pending", "accepted", "started"])
    ).order_by(RideEnhanced.created_at.desc()).first()

    if not active_ride:
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    return enrich_ride_with_driver(active_ride, db)


@router.get("/active/tracking")
async def get_active_ride_tracking(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get active ride tracking data with driver's live location"""
    active_ride = db.query(RideEnhanced).filter(
        RideEnhanced.user_id == current_user.id,
        RideEnhanced.status.in_(["pending", "accepted", "started"])
    ).first()

    if not active_ride:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active trackable ride"
        )

    driver_lat = None
    driver_lng = None
    location_updated_at = None
    if active_ride.driver_id:
        driver = db.query(Driver).filter(Driver.id == active_ride.driver_id).first()
        if driver:
            driver_lat = driver.current_lat
            driver_lng = driver.current_lng
            location_updated_at = (
                driver.location_updated_at.isoformat()
                if getattr(driver, "location_updated_at", None)
                else None
            )

    cached = hub.get_last_location(str(active_ride.id)) or {}

    return {
        "ride_id": str(active_ride.id),
        "status": active_ride.status,
        "driver_lat": cached.get("latitude", driver_lat),
        "driver_lng": cached.get("longitude", driver_lng),
        "heading": cached.get("heading"),
        "speed": cached.get("speed"),
        "accuracy": cached.get("accuracy"),
        "sequence": cached.get("sequence"),
        "location_updated_at": cached.get("recorded_at") or location_updated_at,
        "pickup_lat": active_ride.pickup_lat,
        "pickup_lng": active_ride.pickup_lng,
        "dropoff_lat": active_ride.dropoff_lat,
        "dropoff_lng": active_ride.dropoff_lng,
    }


@router.get("/nearby-drivers")
async def get_nearby_drivers_count(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get count of online drivers nearby (within ~10km of user's active ride pickup)"""
    active_ride = db.query(RideEnhanced).filter(
        RideEnhanced.user_id == current_user.id,
        RideEnhanced.status == "pending"
    ).first()

    online_drivers = db.query(Driver).filter(
        Driver.is_online == True,
        Driver.is_active == True,
        Driver.current_lat.isnot(None),
        Driver.current_lng.isnot(None),
    ).all()

    if not active_ride or not online_drivers:
        return {"nearby_count": 0}

    radius = 0.1
    nearby = 0
    for d in online_drivers:
        lat_diff = abs(d.current_lat - active_ride.pickup_lat)
        lng_diff = abs(d.current_lng - active_ride.pickup_lng)
        if lat_diff <= radius and lng_diff <= radius:
            nearby += 1

    return {"nearby_count": nearby}


@router.get("/nearby-drivers/locations")
async def get_nearby_drivers_locations(
    lat: float = Query(..., description="User latitude"),
    lng: float = Query(..., description="User longitude"),
    vehicle_category: Optional[str] = Query(None, description="bike|auto|mini|sedan|suv — omit for all"),
    women_only: bool = Query(False, description="Only women captains"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Nearby online drivers for map pins, optionally filtered by vehicle category."""
    from app.services.dispatch import normalize_driver_category, vehicle_matches

    online_drivers = db.query(Driver).filter(
        Driver.is_online == True,  # noqa: E712
        Driver.is_active == True,  # noqa: E712
        Driver.current_lat.isnot(None),
        Driver.current_lng.isnot(None),
    ).all()

    want = (vehicle_category or "").lower().strip() or None
    radius = 0.15  # ~15km bbox approx
    drivers = []
    for d in online_drivers:
        if women_only and (getattr(d, "gender", None) or "").lower() != "female":
            continue
        lat_diff = abs(d.current_lat - lat)
        lng_diff = abs(d.current_lng - lng)
        if lat_diff > radius or lng_diff > radius:
            continue
        category = normalize_driver_category(d.vehicle_type)
        if want and want != "all":
            if not vehicle_matches(d, want) and category != want:
                continue
        drivers.append({
            "id": str(d.id),
            "latitude": d.current_lat,
            "longitude": d.current_lng,
            "vehicle_type": d.vehicle_type,
            "category": category,
            "gender": getattr(d, "gender", None),
        })

    return {"drivers": drivers, "filter": want or "all", "count": len(drivers)}


@router.get("/{ride_id}", response_model=RideEnhancedResponse)
async def get_booking(
    ride_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get specific ride details"""
    ride = db.query(RideEnhanced).filter(
        RideEnhanced.id == ride_id,
        RideEnhanced.user_id == current_user.id
    ).first()

    if not ride:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ride not found"
        )

    return enrich_ride_with_driver(ride, db)


@router.put("/{ride_id}/cancel", response_model=RideEnhancedResponse)
async def cancel_booking(
    ride_id: UUID,
    reason: str = Query(default=None, description="Cancellation reason"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Cancel a ride"""
    ride = db.query(RideEnhanced).filter(
        RideEnhanced.id == ride_id,
        RideEnhanced.user_id == current_user.id
    ).first()

    if not ride:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ride not found"
        )

    if ride.status == "completed":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot cancel a completed ride"
        )

    if ride.status == "cancelled":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Ride is already cancelled"
        )

    prior_status = ride.status
    fee = cancellation_fee_for_status(prior_status)
    ride.status = "cancelled"
    ride.cancellation_reason = reason or None
    ride.cancellation_fee = fee
    db.commit()
    db.refresh(ride)

    await _emit_ride(ride, "ride_cancelled", {"reason": reason, "cancellation_fee": fee})
    return enrich_ride_with_driver(ride, db)


@router.get("/history/all", response_model=List[RideEnhancedResponse])
async def get_ride_history(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get user's ride history"""
    rides = db.query(RideEnhanced).filter(
        RideEnhanced.user_id == current_user.id,
        RideEnhanced.status.in_(["completed", "cancelled"])
    ).order_by(RideEnhanced.created_at.desc()).all()

    return [enrich_ride_with_driver(ride, db) for ride in rides]


@router.post("/{ride_id}/payment/cash")
async def mark_cash_payment(
    ride_id: UUID,
    current_driver: Driver = Depends(get_current_driver),
    db: Session = Depends(get_db),
):
    """Mark ride as paid by cash — assigned driver only"""
    ride = db.query(RideEnhanced).filter(RideEnhanced.id == ride_id).first()

    if not ride:
        raise HTTPException(status_code=404, detail="Ride not found")

    if not ride.driver_id or ride.driver_id != current_driver.id:
        raise HTTPException(status_code=403, detail="Only the assigned driver can confirm cash payment")

    if ride.status != "completed":
        raise HTTPException(status_code=400, detail="Ride not completed yet")

    if ride.payment_status == "paid":
        return {"message": "Cash payment already recorded"}

    ride.payment_status = "paid"
    ride.payment_method = "cash"
    db.commit()

    await _emit_ride(ride, "payment_paid", {"payment_method": "cash"})
    return {"message": "Cash payment recorded"}
