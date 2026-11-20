import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from tests.conftest import auth, promote_to_admin, register


def schedule(start_offset=0, close_offset=30, forced_offset=60):
    now = datetime.now(UTC)
    return {
        "bid_start_at": (now + timedelta(minutes=start_offset)).isoformat(),
        "initial_close_at": (now + timedelta(minutes=close_offset)).isoformat(),
        "forced_close_at": (now + timedelta(minutes=forced_offset)).isoformat(),
        "pickup_service_date": (now + timedelta(days=2)).date().isoformat(),
    }


async def create_rfq(client, token, mode="bid_received", **overrides):
    body = {
        "name": "Northstar linehaul",
        "origin": "Delhi",
        "destination": "Mumbai",
        "transport_modes": ["road"],
        "services": [],
        "trigger_window_minutes": 10,
        "extension_duration_minutes": 5,
        "trigger_mode": mode,
        **schedule(-1, 30, 60),
        **overrides,
    }
    response = await client.post("/api/rfqs", json=body, headers=auth(token))
    assert response.status_code == 201, response.text
    return response.json()


async def bid(client, token, rfq_id, key, freight):
    body = {"idempotency_key": key, "carrier_name": "Northstar Transport", "freight_charges": str(freight), "origin_charges": "10.00", "destination_charges": "5.00", "transit_time_hours": 24, "quote_valid_until": (datetime.now(UTC) + timedelta(days=3)).isoformat()}
    return await client.post(f"/api/rfqs/{rfq_id}/bids", json=body, headers=auth(token))


@pytest.mark.anyio
async def test_buyer_only_rfq_creation_and_validation(client):
    supplier = await register(client, "supplier1")
    invalid = {"name": "Invalid", "trigger_window_minutes": 10, "extension_duration_minutes": 5, "trigger_mode": "bid_received", **schedule(-1, 10, 5)}
    response = await client.post("/api/rfqs", json=invalid, headers=auth(supplier))
    assert response.status_code == 403
    buyer = await register(client, "buyer1", "buyer")
    response = await client.post("/api/rfqs", json=invalid, headers=auth(buyer))
    assert response.status_code == 422


@pytest.mark.anyio
async def test_decreasing_quotes_and_deterministic_rankings(client):
    buyer = await register(client, "buyer2", "buyer")
    supplier_a = await register(client, "supplier2")
    supplier_b = await register(client, "supplier3")
    rfq = await create_rfq(client, buyer, remarks="Quote linehaul service; loading requirements apply.")
    assert rfq["reference_id"].startswith("RFQ-")
    assert (await bid(client, supplier_a, rfq["id"], "supplier-a-1", 100)).status_code == 201
    assert (await bid(client, supplier_b, rfq["id"], "supplier-b-1", 80)).status_code == 201
    lower = await bid(client, supplier_a, rfq["id"], "supplier-a-2", 70)
    assert lower.status_code == 201, lower.text
    not_lower = await bid(client, supplier_a, rfq["id"], "supplier-a-3", 75)
    assert not_lower.status_code == 422
    detail = (await client.get(f"/api/rfqs/{rfq['id']}", headers=auth(buyer))).json()
    assert detail["remarks"] == "Quote linehaul service; loading requirements apply."
    best = [b for b in detail["bids"] if b["rank"] == 1]
    assert len(best) == 1 and best[0]["comparison_total"] == "85.00"


@pytest.mark.anyio
async def test_bid_trigger_extends_but_never_beyond_forced_close(client):
    buyer = await register(client, "buyer3", "buyer")
    supplier = await register(client, "supplier4")
    rfq = await create_rfq(client, buyer, **schedule(-1, 3, 4))
    response = await bid(client, supplier, rfq["id"], "supplier-d-1", 50)
    assert response.status_code == 201
    detail = (await client.get(f"/api/rfqs/{rfq['id']}", headers=auth(buyer))).json()
    assert detail["current_close_at"] == detail["forced_close_at"]
    assert len(detail["extensions"]) == 1


