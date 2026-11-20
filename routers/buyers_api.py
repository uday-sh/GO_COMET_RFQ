from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from auth import require_role
from database import get_db
from models import User
from schemas import BuyerActivityItem, BuyerProfile
from services.user_activity import get_buyer_activity

router = APIRouter(prefix="/buyers", tags=["buyers"])


@router.get("/me", response_model=BuyerProfile, summary="Get the signed-in buyer profile")
async def buyer_profile(current_user: Annotated[User, Depends(require_role("buyer"))]):
    return {
        "id": current_user.id,
        "username": current_user.username,
        "email": current_user.email,
        "created_at": current_user.created_at,
    }


@router.get("/me/activity", response_model=list[BuyerActivityItem], summary="List auctions created by the signed-in buyer")
async def buyer_activity(
    current_user: Annotated[User, Depends(require_role("buyer"))],
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
):
    user_id = current_user.id
    await db.rollback()
    return await get_buyer_activity(db, user_id, limit)
