from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import require_role
from database import get_db
import models
from models import User
from schemas import ActivityPage, BuyerAnalytics, BuyerProfile
from services.analytics import buyer_analytics
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


@router.get("/me/activity", response_model=ActivityPage, summary="List paginated RFQs created by the signed-in buyer")
async def buyer_activity(
    current_user: Annotated[User, Depends(require_role("buyer"))],
    db: Annotated[AsyncSession, Depends(get_db)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
):
    user_id = current_user.id
    await db.rollback()
    total = await db.scalar(select(func.count()).select_from(models.RFQ).where(models.RFQ.buyer_id == user_id)) or 0
    start = (page - 1) * page_size
    items = await get_buyer_activity(db, user_id, page_size, start)
    return ActivityPage(items=items, total=total, page=page, page_size=page_size, has_more=start + len(items) < total)


@router.get("/me/analytics", response_model=BuyerAnalytics, summary="View analytics for the signed-in buyer's RFQs")
async def buyer_analytics_endpoint(
    current_user: Annotated[User, Depends(require_role("buyer"))],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    buyer_id = current_user.id
    await db.rollback()
    return await buyer_analytics(db, buyer_id)
