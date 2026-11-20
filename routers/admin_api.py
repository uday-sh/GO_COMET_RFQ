from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

import models
from auth import require_admin
from database import get_db
from schemas import AdminBuyerDetail, AdminSupplierDetail, AdminUserSummary, BuyerActivityItem, PaginatedUsers, SupplierActivityItem
from services.user_activity import get_buyer_activity, get_supplier_activity

router = APIRouter(prefix="/admin", tags=["admin"])
AdminOnly = Annotated[models.User, Depends(require_admin)]


@router.get("/users", response_model=PaginatedUsers, summary="List buyer and supplier accounts")
async def list_users(
    _admin: AdminOnly,
    db: Annotated[AsyncSession, Depends(get_db)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
    role: str | None = Query(default=None, pattern="^(buyer|supplier)$"),
    search: str | None = Query(default=None, max_length=120),
):
    query = select(models.User)
    count_query = select(func.count()).select_from(models.User)
    filters = []
    if role:
        filters.append(models.User.role == role)
    if search and search.strip():
        term = f"%{search.strip().lower()}%"
        filters.append(or_(func.lower(models.User.username).like(term), func.lower(models.User.email).like(term)))
    if filters:
        query = query.where(*filters)
        count_query = count_query.where(*filters)
    total = await db.scalar(count_query) or 0
    start = (page - 1) * page_size
    users = (await db.execute(query.order_by(models.User.id).offset(start).limit(page_size))).scalars().all()
    items = [AdminUserSummary.model_validate(user) for user in users]
    return PaginatedUsers(items=items, total=total, page=page, page_size=page_size, has_more=start + len(items) < total)


@router.get("/buyers/{buyer_id}", response_model=AdminBuyerDetail, summary="Review a buyer profile and RFQ history")
async def get_buyer(buyer_id: int, _admin: AdminOnly, db: Annotated[AsyncSession, Depends(get_db)]):
    buyer = await db.scalar(select(models.User).where(models.User.id == buyer_id, models.User.role == "buyer"))
    if buyer is None:
        raise HTTPException(status_code=404, detail="Buyer not found")
    summary = AdminUserSummary.model_validate(buyer).model_dump()
    history: list[BuyerActivityItem] = await get_buyer_activity(db, buyer.id, 100)
    return AdminBuyerDetail(**summary, auctions_created=history)


@router.get("/suppliers/{supplier_id}", response_model=AdminSupplierDetail, summary="Review a supplier profile and quotation history")
async def get_supplier(supplier_id: int, _admin: AdminOnly, db: Annotated[AsyncSession, Depends(get_db)]):
    supplier = await db.scalar(select(models.User).where(models.User.id == supplier_id, models.User.role == "supplier"))
    if supplier is None:
        raise HTTPException(status_code=404, detail="Supplier not found")
    summary = AdminUserSummary.model_validate(supplier).model_dump()
    history: list[SupplierActivityItem] = await get_supplier_activity(db, supplier.id, 100)
    return AdminSupplierDetail(**summary, quotations_submitted=history)
