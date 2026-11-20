from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


def utc_now() -> datetime:
    return datetime.now(UTC)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    email: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="supplier", server_default="supplier")
    is_admin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    rfqs: Mapped[list[RFQ]] = relationship(back_populates="buyer", cascade="all, delete-orphan")
    bids: Mapped[list[Bid]] = relationship(back_populates="supplier")

    __table_args__ = (CheckConstraint("role IN ('buyer', 'supplier')", name="ck_users_role"),)


class RFQ(Base):
    __tablename__ = "rfqs"

    id: Mapped[int] = mapped_column(primary_key=True)
    reference_id: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    remarks: Mapped[str | None] = mapped_column(Text, nullable=True)
    buyer_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    bid_start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    initial_close_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    current_close_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    forced_close_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    pickup_service_date: Mapped[date] = mapped_column(Date, nullable=False)
    trigger_window_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    extension_duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    trigger_mode: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active", server_default="active", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

    buyer: Mapped[User] = relationship(back_populates="rfqs")
    bids: Mapped[list[Bid]] = relationship(back_populates="rfq", cascade="all, delete-orphan")
    extensions: Mapped[list[AuctionExtension]] = relationship(back_populates="rfq", cascade="all, delete-orphan")
    activities: Mapped[list[AuctionActivity]] = relationship(back_populates="rfq", cascade="all, delete-orphan")

    __table_args__ = (
        CheckConstraint("bid_start_at < initial_close_at", name="ck_rfqs_start_before_initial_close"),
        CheckConstraint("initial_close_at < forced_close_at", name="ck_rfqs_initial_before_forced_close"),
        CheckConstraint("current_close_at <= forced_close_at", name="ck_rfqs_current_before_forced_close"),
        CheckConstraint("trigger_window_minutes > 0", name="ck_rfqs_trigger_window_positive"),
        CheckConstraint("extension_duration_minutes > 0", name="ck_rfqs_extension_positive"),
        CheckConstraint("trigger_mode IN ('bid_received', 'rank_change', 'l1_change')", name="ck_rfqs_trigger_mode"),
        CheckConstraint("status IN ('active', 'closed', 'force_closed')", name="ck_rfqs_status"),
    )


class Bid(Base):
    __tablename__ = "bids"

    id: Mapped[int] = mapped_column(primary_key=True)
    rfq_id: Mapped[int] = mapped_column(ForeignKey("rfqs.id", ondelete="CASCADE"), nullable=False, index=True)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(80), nullable=False)
    carrier_name: Mapped[str] = mapped_column(String(160), nullable=False)
    freight_charges: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    origin_charges: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    destination_charges: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    comparison_total: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    transit_time_hours: Mapped[int] = mapped_column(Integer, nullable=False)
    quote_valid_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    accepted: Mapped[bool] = mapped_column(nullable=False, default=True, server_default="1")
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    rfq: Mapped[RFQ] = relationship(back_populates="bids")
    supplier: Mapped[User] = relationship(back_populates="bids")

    __table_args__ = (
        UniqueConstraint("rfq_id", "supplier_id", "idempotency_key", name="uq_bid_idempotency"),
        CheckConstraint("freight_charges >= 0 AND origin_charges >= 0 AND destination_charges >= 0", name="ck_bid_charges_nonnegative"),
        CheckConstraint("comparison_total = freight_charges + origin_charges + destination_charges", name="ck_bid_total_matches_charges"),
        CheckConstraint("transit_time_hours > 0", name="ck_bid_transit_positive"),
        Index("ix_bids_rfq_accepted_total_time", "rfq_id", "accepted", "comparison_total", "submitted_at"),
    )


class AuctionExtension(Base):
    __tablename__ = "auction_extensions"

    id: Mapped[int] = mapped_column(primary_key=True)
    rfq_id: Mapped[int] = mapped_column(ForeignKey("rfqs.id", ondelete="CASCADE"), nullable=False, index=True)
    bid_id: Mapped[int | None] = mapped_column(ForeignKey("bids.id", ondelete="SET NULL"), nullable=True)
    triggered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    previous_close_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    new_close_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    trigger_reason: Mapped[str] = mapped_column(String(80), nullable=False)

    rfq: Mapped[RFQ] = relationship(back_populates="extensions")


class AuctionActivity(Base):
    __tablename__ = "auction_activities"

    id: Mapped[int] = mapped_column(primary_key=True)
    rfq_id: Mapped[int] = mapped_column(ForeignKey("rfqs.id", ondelete="CASCADE"), nullable=False, index=True)
    bid_id: Mapped[int | None] = mapped_column(ForeignKey("bids.id", ondelete="SET NULL"), nullable=True)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    message: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False, index=True)

    rfq: Mapped[RFQ] = relationship(back_populates="activities")