@pytest.mark.anyio
async def test_rank_and_l1_trigger_modes_extend_on_qualifying_change(client):
    for index, mode in enumerate(("rank_change", "l1_change"), start=1):
        buyer = await register(client, f"buyer-trigger-{index}", "buyer")
        supplier_a = await register(client, f"supplier-trigger-a-{index}")
        supplier_b = await register(client, f"supplier-trigger-b-{index}")
        rfq = await create_rfq(client, buyer, mode=mode, **schedule(-1, 3, 10))
        assert (await bid(client, supplier_a, rfq["id"], f"trigger-a-{index}-1", 100)).status_code == 201
        assert (await bid(client, supplier_b, rfq["id"], f"trigger-b-{index}-1", 90)).status_code == 201
        changed = await bid(client, supplier_a, rfq["id"], f"trigger-a-{index}-2", 80)
        assert changed.status_code == 201, changed.text
        detail = (await client.get(f"/api/rfqs/{rfq['id']}", headers=auth(buyer))).json()
        assert len(detail["extensions"]) >= 1


@pytest.mark.anyio
async def test_idempotent_retry_returns_same_bid(client):
    buyer = await register(client, "buyer4", "buyer")
    supplier = await register(client, "supplier5")
    rfq = await create_rfq(client, buyer)
    first = await bid(client, supplier, rfq["id"], "retry-key-1", 60)
    second = await bid(client, supplier, rfq["id"], "retry-key-1", 60)
    assert first.status_code == 201 and second.status_code == 201
    assert first.json()["id"] == second.json()["id"]


@pytest.mark.anyio
async def test_two_suppliers_can_submit_competing_bids(client):
    buyer = await register(client, "buyer5", "buyer")
    supplier_a = await register(client, "supplier6")
    supplier_b = await register(client, "supplier7")
    rfq = await create_rfq(client, buyer)
    results = await asyncio.gather(bid(client, supplier_a, rfq["id"], "concurrent-a", 90), bid(client, supplier_b, rfq["id"], "concurrent-b", 80), return_exceptions=True)
    responses = [item for item in results if hasattr(item, "status_code")]
    assert len(responses) == 2
    assert all(item.status_code == 201 for item in responses), [getattr(item, "text", str(item)) for item in responses]


@pytest.mark.anyio
async def test_equal_total_bids_from_separate_suppliers_rank_without_timezone_error(client):
    buyer = await register(client, "buyer-equal-bids", "buyer")
    supplier_a = await register(client, "supplier-equal-a")
    supplier_b = await register(client, "supplier-equal-b")
    rfq = await create_rfq(client, buyer)

    first = await bid(client, supplier_a, rfq["id"], "equal-total-a-1", 100)
    second = await bid(client, supplier_b, rfq["id"], "equal-total-b-1", 100)
    assert first.status_code == 201
    assert second.status_code == 201, second.text

    detail = await client.get(f"/api/rfqs/{rfq['id']}", headers=auth(buyer))
    assert detail.status_code == 200
    assert sorted(item["rank"] for item in detail.json()["bids"]) == [1, 2]


@pytest.mark.anyio
async def test_supplier_bid_limit_applies_after_own_bid_privacy_filter(client):
    buyer = await register(client, "buyer-bid-limit", "buyer")
    leading_supplier = await register(client, "supplier-bid-limit-l1")
    trailing_supplier = await register(client, "supplier-bid-limit-own")
    rfq = await create_rfq(client, buyer)

    assert (await bid(client, leading_supplier, rfq["id"], "limit-l1-bid-1", 50)).status_code == 201
    assert (await bid(client, trailing_supplier, rfq["id"], "limit-own-bid-1", 100)).status_code == 201
    detail = await client.get(f"/api/rfqs/{rfq['id']}?bid_limit=1", headers=auth(trailing_supplier))
    assert detail.status_code == 200
    assert len(detail.json()["bids"]) == 1
    assert detail.json()["current_lowest_bid"] is None
    assert detail.json()["bids"][0]["supplier_name"] == "supplier-bid-limit-own"
    assert detail.json()["bids"][0]["rank"] == 2
    buyer_view = await client.get(f"/api/rfqs/{rfq['id']}", headers=auth(buyer))
    assert buyer_view.status_code == 200
    assert buyer_view.json()["current_lowest_bid"] == "65.00"
    supplier_marketplace = await client.get("/api/rfqs", headers=auth(trailing_supplier))
    assert supplier_marketplace.json()["items"][0]["current_lowest_bid"] is None


