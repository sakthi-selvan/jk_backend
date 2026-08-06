"""Persist driver KYC images to local disk and return public URL paths."""
from __future__ import annotations

import base64
import re
import uuid
from pathlib import Path

from fastapi import HTTPException, status

# backend/uploads — next to the app package root
UPLOAD_ROOT = Path(__file__).resolve().parents[2] / "uploads"
DRIVERS_DIR = UPLOAD_ROOT / "drivers"

_DATA_URI_RE = re.compile(
    r"^data:(image/(?:jpeg|jpg|png|webp));base64,(.+)$",
    re.IGNORECASE | re.DOTALL,
)

_EXT = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}


def ensure_upload_dirs() -> None:
    DRIVERS_DIR.mkdir(parents=True, exist_ok=True)


def save_driver_document_data_uri(driver_id: uuid.UUID | str, kind: str, data_uri: str) -> str:
    """
    Decode a data URI and save under uploads/drivers/{id}/{kind}.ext.
    Returns a public path like /uploads/drivers/{id}/license.jpg
    """
    if not data_uri or not str(data_uri).strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{kind.replace('_', ' ').title()} document is required",
        )

    raw = str(data_uri).strip()
    match = _DATA_URI_RE.match(raw)
    if match:
        mime = match.group(1).lower()
        b64 = match.group(2)
    elif raw.startswith("http://") or raw.startswith("https://") or raw.startswith("/uploads/"):
        # Already a URL/path — keep as-is (must fit VARCHAR(500))
        if len(raw) > 500:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"{kind} document URL is too long",
            )
        return raw
    else:
        # Assume raw base64 jpeg
        mime = "image/jpeg"
        b64 = raw

    try:
        binary = base64.b64decode(b64, validate=False)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid {kind} image data",
        ) from exc

    if len(binary) < 100:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{kind} image is empty or corrupt",
        )
    # Cap ~5MB decoded
    if len(binary) > 5 * 1024 * 1024:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{kind} image is too large (max 5MB)",
        )

    ensure_upload_dirs()
    folder = DRIVERS_DIR / str(driver_id)
    folder.mkdir(parents=True, exist_ok=True)
    ext = _EXT.get(mime, ".jpg")
    safe_kind = (
        "license" if "license" in kind.lower()
        else "aadhar" if "aadhar" in kind.lower()
        else "vehicle" if "vehicle" in kind.lower()
        else re.sub(r"[^a-z0-9_-]", "", kind.lower())[:32] or "doc"
    )
    filename = f"{safe_kind}{ext}"
    path = folder / filename
    path.write_bytes(binary)

    public = f"/uploads/drivers/{driver_id}/{filename}"
    if len(public) > 500:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Stored document path exceeds column limit",
        )
    return public
