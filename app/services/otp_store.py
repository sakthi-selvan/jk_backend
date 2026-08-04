"""In-memory OTP store with TTL, attempt limits, and send rate limiting.

For multi-instance production, replace with Redis.
"""
from __future__ import annotations

import random
import time
from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple

from app.core.config import settings


@dataclass
class OTPRecord:
    code: str
    expires_at: float
    attempts: int = 0


@dataclass
class RateBucket:
    timestamps: list = field(default_factory=list)


_otp_by_phone: Dict[str, OTPRecord] = {}
_send_rate: Dict[str, RateBucket] = {}


def _now() -> float:
    return time.time()


def generate_otp(length: Optional[int] = None) -> str:
    length = length or settings.OTP_LENGTH
    low = 10 ** (length - 1)
    high = (10 ** length) - 1
    return str(random.randint(low, high))


def check_send_allowed(phone: str) -> Tuple[bool, str]:
    bucket = _send_rate.setdefault(phone, RateBucket())
    cutoff = _now() - settings.OTP_RATE_LIMIT_WINDOW_SECONDS
    bucket.timestamps = [t for t in bucket.timestamps if t >= cutoff]
    if len(bucket.timestamps) >= settings.OTP_RATE_LIMIT_COUNT:
        return False, "Too many OTP requests. Please try again later."
    return True, ""


def record_send(phone: str) -> None:
    bucket = _send_rate.setdefault(phone, RateBucket())
    bucket.timestamps.append(_now())


def store_otp(phone: str, code: str) -> None:
    _otp_by_phone[phone] = OTPRecord(
        code=code,
        expires_at=_now() + settings.OTP_TTL_SECONDS,
        attempts=0,
    )


def verify_and_consume(phone: str, code: str) -> Tuple[bool, str]:
    record = _otp_by_phone.get(phone)
    if not record:
        return False, "OTP expired or not found. Request a new one."

    if _now() > record.expires_at:
        _otp_by_phone.pop(phone, None)
        return False, "OTP expired. Request a new one."

    if record.attempts >= settings.OTP_MAX_ATTEMPTS:
        _otp_by_phone.pop(phone, None)
        return False, "Too many invalid attempts. Request a new OTP."

    if record.code != code:
        record.attempts += 1
        remaining = settings.OTP_MAX_ATTEMPTS - record.attempts
        if remaining <= 0:
            _otp_by_phone.pop(phone, None)
            return False, "Too many invalid attempts. Request a new OTP."
        return False, f"Invalid OTP. {remaining} attempts remaining."

    _otp_by_phone.pop(phone, None)
    return True, ""
