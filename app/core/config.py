from pydantic_settings import BaseSettings
from typing import List, Optional
import json


class Settings(BaseSettings):
    # App Config
    APP_NAME: str = "JK Taxi API"
    DEBUG: bool = False
    API_VERSION: str = "v1"

    # Database
    DATABASE_URL: str

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # JWT — short-lived access tokens for production safety
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # OTP — never ship with ALLOW_STATIC_OTP=true in production
    ALLOW_STATIC_OTP: bool = False
    STATIC_OTP: str = "123456"
    OTP_LENGTH: int = 4
    OTP_TTL_SECONDS: int = 300
    OTP_MAX_ATTEMPTS: int = 5
    OTP_RATE_LIMIT_COUNT: int = 5
    OTP_RATE_LIMIT_WINDOW_SECONDS: int = 600

    # TeleSign — load only from environment (no defaults)
    TELESIGN_CUSTOMER_ID: Optional[str] = None
    TELESIGN_API_KEY: Optional[str] = None

    # Razorpay — load only from environment (no defaults)
    RAZORPAY_KEY_ID: Optional[str] = None
    RAZORPAY_KEY_SECRET: Optional[str] = None

    # Force-complete: drivers may finish early when customer changes plans
    ALLOW_FORCE_COMPLETE: bool = True
    # Max distance from drop-off to allow normal completion (km)
    COMPLETE_DROP_OFF_RADIUS_KM: float = 1.5

    # Mapbox (server-side Directions for fare/ETA). Prefer a pk. public token.
    MAPBOX_ACCESS_TOKEN: Optional[str] = None
    # Optional dedicated public token for mobile MapViews (falls back to MAPBOX_ACCESS_TOKEN if pk.).
    MAPBOX_PUBLIC_TOKEN: Optional[str] = None
    MAPBOX_ROUTING_PROFILE: str = "driving-traffic"
    MIN_FARE_DISTANCE_KM: float = 1.0
    FALLBACK_SPEED_KMH: float = 30.0

    # Service area bbox: min_lng,min_lat,max_lng,max_lat (default ~ Tamil Nadu)
    SERVICE_AREA_ENABLED: bool = True
    SERVICE_AREA_BBOX: str = "76.0,8.0,80.5,13.6"

    # Dispatch — sequential exclusive offers (one driver at a time)
    SEQUENTIAL_DISPATCH: bool = True
    OFFER_TTL_SECONDS: int = 300  # overall search timeout
    DRIVER_OFFER_SECONDS: int = 25  # exclusive window per driver
    STALE_GPS_SECONDS: int = 120
    ENFORCE_VEHICLE_MATCH: bool = True
    REQUIRE_DRIVER_DOCS: bool = False
    REQUIRE_AADHAR_DOCUMENT: bool = False
    REQUIRE_DRIVER_VERIFIED: bool = True
    SCHEDULED_RELEASE_MINUTES: int = 30
    SCHEDULED_LATE_GRACE_MINUTES: int = 15
    DISPATCH_SWEEP_SECONDS: int = 10
    MAX_PICKUP_ETA_MINUTES: float = 30.0

    # Pricing / cancellations
    SURGE_PEAK_MULTIPLIER: float = 1.2
    CANCEL_FEE_ACCEPTED: float = 30.0
    CANCEL_FEE_STARTED: float = 50.0

    # CORS
    ALLOWED_ORIGINS: str = '["http://localhost:3000","http://localhost:5173","http://localhost:5174","http://localhost:8081","http://localhost:19000","http://localhost:19006","https://jktaxitamilnadu.com","https://admin.jktaxitamilnadu.com"]'

    def client_mapbox_token(self) -> Optional[str]:
        """Public pk. token safe to send to apps after login (never return sk. secrets)."""
        for candidate in (self.MAPBOX_PUBLIC_TOKEN, self.MAPBOX_ACCESS_TOKEN):
            token = (candidate or "").strip()
            if token.startswith("pk."):
                return token
        return None

    @property
    def allowed_origins_list(self) -> List[str]:
        """Parse ALLOWED_ORIGINS from JSON string to list"""
        try:
            return json.loads(self.ALLOWED_ORIGINS)
        except Exception:
            return ["http://localhost:3000", "http://localhost:8081"]

    class Config:
        env_file = ".env"
        case_sensitive = True
        extra = "ignore"


settings = Settings()
