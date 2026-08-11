from pydantic import BaseModel, EmailStr
from typing import Optional
from datetime import datetime
from uuid import UUID


class DriverBase(BaseModel):
    phone: str
    name: str
    email: Optional[EmailStr] = None
    vehicle_number: Optional[str] = None
    vehicle_type: Optional[str] = None
    gender: Optional[str] = None


class DriverResponse(DriverBase):
    id: UUID
    is_online: bool
    is_verified: bool
    is_active: bool
    license_document: Optional[str] = None
    aadhar_document: Optional[str] = None
    vehicle_image: Optional[str] = None
    verification_notes: Optional[str] = None
    created_at: datetime
    total_rides: Optional[int] = 0
    average_rating: Optional[float] = None
    rating_count: Optional[int] = 0

    class Config:
        from_attributes = True


class DriverUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[EmailStr] = None
    vehicle_number: Optional[str] = None
    vehicle_type: Optional[str] = None
    gender: Optional[str] = None
    vehicle_image: Optional[str] = None  # data URI or /uploads path


class DriverStatusUpdate(BaseModel):
    is_online: bool
