"""
Admin Enhanced API Routes
Admin panel for managing vehicle categories, viewing analytics, and monitoring rides
"""
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, case
from typing import List, Optional
from datetime import datetime, timedelta
from uuid import UUID

from app.core.dependencies import get_db, get_current_admin
from app.models.admin import Admin
from app.models.driver import Driver
from app.models.ride_enhanced import RideEnhanced
from app.models.vehicle_category import VehicleCategoryConfig
from app.schemas.ride_enhanced import (
    VehicleCategoryCreate,
    VehicleCategoryUpdate,
    VehicleCategoryResponse,
)

router = APIRouter(prefix="/admin", tags=["admin"])


def verify_admin(admin: Admin = Depends(get_current_admin)) -> Admin:
    """Require a valid admin JWT (Admin table), not a User.role field."""
    return admin


# ============= Vehicle Categories Management =============

@router.get("/vehicle-categories", response_model=List[VehicleCategoryResponse])
async def get_all_vehicle_categories(
    include_inactive: bool = False,
    admin = Depends(verify_admin),
    db: Session = Depends(get_db)
):
    """Get all vehicle categories (including inactive if specified)"""
    query = db.query(VehicleCategoryConfig)

    if not include_inactive:
        query = query.filter(VehicleCategoryConfig.is_active == True)

    categories = query.order_by(VehicleCategoryConfig.display_order).all()
    return categories


@router.post("/vehicle-categories", response_model=VehicleCategoryResponse, status_code=status.HTTP_201_CREATED)
async def create_vehicle_category(
    category: VehicleCategoryCreate,
    admin = Depends(verify_admin),
    db: Session = Depends(get_db)
):
    """Create a new vehicle category"""
    # Check if category with same name exists
    existing = db.query(VehicleCategoryConfig).filter(
        VehicleCategoryConfig.name == category.name
    ).first()

    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Vehicle category '{category.name}' already exists"
        )

    # Create new category
    db_category = VehicleCategoryConfig(**category.model_dump())
    db.add(db_category)
    db.commit()
    db.refresh(db_category)

    return db_category


@router.put("/vehicle-categories/{category_id}", response_model=VehicleCategoryResponse)
async def update_vehicle_category(
    category_id: UUID,
    category_update: VehicleCategoryUpdate,
    admin = Depends(verify_admin),
    db: Session = Depends(get_db)
):
    """Update a vehicle category"""
    db_category = db.query(VehicleCategoryConfig).filter(
        VehicleCategoryConfig.id == category_id
    ).first()

    if not db_category:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Vehicle category not found"
        )

    # Update fields
    update_data = category_update.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(db_category, field, value)

    db.commit()
    db.refresh(db_category)

    return db_category


@router.delete("/vehicle-categories/{category_id}")
async def delete_vehicle_category(
    category_id: UUID,
    admin = Depends(verify_admin),
    db: Session = Depends(get_db)
):
    """Delete (deactivate) a vehicle category"""
    db_category = db.query(VehicleCategoryConfig).filter(
        VehicleCategoryConfig.id == category_id
    ).first()

    if not db_category:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Vehicle category not found"
        )

    # Soft delete - just deactivate
    db_category.is_active = False
    db.commit()

    return {"message": "Vehicle category deactivated successfully"}


# ============= Analytics & Dashboard =============

@router.get("/analytics/overview")
async def get_analytics_overview(
    days: int = Query(7, ge=1, le=90),
    admin = Depends(verify_admin),
    db: Session = Depends(get_db)
):
    """Get overview analytics for the dashboard"""
    start_date = datetime.now() - timedelta(days=days)

    # Total rides by status
    rides_by_status = db.query(
        RideEnhanced.status,
        func.count(RideEnhanced.id).label('count')
    ).filter(
        RideEnhanced.created_at >= start_date
    ).group_by(RideEnhanced.status).all()

    # Total revenue
    total_revenue = db.query(
        func.sum(RideEnhanced.fare)
    ).filter(
        RideEnhanced.created_at >= start_date,
        RideEnhanced.status == 'completed'
    ).scalar() or 0.0

    # Total rides
    total_rides = db.query(func.count(RideEnhanced.id)).filter(
        RideEnhanced.created_at >= start_date
    ).scalar()

    # Completed rides
    completed_rides = db.query(func.count(RideEnhanced.id)).filter(
        RideEnhanced.created_at >= start_date,
        RideEnhanced.status == 'completed'
    ).scalar()

    # Average fare
    avg_fare = db.query(
        func.avg(RideEnhanced.fare)
    ).filter(
        RideEnhanced.created_at >= start_date,
        RideEnhanced.status == 'completed'
    ).scalar() or 0.0

    # Total distance
    total_distance = db.query(
        func.sum(RideEnhanced.distance_km)
    ).filter(
        RideEnhanced.created_at >= start_date,
        RideEnhanced.status == 'completed'
    ).scalar() or 0.0

    return {
        "period_days": days,
        "start_date": start_date.isoformat(),
        "total_rides": total_rides,
        "completed_rides": completed_rides,
        "cancelled_rides": sum(item.count for item in rides_by_status if item.status == 'cancelled'),
        "active_rides": sum(item.count for item in rides_by_status if item.status in ['pending', 'accepted', 'started']),
        "total_revenue": round(total_revenue, 2),
        "average_fare": round(avg_fare, 2),
        "total_distance_km": round(total_distance, 2),
        "completion_rate": round((completed_rides / total_rides * 100) if total_rides > 0 else 0, 2),
        "rides_by_status": {item.status: item.count for item in rides_by_status}
    }


