from collections.abc import AsyncGenerator
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from sqlalchemy import select

from database import Base, get_db
from main import app
import models


pytest_plugins = ["anyio"]


@pytest.fixture(scope="session")
def anyio_backend():
    return "asyncio"


@pytest.fixture(scope="session")
def test_engine():
    db_path = Path(__file__).resolve().parent / "rfq-test.sqlite"
    db_path.unlink(missing_ok=True)
    return create_async_engine(f"sqlite+aiosqlite:///{db_path}", poolclass=NullPool)


@pytest.fixture(scope="session")
async def setup_database(test_engine):
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await test_engine.dispose()


@pytest.fixture
async def client(test_engine, setup_database) -> AsyncGenerator[AsyncClient, None]:
    session_factory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)

    async def override_get_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


async def register(client: AsyncClient, username: str, role: str = "supplier") -> str:
    email = f"{username}@example.com"
    response = await client.post("/api/auth/register", json={"username": username, "email": email, "password": "strong-password-123", "role": role})
    assert response.status_code == 201, response.text
    login = await client.post("/api/auth/token", data={"username": email, "password": "strong-password-123"})
    assert login.status_code == 200, login.text
    return login.json()["access_token"]


async def promote_to_admin(username: str) -> None:
    db_generator = app.dependency_overrides[get_db]()
    db = await anext(db_generator)
    try:
        user = await db.scalar(select(models.User).where(models.User.username == username))
        assert user is not None
        user.is_admin = True
        await db.commit()
    finally:
        await db_generator.aclose()


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}
