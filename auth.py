from datetime import UTC, datetime, timedelta
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from pwdlib import PasswordHash
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import models
from config import settings
from database import get_db

password_hash = PasswordHash.recommended()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/token")


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return password_hash.verify(plain_password, hashed_password)


def create_access_token(user_id: int) -> str:
    now = datetime.now(UTC)
    payload = {"sub": str(user_id), "iat": now, "exp": now + timedelta(minutes=settings.access_token_expire_minutes)}
    return jwt.encode(payload, settings.secret_key.get_secret_value(), algorithm=settings.algorithm)


async def user_from_token(token: str, db: AsyncSession) -> models.User:
    try:
        payload = jwt.decode(token, settings.secret_key.get_secret_value(), algorithms=[settings.algorithm])
        user_id = int(payload["sub"])
    except (jwt.InvalidTokenError, KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token", headers={"WWW-Authenticate": "Bearer"}) from exc

    user = await db.scalar(select(models.User).where(models.User.id == user_id))
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found", headers={"WWW-Authenticate": "Bearer"})
    return user


async def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> models.User:
    return await user_from_token(token, db)


async def get_cookie_user(request: Request, db: Annotated[AsyncSession, Depends(get_db)]) -> models.User:
    token = request.cookies.get("rfq_session")
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Sign in required")
    return await user_from_token(token, db)


CurrentUser = Annotated[models.User, Depends(get_current_user)]
CookieUser = Annotated[models.User, Depends(get_cookie_user)]


def require_role(role: str):
    async def dependency(current_user: CurrentUser) -> models.User:
        if current_user.is_admin or current_user.role != role:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"{role.title()} access required")
        return current_user

    return dependency


async def require_admin(current_user: CurrentUser) -> models.User:
    if not current_user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Senior administrator access required")
    return current_user


async def require_cookie_admin(current_user: CookieUser) -> models.User:
    if not current_user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Senior administrator access required")
    return current_user
