from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

import models
from auth import require_cookie_admin
from database import get_db
from services.user_activity import get_account_activity

router = APIRouter(tags=["admin pages"])
templates = Jinja2Templates(directory="templates")


@router.get("/admin/users", include_in_schema=False)
async def admin_users_page(
    request: Request,
    current_admin: Annotated[models.User, Depends(require_cookie_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
):
    total = await db.scalar(select(func.count()).select_from(models.User)) or 0
    start = (page - 1) * page_size
    users = (
        await db.execute(select(models.User).order_by(models.User.id).offset(start).limit(page_size))
    ).scalars().all()
    return templates.TemplateResponse(
        request,
        "admin_users.html",
        {"title": "User administration", "admin": current_admin, "users": users, "page": page, "page_size": page_size, "total": total},
    )


@router.get("/admin/users/{user_id}", include_in_schema=False)
async def admin_user_detail_page(
    user_id: int,
    request: Request,
    current_admin: Annotated[models.User, Depends(require_cookie_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    user = await db.scalar(select(models.User).where(models.User.id == user_id))
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    activity = await get_account_activity(db, user.id, user.role, 100)
    return templates.TemplateResponse(
        request,
        "admin_user_detail.html",
        {"title": f"User {user.username}", "admin": current_admin, "user": user, "activity": activity},
    )
