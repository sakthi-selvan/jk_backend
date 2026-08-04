from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
from uuid import UUID


class BookingCreate(BaseModel):
    pickup_location: str = Field(..., min_length=3)
    dropoff_location: str = Field(..., min_length=3)
    pickup_lat: float = Field(..., ge=-90, le=90)
    pickup_lng: float = Field(..., ge=-180, le=180)
    dropoff_lat: float = Field(..., ge=-90, le=90)
    dropoff_lng: float = Field(..., ge=-180, le=180)
    payment_method: str = Field(default="cash")


class BookingResponse(BaseModel):
    id: UUID
    user_id: UUID
    driver_id: Optional[UUID] = None
    pickup_location: str
    dropoff_location: str
    pickup_lat: float
    pickup_lng: float
    dropoff_lat: float
    dropoff_lng: float
    status: str
    fare: float
    payment_status: str
    payment_method: str
    transaction_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class PaymentRequest(BaseModel):
    ride_id: UUID
    amount: float = Field(..., gt=0)
    payment_method: str = Field(default="cash")
