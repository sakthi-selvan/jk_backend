#!/usr/bin/env python3
"""Create a test driver account for testing the driver app."""

import asyncio
import sys
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent))

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from app.core.config import settings
from app.core.security import get_password_hash
from app.models.driver import Driver
from app.db.base import Base


async def create_test_driver():
    """Create a test driver account."""

    # Fix DATABASE_URL for async
    database_url = settings.DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://")

    # Create async engine
    engine = create_async_engine(database_url, echo=True)

    # Create session factory
    async_session = sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )

    async with async_session() as session:
        # Check if test driver already exists
        from sqlalchemy import select
        result = await session.execute(
            select(Driver).where(Driver.phone == "1111111111")
        )
        existing_driver = result.scalar_one_or_none()

        if existing_driver:
            print("✅ Test driver already exists!")
            print(f"   Phone: 1111111111")
            print(f"   Password: driver123")
            return

        # Create new test driver
        test_driver = Driver(
            name="Test Driver",
            phone="1111111111",
            email="testdriver@jktaxi.com",
            password_hash=get_password_hash("driver123"),
            vehicle_number="KA01AB1234",
            vehicle_type="Sedan",
            is_verified=True,
            is_online=False,
        )

        session.add(test_driver)
        await session.commit()

        print("✅ Test driver created successfully!")
        print(f"   Phone: 1111111111")
        print(f"   Password: driver123")
        print(f"   Vehicle: KA01AB1234 (Sedan)")


if __name__ == "__main__":
    asyncio.run(create_test_driver())
