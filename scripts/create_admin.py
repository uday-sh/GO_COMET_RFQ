"""Create or promote the initial senior administrator using hidden password input."""

import asyncio
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import func, or_, select

import models
from auth import hash_password
from database import AsyncSessionLocal, engine
from schemas import UserCreate


async def main() -> None:
    username = input("Senior admin username: ").strip()
    email = input("Senior admin email: ").strip()
    password = getpass.getpass("Senior admin password (8-128 characters): ")
    confirmation = getpass.getpass("Confirm password: ")
    if password != confirmation:
        raise SystemExit("Passwords do not match.")
    try:
        payload = UserCreate(username=username, email=email, password=password, role="buyer")
    except Exception as exc:
        raise SystemExit(f"Invalid account details: {exc}") from exc

    normalized_username = payload.username.strip()
    normalized_email = str(payload.email).strip().lower()
    async with AsyncSessionLocal() as db:
        matches = (
            await db.scalars(
                select(models.User).where(
                    or_(
                        func.lower(models.User.username) == normalized_username.lower(),
                        func.lower(models.User.email) == normalized_email,
                    )
                )
            )
        ).all()
        if len(matches) > 1:
            raise SystemExit("Username and email belong to different existing accounts; resolve that conflict first.")
        if matches:
            user = matches[0]
            user.username = normalized_username
            user.email = normalized_email
            user.password_hash = hash_password(password)
            user.is_admin = True
        else:
            user = models.User(
                username=normalized_username,
                email=normalized_email,
                password_hash=hash_password(password),
                role="buyer",
                is_admin=True,
            )
            db.add(user)
        try:
            await db.commit()
        except Exception:
            await db.rollback()
            raise
    print(f"Senior administrator ready: {normalized_username} ({normalized_email})")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    finally:
        asyncio.run(engine.dispose())
