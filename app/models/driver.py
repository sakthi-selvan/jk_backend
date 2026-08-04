import uuid
from sqlalchemy import Column, String, Boolean, DateTime, Float
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from app.db.base import Base


class Driver(Base):
    __tablename__ = "drivers"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    phone = Column(String(15), unique=True, index=True, nullable=False)
    name = Column(String(100), nullable=False)
    email = Column(String(255), unique=True, index=True, nullable=True)
    password_hash = Column(String(255), nullable=False)
    vehicle_number = Column(String(20), nullable=True)
    vehicle_type = Column(String(50), nullable=True)
    # male | female | other — used for women-driver preference matching
    gender = Column(String(20), nullable=True)
    is_online = Column(Boolean, default=False)
    is_verified = Column(Boolean, default=False)  # Admin verification status
    is_active = Column(Boolean, default=False)  # Account active only after admin approval
    license_document = Column(String(500), nullable=True)  # License photo URL/path
    aadhar_document = Column(String(500), nullable=True)  # Aadhar photo URL/path
    verification_notes = Column(String(500), nullable=True)  # Admin notes
    current_lat = Column(Float, nullable=True)
    current_lng = Column(Float, nullable=True)
    location_updated_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