@router.get("/analytics/trip-types")
async def get_trip_type_analytics(
    days: int = Query(7, ge=1, le=90),
    admin = Depends(verify_admin),
    db: Session = Depends(get_db)
):
    """Get analytics by trip type"""
    start_date = datetime.now() - timedelta(days=days)

    trip_analytics = db.query(
        RideEnhanced.trip_type,
        func.count(RideEnhanced.id).label('ride_count'),
        func.sum(RideEnhanced.fare).label('total_revenue'),
        func.avg(RideEnhanced.fare).label('avg_fare'),
        func.sum(RideEnhanced.distance_km).label('total_distance')
    ).filter(
        RideEnhanced.created_at >= start_date,
        RideEnhanced.status == 'completed'
    ).group_by(RideEnhanced.trip_type).all()

    return {
        "period_days": days,
        "trip_types": [
            {
                "trip_type": item.trip_type,
                "ride_count": item.ride_count,
                "total_revenue": round(item.total_revenue or 0, 2),
                "avg_fare": round(item.avg_fare or 0, 2),
                "total_distance_km": round(item.total_distance or 0, 2)
            }
            for item in trip_analytics
        ]
    }


@router.get("/analytics/vehicle-categories")
async def get_vehicle_category_analytics(
    days: int = Query(7, ge=1, le=90),
    admin = Depends(verify_admin),
    db: Session = Depends(get_db)
):
    """Get analytics by vehicle category"""
    start_date = datetime.now() - timedelta(days=days)

    vehicle_analytics = db.query(
        RideEnhanced.vehicle_category,
        func.count(RideEnhanced.id).label('ride_count'),
        func.sum(RideEnhanced.fare).label('total_revenue'),
        func.avg(RideEnhanced.fare).label('avg_fare'),
        func.sum(RideEnhanced.distance_km).label('total_distance')
    ).filter(
        RideEnhanced.created_at >= start_date,
        RideEnhanced.status == 'completed'
    ).group_by(RideEnhanced.vehicle_category).all()

    return {
        "period_days": days,
        "vehicle_categories": [
            {
                "vehicle_category": item.vehicle_category,
                "ride_count": item.ride_count,
                "total_revenue": round(item.total_revenue or 0, 2),
                "avg_fare": round(item.avg_fare or 0, 2),
                "total_distance_km": round(item.total_distance or 0, 2)
            }
            for item in vehicle_analytics
        ]
    }


@router.get("/analytics/hourly-distribution")
async def get_hourly_ride_distribution(
    days: int = Query(7, ge=1, le=90),
    admin = Depends(verify_admin),
    db: Session = Depends(get_db)
):
    """Get ride distribution by hour of day"""
    start_date = datetime.now() - timedelta(days=days)

    hourly_data = db.query(
        func.extract('hour', RideEnhanced.created_at).label('hour'),
        func.count(RideEnhanced.id).label('ride_count'),
        func.sum(RideEnhanced.fare).label('total_revenue')
    ).filter(
        RideEnhanced.created_at >= start_date,
        RideEnhanced.status == 'completed'
    ).group_by('hour').order_by('hour').all()

    return {
        "period_days": days,
        "hourly_distribution": [
            {
                "hour": int(item.hour),
                "ride_count": item.ride_count,
                "total_revenue": round(item.total_revenue or 0, 2)
            }
            for item in hourly_data
        ]
    }


@router.get("/analytics/preferences")
async def get_preference_analytics(
    days: int = Query(7, ge=1, le=90),
    admin = Depends(verify_admin),
    db: Session = Depends(get_db)
):
    """Get analytics on ride preferences usage"""
    start_date = datetime.now() - timedelta(days=days)

    all_rides = db.query(RideEnhanced).filter(
        RideEnhanced.created_at >= start_date
    ).all()

    total_rides = len(all_rides)

    if total_rides == 0:
        return {
            "period_days": days,
            "total_rides": 0,
            "preferences": []
        }

    # Count preference usage
    preferences_count = {
        "ac_preferred": 0,
        "pet_friendly": 0,
        "silent_ride": 0,
        "extra_luggage": 0,
        "wheelchair_support": 0
    }

    for ride in all_rides:
        if ride.preferences:
            for pref, enabled in ride.preferences.items():
                if enabled and pref in preferences_count:
                    preferences_count[pref] += 1

    return {
        "period_days": days,
        "total_rides": total_rides,
        "preferences": [
            {
                "preference": pref,
                "usage_count": count,
                "usage_percentage": round((count / total_rides * 100), 2)
            }
            for pref, count in preferences_count.items()
        ]
    }


