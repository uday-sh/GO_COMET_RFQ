from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

import models
from auth import CurrentUser, create_access_token, hash_password, verify_password
from config import settings
from database import get_db
from schemas import ActivityPage, Token, UserCreate, UserPublic
from services.user_activity import count_account_activity, get_account_activity

router = APIRouter(prefix="/auth", tags=["authentication"])


def attach_session_cookie(request: Request, response: Response, access_token: str) -> None:
    response.set_cookie(
        "rfq_session",
        access_token,
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="lax",
        max_age=settings.access_token_expire_minutes * 60,
        path="/",
    )


@router.post("/register", response_model=UserPublic, status_code=status.HTTP_201_CREATED)
async def register(payload: UserCreate, db: Annotated[AsyncSession, Depends(get_db)]):
    username = payload.username.strip().lower()
    email = str(payload.email).strip().lower()
    existing = await db.scalar(select(models.User).where(func.lower(models.User.email) == email))
    if existing:
        raise HTTPException(status_code=409, detail="Email is already registered")
    existing = await db.scalar(select(models.User).where(func.lower(models.User.username) == username))
    if existing:
        raise HTTPException(status_code=409, detail="Username is already registered")
    user = models.User(username=username, email=email, password_hash=hash_password(payload.password), role=payload.role.value)
    db.add(user)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Username or email is already registered") from exc
    await db.refresh(user)
    return user


@router.post("/token", response_model=Token)
async def login(form_data: Annotated[OAuth2PasswordRequestForm, Depends()], request: Request, response: Response, db: Annotated[AsyncSession, Depends(get_db)]):
    login_id = form_data.username.strip().lower()
    user = await db.scalar(
        select(models.User).where(
            or_(func.lower(models.User.email) == login_id, func.lower(models.User.username) == login_id)
        )
    )
    if not user or not verify_password(form_data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Incorrect email or password", headers={"WWW-Authenticate": "Bearer"})
    if user.is_admin:
        raise HTTPException(status_code=403, detail="Use the administrator sign-in option")
    access_token = create_access_token(user.id)
    attach_session_cookie(request, response, access_token)
    return Token(access_token=access_token, token_type="bearer")


@router.post("/admin/token", response_model=Token, summary="Sign in to the senior-admin portal")
async def admin_login(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    request: Request,
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    login_id = form_data.username.strip().lower()
    user = await db.scalar(
        select(models.User).where(
            or_(func.lower(models.User.email) == login_id, func.lower(models.User.username) == login_id)
        )
    )
    if not user or not verify_password(form_data.password, user.password_hash) or not user.is_admin:
        raise HTTPException(status_code=401, detail="Invalid administrator username or password", headers={"WWW-Authenticate": "Bearer"})
    access_token = create_access_token(user.id)
    attach_session_cookie(request, response, access_token)
    return Token(access_token=access_token, token_type="bearer")


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(response: Response):
    response.delete_cookie("rfq_session", path="/")


@router.get("/me", response_model=UserPublic)
async def me(current_user: CurrentUser):
    return current_user


@router.get("/activity", response_model=ActivityPage, include_in_schema=False)
async def account_activity(
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
):
    role = current_user.role
    user_id = current_user.id
    await db.rollback()
    total = await count_account_activity(db, user_id, role)
    offset = (page - 1) * page_size
    items = await get_account_activity(db, user_id, role, page_size, offset)
    return ActivityPage(items=items, total=total, page=page, page_size=page_size, has_more=offset + len(items) < total)
