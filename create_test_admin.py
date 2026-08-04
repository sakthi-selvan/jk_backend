#!/usr/bin/env python3
"""Create a test admin account for testing the admin dashboard."""

import asyncio
import sys
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent))

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from app.core.config import settings
from app.core.security import get_password_hash
from app.models.admin import Admin
from app.db.base import Base


async def create_test_admin():
    """Create a test admin account."""

    # Fix DATABASE_URL for async
    database_url = settings.DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://")

    # Create async engine
    engine = create_async_engine(database_url, echo=True)

    # Create session factory
    async_session = sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )

    async with async_session() as session:
        # Check if test admin already exists
        from sqlalchemy import select
        result = await session.execute(
            select(Admin).where(Admin.username == "admin")
        )
        existing_admin = result.scalar_one_or_none()

        if existing_admin:
            print("✅ Test admin already exists!")
            print(f"   Username: admin")
            print(f"   Password: admin123")
            return

        # Create new test admin
        test_admin = Admin(
            username="admin",
            email="admin@jktaxi.com",
            password_hash=get_password_hash("admin123"),
            is_active=True,
        )

        session.add(test_admin)
        await session.commit()

        print("✅ Test admin created successfully!")
        print(f"   Username: admin")
        print(f"   Password: admin123")
        print(f"   Email: admin@jktaxi.com")


if __name__ == "__main__":
    asyncio.run(create_test_admin())
