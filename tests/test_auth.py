import pytest


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
