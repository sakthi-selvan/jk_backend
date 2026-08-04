from pydantic import BaseModel, EmailStr, Field
from typing import Optional


# OTP-based auth
class SendOTP(BaseModel):
    phone: str = Field(..., min_length=10, max_length=15)


class VerifyOTP(BaseModel):
    phone: str = Field(..., min_length=10, max_length=15)
    otp: str = Field(..., min_length=4, max_length=6)


class CompleteProfile(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    email: Optional[EmailStr] = None
    emergency_contact_name: Optional[str] = Field(None, min_length=2, max_length=100)
    emergency_contact_phone: Optional[str] = Field(None, min_length=10, max_length=15)


# Legacy - kept for backward compatibility
class UserRegister(BaseModel):
    phone: str = Field(..., min_length=10, max_length=15)
    name: str = Field(..., min_length=2, max_length=100)
    email: Optional[EmailStr] = None
    password: str = Field(..., min_length=6)


class UserLogin(BaseModel):
    phone: str = Field(..., min_length=10, max_length=15)
    password: str = Field(..., min_length=6)


# Driver Registration/Login
class DriverRegister(BaseModel):
    phone: str = Field(..., min_length=10, max_length=15)
    name: str = Field(..., min_length=2, max_length=100)
    email: Optional[EmailStr] = None
    password: str = Field(..., min_length=6)
    vehicle_number: Optional[str] = None
    vehicle_type: Optional[str] = None
    license_document: Optional[str] = None  # Base64 or URL
    aadhar_document: Optional[str] = None  # Base64 or URL


class DriverLogin(BaseModel):
    phone: str = Field(..., min_length=10, max_length=15)
    password: str = Field(..., min_length=6)


# Admin Login
class AdminLogin(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    password: str = Field(..., min_length=6)


# Token Response
class Token(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshToken(BaseModel):
    refresh_token: str
