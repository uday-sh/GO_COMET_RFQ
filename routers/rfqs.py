from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
import secrets
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

import models
from auth import CurrentUser, require_role
from database import get_db
from schemas import ActivityResponse, BidCreate, BidResponse, ExtensionResponse, PaginatedRFQs, RFQCreate, RFQDetail, RFQSummary

router = APIRouter(prefix="/rfqs", tags=["rfqs"])


def as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


async def database_now(db: AsyncSession) -> datetime:
    value = await db.scalar(select(func.current_timestamp()))
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    if value is None:
        value = datetime.now(UTC)
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value


async def sync_status(rfq: models.RFQ, now: datetime, db: AsyncSession) -> None:
    rfq.bid_start_at = as_utc(rfq.bid_start_at)
    rfq.current_close_at = as_utc(rfq.current_close_at)
    rfq.forced_close_at = as_utc(rfq.forced_close_at)
    new_status = rfq.status
    if rfq.status == "active" and now >= rfq.forced_close_at:
        new_status = "force_closed"
    elif rfq.status == "active" and now >= rfq.current_close_at:
        new_status = "closed"
    if new_status != rfq.status:
        rfq.status = new_status
        db.add(models.AuctionActivity(rfq_id=rfq.id, event_type="status_changed", message=f"Auction is now {new_status.replace('_', ' ').title()}"))


async def best_bids(db: AsyncSession, rfq_id: int) -> list[models.Bid]:
    result = await db.execute(
        select(models.Bid)
        .where(models.Bid.rfq_id == rfq_id, models.Bid.accepted.is_(True))
        .order_by(models.Bid.comparison_total.asc(), models.Bid.submitted_at.asc(), models.Bid.id.asc()),
    )
    best: dict[int, models.Bid] = {}
    for bid in result.scalars().all():
        best.setdefault(bid.supplier_id, bid)
    # SQLite drops timezone information when reading DateTime values. Normalize
    # persisted timestamps before this tie-break so equal-price bids from
    # separate requests cannot mix naive and aware datetimes.
    return sorted(best.values(), key=lambda bid: (bid.comparison_total, as_utc(bid.submitted_at), bid.id))


async def ranking_snapshot(db: AsyncSession, rfq_id: int) -> dict[int, int]:
    return {bid.supplier_id: index for index, bid in enumerate(await best_bids(db, rfq_id), start=1)}


def summary_from(rfq: models.RFQ, lowest: Decimal | None) -> RFQSummary:
    return RFQSummary(
        id=rfq.id,
        reference_id=rfq.reference_id,
        name=rfq.name,
        current_lowest_bid=lowest,
        bid_start_at=as_utc(rfq.bid_start_at),
        current_close_at=as_utc(rfq.current_close_at),
        forced_close_at=as_utc(rfq.forced_close_at),
        status=rfq.status,
        trigger_mode=rfq.trigger_mode,
    )


def bid_response(bid: models.Bid, rank: int | None) -> BidResponse:
    return BidResponse(
        id=bid.id,
        supplier_id=bid.supplier_id,
        supplier_name=bid.supplier.username,
        carrier_name=bid.carrier_name,
        freight_charges=bid.freight_charges,
        origin_charges=bid.origin_charges,
        destination_charges=bid.destination_charges,
        comparison_total=bid.comparison_total,
        transit_time_hours=bid.transit_time_hours,
        quote_valid_until=bid.quote_valid_until,
        submitted_at=bid.submitted_at,
        accepted=bid.accepted,
        rank=rank,
    )


@router.post("", response_model=RFQSummary, status_code=status.HTTP_201_CREATED)
async def create_rfq(payload: RFQCreate, current_user: Annotated[models.User, Depends(require_role("buyer"))], db: Annotated[AsyncSession, Depends(get_db)]):
    buyer_id = current_user.id
    await db.rollback()
    async with db.begin():
        rfq = models.RFQ(
            reference_id=f"NEW-{secrets.token_hex(8)}",
            name=payload.name.strip(),
            remarks=payload.remarks.strip() or None if payload.remarks else None,
            buyer_id=buyer_id,
            bid_start_at=payload.bid_start_at.astimezone(UTC),
            initial_close_at=payload.initial_close_at.astimezone(UTC),
            current_close_at=payload.initial_close_at.astimezone(UTC),
            forced_close_at=payload.forced_close_at.astimezone(UTC),
            pickup_service_date=payload.pickup_service_date,
            trigger_window_minutes=payload.trigger_window_minutes,
            extension_duration_minutes=payload.extension_duration_minutes,
            trigger_mode=payload.trigger_mode.value,
            status="active",
        )
        db.add(rfq)
        await db.flush()
        rfq.reference_id = f"RFQ-{datetime.now(UTC).year}-{rfq.id:06d}"
        if await db.scalar(select(models.RFQ.id).where(models.RFQ.reference_id == rfq.reference_id, models.RFQ.id != rfq.id)):
            rfq.reference_id = f"RFQ-{datetime.now(UTC).year}-{rfq.id:06d}-{secrets.token_hex(3).upper()}"
        activity_message = f"Created auction {rfq.reference_id}"
        db.add(models.AuctionActivity(rfq_id=rfq.id, actor_id=buyer_id, event_type="rfq_created", message=activity_message))
    return summary_from(rfq, None)


