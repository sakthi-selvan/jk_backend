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


class DriverResponse(DriverBase):
    id: UUID
    is_online: bool
    is_verified: bool
    is_active: bool
    license_document: Optional[str] = None
    aadhar_document: Optional[str] = None
    verification_notes: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class DriverUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[EmailStr] = None
    vehicle_number: Optional[str] = None
    vehicle_type: Optional[str] = None


class DriverStatusUpdate(BaseModel):
    is_online: bool