@pytest.mark.anyio
async def test_supplier_capabilities_and_marketplace_filters(client):
    buyer = await register(client, "buyer-category-filter", "buyer")
    supplier = await register(client, "supplier-category-filter")
    supplier_without_capabilities = await register(client, "supplier-no-capabilities")

    road_rfq = await create_rfq(
        client,
        buyer,
        name="Delhi to Mumbai full truckload",
        origin="Delhi",
        destination="Mumbai",
        transport_modes=["road"],
        services=["ftl"],
    )
    air_rfq = await create_rfq(
        client,
        buyer,
        name="Air express shipment",
        origin="Pune",
        destination="Chennai",
        transport_modes=["air"],
        services=["express"],
    )

    supplier_profile = await client.get("/api/suppliers/me", headers=auth(supplier))
    assert supplier_profile.status_code == 200
    assert supplier_profile.json()["transport_modes"] == []

    saved = await client.put(
        "/api/suppliers/me/capabilities",
        json={"transport_modes": ["road"], "services": ["ftl"]},
        headers=auth(supplier),
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["transport_modes"] == ["road"]
    assert saved.json()["services"] == ["ftl"]

    filtered = await client.get(
        "/api/rfqs",
        params={"transport_mode": "road", "service": "ftl", "origin": "del", "destination": "mum"},
        headers=auth(supplier),
    )
    assert filtered.status_code == 200
    assert [item["id"] for item in filtered.json()["items"]] == [road_rfq["id"]]

    matches = await client.get("/api/rfqs?matching_only=true", headers=auth(supplier))
    assert matches.status_code == 200
    matched_ids = {item["id"] for item in matches.json()["items"]}
    assert road_rfq["id"] in matched_ids
    assert air_rfq["id"] not in matched_ids

    no_matches = await client.get("/api/rfqs?matching_only=true", headers=auth(supplier_without_capabilities))
    assert no_matches.status_code == 200 and no_matches.json()["items"] == []

    reversed_dates = await client.get(
        "/api/rfqs",
        params={"pickup_from": "2027-12-31", "pickup_to": "2027-01-01"},
        headers=auth(supplier),
    )
    assert reversed_dates.status_code == 422

    buyer_cannot_set_capabilities = await client.put(
        "/api/suppliers/me/capabilities",
        json={"transport_modes": ["road"], "services": []},
        headers=auth(buyer),
    )
    assert buyer_cannot_set_capabilities.status_code == 403


@pytest.mark.anyio
async def test_rfq_list_paginates_and_reports_total(client):
    buyer = await register(client, "buyer-pagination", "buyer")
    before = await client.get("/api/rfqs?page=1&page_size=100", headers=auth(buyer))
    before_total = before.json()["total"]
    await create_rfq(client, buyer)
    await create_rfq(client, buyer)

    first = await client.get("/api/rfqs?page=1&page_size=1", headers=auth(buyer))
    second = await client.get("/api/rfqs?page=2&page_size=1", headers=auth(buyer))
    assert first.status_code == second.status_code == 200
    assert first.json()["total"] == before_total + 2
    assert first.json()["has_more"] is True
    assert second.json()["has_more"] is (before_total + 2 > 2)
    assert first.json()["items"][0]["id"] != second.json()["items"][0]["id"]
    last_page = await client.get(f"/api/rfqs?page={before_total + 2}&page_size=1", headers=auth(buyer))
    assert last_page.json()["has_more"] is False


@pytest.mark.anyio
async def test_buyers_only_list_and_open_their_own_rfqs(client):
    buyer_a = await register(client, "buyer-owner-a", "buyer")
    buyer_b = await register(client, "buyer-owner-b", "buyer")
    rfq_a = await create_rfq(client, buyer_a)
    rfq_b = await create_rfq(client, buyer_b)

    listed = await client.get("/api/rfqs", headers=auth(buyer_a))
    assert listed.status_code == 200
    assert listed.json()["total"] == 1
    assert [item["reference_id"] for item in listed.json()["items"]] == [rfq_a["reference_id"]]
    hidden = await client.get(f"/api/rfqs/{rfq_b['id']}", headers=auth(buyer_a))
    own = await client.get(f"/api/rfqs/{rfq_a['id']}", headers=auth(buyer_a))
    assert hidden.status_code == 404
    assert own.status_code == 200


@pytest.mark.anyio
async def test_account_activity_tracks_buyer_rfqs_and_supplier_bids(client):
    buyer = await register(client, "buyer-activity", "buyer")
    supplier = await register(client, "supplier-activity")
    empty_history = await client.get("/api/buyers/me/activity", headers=auth(buyer))
    assert empty_history.status_code == 200 and empty_history.json()["items"] == []

    rfq = await create_rfq(client, buyer, remarks="Deliver on weekdays; provide liftgate service.")
    immediate_history = await client.get("/api/buyers/me/activity", headers=auth(buyer))
    assert immediate_history.status_code == 200
    assert immediate_history.json()["items"][0]["auction_id"] == rfq["reference_id"]

    supplier_detail = await client.get(f"/api/rfqs/{rfq['id']}", headers=auth(supplier))
    assert supplier_detail.status_code == 200
    assert supplier_detail.json()["remarks"] == "Deliver on weekdays; provide liftgate service."

    buyer_history = await client.get("/api/buyers/me/activity", headers=auth(buyer))
    assert buyer_history.status_code == 200
    assert buyer_history.json()["items"][0]["auction_id"] == rfq["reference_id"]

    submitted = await bid(client, supplier, rfq["id"], "supplier-history-bid", 100)
    assert submitted.status_code == 201
    supplier_history = await client.get("/api/suppliers/me/activity", headers=auth(supplier))
    assert supplier_history.status_code == 200
    assert supplier_history.json()["items"][0]["auction_id"] == rfq["reference_id"]
    assert supplier_history.json()["items"][0]["bid_status"] == "Accepted"
    assert supplier_history.json()["items"][0]["amount"] == "115.00"


@pytest.mark.anyio
async def test_rfq_quote_filters_and_bid_pagination(client):
    buyer = await register(client, "buyer-filter-pages", "buyer")
    suppliers = [await register(client, f"supplier-filter-pages-{index}") for index in range(4)]
    rfq = await create_rfq(client, buyer, remarks="Palletized freight; rear loading dock.")
    other_rfq = await create_rfq(client, buyer, name="No notes request", remarks=None)
    for index, token in enumerate(suppliers):
        response = await bid(client, token, rfq["id"], f"filter-pages-key-{index}", 100 - index * 10)
        assert response.status_code == 201

    with_quotes = await client.get("/api/rfqs?has_bids=true", headers=auth(buyer))
    assert rfq["id"] in {item["id"] for item in with_quotes.json()["items"]}
    assert other_rfq["id"] not in {item["id"] for item in with_quotes.json()["items"]}
    with_notes = await client.get("/api/rfqs?has_remarks=true", headers=auth(buyer))
    assert rfq["id"] in {item["id"] for item in with_notes.json()["items"]}
    assert other_rfq["id"] not in {item["id"] for item in with_notes.json()["items"]}
    closing_soon = await client.get("/api/rfqs?closing_soon=true", headers=auth(buyer))
    assert rfq["id"] in {item["id"] for item in closing_soon.json()["items"]}

    first_page = await client.get(f"/api/rfqs/{rfq['id']}?bid_page=1&bid_page_size=2", headers=auth(buyer))
    second_page = await client.get(f"/api/rfqs/{rfq['id']}?bid_page=2&bid_page_size=2", headers=auth(buyer))
    assert first_page.status_code == second_page.status_code == 200
    assert first_page.json()["bid_total"] == 4 and first_page.json()["bid_has_more"] is True
    assert len(first_page.json()["bids"]) == len(second_page.json()["bids"]) == 2
    assert {item["id"] for item in first_page.json()["bids"]}.isdisjoint({item["id"] for item in second_page.json()["bids"]})

    filtered_bids = await client.get(
        f"/api/rfqs/{rfq['id']}?leaders_only=true&top_three=true&bid_page_size=10",
        headers=auth(buyer),
    )
    assert filtered_bids.json()["bid_total"] == 3
    assert all(item["rank"] in (1, 2, 3) for item in filtered_bids.json()["bids"])
    supplier_view = await client.get(f"/api/rfqs/{rfq['id']}?leaders_only=true", headers=auth(suppliers[-1]))
    assert supplier_view.status_code == 200
    assert all(item["supplier_id"] == int(supplier_view.json()["bids"][0]["supplier_id"]) for item in supplier_view.json()["bids"])
    assert supplier_view.json()["current_lowest_bid"] is None


@pytest.mark.anyio
async def test_status_filters_include_expired_active_rows_and_transition_them(client):
    buyer = await register(client, "buyer-stale-status", "buyer")
    expired = await create_rfq(client, buyer, **schedule(-60, -30, 60))
    forced = await create_rfq(client, buyer, name="Expired hard stop", **schedule(-120, -60, -30))
    closed = await client.get("/api/rfqs?status=closed", headers=auth(buyer))
    force_closed = await client.get("/api/rfqs?status=force_closed", headers=auth(buyer))
    assert closed.status_code == force_closed.status_code == 200
    assert next(item for item in closed.json()["items"] if item["id"] == expired["id"])["status"] == "closed"
    assert next(item for item in force_closed.json()["items"] if item["id"] == forced["id"])["status"] == "force_closed"


@pytest.mark.anyio
async def test_role_scoped_analytics_and_activity_pagination(client):
    buyer = await register(client, "buyer-analytics-pages", "buyer")
    supplier = await register(client, "supplier-analytics-pages")
    rfqs = [await create_rfq(client, buyer, name=f"Analytics RFQ {index}") for index in range(2)]
    for index, rfq in enumerate(rfqs):
        assert (await bid(client, supplier, rfq["id"], f"analytics-bid-{index}", 90 - index * 10)).status_code == 201

    buyer_page = await client.get("/api/buyers/me/activity?page=1&page_size=1", headers=auth(buyer))
    supplier_page = await client.get("/api/suppliers/me/activity?page=2&page_size=1", headers=auth(supplier))
    general_page = await client.get("/api/auth/activity?page=1&page_size=1", headers=auth(buyer))
    assert buyer_page.status_code == supplier_page.status_code == 200
    assert general_page.status_code == 200 and general_page.json()["items"][0]["action"] == "Created RFQ"
    assert buyer_page.json()["total"] == 2 and buyer_page.json()["has_more"] is True
    assert len(buyer_page.json()["items"]) == 1
    assert supplier_page.json()["total"] == 2 and supplier_page.json()["has_more"] is False
    assert len(supplier_page.json()["items"]) == 1

    buyer_stats = await client.get("/api/buyers/me/analytics", headers=auth(buyer))
    supplier_stats = await client.get("/api/suppliers/me/analytics", headers=auth(supplier))
    assert buyer_stats.status_code == supplier_stats.status_code == 200
    assert buyer_stats.json()["rfq_total"] == 2 and buyer_stats.json()["quote_total"] == 2
    assert supplier_stats.json()["quote_total"] == 2 and supplier_stats.json()["auctions_quoted"] == 2
    assert supplier_stats.json()["leading_quotes"] <= supplier_stats.json()["auctions_quoted"]
    assert (await client.get("/api/admin/analytics", headers=auth(buyer))).status_code == 403


@pytest.mark.anyio
async def test_admin_directory_filters_analytics_and_detail_pagination(client):
    admin_token = await register(client, "admin-console-pages", "buyer")
    buyer = await register(client, "buyer-admin-pages", "buyer")
    supplier = await register(client, "supplier-admin-pages")
    rfqs = [await create_rfq(client, buyer, name=f"Admin RFQ {index}") for index in range(2)]
    for index, rfq in enumerate(rfqs):
        assert (await bid(client, supplier, rfq["id"], f"admin-bid-{index}", 80 - index * 10)).status_code == 201
    await promote_to_admin("admin-console-pages")
    login = await client.post("/api/auth/admin/token", data={"username": "admin-console-pages", "password": "strong-password-123"})
    assert login.status_code == 200
    admin_token = login.json()["access_token"]

    users = await client.get("/api/admin/users?role=buyer&search=buyer-admin-pages&page=1&page_size=1&has_activity=true", headers=auth(admin_token))
    assert users.status_code == 200
    assert users.json()["total"] == 1 and users.json()["items"][0]["username"] == "buyer-admin-pages"
    admin_only = await client.get("/api/admin/users?admin_only=true", headers=auth(admin_token))
    assert all(item["is_admin"] for item in admin_only.json()["items"])

    buyer_detail = await client.get(f"/api/admin/buyers/{(await client.get('/api/buyers/me', headers=auth(buyer))).json()['id']}?page=2&page_size=1", headers=auth(admin_token))
    supplier_profile = (await client.get("/api/suppliers/me", headers=auth(supplier))).json()
    supplier_detail = await client.get(f"/api/admin/suppliers/{supplier_profile['id']}?page=2&page_size=1", headers=auth(admin_token))
    assert buyer_detail.status_code == supplier_detail.status_code == 200
    assert buyer_detail.json()["activity_total"] == 2 and len(buyer_detail.json()["auctions_created"]) == 1
    assert supplier_detail.json()["activity_total"] == 2 and len(supplier_detail.json()["quotations_submitted"]) == 1

    stats = await client.get("/api/admin/analytics", headers=auth(admin_token))
    assert stats.status_code == 200
    assert stats.json()["user_total"] >= 3 and stats.json()["rfq_total"] >= 2 and stats.json()["quote_total"] >= 2
    dashboard = await client.get("/admin")
    assert dashboard.status_code == 200 and "Admin overview" in dashboard.text and "Marketplace activity" in dashboard.text
    directory = await client.get("/admin/users?role=buyer&search=buyer-admin-pages&page_size=1")
    assert directory.status_code == 200 and "Senior admins only" in directory.text
    search_results = await client.get(
        "/admin/users?search=supplier-admin-pages&role=&page_size=10&has_activity=true"
    )
    assert search_results.status_code == 200
    assert search_results.headers["content-type"].startswith("text/html")
    assert "supplier-admin-pages" in search_results.text
    assert f"/admin/users/{supplier_profile['id']}" in search_results.text
    user_activity = await client.get(f"/admin/users/{supplier_profile['id']}?page=1&page_size=10")
    assert user_activity.status_code == 200
    assert user_activity.headers["content-type"].startswith("text/html")
    assert "Submitted quotation" in user_activity.text and "Admin RFQ 0" in user_activity.text
    bad_browser_filter = await client.get("/admin/users?page=0")
    assert bad_browser_filter.status_code == 422
    assert bad_browser_filter.headers["content-type"].startswith("text/html")
    assert "Check your filters" in bad_browser_filter.text
    bad_role_browser = await client.get("/admin/users?role=carrier")
    assert bad_role_browser.status_code == 422
    assert bad_role_browser.headers["content-type"].startswith("text/html")
    assert "Choose buyer, supplier, or all account types" in bad_role_browser.text
    blank_role_api = await client.get("/api/admin/users?role=", headers=auth(admin_token))
    assert blank_role_api.status_code == 200
    invalid_api = await client.get("/api/admin/users?page=0", headers=auth(admin_token))
    assert invalid_api.status_code == 422
    assert invalid_api.headers["content-type"].startswith("application/json")
    assert "input" not in invalid_api.json()["detail"][0]
    auction_list = await client.get("/admin/auctions?has_bids=true&status=active&page_size=1")
    assert auction_list.status_code == 200 and "Auction oversight" in auction_list.text
    auction_detail = await client.get(f"/admin/auctions/{rfqs[0]['id']}?leaders_only=true&top_three=true&page_size=1")
    assert auction_detail.status_code == 200 and "Quote ranking and history" in auction_detail.text
