"""Best-effort schema patches for environments that rely on create_all."""
from sqlalchemy import text
from app.db.database import engine

# Default fleet (no premium). Inserted only when missing so admin edits are preserved.
_DEFAULT_CATEGORIES = [
    {
        "name": "bike",
        "display_name": "Bike Taxi",
        "description": "Fast & affordable bike taxi",
        "seater_capacity": 1,
        "base_fare": 23.0,
        "per_km_rate": 13.0,
        "hourly_rate": 150.0,
        "example_vehicles": '["Pulsar", "Apache", "Activa"]',
        "features": '["1 Seater", "Fastest", "Helmet"]',
        "icon_name": "bicycle-outline",
        "display_order": 1,
    },
    {
        "name": "auto",
        "display_name": "Auto Rickshaw",
        "description": "Quick auto rickshaw rides",
        "seater_capacity": 3,
        "base_fare": 80.0,
        "per_km_rate": 21.0,
        "hourly_rate": 200.0,
        "example_vehicles": '["Bajaj RE", "Piaggio Ape"]',
        "features": '["3 Seater", "Budget", "No bargaining"]',
        "icon_name": "bus-outline",
        "display_order": 2,
    },
    {
        "name": "mini",
        "display_name": "Mini / Hatchback",
        "description": "Small car for city rides",
        "seater_capacity": 4,
        "base_fare": 100.0,
        "per_km_rate": 20.0,
        "hourly_rate": 280.0,
        "example_vehicles": '["WagonR", "Alto", "Tiago"]',
        "features": '["AC", "4 Seater", "Budget Friendly"]',
        "icon_name": "car-outline",
        "display_order": 3,
    },
    {
        "name": "sedan",
        "display_name": "Sedan",
        "description": "Comfortable sedan rides",
        "seater_capacity": 4,
        "base_fare": 100.0,
        "per_km_rate": 23.0,
        "hourly_rate": 336.0,
        "example_vehicles": '["Dzire", "Etios", "Aura"]',
        "features": '["AC", "4 Seater", "Comfortable"]',
        "icon_name": "car-sport-outline",
        "display_order": 4,
    },
    {
        "name": "suv",
        "display_name": "SUV",
        "description": "Spacious 6-7 seater",
        "seater_capacity": 7,
        "base_fare": 150.0,
        "per_km_rate": 26.0,
        "hourly_rate": 336.0,
        "example_vehicles": '["Ertiga", "Innova", "Marazzo"]',
        "features": '["AC", "6-7 Seater", "Spacious"]',
        "icon_name": "car-outline",
        "display_order": 5,
    },
]


def ensure_default_vehicle_categories() -> None:
    """Seed bike/auto/mini/sedan/suv if missing; keep premium inactive."""
    import uuid
    from app.db.database import SessionLocal
    from app.models.vehicle_category import VehicleCategoryConfig

    db = SessionLocal()
    try:
        existing = {
            row.name: row
            for row in db.query(VehicleCategoryConfig).all()
        }
        for cat in _DEFAULT_CATEGORIES:
            row = existing.get(cat["name"])
            if row is None:
                db.add(
                    VehicleCategoryConfig(
                        id=uuid.uuid4(),
                        name=cat["name"],
                        display_name=cat["display_name"],
                        description=cat["description"],
                        seater_capacity=cat["seater_capacity"],
                        base_fare=cat["base_fare"],
                        per_km_rate=cat["per_km_rate"],
                        hourly_rate=cat["hourly_rate"],
                        platform_fee=40.0,
                        night_surcharge_percent=15.0,
                        gst_percent=5.0,
                        waiting_charge_per_min=0.0,
                        example_vehicles=__import__("json").loads(cat["example_vehicles"]),
                        features=__import__("json").loads(cat["features"]),
                        icon_name=cat["icon_name"],
                        is_active=True,
                        display_order=cat["display_order"],
                    )
                )
            else:
                row.is_active = True
        premium = existing.get("premium")
        if premium is not None:
            premium.is_active = False
        db.commit()
        print("[schema_ensure] vehicle categories ensured")
    except Exception as exc:
        db.rollback()
        print(f"[schema_ensure] vehicle categories skipped: {exc}")
    finally:
        db.close()


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
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS age INTEGER",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS gender VARCHAR(20)",
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

    ensure_default_vehicle_categories()
