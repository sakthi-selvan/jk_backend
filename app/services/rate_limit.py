"""Simple in-memory rate limiter (per-process). Replace with Redis for multi-instance."""
from __future__ import annotations

import time
from collections import defaultdict, deque
from typing import Deque, Dict, Tuple

from fastapi import HTTPException, Request, status


_buckets: Dict[str, Deque[float]] = defaultdict(deque)


def check_rate_limit(key: str, limit: int, window_seconds: int) -> Tuple[bool, str]:
    now = time.time()
    q = _buckets[key]
    while q and q[0] < now - window_seconds:
        q.popleft()
    if len(q) >= limit:
        return False, f"Rate limit exceeded. Try again in {window_seconds}s."
    q.append(now)
    return True, ""


async def rate_limit_dependency(request: Request, limit: int = 60, window_seconds: int = 60):
    client = request.client.host if request.client else "unknown"
    path = request.url.path
    ok, msg = check_rate_limit(f"{client}:{path}", limit, window_seconds)
    if not ok:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=msg)
