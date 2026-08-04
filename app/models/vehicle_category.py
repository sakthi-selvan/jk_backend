import uuid
from sqlalchemy import Column, String, Float, Boolean, Integer, Text
from sqlalchemy.dialects.postgresql import UUID, JSON
from sqlalchemy.sql import func
from sqlalchemy import DateTime
from app.db.base import Base


class VehicleCategoryConfig(Base):
    """Configuration for vehicle categories with pricing and features"""
    __tablename__ = "vehicle_categories"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)

    # Category details
    name = Column(String(50), unique=True, nullable=False)  # mini, sedan, suv
    display_name = Column(String(100), nullable=False)  # Mini / Hatchback, Sedan, SUV
    description = Column(Text, nullable=True)

    # Capacity
    seater_capacity = Column(Integer, default=4)

    # Pricing
    base_fare = Column(Float, default=80.0)
    per_km_rate = Column(Float, default=14.0)

    # Example vehicles (JSON array)
    example_vehicles = Column(JSON, default=list)  # ["WagonR", "Alto", "Tiago"]

    # Features (JSON)
    features = Column(JSON, default=list)  # ["AC", "Music System", "Comfortable"]

    # Icon/Image
    icon_name = Column(String(100), nullable=True)  # For UI icon reference

    # Status
    is_active = Column(Boolean, default=True)

    # Priority for display (lower number = higher priority)
    display_order = Column(Integer, default=0)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
