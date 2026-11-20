from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.templating import Jinja2Templates
from sqlalchemy import exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

import models
from auth import require_cookie_admin
from database import get_db
from schemas import FreightService, RFQStatus, TransportMode
from services.analytics import admin_analytics
from services.rfq_filters import current_status_filter, effective_status_value
from services.user_activity import count_account_activity, get_account_activity

router = APIRouter(tags=["admin pages"])
templates = Jinja2Templates(directory="templates")


@router.get("/admin", include_in_schema=False)
async def admin_dashboard_page(
    request: Request,
    current_admin: Annotated[models.User, Depends(require_cookie_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    analytics = await admin_analytics(db)
    return templates.TemplateResponse(
        request,
        "admin_dashboard.html",
        {
            "title": "Admin analytics", "admin": current_admin, "analytics": analytics,
            "max_activity": max((point.value for point in analytics.activity_trend), default=0),
            "max_status": max((point.value for point in analytics.status_breakdown), default=0),
        },
    )


@router.get("/admin/users", include_in_schema=False)
async def admin_users_page(
    request: Request,
    current_admin: Annotated[models.User, Depends(require_cookie_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
    role: str | None = Query(default=None, max_length=20),
    search: str | None = Query(default=None, max_length=120),
    admin_only: bool = False,
    has_activity: bool = False,
):
    role = (role.strip().lower() or None) if role is not None else None
    if role is not None and role not in {"buyer", "supplier"}:
        raise HTTPException(status_code=422, detail="Choose buyer, supplier, or all account types.")
    filters = []
    if role:
        filters.append(models.User.role == role)
    if search and search.strip():
        term = f"%{search.strip().lower()}%"
        filters.append(or_(func.lower(models.User.username).like(term), func.lower(models.User.email).like(term)))
    if admin_only:
        filters.append(models.User.is_admin.is_(True))
    if has_activity:
        filters.append(or_(
            models.User.id.in_(select(models.RFQ.buyer_id)),
            models.User.id.in_(select(models.Bid.supplier_id)),
        ))
    users_query = select(models.User)
    count_query = select(func.count()).select_from(models.User)
    if filters:
        users_query = users_query.where(*filters)
        count_query = count_query.where(*filters)
    total = await db.scalar(count_query) or 0
    start = (page - 1) * page_size
    users = (
        await db.execute(users_query.order_by(models.User.id).offset(start).limit(page_size))
    ).scalars().all()
    return templates.TemplateResponse(
        request,
        "admin_users.html",
        {
            "title": "User administration", "admin": current_admin, "users": users,
            "page": page, "page_size": page_size, "total": total,
            "role": role or "", "search": search or "", "admin_only": admin_only,
            "has_activity": has_activity,
            "previous_url": str(request.url.include_query_params(page=max(1, page - 1))),
            "next_url": str(request.url.include_query_params(page=page + 1)),
        },
    )


@router.get("/admin/auctions", include_in_schema=False)
async def admin_auctions_page(
    request: Request,
    current_admin: Annotated[models.User, Depends(require_cookie_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    status_filter: RFQStatus | None = Query(default=None, alias="status"),
    transport_mode: TransportMode | None = None,
    service: FreightService | None = None,
    has_bids: bool = False,
    has_remarks: bool = False,
    closing_soon: bool = False,
):
    filters = []
    now = datetime.now(UTC)
    if status_filter:
        filters.append(current_status_filter(status_filter, now))
    if transport_mode:
        filters.append(models.RFQ.id.in_(select(models.RFQTransportMode.rfq_id).where(models.RFQTransportMode.mode == transport_mode.value)))
    if service:
        filters.append(models.RFQ.id.in_(select(models.RFQService.rfq_id).where(models.RFQService.service == service.value)))
    if has_bids:
        filters.append(exists(select(models.Bid.id).where(models.Bid.rfq_id == models.RFQ.id, models.Bid.accepted.is_(True))))
    if has_remarks:
        filters.append(models.RFQ.remarks.is_not(None))
    if closing_soon:
        filters.extend((models.RFQ.status == "active", models.RFQ.current_close_at >= now, models.RFQ.current_close_at <= now + timedelta(hours=24)))

    bid_stats = (
        select(
            models.Bid.rfq_id.label("rfq_id"),
            func.count(models.Bid.id).label("bid_count"),
            func.min(models.Bid.comparison_total).label("lowest_bid"),
        )
        .where(models.Bid.accepted.is_(True))
        .group_by(models.Bid.rfq_id)
        .subquery()
    )
    query = select(models.RFQ, func.coalesce(bid_stats.c.bid_count, 0), bid_stats.c.lowest_bid).outerjoin(bid_stats, bid_stats.c.rfq_id == models.RFQ.id)
    count_query = select(func.count()).select_from(models.RFQ)
    if filters:
        query = query.where(*filters)
        count_query = count_query.where(*filters)
    total = await db.scalar(count_query) or 0
    offset = (page - 1) * page_size
    rows = (await db.execute(query.order_by(models.RFQ.created_at.desc(), models.RFQ.id.desc()).offset(offset).limit(page_size))).all()
    display_status = {}
    for rfq, _, _ in rows:
        display_status[rfq.id] = effective_status_value(rfq.status, rfq.current_close_at, rfq.forced_close_at, now)
    return templates.TemplateResponse(
        request,
        "admin_auctions.html",
        {
            "title": "Auction oversight", "admin": current_admin,
            "rows": rows, "total": total, "page": page, "page_size": page_size,
            "display_status": display_status,
            "status_filter": status_filter.value if status_filter else "",
            "transport_mode": transport_mode.value if transport_mode else "",
            "service": service.value if service else "",
            "has_bids": has_bids, "has_remarks": has_remarks, "closing_soon": closing_soon,
            "previous_url": str(request.url.include_query_params(page=max(1, page - 1))),
            "next_url": str(request.url.include_query_params(page=page + 1)),
        },
    )


@router.get("/admin/auctions/{rfq_id}", include_in_schema=False)
async def admin_auction_detail_page(
    rfq_id: int,
    request: Request,
    current_admin: Annotated[models.User, Depends(require_cookie_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    leaders_only: bool = False,
    top_three: bool = False,
):
    rfq = await db.scalar(select(models.RFQ).where(models.RFQ.id == rfq_id).options(
        selectinload(models.RFQ.transport_modes), selectinload(models.RFQ.services),
    ))
    if rfq is None:
        raise HTTPException(status_code=404, detail="RFQ not found")

    supplier_order = func.row_number().over(
        partition_by=models.Bid.supplier_id,
        order_by=(models.Bid.comparison_total.asc(), models.Bid.submitted_at.asc(), models.Bid.id.asc()),
    ).label("supplier_order")
    per_supplier = (
        select(models.Bid.id, models.Bid.supplier_id, supplier_order)
        .where(models.Bid.rfq_id == rfq_id, models.Bid.accepted.is_(True))
        .subquery()
    )
    global_rank = func.row_number().over(
        order_by=(models.Bid.comparison_total.asc(), models.Bid.submitted_at.asc(), models.Bid.id.asc()),
    ).label("global_rank")
    ranked_best = (
        select(per_supplier.c.id, per_supplier.c.supplier_id, global_rank)
        .join(models.Bid, models.Bid.id == per_supplier.c.id)
        .where(per_supplier.c.supplier_order == 1)
        .subquery()
    )
    query = select(models.Bid).where(models.Bid.rfq_id == rfq_id, models.Bid.accepted.is_(True))
    if leaders_only:
        query = query.where(models.Bid.id.in_(select(ranked_best.c.id)))
    if top_three:
        query = query.where(models.Bid.id.in_(select(ranked_best.c.id).where(ranked_best.c.global_rank <= 3)))
    total = await db.scalar(select(func.count()).select_from(query.order_by(None).subquery())) or 0
    offset = (page - 1) * page_size
    bids = (
        await db.execute(query.options(selectinload(models.Bid.supplier))
            .order_by(models.Bid.comparison_total, models.Bid.submitted_at, models.Bid.id)
            .offset(offset).limit(page_size))
    ).scalars().all()
    ranks = dict((await db.execute(select(ranked_best.c.id, ranked_best.c.global_rank))).all())
    effective_status = effective_status_value(rfq.status, rfq.current_close_at, rfq.forced_close_at, datetime.now(UTC))
    return templates.TemplateResponse(
        request,
        "admin_auction_detail.html",
        {
            "title": f"Auction {rfq.reference_id}", "admin": current_admin,
            "rfq": rfq, "bids": bids, "ranks": ranks, "total": total,
            "effective_status": effective_status,
            "page": page, "page_size": page_size, "leaders_only": leaders_only,
            "top_three": top_three,
            "previous_url": str(request.url.include_query_params(page=max(1, page - 1))),
            "next_url": str(request.url.include_query_params(page=page + 1)),
        },
    )


@router.get("/admin/users/{user_id}", include_in_schema=False)
async def admin_user_detail_page(
    user_id: int,
    request: Request,
    current_admin: Annotated[models.User, Depends(require_cookie_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
):
    user = await db.scalar(select(models.User).where(models.User.id == user_id))
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    total = await count_account_activity(db, user.id, user.role)
    offset = (page - 1) * page_size
    activity = await get_account_activity(db, user.id, user.role, page_size, offset)
    return templates.TemplateResponse(
        request,
        "admin_user_detail.html",
        {
            "title": f"User {user.username}", "admin": current_admin, "user": user,
            "activity": activity, "page": page, "page_size": page_size, "total": total,
            "previous_url": str(request.url.include_query_params(page=max(1, page - 1))),
            "next_url": str(request.url.include_query_params(page=page + 1)),
        },
    )
