from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

import models
from schemas import AdminAnalytics, AmountPoint, BuyerAnalytics, MetricPoint, RFQStatus, SupplierAnalytics
from services.rfq_filters import current_status_filter


def _date_labels(days: int = 14) -> list[str]:
    today = datetime.now(UTC).date()
    return [(today - timedelta(days=offset)).isoformat() for offset in reversed(range(days))]


def _normalize_date(value) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


async def _daily_counts(db: AsyncSession, timestamp_column, owner_filter=None) -> dict[str, int]:
    start = datetime.combine(date.fromisoformat(_date_labels()[0]), time.min, UTC)
    statement = select(func.date(timestamp_column), func.count()).where(timestamp_column >= start)
    if owner_filter is not None:
        statement = statement.where(owner_filter)
    statement = statement.group_by(func.date(timestamp_column))
    return {_normalize_date(day): count for day, count in (await db.execute(statement)).all()}


async def _rfq_status_counts(db: AsyncSession, owner_id: int | None = None) -> dict[str, int]:
    now = datetime.now(UTC)
    counts: dict[str, int] = {}
    for rfq_status in RFQStatus:
        statement = select(func.count()).select_from(models.RFQ).where(current_status_filter(rfq_status, now))
        if owner_id is not None:
            statement = statement.where(models.RFQ.buyer_id == owner_id)
        counts[rfq_status.value] = await db.scalar(statement) or 0
    return counts


async def buyer_analytics(db: AsyncSession, buyer_id: int) -> BuyerAnalytics:
    rfq_total = await db.scalar(select(func.count()).select_from(models.RFQ).where(models.RFQ.buyer_id == buyer_id)) or 0
    status_counts = await _rfq_status_counts(db, buyer_id)
    quote_total = await db.scalar(
        select(func.count())
        .select_from(models.Bid)
        .join(models.RFQ, models.RFQ.id == models.Bid.rfq_id)
        .where(models.RFQ.buyer_id == buyer_id, models.Bid.accepted.is_(True))
    ) or 0
    daily = await _daily_counts(db, models.RFQ.created_at, models.RFQ.buyer_id == buyer_id)
    labels = _date_labels()
    return BuyerAnalytics(
        rfq_total=rfq_total,
        rfq_active=status_counts.get("active", 0),
        rfq_closed=status_counts.get("closed", 0) + status_counts.get("force_closed", 0),
        quote_total=quote_total,
        average_quotes_per_rfq=Decimal(quote_total) / Decimal(rfq_total) if rfq_total else Decimal("0"),
        status_breakdown=[MetricPoint(label=name.replace("_", " ").title(), value=status_counts.get(name, 0)) for name in ("active", "closed", "force_closed")],
        activity_trend=[MetricPoint(label=label, value=daily.get(label, 0)) for label in labels],
    )


async def supplier_analytics(db: AsyncSession, supplier_id: int) -> SupplierAnalytics:
    quote_total = await db.scalar(
        select(func.count()).select_from(models.Bid).where(models.Bid.supplier_id == supplier_id, models.Bid.accepted.is_(True))
    ) or 0
    auctions_quoted = await db.scalar(
        select(func.count(func.distinct(models.Bid.rfq_id))).where(models.Bid.supplier_id == supplier_id, models.Bid.accepted.is_(True))
    ) or 0
    leading_query = (
        select(
            models.Bid.supplier_id,
            func.row_number().over(
                partition_by=models.Bid.rfq_id,
                order_by=(models.Bid.comparison_total.asc(), models.Bid.submitted_at.asc(), models.Bid.id.asc()),
            ).label("position"),
        )
        .where(models.Bid.accepted.is_(True))
        .subquery()
    )
    leading_quotes = await db.scalar(
        select(func.count()).select_from(leading_query).where(
            leading_query.c.supplier_id == supplier_id,
            leading_query.c.position == 1,
        )
    ) or 0
    average_quote, best_quote = (
        await db.execute(
            select(func.avg(models.Bid.comparison_total), func.min(models.Bid.comparison_total))
            .where(models.Bid.supplier_id == supplier_id, models.Bid.accepted.is_(True))
        )
    ).one()
    start = datetime.combine(date.fromisoformat(_date_labels()[0]), time.min, UTC)
    trend_rows = await db.execute(
        select(func.date(models.Bid.submitted_at), func.count(), func.avg(models.Bid.comparison_total))
        .where(models.Bid.supplier_id == supplier_id, models.Bid.accepted.is_(True), models.Bid.submitted_at >= start)
        .group_by(func.date(models.Bid.submitted_at))
    )
    trend = {_normalize_date(day): (count, average) for day, count, average in trend_rows.all()}
    labels = _date_labels()
    return SupplierAnalytics(
        quote_total=quote_total,
        auctions_quoted=auctions_quoted,
        leading_quotes=leading_quotes,
        average_quote=Decimal(str(average_quote)) if average_quote is not None else None,
        best_quote=Decimal(str(best_quote)) if best_quote is not None else None,
        activity_trend=[
            AmountPoint(
                label=label,
                count=trend[label][0] if label in trend else 0,
                average_amount=Decimal(str(trend[label][1])) if label in trend and trend[label][1] is not None else None,
            )
            for label in labels
        ],
    )


async def admin_analytics(db: AsyncSession) -> AdminAnalytics:
    async def count(query) -> int:
        return await db.scalar(query) or 0

    user_total = await count(select(func.count()).select_from(models.User))
    buyer_total = await count(select(func.count()).select_from(models.User).where(models.User.role == "buyer"))
    supplier_total = await count(select(func.count()).select_from(models.User).where(models.User.role == "supplier"))
    admin_total = await count(select(func.count()).select_from(models.User).where(models.User.is_admin.is_(True)))
    rfq_total = await count(select(func.count()).select_from(models.RFQ))
    status_counts = await _rfq_status_counts(db)
    rfq_active = status_counts.get("active", 0)
    rfq_closed = status_counts.get("closed", 0) + status_counts.get("force_closed", 0)
    quote_total = await count(select(func.count()).select_from(models.Bid).where(models.Bid.accepted.is_(True)))
    rfq_daily = await _daily_counts(db, models.RFQ.created_at)
    bid_daily = await _daily_counts(db, models.Bid.submitted_at, models.Bid.accepted.is_(True))
    labels = _date_labels()
    return AdminAnalytics(
        user_total=user_total,
        buyer_total=buyer_total,
        supplier_total=supplier_total,
        admin_total=admin_total,
        rfq_total=rfq_total,
        rfq_active=rfq_active,
        rfq_closed=rfq_closed,
        quote_total=quote_total,
        status_breakdown=[MetricPoint(label=name.replace("_", " ").title(), value=status_counts.get(name, 0)) for name in ("active", "closed", "force_closed")],
        activity_trend=[MetricPoint(label=label, value=rfq_daily.get(label, 0) + bid_daily.get(label, 0)) for label in labels],
    )