@router.get("", response_model=PaginatedRFQs)
async def list_rfqs(
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
):
    viewer_role = current_user.role
    viewer_id = current_user.id
    await db.rollback()
    rfq_filter = select(models.RFQ)
    count_filter = select(func.count()).select_from(models.RFQ)
    if viewer_role == "buyer":
        rfq_filter = rfq_filter.where(models.RFQ.buyer_id == viewer_id)
        count_filter = count_filter.where(models.RFQ.buyer_id == viewer_id)
    total = await db.scalar(count_filter) or 0
    start = (page - 1) * page_size
    rows = (
        await db.execute(
            rfq_filter
            .order_by(models.RFQ.created_at.desc(), models.RFQ.id.desc())
            .offset(start)
            .limit(page_size)
        )
    ).scalars().all()
    now = await database_now(db)
    for rfq in rows:
        await sync_status(rfq, now, db)
    if any(r.status != "active" for r in rows):
        await db.commit()
    lowest_by_rfq: dict[int, Decimal] = {}
    if rows:
        lowest_rows = await db.execute(
            select(models.Bid.rfq_id, func.min(models.Bid.comparison_total))
            .where(models.Bid.rfq_id.in_([rfq.id for rfq in rows]), models.Bid.accepted.is_(True))
            .group_by(models.Bid.rfq_id)
        )
        lowest_by_rfq = {rfq_id: lowest for rfq_id, lowest in lowest_rows.all()}
    items = [summary_from(rfq, lowest_by_rfq.get(rfq.id)) for rfq in rows]
    return PaginatedRFQs(items=items, total=total, page=page, page_size=page_size, has_more=start + len(items) < total)


@router.get("/{rfq_id}", response_model=RFQDetail)
async def get_rfq(rfq_id: int, current_user: CurrentUser, db: Annotated[AsyncSession, Depends(get_db)], bid_limit: Annotated[int, Query(ge=1, le=200)] = 100, activity_limit: Annotated[int, Query(ge=1, le=200)] = 100):
    viewer_role = current_user.role
    viewer_id = current_user.id
    await db.rollback()
    rfq = await db.scalar(select(models.RFQ).where(models.RFQ.id == rfq_id).options(selectinload(models.RFQ.extensions), selectinload(models.RFQ.activities)))
    if rfq is None:
        raise HTTPException(status_code=404, detail="RFQ not found")
    if viewer_role == "buyer" and rfq.buyer_id != viewer_id:
        raise HTTPException(status_code=404, detail="RFQ not found")
    now = await database_now(db)
    await sync_status(rfq, now, db)
    if rfq.status != "active":
        await db.commit()
    ranking = await ranking_snapshot(db, rfq.id)
    bid_query = select(models.Bid).where(models.Bid.rfq_id == rfq.id, models.Bid.accepted.is_(True))
    if viewer_role == "supplier":
        # Scope the supplier's own history before limiting, otherwise a page of
        # lower-priced competitors could crowd out this supplier's own quote.
        bid_query = bid_query.where(models.Bid.supplier_id == viewer_id)
    all_bids = (
        await db.execute(
            bid_query
            .options(selectinload(models.Bid.supplier))
            .order_by(models.Bid.comparison_total, models.Bid.submitted_at, models.Bid.id)
            .limit(bid_limit)
        )
    ).scalars().all()
    best = await best_bids(db, rfq.id)
    activities = sorted(rfq.activities, key=lambda activity: activity.created_at, reverse=True)[:activity_limit]
    return RFQDetail(
        **summary_from(rfq, best[0].comparison_total if best else None).model_dump(),
        initial_close_at=rfq.initial_close_at,
        remarks=rfq.remarks,
        pickup_service_date=rfq.pickup_service_date,
        trigger_window_minutes=rfq.trigger_window_minutes,
        extension_duration_minutes=rfq.extension_duration_minutes,
        bids=[bid_response(bid, ranking.get(bid.supplier_id) if bid.id in {item.id for item in best} else None) for bid in all_bids],
        extensions=[ExtensionResponse.model_validate(extension) for extension in sorted(rfq.extensions, key=lambda item: item.triggered_at, reverse=True)],
        activities=[ActivityResponse.model_validate(activity) for activity in activities],
    )


