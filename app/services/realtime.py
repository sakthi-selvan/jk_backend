"""In-process realtime hub for ride status and driver location events.

Clients subscribe via WebSocket. For multi-instance deploy, back with Redis pub/sub.
"""
from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from typing import Any, DefaultDict, Dict, Optional, Set

from fastapi import WebSocket


class RealtimeHub:
    def __init__(self) -> None:
        # channel -> websockets
        self._channels: DefaultDict[str, Set[WebSocket]] = defaultdict(set)
        self._lock = asyncio.Lock()
        # ride_id -> last location payload (sequence ordered)
        self._last_locations: Dict[str, Dict[str, Any]] = {}

    @staticmethod
    def ride_channel(ride_id: str) -> str:
        return f"ride:{ride_id}"

    @staticmethod
    def driver_channel(driver_id: str) -> str:
        return f"driver:{driver_id}"

    @staticmethod
    def user_channel(user_id: str) -> str:
        return f"user:{user_id}"

    @staticmethod
    def drivers_online_channel() -> str:
        return "drivers:online"

    async def connect(self, websocket: WebSocket, channels: list[str]) -> None:
        await websocket.accept()
        async with self._lock:
            for channel in channels:
                self._channels[channel].add(websocket)

    async def disconnect(self, websocket: WebSocket) -> None:
        async with self._lock:
            empty = []
            for channel, sockets in self._channels.items():
                sockets.discard(websocket)
                if not sockets:
                    empty.append(channel)
            for channel in empty:
                del self._channels[channel]

    async def subscribe(self, websocket: WebSocket, channels: list[str]) -> None:
        async with self._lock:
            for channel in channels:
                self._channels[channel].add(websocket)

    async def publish(self, channel: str, event: str, data: Dict[str, Any]) -> None:
        payload = json.dumps({"event": event, "data": data})
        async with self._lock:
            sockets = list(self._channels.get(channel, set()))
        dead: list[WebSocket] = []
        for ws in sockets:
            try:
                await ws.send_text(payload)
            except Exception:
                dead.append(ws)
        if dead:
            async with self._lock:
                for ws in dead:
                    for sockets in self._channels.values():
                        sockets.discard(ws)

    async def publish_ride(self, ride_id: str, event: str, data: Dict[str, Any]) -> None:
        await self.publish(self.ride_channel(str(ride_id)), event, data)

    async def publish_user(self, user_id: str, event: str, data: Dict[str, Any]) -> None:
        await self.publish(self.user_channel(str(user_id)), event, data)

    async def publish_driver(self, driver_id: str, event: str, data: Dict[str, Any]) -> None:
        await self.publish(self.driver_channel(str(driver_id)), event, data)

    def remember_location(self, ride_id: str, payload: Dict[str, Any]) -> bool:
        """Store location if sequence is newer. Returns True if accepted."""
        key = str(ride_id)
        incoming_seq = payload.get("sequence")
        existing = self._last_locations.get(key)
        if existing is not None and incoming_seq is not None:
            prev_seq = existing.get("sequence")
            if prev_seq is not None and incoming_seq <= prev_seq:
                return False
        self._last_locations[key] = payload
        return True

    def get_last_location(self, ride_id: str) -> Optional[Dict[str, Any]]:
        return self._last_locations.get(str(ride_id))


hub = RealtimeHub()
