import pytest

from tests.conftest import auth, promote_to_admin, register


@pytest.mark.anyio
async def test_landing_page_has_header_buttons_for_each_access_flow(client):
    page = await client.get("/")
    assert page.status_code == 200
    assert 'id="auth-nav"' in page.text
    assert 'data-auth-tab="login"' in page.text
    assert 'data-auth-tab="register"' in page.text
    assert 'data-auth-tab="admin"' in page.text
    assert 'id="login-form"' in page.text
    assert 'id="register-form"' in page.text
    assert 'id="admin-login-form"' in page.text


@pytest.mark.anyio
async def test_browser_auth_token_is_tab_scoped(client):
    script = await client.get("/static/js/app.js?v=9")
    assert script.status_code == 200
    assert "sessionStorage.getItem('rfq_token')" in script.text
    assert "sessionStorage.setItem('rfq_token'" in script.text
    assert "localStorage.removeItem('rfq_token')" in script.text
    assert "localStorage.getItem('rfq_token')" not in script.text
    assert "localStorage.setItem('rfq_token'" not in script.text


@pytest.mark.anyio
async def test_buyer_and_supplier_profiles_are_self_scoped_and_html_is_rendered(client):
    buyer_token = await register(client, "profile-buyer", "buyer")
    supplier_token = await register(client, "profile-supplier", "supplier")
    buyer = (await client.get("/api/buyers/me", headers=auth(buyer_token))).json()
    supplier = (await client.get("/api/suppliers/me", headers=auth(supplier_token))).json()

    assert buyer["account_type"] == "buyer" and supplier["account_type"] == "supplier"
    assert (await client.get("/api/buyers/me/activity", headers=auth(buyer_token))).status_code == 200
    assert (await client.get("/api/buyers/me", headers=auth(supplier_token))).status_code == 403
    assert (await client.get(f"/api/admin/suppliers/{supplier['id']}", headers=auth(buyer_token))).status_code == 403
    assert (await client.get("/api/admin/users", headers=auth(supplier_token))).status_code == 403

    denied_page = await client.get("/admin/users")
    assert denied_page.status_code == 403
    assert denied_page.headers["content-type"].startswith("text/html")
    assert "Access denied" in denied_page.text


@pytest.mark.anyio
async def test_senior_admin_can_list_and_review_users_without_password_fields(client):
    admin_token = await register(client, "senior-admin-test", "buyer")
    await promote_to_admin("senior-admin-test")

    standard_login = await client.post(
        "/api/auth/token",
        data={"username": "senior-admin-test", "password": "strong-password-123"},
    )
    assert standard_login.status_code == 403
    wrong_portal = await client.post(
        "/api/auth/admin/token",
        data={"username": "profile-buyer@example.com", "password": "strong-password-123"},
    )
    assert wrong_portal.status_code == 401

    username_login = await client.post(
        "/api/auth/admin/token",
        data={"username": "senior-admin-test", "password": "strong-password-123"},
    )
    assert username_login.status_code == 200
    admin_token = username_login.json()["access_token"]

    listed = await client.get("/api/admin/users?page=1&page_size=100", headers=auth(admin_token))
    assert listed.status_code == 200
    admin = next(user for user in listed.json()["items"] if user["username"] == "senior-admin-test")
    assert admin["is_admin"] is True
    assert "password_hash" not in admin

    detail = await client.get(f"/api/admin/buyers/{admin['id']}", headers=auth(admin_token))
    assert detail.status_code == 200
    assert detail.json()["email"] == "senior-admin-test@example.com"
    assert "password_hash" not in detail.json()
    assert "auctions_created" in detail.json()

    admin_page = await client.get("/admin/users")
    assert admin_page.status_code == 200
    assert admin_page.headers["content-type"].startswith("text/html")
    assert "User administration" in admin_page.text

    openapi = (await client.get("/openapi.json")).json()
    assert "/api/buyers/me" in openapi["paths"]
    assert "/api/suppliers/me" in openapi["paths"]
    assert "/api/admin/users" in openapi["paths"]
    assert "/admin/users" not in openapi["paths"]
    tags = {tag["name"] for tag in openapi["tags"]}
    assert {"authentication", "buyers", "suppliers", "admin"}.issubset(tags)
    assert openapi["paths"]["/api/buyers/me"]["get"]["tags"] == ["buyers"]
    assert openapi["paths"]["/api/suppliers/me"]["get"]["tags"] == ["suppliers"]
    assert openapi["paths"]["/api/admin/users"]["get"]["tags"] == ["admin"]

    cookie = username_login.headers["set-cookie"].lower()
    assert "rfq_session=" in cookie and "httponly" in cookie and "samesite=lax" in cookie
