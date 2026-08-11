"""Public driver stats for customer + driver UIs (trips + average rating)."""
from __future__ import annotations

from typing import Any, Dict, Optional
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.ride_enhanced import RideEnhanced
from app.models.rating import RideRating


def get_driver_public_stats(db: Session, driver_id: Optional[UUID]) -> Dict[str, Any]:
    """
    Return completed trip count and average star rating for a driver.
    Safe defaults when the driver has no history yet.
    """
    empty = {
        "driver_total_rides": 0,
        "driver_average_rating": None,
        "driver_rating_count": 0,
    }
    if not driver_id:
        return empty

    total_rides = (
        db.query(func.count(RideEnhanced.id))
        .filter(
            RideEnhanced.driver_id == driver_id,
            RideEnhanced.status == "completed",
        )
        .scalar()
        or 0
    )

    rating_row = (
        db.query(func.avg(RideRating.rating), func.count(RideRating.id))
        .filter(RideRating.driver_id == driver_id)
        .one()
    )
    avg_raw, rating_count = rating_row[0], int(rating_row[1] or 0)
    average = round(float(avg_raw), 1) if avg_raw is not None and rating_count > 0 else None

    return {
        "driver_total_rides": int(total_rides),
        "driver_average_rating": average,
        "driver_rating_count": rating_count,
    }
