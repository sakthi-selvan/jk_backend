"""Best-effort schema patches for environments that rely on create_all."""
from sqlalchemy import text
from app.db.database import engine


def ensure_runtime_columns() -> None:
    statements = [
        "ALTER TABLE rides_enhanced ADD COLUMN IF NOT EXISTS route_geometry JSON",
        "ALTER TABLE rides_enhanced ADD COLUMN IF NOT EXISTS route_duration_seconds DOUBLE PRECISION",
        "ALTER TABLE rides_enhanced ADD COLUMN IF NOT EXISTS route_source VARCHAR(20)",
        "ALTER TABLE rides_enhanced ADD COLUMN IF NOT EXISTS cancellation_fee DOUBLE PRECISION DEFAULT 0",
        "ALTER TABLE rides_enhanced ADD COLUMN IF NOT EXISTS surge_multiplier DOUBLE PRECISION DEFAULT 1",
        "ALTER TABLE rides_enhanced ADD COLUMN IF NOT EXISTS offered_driver_id UUID",
        "ALTER TABLE rides_enhanced ADD COLUMN IF NOT EXISTS offer_started_at TIMESTAMPTZ",
        "ALTER TABLE rides_enhanced ADD COLUMN IF NOT EXISTS dispatch_started_at TIMESTAMPTZ",
        "ALTER TABLE drivers ADD COLUMN IF NOT EXISTS gender VARCHAR(20)",
        "ALTER TABLE vehicle_categories ADD COLUMN IF NOT EXISTS hourly_rate DOUBLE PRECISION DEFAULT 280",
        "ALTER TABLE vehicle_categories ADD COLUMN IF NOT EXISTS platform_fee DOUBLE PRECISION DEFAULT 40",
        "ALTER TABLE vehicle_categories ADD COLUMN IF NOT EXISTS night_surcharge_percent DOUBLE PRECISION DEFAULT 15",
        "ALTER TABLE vehicle_categories ADD COLUMN IF NOT EXISTS gst_percent DOUBLE PRECISION DEFAULT 5",
        "ALTER TABLE vehicle_categories ADD COLUMN IF NOT EXISTS waiting_charge_per_min DOUBLE PRECISION DEFAULT 0",
        # Sensible defaults for existing categories (only fill NULLs)
        "UPDATE vehicle_categories SET hourly_rate = 280 WHERE hourly_rate IS NULL",
        "UPDATE vehicle_categories SET platform_fee = 40 WHERE platform_fee IS NULL",
        "UPDATE vehicle_categories SET night_surcharge_percent = 15 WHERE night_surcharge_percent IS NULL",
        "UPDATE vehicle_categories SET gst_percent = 5 WHERE gst_percent IS NULL",
        "UPDATE vehicle_categories SET waiting_charge_per_min = 0 WHERE waiting_charge_per_min IS NULL",
        # Align rental hourly with previous hard-coded non-mini/bike uplift if still at default
        "UPDATE vehicle_categories SET hourly_rate = 336 WHERE name NOT IN ('mini','bike','auto') AND hourly_rate = 280",
        """
        CREATE TABLE IF NOT EXISTS ride_ratings (
            id UUID PRIMARY KEY,
            ride_id UUID NOT NULL UNIQUE,
            user_id UUID NOT NULL,
            driver_id UUID,
            rating INTEGER NOT NULL,
            comment TEXT,
            created_at TIMESTAMPTZ DEFAULT NOW()
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS safety_events (
            id UUID PRIMARY KEY,
            ride_id UUID NOT NULL,
            user_id UUID NOT NULL,
            event_type VARCHAR(50) NOT NULL,
            latitude DOUBLE PRECISION,
            longitude DOUBLE PRECISION,
            share_token VARCHAR(64),
            meta TEXT,
            created_at TIMESTAMPTZ DEFAULT NOW()
        )
        """,
    ]
    try:
        with engine.begin() as conn:
            for sql in statements:
                conn.execute(text(sql))
    except Exception as exc:
        print(f"[schema_ensure] skipped: {exc}")
