from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import require_role
from database import get_db
import models
from schemas import ActivityPage, SupplierAnalytics, SupplierCapabilitiesUpdate, SupplierProfile
from services.analytics import supplier_analytics
from services.user_activity import get_supplier_activity

router = APIRouter(prefix="/suppliers", tags=["suppliers"])


@router.get("/me", response_model=SupplierProfile, summary="Get the signed-in supplier profile")
async def supplier_profile(current_user: Annotated[models.User, Depends(require_role("supplier"))]):
    return {
        "id": current_user.id,
        "username": current_user.username,
        "email": current_user.email,
        "created_at": current_user.created_at,
        "transport_modes": [item.mode for item in current_user.transport_modes],
        "services": [item.service for item in current_user.services],
    }


@router.put("/me/capabilities", response_model=SupplierProfile, summary="Update the signed-in supplier's service capabilities")
async def update_supplier_capabilities(
    payload: SupplierCapabilitiesUpdate,
    current_user: Annotated[models.User, Depends(require_role("supplier"))],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    current_user.transport_modes = [models.SupplierTransportMode(mode=mode.value) for mode in payload.transport_modes]
    current_user.services = [models.SupplierService(service=service.value) for service in payload.services]
    await db.commit()
    return {
        "id": current_user.id,
        "username": current_user.username,
        "email": current_user.email,
        "created_at": current_user.created_at,
        "transport_modes": [mode.value for mode in payload.transport_modes],
        "services": [service.value for service in payload.services],
    }


@router.get("/me/activity", response_model=ActivityPage, summary="List paginated quotations from the signed-in supplier")
async def supplier_activity(
    current_user: Annotated[models.User, Depends(require_role("supplier"))],
    db: Annotated[AsyncSession, Depends(get_db)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
):
    user_id = current_user.id
    await db.rollback()
    total = await db.scalar(select(func.count()).select_from(models.Bid).where(models.Bid.supplier_id == user_id)) or 0
    start = (page - 1) * page_size
    items = await get_supplier_activity(db, user_id, page_size, start)
    return ActivityPage(items=items, total=total, page=page, page_size=page_size, has_more=start + len(items) < total)


@router.get("/me/analytics", response_model=SupplierAnalytics, summary="View analytics for the signed-in supplier's quotations")
async def supplier_analytics_endpoint(
    current_user: Annotated[models.User, Depends(require_role("supplier"))],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    supplier_id = current_user.id
    await db.rollback()
    return await supplier_analytics(db, supplier_id)
