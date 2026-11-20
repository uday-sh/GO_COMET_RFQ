from datetime import UTC, datetime, timedelta

import jwt
import pytest
from httpx import ASGITransport, AsyncClient

from config import settings
from core.app_factory import create_app
from database import get_db
from main import app
from tests.conftest import auth, register


@pytest.mark.anyio
async def test_simple_password_and_canonical_email_login(client):
    payload = {
        "username": "Test Buyer",
        "email": "test.buyer.auth@example.com",
        "password": "test-passphrase-4831",
        "role": "buyer",
        "is_admin": True,
    }
    registered = await client.post("/api/auth/register", json=payload)
    assert registered.status_code == 201, registered.text
    assert registered.json()["role"] == "buyer"
    assert registered.json()["is_admin"] is False

    login = await client.post(
        "/api/auth/token",
        data={"username": "  TEST.BUYER.AUTH@EXAMPLE.COM  ", "password": "test-passphrase-4831"},
    )
    assert login.status_code == 200, login.text

    duplicate = await client.post(
        "/api/auth/register",
        json={**payload, "username": "another-name"},
    )
    assert duplicate.status_code == 409


@pytest.mark.anyio
async def test_simple_password_from_strength_warning_is_accepted(client):
    password = "Simple-passphrase-2026"
    registered = await client.post(
        "/api/auth/register",
        json={
            "username": "simple-password-buyer",
            "email": "simple-password-buyer@example.com",
            "password": password,
            "role": "buyer",
        },
    )
    assert registered.status_code == 201, registered.text

    login = await client.post(
        "/api/auth/token",
        data={"username": "simple-password-buyer@example.com", "password": password},
    )
    assert login.status_code == 200, login.text


@pytest.mark.anyio
async def test_login_session_is_shared_between_replicas_and_revoked_on_logout(client):
    token = await register(client, "shared-session-buyer", "buyer")

    replica = create_app()
    replica.dependency_overrides[get_db] = app.dependency_overrides[get_db]
    async with AsyncClient(
        transport=ASGITransport(app=replica),
        base_url="http://replica-two",
    ) as second_instance:
        profile = await second_instance.get("/api/auth/me", headers=auth(token))
        assert profile.status_code == 200
        assert profile.json()["username"] == "shared-session-buyer"

        logout = await second_instance.post("/api/auth/logout", headers=auth(token))
        assert logout.status_code == 204

    revoked = await client.get("/api/auth/me", headers=auth(token))
    assert revoked.status_code == 401


@pytest.mark.anyio
async def test_pre_session_jwt_stays_valid_until_logout_or_expiry(client):
    current_token = await register(client, "legacy-session-buyer", "buyer")
    user = (await client.get("/api/auth/me", headers=auth(current_token))).json()
    now = datetime.now(UTC)
    legacy_token = jwt.encode(
        {"sub": str(user["id"]), "iat": now, "exp": now + timedelta(minutes=30)},
        settings.secret_key.get_secret_value(),
        algorithm=settings.algorithm,
    )

    before_logout = await client.get("/api/auth/me", headers=auth(legacy_token))
    assert before_logout.status_code == 200
    logout = await client.post("/api/auth/logout", headers=auth(legacy_token))
    assert logout.status_code == 204
    after_logout = await client.get("/api/auth/me", headers=auth(legacy_token))
    assert after_logout.status_code == 401
