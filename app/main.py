from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import asyncio
from app.core.config import settings
from app.db.base import Base
from app.db.database import engine, SessionLocal
from app.api.auth import routes as auth_routes
from app.api.user import routes as user_routes
from app.api.driver import routes as driver_routes
from app.api.booking import routes as booking_routes
from app.api.admin import routes as admin_routes
from app.api.booking_enhanced import routes as booking_enhanced_routes
from app.api.driver_enhanced import routes as driver_enhanced_routes
from app.api.user_enhanced import routes as user_enhanced_routes
from app.api.admin_enhanced import routes as admin_enhanced_routes
from app.api.realtime import routes as realtime_routes
from app.api.safety import routes as safety_routes
from app.services.rate_limit import check_rate_limit
from app.services.document_storage import UPLOAD_ROOT, ensure_upload_dirs

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.API_VERSION,
    debug=settings.DEBUG,
    docs_url="/docs" if settings.DEBUG else None,
    redoc_url="/redoc" if settings.DEBUG else None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)

# Driver KYC images (license / aadhar) — public read for admin preview
ensure_upload_dirs()
app.mount("/uploads", StaticFiles(directory=str(UPLOAD_ROOT)), name="uploads")

_dispatch_task = None


async def _dispatch_sweep_loop():
    """Advance timed-out exclusive offers + expire overall search TTL."""
    from app.services.dispatch import (
        expire_stale_pending_rides,
        advance_timed_out_offers,
        emit_advance_events,
        assign_next_offer,
        emit_ride_offer,
        scheduled_ready_for_dispatch,
        begin_dispatch,
    )
    from app.models.ride_enhanced import RideEnhanced
    from app.services.realtime import hub

    while True:
        try:
            db = SessionLocal()
            try:
                # 1) Advance per-driver exclusive timeouts
                events = await advance_timed_out_offers(db)
                await emit_advance_events(events)

                # 2) Pick up pending rides with no current offer (new / waiting)
                waiting = (
                    db.query(RideEnhanced)
                    .filter(
                        RideEnhanced.status == "pending",
                        RideEnhanced.driver_id.is_(None),
                        RideEnhanced.offered_driver_id.is_(None),
                    )
                    .all()
                )
                for ride in waiting:
                    if not scheduled_ready_for_dispatch(ride):
                        continue
                    if not getattr(ride, "dispatch_started_at", None):
                        begin_dispatch(ride)
                    driver = assign_next_offer(db, ride)
                    if driver:
                        db.commit()
                        db.refresh(ride)
                        await emit_ride_offer(ride, driver)

                # 3) Expire overall search TTL
                expired = expire_stale_pending_rides(db)
                for ride in expired:
                    data = {
                        "ride_id": str(ride.id),
                        "status": "cancelled",
                        "user_id": str(ride.user_id),
                        "reason": ride.cancellation_reason or "offer_ttl_expired",
                    }
                    await hub.publish_ride(str(ride.id), "ride_cancelled", data)
                    await hub.publish_user(str(ride.user_id), "ride_cancelled", data)
                    await hub.publish(hub.drivers_online_channel(), "ride_cancelled", data)
            finally:
                db.close()
        except Exception as exc:
            print(f"[dispatch_sweep] error: {exc}")
        await asyncio.sleep(settings.DISPATCH_SWEEP_SECONDS)


@app.middleware("http")
async def global_rate_limit(request, call_next):
    # Lightweight global cap; auth OTP has its own tighter limit
    client = request.client.host if request.client else "unknown"
    ok, msg = check_rate_limit(f"global:{client}", limit=120, window_seconds=60)
    if not ok:
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=429, content={"detail": msg})
    return await call_next(request)


@app.on_event("startup")
async def startup():
    global _dispatch_task
    import app.models.user
    import app.models.driver
    import app.models.admin
    import app.models.ride
    import app.models.ride_enhanced
    import app.models.vehicle_category
    import app.models.ride_cancellation
    import app.models.rating

    # Safe if tables already exist — needed so empty DBs get vehicle_categories before seed.
    Base.metadata.create_all(bind=engine)
    try:
        from app.services.schema_ensure import ensure_runtime_columns, ensure_default_vehicle_categories
        ensure_runtime_columns()
        # Explicit seed: hardcoded defaults only when category rows are missing.
        ensure_default_vehicle_categories()
    except Exception as exc:
        print(f"[startup] schema_ensure failed: {exc}")

    _dispatch_task = asyncio.create_task(_dispatch_sweep_loop())


@app.on_event("shutdown")
async def shutdown():
    global _dispatch_task
    if _dispatch_task:
        _dispatch_task.cancel()
        try:
            await _dispatch_task
        except Exception:
            pass


# Health check
@app.get("/health")
async def health_check():
    return {"status": "healthy", "app": settings.APP_NAME}

# Include routers
app.include_router(auth_routes.router, prefix="/api/auth", tags=["Authentication"])
app.include_router(user_routes.router, prefix="/api/user", tags=["User"])
app.include_router(driver_routes.router, prefix="/api/driver", tags=["Driver"])
app.include_router(booking_routes.router, prefix="/api/bookings", tags=["Booking"])
app.include_router(admin_routes.router, prefix="/api/admin", tags=["Admin"])

# Enhanced v2 routers with full features
app.include_router(booking_enhanced_routes.router, prefix="/api/v2/bookings", tags=["Booking Enhanced"])
app.include_router(driver_enhanced_routes.router, prefix="/api/v2/driver", tags=["Driver Enhanced"])
app.include_router(user_enhanced_routes.router, prefix="/api/v2/user", tags=["User Enhanced"])
app.include_router(admin_enhanced_routes.router, prefix="/api/v2/admin", tags=["Admin Enhanced"])
app.include_router(realtime_routes.router, prefix="/api/realtime", tags=["Realtime"])
app.include_router(safety_routes.router, prefix="/api/v2/safety", tags=["Safety"])

@app.get("/")
async def root():
    return {
        "message": "Welcome to JK Taxi API",
        "version": settings.API_VERSION,
        "docs": "/docs" if settings.DEBUG else None,
        "redoc": "/redoc" if settings.DEBUG else None,
        "realtime": "/api/realtime/ws",
    }
