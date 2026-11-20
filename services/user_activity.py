from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

import models
from schemas import AccountActivityItem, BuyerActivityItem, SupplierActivityItem


async def get_buyer_activity(db: AsyncSession, user_id: int, limit: int = 50, offset: int = 0) -> list[BuyerActivityItem]:
    rows = (
        await db.execute(
            select(models.RFQ)
            .where(models.RFQ.buyer_id == user_id)
            .order_by(models.RFQ.created_at.desc(), models.RFQ.id.desc())
            .offset(offset)
            .limit(limit)
        )
    ).scalars().all()
    return [
        BuyerActivityItem(
            rfq_id=rfq.id,
            auction_id=rfq.reference_id,
            auction_name=rfq.name,
            status=rfq.status,
            created_at=rfq.created_at,
        )
        for rfq in rows
    ]


async def get_supplier_activity(db: AsyncSession, user_id: int, limit: int = 50, offset: int = 0) -> list[SupplierActivityItem]:
    rows = (
        await db.execute(
            select(models.Bid)
            .where(models.Bid.supplier_id == user_id)
            .options(selectinload(models.Bid.rfq))
            .order_by(models.Bid.submitted_at.desc(), models.Bid.id.desc())
            .offset(offset)
            .limit(limit)
        )
    ).scalars().all()
    return [
        SupplierActivityItem(
            bid_id=bid.id,
            rfq_id=bid.rfq_id,
            auction_id=bid.rfq.reference_id,
            auction_name=bid.rfq.name,
            bid_status="Accepted" if bid.accepted else "Rejected",
            amount=bid.comparison_total,
            submitted_at=bid.submitted_at,
        )
        for bid in rows
    ]


async def count_account_activity(db: AsyncSession, user_id: int, role: str) -> int:
    if role == "buyer":
        count = await db.scalar(select(func.count()).select_from(models.RFQ).where(models.RFQ.buyer_id == user_id))
    else:
        count = await db.scalar(select(func.count()).select_from(models.Bid).where(models.Bid.supplier_id == user_id))
    return count or 0


async def get_account_activity(db: AsyncSession, user_id: int, role: str, limit: int = 50, offset: int = 0) -> list[AccountActivityItem]:
    if role == "buyer":
        return [
            AccountActivityItem(
                id=item.rfq_id,
                action="Created RFQ",
                reference_id=item.auction_id,
                item_name=item.auction_name,
                status=item.status,
                occurred_at=item.created_at,
            )
            for item in await get_buyer_activity(db, user_id, limit, offset)
        ]

    return [
        AccountActivityItem(
            id=item.bid_id,
            action="Submitted quotation",
            reference_id=item.auction_id,
            item_name=item.auction_name,
            status=item.bid_status,
            amount=item.amount,
            occurred_at=item.submitted_at,
        )
        for item in await get_supplier_activity(db, user_id, limit, offset)
    ]
