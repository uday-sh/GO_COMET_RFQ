import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from tests.conftest import auth, register


def schedule(start_offset=0, close_offset=30, forced_offset=60):
    now = datetime.now(UTC)
    return {
        "bid_start_at": (now + timedelta(minutes=start_offset)).isoformat(),
        "initial_close_at": (now + timedelta(minutes=close_offset)).isoformat(),
        "forced_close_at": (now + timedelta(minutes=forced_offset)).isoformat(),
        "pickup_service_date": (now + timedelta(days=2)).date().isoformat(),
    }


async def create_rfq(client, token, mode="bid_received", **overrides):
    body = {"name": "Northstar linehaul", "trigger_window_minutes": 10, "extension_duration_minutes": 5, "trigger_mode": mode, **schedule(-1, 30, 60), **overrides}
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
    assert detail.json()["bids"][0]["supplier_name"] == "supplier-bid-limit-own"
    assert detail.json()["bids"][0]["rank"] == 2


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
    assert empty_history.status_code == 200 and empty_history.json() == []

    rfq = await create_rfq(client, buyer, remarks="Deliver on weekdays; provide liftgate service.")
    immediate_history = await client.get("/api/buyers/me/activity", headers=auth(buyer))
    assert immediate_history.status_code == 200
    assert immediate_history.json()[0]["auction_id"] == rfq["reference_id"]

    supplier_detail = await client.get(f"/api/rfqs/{rfq['id']}", headers=auth(supplier))
    assert supplier_detail.status_code == 200
    assert supplier_detail.json()["remarks"] == "Deliver on weekdays; provide liftgate service."

    buyer_history = await client.get("/api/buyers/me/activity", headers=auth(buyer))
    assert buyer_history.status_code == 200
    assert buyer_history.json()[0]["auction_id"] == rfq["reference_id"]

    submitted = await bid(client, supplier, rfq["id"], "supplier-history-bid", 100)
    assert submitted.status_code == 201
    supplier_history = await client.get("/api/suppliers/me/activity", headers=auth(supplier))
    assert supplier_history.status_code == 200
    assert supplier_history.json()[0]["auction_id"] == rfq["reference_id"]
    assert supplier_history.json()[0]["bid_status"] == "Accepted"
    assert supplier_history.json()[0]["amount"] == "115.00"
