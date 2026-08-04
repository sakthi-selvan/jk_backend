import uuid
import random
from sqlalchemy import Column, String, Boolean, DateTime
from sqlalchemy.dialects.postgresql import UUID, JSON
from sqlalchemy.sql import func
from app.db.base import Base


def generate_user_otp():
    """Generate a static 4-digit OTP for user (like Rapido)"""
    return str(random.randint(1000, 9999))


class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    phone = Column(String(15), unique=True, index=True, nullable=False)
    name = Column(String(100), nullable=False)
    email = Column(String(255), unique=True, index=True, nullable=True)
    password_hash = Column(String(255), nullable=True)
    emergency_contact_name = Column(String(100), nullable=True)
    emergency_contact_phone = Column(String(15), nullable=True)

    # Static OTP for all rides (like Rapido)
    ride_otp = Column(String(4), default=generate_user_otp, nullable=False)

    # Saved Places: {home: {address, lat, lng}, work: {address, lat, lng}}
    saved_places = Column(JSON, default=dict, nullable=True)

    is_verified = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
