import uuid
from sqlalchemy import Column, String, DateTime, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from app.db.base import Base


class RideCancellation(Base):
    __tablename__ = "ride_cancellations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    ride_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    cancelled_by = Column(String(10), nullable=False)  # 'driver' or 'customer'
    canceller_id = Column(UUID(as_uuid=True), nullable=False)
    reason = Column(String(100), nullable=False)  # Predefined reason
    custom_reason = Column(Text, nullable=True)  # Custom text if "Other" selected
    created_at = Column(DateTime(timezone=True), server_default=func.now())
