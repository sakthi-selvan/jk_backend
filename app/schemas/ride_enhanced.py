from pydantic import BaseModel, Field
from typing import Optional, List, Dict
from datetime import datetime
from uuid import UUID
from enum import Enum


class TripType(str, Enum):
    ONE_WAY = "one_way"
    RENTAL = "rental"
    OUTSTATION = "outstation"


class VehicleCategory(str, Enum):
    AUTO = "auto"
    BIKE = "bike"
    MINI = "mini"
    SEDAN = "sedan"
    SUV = "suv"


class RideStatus(str, Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    STARTED = "started"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class PaymentStatus(str, Enum):
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"


class StopLocation(BaseModel):
    address: str
    latitude: float
    longitude: float


class RidePreferences(BaseModel):
    ac_preferred: bool = False
    pet_friendly: bool = False
    silent_ride: bool = False
    extra_luggage: bool = False
    wheelchair_support: bool = False
    women_driver: bool = False


class VehicleCategoryCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=50)
    display_name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = None
    seater_capacity: int = Field(..., ge=1, le=20)
    base_fare: float = Field(..., ge=0)
    per_km_rate: float = Field(..., ge=0)
    hourly_rate: float = Field(default=280.0, ge=0)
    platform_fee: float = Field(default=40.0, ge=0)
    night_surcharge_percent: float = Field(default=15.0, ge=0, le=100)
    gst_percent: float = Field(default=5.0, ge=0, le=100)
    waiting_charge_per_min: float = Field(default=0.0, ge=0)
    example_vehicles: List[str] = Field(default_factory=list)
    features: List[str] = Field(default_factory=list)
    icon_name: str = Field(default="car-outline")
    is_active: bool = True
    display_order: int = Field(default=999)


class VehicleCategoryUpdate(BaseModel):
    display_name: Optional[str] = None
    description: Optional[str] = None
    seater_capacity: Optional[int] = Field(None, ge=1, le=20)
    base_fare: Optional[float] = Field(None, ge=0)
    per_km_rate: Optional[float] = Field(None, ge=0)
    hourly_rate: Optional[float] = Field(None, ge=0)
    platform_fee: Optional[float] = Field(None, ge=0)
    night_surcharge_percent: Optional[float] = Field(None, ge=0, le=100)
    gst_percent: Optional[float] = Field(None, ge=0, le=100)
    waiting_charge_per_min: Optional[float] = Field(None, ge=0)
    example_vehicles: Optional[List[str]] = None
    features: Optional[List[str]] = None
    icon_name: Optional[str] = None
    is_active: Optional[bool] = None
    display_order: Optional[int] = None


class FareBreakdown(BaseModel):
    base_fare: float
    distance_fare: float
    platform_fee: float
    gst: float
    toll_charges: float = 0.0
    night_charges: float = 0.0
    waiting_charges: float = 0.0
    total: float
    distance_km: float = 0.0
    duration_minutes: float = 0.0
    route_source: Optional[str] = None
    surge_multiplier: float = 1.0
    rental_hours: Optional[int] = None
    included_km: Optional[float] = None


class BookingCreate(BaseModel):
    # Trip Details
    trip_type: TripType = TripType.ONE_WAY
    vehicle_category: VehicleCategory = VehicleCategory.MINI
    rental_hours: Optional[int] = Field(default=1, ge=1, le=12)

    # Locations
    pickup_location: str
    dropoff_location: Optional[str] = None
    pickup_lat: float
    pickup_lng: float
    dropoff_lat: Optional[float] = None
    dropoff_lng: Optional[float] = None
    stops: List[StopLocation] = []

    # Timing
    is_scheduled: bool = False
    scheduled_datetime: Optional[datetime] = None

    # Booking For Someone Else
    booking_for_self: bool = True
    passenger_name: Optional[str] = None
    passenger_phone: Optional[str] = None
    passenger_notes: Optional[str] = None

    # Preferences
    preferences: RidePreferences = RidePreferences()
    driver_notes: Optional[str] = None

    # Payment
    payment_method: str = "cash"


class RideEnhancedResponse(BaseModel):
    id: UUID
    user_id: UUID
    driver_id: Optional[UUID] = None

    # Trip Details
    trip_type: str
    vehicle_category: str

    # Locations
    pickup_location: str
    dropoff_location: Optional[str]
    pickup_lat: float
    pickup_lng: float
    dropoff_lat: Optional[float]
    dropoff_lng: Optional[float]
    stops: List[Dict] = []

    # Timing
    is_scheduled: bool
    scheduled_datetime: Optional[datetime]

    # Booking For Someone Else
    booking_for_self: bool
    passenger_name: Optional[str]
    passenger_phone: Optional[str]
    passenger_notes: Optional[str]

    # Preferences
    preferences: Dict = {}
    driver_notes: Optional[str]

    # OTP — may be omitted/null for driver-facing responses
    ride_otp: Optional[str] = None
    otp_verified: bool

    # Status & Tracking
    status: str
    rejection_count: int = 0
    cancellation_reason: Optional[str] = None

    # Fare
    base_fare: float
    distance_fare: float
    platform_fee: float
    gst: float
    toll_charges: float
    night_charges: float
    waiting_charges: float
    fare: float

    # Payment
    payment_status: str
    payment_method: str
    transaction_id: Optional[str]

    # Distance & ETA
    distance_km: float
    eta_minutes: int
    route_geometry: Optional[List] = None
    route_duration_seconds: Optional[float] = None
    route_source: Optional[str] = None

    # Customer info (populated for driver-facing responses)
    customer_name: Optional[str] = None
    customer_phone: Optional[str] = None

    # Driver info (populated when driver accepts)
    driver_name: Optional[str] = None
    driver_phone: Optional[str] = None
    driver_vehicle_number: Optional[str] = None
    driver_vehicle_type: Optional[str] = None
    driver_vehicle_image: Optional[str] = None
    driver_total_rides: Optional[int] = None
    driver_average_rating: Optional[float] = None
    driver_rating_count: Optional[int] = None

    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class VerifyOTPRequest(BaseModel):
    ride_id: UUID
    otp: str = Field(..., min_length=4, max_length=4)


class VehicleCategoryResponse(BaseModel):
    id: UUID
    name: str
    display_name: str
    description: Optional[str]
    seater_capacity: int
    base_fare: float
    per_km_rate: float
    hourly_rate: float = 280.0
    platform_fee: float = 40.0
    night_surcharge_percent: float = 15.0
    gst_percent: float = 5.0
    waiting_charge_per_min: float = 0.0
    example_vehicles: List[str]
    features: List[str]
    icon_name: Optional[str]
    is_active: bool
    display_order: int

    class Config:
        from_attributes = True


class SavedPlaceRequest(BaseModel):
    place_type: str = Field(..., pattern="^(home|work)$")  # home or work
    address: str
    latitude: float
    longitude: float
