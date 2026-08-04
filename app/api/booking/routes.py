from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import or_
from typing import List
from uuid import UUID, uuid4
from app.core.dependencies import get_db, get_current_user
from app.schemas.booking import BookingCreate, BookingResponse, PaymentRequest
from app.models.ride import Ride, RideStatus, PaymentStatus
from app.models.user import User
from app.models.driver import Driver

router = APIRouter()


@router.post("/", response_model=BookingResponse, status_code=status.HTTP_201_CREATED)
async def create_booking(
    booking: BookingCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create a new ride booking"""
    # Calculate mock fare (simple distance-based)
    distance = abs(booking.dropoff_lat - booking.pickup_lat) + abs(booking.dropoff_lng - booking.pickup_lng)
    fare = max(50.0, distance * 100)  # Minimum 50 rupees

    new_ride = Ride(
        user_id=current_user.id,
        pickup_location=booking.pickup_location,
        dropoff_location=booking.dropoff_location,
        pickup_lat=booking.pickup_lat,
        pickup_lng=booking.pickup_lng,
        dropoff_lat=booking.dropoff_lat,
        dropoff_lng=booking.dropoff_lng,
        fare=fare,
        payment_method=booking.payment_method,
        status=RideStatus.PENDING
    )

    db.add(new_ride)
    db.commit()
    db.refresh(new_ride)

    return new_ride


@router.get("/active", response_model=BookingResponse)
async def get_active_booking(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get user's active ride"""
    active_ride = db.query(Ride).filter(
        Ride.user_id == current_user.id,
        Ride.status.in_([RideStatus.PENDING, RideStatus.ACCEPTED, RideStatus.STARTED])
    ).first()

    if not active_ride:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active ride found"
        )

    return active_ride


@router.get("/{ride_id}", response_model=BookingResponse)
async def get_booking(
    ride_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get specific ride details"""
    ride = db.query(Ride).filter(
        Ride.id == ride_id,
        Ride.user_id == current_user.id
    ).first()

    if not ride:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ride not found"
        )

    return ride


@router.put("/{ride_id}/cancel", response_model=BookingResponse)
async def cancel_booking(
    ride_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Cancel a ride"""
    ride = db.query(Ride).filter(
        Ride.id == ride_id,
        Ride.user_id == current_user.id
    ).first()

    if not ride:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ride not found"
        )

    if ride.status == RideStatus.COMPLETED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot cancel a completed ride"
        )

    if ride.status == RideStatus.CANCELLED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Ride is already cancelled"
        )

    ride.status = RideStatus.CANCELLED
    db.commit()
    db.refresh(ride)

    return ride


@router.post("/{ride_id}/payment")
async def process_payment(
    ride_id: UUID,
    payment: PaymentRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Process mock payment for ride"""
    ride = db.query(Ride).filter(
        Ride.id == ride_id,
        Ride.user_id == current_user.id
    ).first()

    if not ride:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ride not found"
        )

    if ride.status != RideStatus.COMPLETED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Can only pay for completed rides"
        )

    # Mock payment processing
    transaction_id = f"MOCK_TXN_{uuid4().hex[:12].upper()}"

    ride.payment_status = PaymentStatus.COMPLETED
    ride.transaction_id = transaction_id
    db.commit()

    return {
        "status": "success",
        "message": "Payment processed successfully",
        "transaction_id": transaction_id,
        "amount": ride.fare
    }


@router.get("/history/all", response_model=List[BookingResponse])
async def get_ride_history(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get user's ride history"""
    rides = db.query(Ride).filter(
        Ride.user_id == current_user.id,
        Ride.status.in_([RideStatus.COMPLETED, RideStatus.CANCELLED])
    ).order_by(Ride.created_at.desc()).all()

    return rides
