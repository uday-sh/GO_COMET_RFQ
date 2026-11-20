import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from pwdlib import PasswordHash
from sqlalchemy import delete, select
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


def _invalid_token() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired token",
        headers={"WWW-Authenticate": "Bearer"},
    )


def _legacy_revocation_id(token: str) -> str:
    return f"legacy-{hashlib.sha256(token.encode('utf-8')).hexdigest()}"


async def create_access_token(user_id: int, db: AsyncSession) -> str:
    now = datetime.now(UTC)
    expires_at = now + timedelta(minutes=settings.access_token_expire_minutes)
    session_id = secrets.token_urlsafe(32)
    payload = {"sub": str(user_id), "sid": session_id, "iat": now, "exp": expires_at}
    token = jwt.encode(payload, settings.secret_key.get_secret_value(), algorithm=settings.algorithm)
    await db.execute(delete(models.UserSession).where(models.UserSession.expires_at <= now))
    db.add(models.UserSession(id=session_id, user_id=user_id, expires_at=expires_at))
    await db.commit()
    return token


async def user_from_token(token: str, db: AsyncSession) -> models.User:
    try:
        payload = jwt.decode(
            token,
            settings.secret_key.get_secret_value(),
            algorithms=[settings.algorithm],
            options={"require": ["exp", "sub"]},
        )
        user_id = int(payload["sub"])
    except (jwt.InvalidTokenError, KeyError, TypeError, ValueError) as exc:
        raise _invalid_token() from exc

    session_id = payload.get("sid")
    if session_id is not None:
        if not isinstance(session_id, str) or not session_id:
            raise _invalid_token()
        session = await db.scalar(
            select(models.UserSession).where(
                models.UserSession.id == session_id,
                models.UserSession.user_id == user_id,
                models.UserSession.expires_at > datetime.now(UTC),
                models.UserSession.revoked_at.is_(None),
            )
        )
        if session is None:
            raise _invalid_token()
    elif await db.get(models.UserSession, _legacy_revocation_id(token)) is not None:
        # Keep pre-session-table JWTs working through their original expiry,
        # but let logout revoke them during the rollout window.
        raise _invalid_token()

    user = await db.scalar(select(models.User).where(models.User.id == user_id))
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found", headers={"WWW-Authenticate": "Bearer"})
    return user


async def revoke_access_token(token: str, db: AsyncSession) -> None:
    try:
        payload = jwt.decode(
            token,
            settings.secret_key.get_secret_value(),
            algorithms=[settings.algorithm],
            options={"require": ["exp", "sub"]},
        )
        user_id = int(payload["sub"])
        expires_at = datetime.fromtimestamp(float(payload["exp"]), UTC)
    except (jwt.InvalidTokenError, KeyError, TypeError, ValueError, OverflowError):
        return

    now = datetime.now(UTC)
    session_id = payload.get("sid")
    if isinstance(session_id, str) and session_id:
        session = await db.get(models.UserSession, session_id)
        if session is not None and session.user_id == user_id:
            session.revoked_at = now
    elif expires_at > now and await db.get(models.User, user_id) is not None:
        legacy_id = _legacy_revocation_id(token)
        if await db.get(models.UserSession, legacy_id) is None:
            db.add(models.UserSession(
                id=legacy_id,
                user_id=user_id,
                expires_at=expires_at,
                revoked_at=now,
            ))
    await db.commit()


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
