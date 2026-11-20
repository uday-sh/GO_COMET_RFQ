"""Provision a buyer account locally or in a controlled admin environment."""

import asyncio
import getpass
import sys
from pathlib import Path

from sqlalchemy import func, select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import models
from auth import hash_password
from database import AsyncSessionLocal, engine


async def main() -> None:
    username = input("Buyer username: ").strip().lower()
    email = input("Buyer email: ").strip().lower()
    password = getpass.getpass("Buyer password (8+ characters; any character mix): ")
    confirmation = getpass.getpass("Confirm password: ")
    if len(password) < 8 or len(password) > 128 or password != confirmation:
        raise SystemExit("Use a matching password of 8 to 128 characters.")

    async with AsyncSessionLocal() as db:
        existing = await db.scalar(
            select(models.User).where(
                (func.lower(models.User.username) == username.lower())
                | (func.lower(models.User.email) == email)
            )
        )
        if existing:
            raise SystemExit("That username or email already exists.")
        db.add(
            models.User(
                username=username,
                email=email,
                password_hash=hash_password(password),
                role="buyer",
            )
        )
        try:
            await db.commit()
        except Exception:
            await db.rollback()
            raise
    print(f"Buyer account created: {username}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    finally:
        asyncio.run(engine.dispose())