@router.get("/rides/recent")
async def get_recent_rides(
    limit: int = Query(50, ge=1, le=200),
    status_filter: Optional[str] = None,
    admin = Depends(verify_admin),
    db: Session = Depends(get_db)
):
    """Get recent rides for monitoring"""
    query = db.query(RideEnhanced)

    if status_filter:
        query = query.filter(RideEnhanced.status == status_filter)

    rides = query.order_by(RideEnhanced.created_at.desc()).limit(limit).all()

    return {
        "total": len(rides),
        "status_filter": status_filter,
        "rides": [
            {
                "id": str(ride.id),
                "user_id": str(ride.user_id),
                "driver_id": str(ride.driver_id) if ride.driver_id else None,
                "trip_type": ride.trip_type,
                "vehicle_category": ride.vehicle_category,
                "status": ride.status,
                "fare": ride.fare,
                "distance_km": ride.distance_km,
                "pickup_location": ride.pickup_location,
                "dropoff_location": ride.dropoff_location,
                "otp_verified": ride.otp_verified,
                "is_scheduled": ride.is_scheduled,
                "scheduled_datetime": ride.scheduled_datetime.isoformat() if ride.scheduled_datetime else None,
                "created_at": ride.created_at.isoformat(),
                "started_at": ride.started_at.isoformat() if ride.started_at else None,
                "completed_at": ride.completed_at.isoformat() if ride.completed_at else None
            }
            for ride in rides
        ]
    }


@router.get("/analytics/revenue-forecast")
async def get_revenue_forecast(
    admin = Depends(verify_admin),
    db: Session = Depends(get_db)
):
    """Get revenue trends and forecast"""
    # Last 30 days daily revenue
    start_date = datetime.now() - timedelta(days=30)

    daily_revenue = db.query(
        func.date(RideEnhanced.created_at).label('date'),
        func.count(RideEnhanced.id).label('ride_count'),
        func.sum(RideEnhanced.fare).label('revenue')
    ).filter(
        RideEnhanced.created_at >= start_date,
        RideEnhanced.status == 'completed'
    ).group_by('date').order_by('date').all()

    # Calculate averages
    total_revenue = sum(item.revenue for item in daily_revenue if item.revenue)
    total_rides = sum(item.ride_count for item in daily_revenue)

    avg_daily_revenue = total_revenue / 30 if total_revenue > 0 else 0
    avg_daily_rides = total_rides / 30 if total_rides > 0 else 0

    return {
        "last_30_days": {
            "total_revenue": round(total_revenue, 2),
            "total_rides": total_rides,
            "avg_daily_revenue": round(avg_daily_revenue, 2),
            "avg_daily_rides": round(avg_daily_rides, 2)
        },
        "daily_data": [
            {
                "date": item.date.isoformat(),
                "ride_count": item.ride_count,
                "revenue": round(item.revenue or 0, 2)
            }
            for item in daily_revenue
        ],
        "forecast_next_30_days": {
            "estimated_revenue": round(avg_daily_revenue * 30, 2),
            "estimated_rides": round(avg_daily_rides * 30)
        }
    }


@router.get("/drivers/earnings")
async def get_all_drivers_earnings(
    admin = Depends(verify_admin),
    db: Session = Depends(get_db)
):
    """Get earnings for all drivers - admin view"""
    drivers = db.query(Driver).filter(Driver.is_active == True).all()

    now = datetime.utcnow()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = today_start - timedelta(days=now.weekday())
    month_start = today_start.replace(day=1)

    results = []
    for driver in drivers:
        completed = db.query(RideEnhanced).filter(
            RideEnhanced.driver_id == driver.id,
            RideEnhanced.status == "completed"
        ).all()

        today_rides = [r for r in completed if r.created_at and r.created_at.replace(tzinfo=None) >= today_start]
        week_rides = [r for r in completed if r.created_at and r.created_at.replace(tzinfo=None) >= week_start]
        month_rides = [r for r in completed if r.created_at and r.created_at.replace(tzinfo=None) >= month_start]

        results.append({
            "driver_id": str(driver.id),
            "name": driver.name,
            "phone": driver.phone,
            "is_online": driver.is_online,
            "today": {"earnings": round(sum(r.fare for r in today_rides), 2), "rides": len(today_rides)},
            "week": {"earnings": round(sum(r.fare for r in week_rides), 2), "rides": len(week_rides)},
            "month": {"earnings": round(sum(r.fare for r in month_rides), 2), "rides": len(month_rides)},
            "total": {"earnings": round(sum(r.fare for r in completed), 2), "rides": len(completed)},
        })

    results.sort(key=lambda x: x["month"]["earnings"], reverse=True)
    return results
