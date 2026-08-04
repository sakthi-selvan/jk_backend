from __future__ import annotations

import json
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from sqlalchemy.orm import Session

from app.core.security import decode_token
from app.db.database import SessionLocal
from app.models.ride_enhanced import RideEnhanced
from app.services.realtime import hub

router = APIRouter()


def _open_db() -> Session:
    return SessionLocal()


@router.websocket("/ws")
async def realtime_ws(
    websocket: WebSocket,
    token: str = Query(...),
    ride_id: Optional[str] = Query(None),
):
    """Authenticated realtime channel for ride + role-scoped events."""
    payload = decode_token(token)
    if not payload or payload.get("type") != "access":
        await websocket.close(code=4401)
        return

    subject = payload.get("sub")
    role = payload.get("role")
    if not subject or role not in ("user", "driver", "admin"):
        await websocket.close(code=4401)
        return

    channels: list[str] = []
    if role == "user":
        channels.append(hub.user_channel(subject))
    elif role == "driver":
        channels.append(hub.driver_channel(subject))
        channels.append(hub.drivers_online_channel())

    last = None
    if ride_id:
        db = _open_db()
        try:
            ride = db.query(RideEnhanced).filter(RideEnhanced.id == ride_id).first()
            if not ride:
                await websocket.close(code=4404)
                return
            if role == "user" and str(ride.user_id) != subject:
                await websocket.close(code=4403)
                return
            if role == "driver" and ride.driver_id and str(ride.driver_id) != subject:
                await websocket.close(code=4403)
                return
            channels.append(hub.ride_channel(str(ride.id)))
            last = hub.get_last_location(str(ride.id))
        finally:
            db.close()

    await hub.connect(websocket, channels)
    try:
        await websocket.send_text(json.dumps({
            "event": "connected",
            "data": {"role": role, "channels": channels},
        }))
        if last:
            await websocket.send_text(json.dumps({
                "event": "driver_location",
                "data": last,
            }))

        while True:
            raw = await websocket.receive_text()
            try:
                message = json.loads(raw)
            except json.JSONDecodeError:
                continue

            if message.get("type") == "subscribe_ride":
                rid = message.get("ride_id")
                if not rid:
                    continue
                db = _open_db()
                try:
                    ride = db.query(RideEnhanced).filter(RideEnhanced.id == UUID(rid)).first()
                    if not ride:
                        continue
                    allowed = False
                    if role == "user" and str(ride.user_id) == subject:
                        allowed = True
                    if role == "driver" and (
                        ride.driver_id is None or str(ride.driver_id) == subject
                    ):
                        allowed = True
                    if allowed:
                        await hub.subscribe(websocket, [hub.ride_channel(str(ride.id))])
                        await websocket.send_text(json.dumps({
                            "event": "subscribed",
                            "data": {"ride_id": str(ride.id)},
                        }))
                        cached = hub.get_last_location(str(ride.id))
                        if cached:
                            await websocket.send_text(json.dumps({
                                "event": "driver_location",
                                "data": cached,
                            }))
                finally:
                    db.close()
    except WebSocketDisconnect:
        pass
    finally:
        await hub.disconnect(websocket)
