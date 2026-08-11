"""Dispatch: sequential one-by-one exclusive offers, TTL, vehicle match, reassign."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional, Set, List, Tuple
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.driver import Driver
from app.models.ride_enhanced import RideEnhanced
from app.models.ride_cancellation import RideCancellation
from app.services.realtime import hub


CATEGORY_MATCH: dict[str, Set[str]] = {
    "bike": {"bike", "motorcycle", "scooter", "two_wheeler", "2wheeler"},
    "auto": {"auto", "auto_rickshaw", "rickshaw", "three_wheeler", "3wheeler"},
    "mini": {"mini", "hatchback", "car", "compact"},
    "sedan": {"sedan", "car"},
    "suv": {"suv", "muv", "xl", "car", "premium", "luxury", "crysta"},
}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def ensure_aware(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def driver_docs_ready(driver: Driver) -> tuple[bool, str]:
    if settings.REQUIRE_DRIVER_DOCS:
        if not driver.license_document:
            return False, "Upload your driving license before going online"
        if settings.REQUIRE_AADHAR_DOCUMENT and not driver.aadhar_document:
            return False, "Upload your Aadhaar document before going online"
    if settings.REQUIRE_DRIVER_VERIFIED and not driver.is_verified:
        return False, "Account pending admin verification"
    return True, ""


def driver_location_fresh(driver: Driver) -> bool:
    updated = ensure_aware(driver.location_updated_at)
    if updated is None or driver.current_lat is None or driver.current_lng is None:
        return False
    age = (_utcnow() - updated).total_seconds()
    return age <= settings.STALE_GPS_SECONDS


def vehicle_matches(driver: Driver, vehicle_category: str) -> bool:
    if not settings.ENFORCE_VEHICLE_MATCH:
        return True
    cat = (vehicle_category or "").lower().strip()
    dtype = (driver.vehicle_type or "").lower().strip().replace(" ", "_").replace("-", "_")
    if not dtype:
        return False
    allowed = CATEGORY_MATCH.get(cat)
    if not allowed:
        return True
    if dtype in allowed:
        return True
    return any(token in dtype for token in allowed)


def normalize_driver_category(vehicle_type: Optional[str]) -> str:
    """Map free-text driver.vehicle_type → bike|auto|mini|sedan|suv|other."""
    t = (vehicle_type or "").lower().replace(" ", "_").replace("-", "_")
    if not t:
        return "other"
    if any(tok in t for tok in ("premium", "luxury", "crysta", "byd")):
        return "suv"
    for cat, tokens in CATEGORY_MATCH.items():
        if t in tokens or any(tok in t for tok in tokens):
            return cat
    if "car" in t:
        return "mini"
    return "other"

def declined_driver_ids(db: Session, ride_id: UUID) -> Set[UUID]:
    rows = db.query(RideCancellation.canceller_id).filter(
        RideCancellation.ride_id == ride_id,
        RideCancellation.cancelled_by == "driver",
    ).all()
    return {r[0] for r in rows if r[0]}


def driver_has_active_ride(db: Session, driver_id: UUID) -> bool:
    return (
        db.query(RideEnhanced)
        .filter(
            RideEnhanced.driver_id == driver_id,
            RideEnhanced.status.in_(["accepted", "started"]),
        )
        .first()
        is not None
    )


def user_has_active_ride(db: Session, user_id: UUID) -> bool:
    return (
        db.query(RideEnhanced)
        .filter(
            RideEnhanced.user_id == user_id,
            RideEnhanced.status.in_(["pending", "accepted", "started"]),
        )
        .first()
        is not None
    )


def search_anchor_time(ride: RideEnhanced) -> Optional[datetime]:
    """Overall search TTL clock (resets on reassign after accept)."""
    started = ensure_aware(getattr(ride, "dispatch_started_at", None))
    if started:
        return started
    return offer_anchor_time_legacy(ride)


def offer_anchor_time_legacy(ride: RideEnhanced) -> Optional[datetime]:
    created = ensure_aware(ride.created_at)
    if ride.is_scheduled and ride.scheduled_datetime:
        when = ensure_aware(ride.scheduled_datetime)
        if when:
            release_at = when - timedelta(minutes=settings.SCHEDULED_RELEASE_MINUTES)
            if created and created > release_at:
                return created
            return release_at
    return created


def offer_anchor_time(ride: RideEnhanced) -> Optional[datetime]:
    """Back-compat alias used by older callers — overall search clock."""
    return search_anchor_time(ride)


def search_remaining_seconds(ride: RideEnhanced) -> int:
    anchor = search_anchor_time(ride)
    if not anchor:
        return settings.OFFER_TTL_SECONDS
    age = int((_utcnow() - anchor).total_seconds())
    return max(0, settings.OFFER_TTL_SECONDS - age)


def offer_remaining_seconds(ride: RideEnhanced) -> int:
    """Overall booking search remaining (alias used across codebase)."""
    return search_remaining_seconds(ride)


def driver_offer_remaining_seconds(ride: RideEnhanced) -> int:
    """Exclusive per-driver window remaining."""
    started = ensure_aware(getattr(ride, "offer_started_at", None))
    if not started:
        return settings.DRIVER_OFFER_SECONDS
    age = int((_utcnow() - started).total_seconds())
    return max(0, settings.DRIVER_OFFER_SECONDS - age)


def scheduled_ready_for_dispatch(ride: RideEnhanced) -> bool:
    if not ride.is_scheduled or not ride.scheduled_datetime:
        return True
    when = ensure_aware(ride.scheduled_datetime)
    if not when:
        return True
    release_at = when - timedelta(minutes=settings.SCHEDULED_RELEASE_MINUTES)
    late_cutoff = when + timedelta(minutes=settings.SCHEDULED_LATE_GRACE_MINUTES)
    now = _utcnow()
    return release_at <= now <= late_cutoff


def _rank_eligible_drivers(db: Session, ride: RideEnhanced) -> List[Tuple[Driver, float]]:
    from app.services.routing import estimate_pickup_eta_minutes, haversine_km

    excluded = declined_driver_ids(db, ride.id)
    prefs = ride.preferences or {}
    women_only = bool(prefs.get("women_driver"))

    drivers = (
        db.query(Driver)
        .filter(Driver.is_online == True)  # noqa: E712
        .all()
    )

    ranked: List[Tuple[Driver, float]] = []
    for driver in drivers:
        if driver.id in excluded:
            continue
        ok, _ = driver_docs_ready(driver)
        if not ok:
            continue
        if not driver_location_fresh(driver):
            continue
        if not vehicle_matches(driver, ride.vehicle_category):
            continue
        if women_only and (getattr(driver, "gender", None) or "").lower() != "female":
            continue
        if driver_has_active_ride(db, driver.id):
            continue

        distance = haversine_km(
            driver.current_lat,
            driver.current_lng,
            ride.pickup_lat,
            ride.pickup_lng,
        )
        eta = estimate_pickup_eta_minutes(distance)
        if eta > settings.MAX_PICKUP_ETA_MINUTES:
            continue
        ranked.append((driver, distance))

    ranked.sort(key=lambda x: x[1])
    return ranked


def begin_dispatch(ride: RideEnhanced) -> None:
    """Start (or restart) overall search clock and clear exclusive offer."""
    now = _utcnow()
    ride.dispatch_started_at = now
    ride.offered_driver_id = None
    ride.offer_started_at = None


def assign_next_offer(db: Session, ride: RideEnhanced) -> Optional[Driver]:
    """
    Give exclusive offer to the next nearest eligible driver.
    Returns the offered driver, or None if nobody available.
    """
    if ride.status != "pending" or ride.driver_id is not None:
        return None
    if not scheduled_ready_for_dispatch(ride):
        return None
    if search_remaining_seconds(ride) <= 0:
        return None

    if not getattr(ride, "dispatch_started_at", None):
        begin_dispatch(ride)

    ranked = _rank_eligible_drivers(db, ride)
    if not ranked:
        ride.offered_driver_id = None
        ride.offer_started_at = None
        return None

    driver = ranked[0][0]
    ride.offered_driver_id = driver.id
    ride.offer_started_at = _utcnow()
    return driver


def record_driver_pass(db: Session, ride: RideEnhanced, driver_id: UUID, reason: str) -> None:
    """Exclude driver from further offers for this ride."""
    exists = (
        db.query(RideCancellation)
        .filter(
            RideCancellation.ride_id == ride.id,
            RideCancellation.canceller_id == driver_id,
        )
        .first()
    )
    if exists:
        return
    db.add(
        RideCancellation(
            ride_id=ride.id,
            cancelled_by="driver",
            canceller_id=driver_id,
            reason=reason,
        )
    )
    ride.rejection_count = (ride.rejection_count or 0) + 1
    db.flush()  # so subsequent ranking queries see the exclusion


async def emit_ride_offer(ride: RideEnhanced, driver: Driver) -> None:
    """Push a full offer payload so the driver app can show Accept UI immediately."""
    from app.services.routing import estimate_pickup_eta_minutes, haversine_km

    distance_to_pickup = None
    eta_to_pickup = None
    if (
        driver.current_lat is not None
        and driver.current_lng is not None
        and ride.pickup_lat is not None
        and ride.pickup_lng is not None
    ):
        distance_to_pickup = haversine_km(
            driver.current_lat,
            driver.current_lng,
            ride.pickup_lat,
            ride.pickup_lng,
        )
        eta_to_pickup = estimate_pickup_eta_minutes(distance_to_pickup)

    data = {
        "ride_id": str(ride.id),
        "id": str(ride.id),
        "status": "pending",
        "user_id": str(ride.user_id),
        "offered_driver_id": str(driver.id),
        "trip_type": ride.trip_type,
        "vehicle_category": ride.vehicle_category,
        "pickup_location": ride.pickup_location,
        "dropoff_location": ride.dropoff_location,
        "pickup_lat": ride.pickup_lat,
        "pickup_lng": ride.pickup_lng,
        "dropoff_lat": ride.dropoff_lat,
        "dropoff_lng": ride.dropoff_lng,
        "stops": ride.stops or [],
        "is_scheduled": bool(ride.is_scheduled),
        "booking_for_self": ride.booking_for_self,
        "passenger_name": ride.passenger_name,
        "passenger_phone": ride.passenger_phone,
        "preferences": ride.preferences or {},
        "fare": ride.fare,
        "base_fare": ride.base_fare,
        "distance_fare": ride.distance_fare,
        "platform_fee": ride.platform_fee,
        "gst": ride.gst,
        "toll_charges": ride.toll_charges,
        "night_charges": ride.night_charges,
        "waiting_charges": ride.waiting_charges,
        "payment_method": ride.payment_method,
        "payment_status": ride.payment_status,
        "trip_distance_km": ride.distance_km,
        "distance_km": round(distance_to_pickup, 2) if distance_to_pickup is not None else ride.distance_km,
        "eta_minutes": round(eta_to_pickup) if eta_to_pickup is not None else ride.eta_minutes,
        "otp_verified": False,
        "offer_remaining_seconds": driver_offer_remaining_seconds(ride),
        "driver_offer_seconds": settings.DRIVER_OFFER_SECONDS,
        "search_remaining_seconds": search_remaining_seconds(ride),
        "offer_ttl_seconds": settings.DRIVER_OFFER_SECONDS,
    }
    await hub.publish_driver(str(driver.id), "ride_offer", data)
    await hub.publish_ride(str(ride.id), "ride_offer", data)
    await hub.publish_user(str(ride.user_id), "ride_searching", {
        "ride_id": str(ride.id),
        "status": "pending",
        "search_remaining_seconds": search_remaining_seconds(ride),
    })


async def advance_timed_out_offers(db: Session) -> list[dict]:
    """
    For pending rides with an exclusive offer past DRIVER_OFFER_SECONDS:
    auto-pass that driver and offer the next one.
    Returns event descriptors for callers to emit after commit.
    """
    events: list[dict] = []
    rides = (
        db.query(RideEnhanced)
        .filter(
            RideEnhanced.status == "pending",
            RideEnhanced.driver_id.is_(None),
            RideEnhanced.offered_driver_id.isnot(None),
        )
        .all()
    )

    for ride in rides:
        if not scheduled_ready_for_dispatch(ride):
            continue
        if driver_offer_remaining_seconds(ride) > 0:
            continue

        timed_out_id = ride.offered_driver_id
        if timed_out_id:
            record_driver_pass(db, ride, timed_out_id, "offer_timeout")
            events.append({
                "type": "offer_timeout",
                "ride_id": str(ride.id),
                "driver_id": str(timed_out_id),
            })

        next_driver = assign_next_offer(db, ride)
        if next_driver:
            events.append({
                "type": "ride_offer",
                "ride": ride,
                "driver": next_driver,
            })
        elif search_remaining_seconds(ride) <= 0:
            ride.status = "cancelled"
            ride.cancellation_reason = (
                f"Auto-cancelled: no driver accepted within {settings.OFFER_TTL_SECONDS // 60} minutes"
            )
            ride.offered_driver_id = None
            ride.offer_started_at = None
            events.append({"type": "ride_cancelled", "ride": ride})
        else:
            # Keep searching; clear exclusive so next sweep can retry
            ride.offered_driver_id = None
            ride.offer_started_at = None
            events.append({"type": "waiting_drivers", "ride_id": str(ride.id)})

    if events:
        db.commit()
        for ev in events:
            if ev.get("type") == "ride_offer" and ev.get("ride"):
                db.refresh(ev["ride"])
            if ev.get("type") == "ride_cancelled" and ev.get("ride"):
                db.refresh(ev["ride"])
    return events


async def emit_advance_events(events: list[dict]) -> None:
    for ev in events:
        kind = ev.get("type")
        if kind == "ride_offer":
            await emit_ride_offer(ev["ride"], ev["driver"])
        elif kind == "offer_timeout":
            await hub.publish_driver(ev["driver_id"], "offer_expired", {
                "ride_id": ev["ride_id"],
            })
        elif kind == "ride_cancelled":
            ride = ev["ride"]
            data = {
                "ride_id": str(ride.id),
                "status": "cancelled",
                "user_id": str(ride.user_id),
                "reason": ride.cancellation_reason,
            }
            await hub.publish_ride(str(ride.id), "ride_cancelled", data)
            await hub.publish_user(str(ride.user_id), "ride_cancelled", data)
            await hub.publish(hub.drivers_online_channel(), "ride_cancelled", data)


def expire_stale_pending_rides(db: Session) -> list[RideEnhanced]:
    """Cancel pending rides past overall search TTL. Returns expired rides."""
    rides = db.query(RideEnhanced).filter(
        RideEnhanced.status == "pending",
        RideEnhanced.driver_id.is_(None),
    ).all()

    expired: list[RideEnhanced] = []
    for ride in rides:
        if ride.is_scheduled and not scheduled_ready_for_dispatch(ride):
            continue
        if search_remaining_seconds(ride) > 0:
            continue
        ride.status = "cancelled"
        ride.cancellation_reason = (
            f"Auto-cancelled: no driver accepted within {settings.OFFER_TTL_SECONDS // 60} minutes"
        )
        ride.offered_driver_id = None
        ride.offer_started_at = None
        expired.append(ride)

    if expired:
        db.commit()
        for ride in expired:
            db.refresh(ride)
    return expired


async def emit_expired(rides: list[RideEnhanced]) -> None:
    for ride in rides:
        data = {
            "ride_id": str(ride.id),
            "status": "cancelled",
            "user_id": str(ride.user_id),
            "reason": ride.cancellation_reason,
        }
        await hub.publish_ride(str(ride.id), "ride_cancelled", data)
        await hub.publish_user(str(ride.user_id), "ride_cancelled", data)


def reassign_after_reject(ride: RideEnhanced) -> None:
    """Return ride to pending and restart search clock for next driver."""
    ride.driver_id = None
    ride.status = "pending"
    ride.otp_verified = False
    begin_dispatch(ride)


def offer_is_for_driver(ride: RideEnhanced, driver_id: UUID) -> bool:
    """True if this driver currently holds the exclusive offer (or sequential off)."""
    if not settings.SEQUENTIAL_DISPATCH:
        return True
    offered = getattr(ride, "offered_driver_id", None)
    if offered is None:
        # No exclusive holder yet — allow only if sequential just starting
        return False
    return offered == driver_id
