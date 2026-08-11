from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from uuid import UUID
from app.core.dependencies import get_db, get_current_driver
from app.schemas.driver import DriverResponse, DriverUpdate, DriverStatusUpdate
from app.schemas.booking import BookingResponse
from app.models.driver import Driver
from app.models.ride import Ride, RideStatus
from app.services.driver_stats import get_driver_public_stats

router = APIRouter()


def enrich_driver_response(driver: Driver, db: Session) -> dict:
    """Attach public trip/rating stats to a driver profile payload."""
    data = {c.name: getattr(driver, c.name) for c in driver.__table__.columns}
    stats = get_driver_public_stats(db, driver.id)
    data["total_rides"] = stats["driver_total_rides"]
    data["average_rating"] = stats["driver_average_rating"]
    data["rating_count"] = stats["driver_rating_count"]
    return data


@router.get("/profile", response_model=DriverResponse)
async def get_driver_profile(
    current_driver: Driver = Depends(get_current_driver),
    db: Session = Depends(get_db)
):
    """Get driver profile"""
    return enrich_driver_response(current_driver, db)


@router.put("/profile", response_model=DriverResponse)
async def update_driver_profile(
    driver_update: DriverUpdate,
    current_driver: Driver = Depends(get_current_driver),
    db: Session = Depends(get_db)
):
    """Update driver profile"""
    if driver_update.name:
        current_driver.name = driver_update.name
    if driver_update.email:
        current_driver.email = driver_update.email
    if driver_update.vehicle_number:
        current_driver.vehicle_number = driver_update.vehicle_number
    if driver_update.vehicle_type:
        current_driver.vehicle_type = driver_update.vehicle_type
    if driver_update.gender is not None:
        current_driver.gender = driver_update.gender.strip() or None
    if driver_update.vehicle_image:
        from app.services.document_storage import save_driver_document_data_uri
        current_driver.vehicle_image = save_driver_document_data_uri(
            current_driver.id, "vehicle", driver_update.vehicle_image
        )

    db.commit()
    db.refresh(current_driver)
    return enrich_driver_response(current_driver, db)


@router.put("/status", response_model=DriverResponse)
async def update_driver_status(
    status_update: DriverStatusUpdate,
    current_driver: Driver = Depends(get_current_driver),
    db: Session = Depends(get_db)
):
    """Update driver online/offline status"""
    from app.services.dispatch import driver_docs_ready, driver_location_fresh

    if status_update.is_online:
        ok, reason = driver_docs_ready(current_driver)
        if not ok:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=reason)
        if current_driver.current_lat is None or current_driver.current_lng is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Share your GPS location before going online",
            )
        # Soft warning path: allow if coords exist even if slightly stale on first toggle
        _ = driver_location_fresh(current_driver)

    current_driver.is_online = status_update.is_online
    db.commit()
    db.refresh(current_driver)
    return enrich_driver_response(current_driver, db)


@router.get("/rides/available", response_model=List[BookingResponse])
async def get_available_rides(
    current_driver: Driver = Depends(get_current_driver),
    db: Session = Depends(get_db)
):
    """Get available rides for driver"""
    if not current_driver.is_online:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Driver must be online to view available rides"
        )

    # Get pending rides (not assigned to any driver)
    available_rides = db.query(Ride).filter(
        Ride.status == RideStatus.PENDING,
        Ride.driver_id.is_(None)
    ).order_by(Ride.created_at.desc()).limit(10).all()

    return available_rides


@router.post("/rides/{ride_id}/accept", response_model=BookingResponse)
async def accept_ride(
    ride_id: UUID,
    current_driver: Driver = Depends(get_current_driver),
    db: Session = Depends(get_db)
):
    """Accept a ride"""
    if not current_driver.is_online:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Driver must be online to accept rides"
        )

    ride = db.query(Ride).filter(Ride.id == ride_id).first()
    if not ride:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ride not found"
        )

    if ride.status != RideStatus.PENDING:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Ride is not available"
        )

    ride.driver_id = current_driver.id
    ride.status = RideStatus.ACCEPTED
    db.commit()
    db.refresh(ride)

    return ride


@router.post("/rides/{ride_id}/reject")
async def reject_ride(
    ride_id: UUID,
    current_driver: Driver = Depends(get_current_driver),
    db: Session = Depends(get_db)
):
    """Reject a ride (no change to ride, just notification)"""
    ride = db.query(Ride).filter(Ride.id == ride_id).first()
    if not ride:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ride not found"
        )

    return {"message": "Ride rejected"}


@router.post("/rides/{ride_id}/start", response_model=BookingResponse)
async def start_ride(
    ride_id: UUID,
    current_driver: Driver = Depends(get_current_driver),
    db: Session = Depends(get_db)
):
    """Start a ride"""
    ride = db.query(Ride).filter(
        Ride.id == ride_id,
        Ride.driver_id == current_driver.id
    ).first()

    if not ride:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ride not found"
        )

    if ride.status != RideStatus.ACCEPTED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Can only start accepted rides"
        )

    ride.status = RideStatus.STARTED
    db.commit()
    db.refresh(ride)

    return ride


@router.post("/rides/{ride_id}/complete", response_model=BookingResponse)
async def complete_ride(
    ride_id: UUID,
    current_driver: Driver = Depends(get_current_driver),
    db: Session = Depends(get_db)
):
    """Complete a ride"""
    ride = db.query(Ride).filter(
        Ride.id == ride_id,
        Ride.driver_id == current_driver.id
    ).first()

    if not ride:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ride not found"
        )

    if ride.status != RideStatus.STARTED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Can only complete started rides"
        )

    ride.status = RideStatus.COMPLETED
    db.commit()
    db.refresh(ride)

    return ride


@router.get("/rides/history", response_model=List[BookingResponse])
async def get_driver_ride_history(
    current_driver: Driver = Depends(get_current_driver),
    db: Session = Depends(get_db)
):
    """Get driver's ride history"""
    rides = db.query(Ride).filter(
        Ride.driver_id == current_driver.id,
        Ride.status.in_([RideStatus.COMPLETED, RideStatus.CANCELLED])
    ).order_by(Ride.created_at.desc()).all()

    return rides


@router.get("/earnings")
async def get_driver_earnings(
    current_driver: Driver = Depends(get_current_driver),
    db: Session = Depends(get_db)
):
    """Get mock driver earnings"""
    completed_rides = db.query(Ride).filter(
        Ride.driver_id == current_driver.id,
        Ride.status == RideStatus.COMPLETED
    ).all()

    total_earnings = sum(ride.fare for ride in completed_rides)
    total_rides = len(completed_rides)

    return {
        "total_earnings": total_earnings,
        "total_rides": total_rides,
        "average_fare": total_earnings / total_rides if total_rides > 0 else 0
    }
