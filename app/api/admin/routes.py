from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List
from uuid import UUID
from app.core.dependencies import get_db, get_current_admin
from app.schemas.user import UserResponse
from app.schemas.driver import DriverResponse
from app.schemas.booking import BookingResponse
from app.models.admin import Admin
from app.models.user import User
from app.models.driver import Driver
from app.models.ride import Ride, RideStatus

router = APIRouter()


@router.get("/dashboard/stats")
async def get_dashboard_stats(
    current_admin: Admin = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """Get dashboard statistics"""
    total_users = db.query(func.count(User.id)).scalar()
    total_drivers = db.query(func.count(Driver.id)).scalar()
    total_rides = db.query(func.count(Ride.id)).scalar()
    active_rides = db.query(func.count(Ride.id)).filter(
        Ride.status.in_([RideStatus.PENDING, RideStatus.ACCEPTED, RideStatus.STARTED])
    ).scalar()
    completed_rides = db.query(func.count(Ride.id)).filter(
        Ride.status == RideStatus.COMPLETED
    ).scalar()

    total_revenue = db.query(func.sum(Ride.fare)).filter(
        Ride.status == RideStatus.COMPLETED
    ).scalar() or 0

    return {
        "total_users": total_users,
        "total_drivers": total_drivers,
        "total_rides": total_rides,
        "active_rides": active_rides,
        "completed_rides": completed_rides,
        "total_revenue": float(total_revenue)
    }


@router.get("/users", response_model=List[UserResponse])
async def get_all_users(
    current_admin: Admin = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """Get all users"""
    users = db.query(User).order_by(User.created_at.desc()).all()
    return users


@router.get("/users/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: UUID,
    current_admin: Admin = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """Get specific user"""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    return user


@router.put("/users/{user_id}/block")
async def block_user(
    user_id: UUID,
    current_admin: Admin = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """Block a user"""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    user.is_active = False
    db.commit()
    return {"message": "User blocked successfully"}


@router.put("/users/{user_id}/unblock")
async def unblock_user(
    user_id: UUID,
    current_admin: Admin = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """Unblock a user"""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    user.is_active = True
    db.commit()
    return {"message": "User unblocked successfully"}


@router.get("/drivers", response_model=List[DriverResponse])
async def get_all_drivers(
    current_admin: Admin = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """Get all drivers"""
    drivers = db.query(Driver).order_by(Driver.created_at.desc()).all()
    return drivers


@router.get("/drivers/{driver_id}", response_model=DriverResponse)
async def get_driver(
    driver_id: UUID,
    current_admin: Admin = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """Get specific driver"""
    driver = db.query(Driver).filter(Driver.id == driver_id).first()
    if not driver:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Driver not found"
        )
    return driver


@router.put("/drivers/{driver_id}/block")
async def block_driver(
    driver_id: UUID,
    current_admin: Admin = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """Block a driver"""
    driver = db.query(Driver).filter(Driver.id == driver_id).first()
    if not driver:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Driver not found"
        )

    driver.is_active = False
    db.commit()
    return {"message": "Driver blocked successfully"}


@router.put("/drivers/{driver_id}/unblock")
async def unblock_driver(
    driver_id: UUID,
    current_admin: Admin = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """Unblock a driver"""
    driver = db.query(Driver).filter(Driver.id == driver_id).first()
    if not driver:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Driver not found"
        )

    driver.is_active = True
    db.commit()
    return {"message": "Driver unblocked successfully"}


@router.get("/rides/active")
async def get_active_rides(
    current_admin: Admin = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """Get all active rides with driver location"""
    active_rides = db.query(Ride).filter(
        Ride.status.in_([RideStatus.PENDING, RideStatus.ACCEPTED, RideStatus.STARTED])
    ).order_by(Ride.created_at.desc()).all()

    results = []
    for ride in active_rides:
        ride_data = {
            "id": str(ride.id),
            "user_id": str(ride.user_id),
            "driver_id": str(ride.driver_id) if ride.driver_id else None,
            "status": ride.status.value,
            "pickup_location": ride.pickup_location,
            "dropoff_location": ride.dropoff_location,
            "pickup_lat": ride.pickup_lat,
            "pickup_lng": ride.pickup_lng,
            "dropoff_lat": ride.dropoff_lat,
            "dropoff_lng": ride.dropoff_lng,
            "fare": ride.fare,
            "created_at": ride.created_at.isoformat() if ride.created_at else None,
        }
        if ride.driver_id:
            driver = db.query(Driver).filter(Driver.id == ride.driver_id).first()
            if driver:
                ride_data["driver_name"] = driver.name
                ride_data["driver_phone"] = driver.phone
                ride_data["driver_lat"] = driver.current_lat
                ride_data["driver_lng"] = driver.current_lng
        results.append(ride_data)

    return results


@router.get("/drivers/online")
async def get_online_drivers(
    current_admin: Admin = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """Get all online drivers with their current location"""
    drivers = db.query(Driver).filter(
        Driver.is_online == True,
        Driver.current_lat.isnot(None),
        Driver.current_lng.isnot(None)
    ).all()

    return [
        {
            "id": str(d.id),
            "name": d.name,
            "phone": d.phone,
            "vehicle_number": d.vehicle_number,
            "vehicle_type": d.vehicle_type,
            "lat": d.current_lat,
            "lng": d.current_lng,
            "location_updated_at": d.location_updated_at.isoformat() if d.location_updated_at else None,
        }
        for d in drivers
    ]


@router.get("/rides", response_model=List[BookingResponse])
async def get_all_rides(
    current_admin: Admin = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """Get all rides"""
    rides = db.query(Ride).order_by(Ride.created_at.desc()).all()
    return rides


@router.get("/rides/{ride_id}", response_model=BookingResponse)
async def get_ride(
    ride_id: UUID,
    current_admin: Admin = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """Get specific ride"""
    ride = db.query(Ride).filter(Ride.id == ride_id).first()
    if not ride:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ride not found"
        )
    return ride
