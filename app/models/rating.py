"""Ride ratings and safety events."""
import uuid
from sqlalchemy import Column, String, Integer, Float, DateTime, Text, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from app.db.base import Base


class RideRating(Base):
    __tablename__ = "ride_ratings"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    ride_id = Column(UUID(as_uuid=True), ForeignKey("rides_enhanced.id"), nullable=False, index=True, unique=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    driver_id = Column(UUID(as_uuid=True), ForeignKey("drivers.id"), nullable=True, index=True)
    rating = Column(Integer, nullable=False)  # 1-5
    comment = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class SafetyEvent(Base):
    __tablename__ = "safety_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    ride_id = Column(UUID(as_uuid=True), ForeignKey("rides_enhanced.id"), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    event_type = Column(String(50), nullable=False)  # sos | trip_share
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    share_token = Column(String(64), nullable=True, index=True)
    meta = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
