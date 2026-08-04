from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.core.dependencies import get_db, get_current_user
from app.schemas.ride_enhanced import SavedPlaceRequest
from app.models.user import User

router = APIRouter()


@router.get("/saved-places")
async def get_saved_places(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get user's saved places"""
    saved_places = current_user.saved_places or {}
    return saved_places


@router.put("/saved-places/{place_type}")
async def save_place(
    place_type: str,
    place_data: SavedPlaceRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Save or update a place (home or work)"""
    if place_type not in ["home", "work"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="place_type must be 'home' or 'work'"
        )

    # Get current saved places or initialize empty dict
    saved_places = current_user.saved_places or {}

    # Update the place
    saved_places[place_type] = {
        "address": place_data.address,
        "latitude": place_data.latitude,
        "longitude": place_data.longitude
    }

    # Update user
    current_user.saved_places = saved_places
    db.commit()
    db.refresh(current_user)

    return {
        "message": f"{place_type.capitalize()} saved successfully",
        "saved_places": saved_places
    }


@router.delete("/saved-places/{place_type}")
async def delete_saved_place(
    place_type: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Delete a saved place"""
    if place_type not in ["home", "work"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="place_type must be 'home' or 'work'"
        )

    saved_places = current_user.saved_places or {}

    if place_type in saved_places:
        del saved_places[place_type]
        current_user.saved_places = saved_places
        db.commit()

    return {"message": f"{place_type.capitalize()} deleted successfully"}
