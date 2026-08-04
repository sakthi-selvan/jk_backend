#!/usr/bin/env python3
"""
Manual script to cancel a ride
Usage: python cancel_ride.py <ride_id>
"""
import sys
import os

# Add backend directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.db.database import SessionLocal
from app.models.ride_enhanced import RideEnhanced

def cancel_ride(ride_id: str):
    db = SessionLocal()
    try:
        # Find the ride
        ride = db.query(RideEnhanced).filter(RideEnhanced.id == ride_id).first()

        if not ride:
            print(f"❌ Ride not found: {ride_id}")
            return False

        print(f"Found ride: {ride.id}")
        print(f"Current status: {ride.status}")
        print(f"Driver ID: {ride.driver_id}")
        print(f"Pickup: {ride.pickup_location}")

        # Cancel the ride
        ride.status = "cancelled"
        ride.driver_id = None
        ride.cancellation_reason = "Manual cancellation - Admin"

        db.commit()

        print("\n✅ Ride cancelled successfully!")
        print(f"New status: {ride.status}")
        print(f"Driver ID: {ride.driver_id}")
        return True

    except Exception as e:
        print(f"❌ Error: {e}")
        db.rollback()
        return False
    finally:
        db.close()

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python cancel_ride.py <ride_id>")
        print("\nExample:")
        print("python cancel_ride.py f64aa3f8-7ba1-489c-9247-5b69ebe7067d")
        sys.exit(1)

    ride_id = sys.argv[1]
    cancel_ride(ride_id)
