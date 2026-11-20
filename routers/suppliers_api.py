from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from auth import require_role
from database import get_db
from models import User
from schemas import SupplierActivityItem, SupplierProfile
from services.user_activity import get_supplier_activity

router = APIRouter(prefix="/suppliers", tags=["suppliers"])


@router.get("/me", response_model=SupplierProfile, summary="Get the signed-in supplier profile")
async def supplier_profile(current_user: Annotated[User, Depends(require_role("supplier"))]):
    return {
        "id": current_user.id,
        "username": current_user.username,
        "email": current_user.email,
        "created_at": current_user.created_at,
    }


@router.get("/me/activity", response_model=list[SupplierActivityItem], summary="List quotations from the signed-in supplier")
async def supplier_activity(
    current_user: Annotated[User, Depends(require_role("supplier"))],
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
):
    user_id = current_user.id
    await db.rollback()
    return await get_supplier_activity(db, user_id, limit)
