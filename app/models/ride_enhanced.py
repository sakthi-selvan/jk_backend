import uuid
import random
from sqlalchemy import Column, String, Float, DateTime, ForeignKey, Boolean, Integer, Text
from sqlalchemy.dialects.postgresql import UUID, JSON
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
import enum
from app.db.base import Base


class TripType(str, enum.Enum):
    ONE_WAY = "one_way"
    RENTAL = "rental"
    OUTSTATION = "outstation"


class RideStatus(str, enum.Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    STARTED = "started"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class PaymentStatus(str, enum.Enum):
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"


class VehicleCategory(str, enum.Enum):
    AUTO = "auto"
    BIKE = "bike"
    MINI = "mini"
    SEDAN = "sedan"
    SUV = "suv"


def generate_ride_otp():
    """Generate a 4-digit OTP for ride verification"""
    return str(random.randint(1000, 9999))


class RideEnhanced(Base):
    __tablename__ = "rides_enhanced"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    driver_id = Column(UUID(as_uuid=True), ForeignKey("drivers.id"), nullable=True, index=True)

    # Trip Details
    trip_type = Column(String(50), default="one_way", nullable=False)
    vehicle_category = Column(String(50), default="mini", nullable=False)

    # Locations
    pickup_location = Column(String(255), nullable=False)
    dropoff_location = Column(String(255), nullable=True)  # Nullable for rental
    pickup_lat = Column(Float, nullable=False)
    pickup_lng = Column(Float, nullable=False)
    dropoff_lat = Column(Float, nullable=True)
    dropoff_lng = Column(Float, nullable=True)
    stops = Column(JSON, default=list)  # List of intermediate stops

    # Timing
    is_scheduled = Column(Boolean, default=False)
    scheduled_datetime = Column(DateTime(timezone=True), nullable=True)

    # Booking For Someone Else
    booking_for_self = Column(Boolean, default=True)
    passenger_name = Column(String(100), nullable=True)
    passenger_phone = Column(String(15), nullable=True)
    passenger_notes = Column(Text, nullable=True)

    # Ride Preferences (JSON)
    preferences = Column(JSON, default=dict)  # {ac_preferred, pet_friendly, silent_ride, extra_luggage, wheelchair}
    driver_notes = Column(Text, nullable=True)  # Pickup instructions

    # OTP for ride verification (copied from user's static OTP)
    ride_otp = Column(String(4), nullable=False)
    otp_verified = Column(Boolean, default=False)

    # Status & Tracking (like Rapido)
    status = Column(String(50), default="pending", nullable=False, index=True)
    rejection_count = Column(Integer, default=0)  # Number of drivers who rejected this ride

    # Sequential one-by-one dispatch
    offered_driver_id = Column(UUID(as_uuid=True), ForeignKey("drivers.id"), nullable=True, index=True)
    offer_started_at = Column(DateTime(timezone=True), nullable=True)  # exclusive offer window start
    dispatch_started_at = Column(DateTime(timezone=True), nullable=True)  # overall search clock

    # Fare Breakdown
    base_fare = Column(Float, default=0.0)
    distance_fare = Column(Float, default=0.0)
    platform_fee = Column(Float, default=40.0)
    gst = Column(Float, default=0.0)
    toll_charges = Column(Float, default=0.0)
    night_charges = Column(Float, default=0.0)
    waiting_charges = Column(Float, default=0.0)
    fare = Column(Float, default=0.0)  # Total fare

    # Payment
    payment_status = Column(String(50), default="pending", nullable=False)
    payment_method = Column(String(50), default="cash")
    transaction_id = Column(String(100), nullable=True)

    # Cancellation
    cancellation_reason = Column(String(255), nullable=True)
    cancellation_fee = Column(Float, default=0.0)

    # Surge multiplier applied at booking (1.0 = none)
    surge_multiplier = Column(Float, default=1.0)

    # Distance (in km)
    distance_km = Column(Float, default=0.0)

    # ETA (in minutes)
    eta_minutes = Column(Integer, default=5)

    # Road-network route (Mapbox GeoJSON coordinates [[lng,lat], ...] or null)
    route_geometry = Column(JSON, nullable=True)
    route_duration_seconds = Column(Float, nullable=True)
    route_source = Column(String(20), nullable=True)  # mapbox | haversine

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
