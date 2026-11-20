from datetime import UTC, datetime

from sqlalchemy import and_, or_

import models
from schemas import RFQStatus


def effective_status_value(status: str, current_close_at: datetime, forced_close_at: datetime, now: datetime) -> str:
    def as_utc(value: datetime) -> datetime:
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)

    now = as_utc(now)
    if status == "active" and now >= as_utc(forced_close_at):
        return "force_closed"
    if status == "active" and now >= as_utc(current_close_at):
        return "closed"
    return status


def current_status_filter(status: RFQStatus, now: datetime):
    if status == RFQStatus.ACTIVE:
        return and_(models.RFQ.status == "active", models.RFQ.current_close_at > now)
    if status == RFQStatus.CLOSED:
        return or_(
            models.RFQ.status == "closed",
            and_(models.RFQ.status == "active", models.RFQ.current_close_at <= now, models.RFQ.forced_close_at > now),
        )
    return or_(
        models.RFQ.status == "force_closed",
        and_(models.RFQ.status == "active", models.RFQ.forced_close_at <= now),
    )