@router.post("/{rfq_id}/bids", response_model=BidResponse, status_code=status.HTTP_201_CREATED)
async def submit_bid(rfq_id: int, payload: BidCreate, current_user: Annotated[models.User, Depends(require_role("supplier"))], db: Annotated[AsyncSession, Depends(get_db)]):
    supplier_id = current_user.id
    await db.rollback()
    async with db.begin():
        rfq = await db.scalar(select(models.RFQ).where(models.RFQ.id == rfq_id).with_for_update())
        if rfq is None:
            raise HTTPException(status_code=404, detail="RFQ not found")
        duplicate = await db.scalar(select(models.Bid).where(models.Bid.rfq_id == rfq_id, models.Bid.supplier_id == supplier_id, models.Bid.idempotency_key == payload.idempotency_key).options(selectinload(models.Bid.supplier)))
        if duplicate:
            return bid_response(duplicate, None)
        now = await database_now(db)
        await sync_status(rfq, now, db)
        if rfq.status != "active":
            raise HTTPException(status_code=409, detail=f"Auction is {rfq.status.replace('_', ' ')}")
        if now < rfq.bid_start_at:
            raise HTTPException(status_code=409, detail="Auction has not started")
        if now >= rfq.current_close_at or now >= rfq.forced_close_at:
            raise HTTPException(status_code=409, detail="Auction deadline has passed")
        if payload.quote_valid_until.astimezone(UTC) <= now:
            raise HTTPException(status_code=422, detail="Quote validity must be in the future")

        before_ranks = await ranking_snapshot(db, rfq.id)
        before_l1 = min(before_ranks, key=before_ranks.get) if before_ranks else None
        latest = (await db.execute(select(models.Bid).where(models.Bid.rfq_id == rfq.id, models.Bid.supplier_id == supplier_id, models.Bid.accepted.is_(True)).order_by(models.Bid.comparison_total, models.Bid.submitted_at, models.Bid.id).limit(1))).scalar_one_or_none()
        total = (payload.freight_charges + payload.origin_charges + payload.destination_charges).quantize(Decimal("0.01"))
        if latest and total >= latest.comparison_total:
            raise HTTPException(status_code=422, detail=f"New quotation must be lower than your accepted best of {latest.comparison_total}")

        bid = models.Bid(rfq_id=rfq.id, supplier_id=supplier_id, idempotency_key=payload.idempotency_key, carrier_name=payload.carrier_name.strip(), freight_charges=payload.freight_charges, origin_charges=payload.origin_charges, destination_charges=payload.destination_charges, comparison_total=total, transit_time_hours=payload.transit_time_hours, quote_valid_until=payload.quote_valid_until.astimezone(UTC), submitted_at=now, accepted=True)
        db.add(bid)
        await db.flush()
        bid.supplier = current_user
        # Supplier activity feeds are visible to competitors; never put the
        # submitted amount in this shared event message.
        db.add(models.AuctionActivity(rfq_id=rfq.id, bid_id=bid.id, actor_id=supplier_id, event_type="bid_submitted", message="A supplier submitted a quotation"))
        after_ranks = await ranking_snapshot(db, rfq.id)
        after_l1 = min(after_ranks, key=after_ranks.get) if after_ranks else None
        rank_changed = before_ranks != after_ranks
        l1_changed = before_l1 != after_l1
        within_window = now >= rfq.current_close_at - timedelta(minutes=rfq.trigger_window_minutes)
        triggered = {"bid_received": True, "rank_change": rank_changed, "l1_change": l1_changed}[rfq.trigger_mode]
        if within_window and triggered and rfq.current_close_at < rfq.forced_close_at:
            previous = rfq.current_close_at
            rfq.current_close_at = min(rfq.current_close_at + timedelta(minutes=rfq.extension_duration_minutes), rfq.forced_close_at)
            reason = {"bid_received": "Bid received in trigger window", "rank_change": "Supplier ranking changed in trigger window", "l1_change": "L1 supplier changed in trigger window"}[rfq.trigger_mode]
            db.add(models.AuctionExtension(rfq_id=rfq.id, bid_id=bid.id, triggered_at=now, previous_close_at=previous, new_close_at=rfq.current_close_at, trigger_reason=reason))
            db.add(models.AuctionActivity(rfq_id=rfq.id, bid_id=bid.id, actor_id=supplier_id, event_type="auction_extended", message=f"{reason}; new close {rfq.current_close_at.isoformat()}"))
    return bid_response(bid, after_ranks.get(supplier_id))
