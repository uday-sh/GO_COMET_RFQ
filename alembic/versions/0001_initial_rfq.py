"""Create RFQ and British reverse auction tables.

Revision ID: 0001_initial_rfq
"""

from alembic import op
import sqlalchemy as sa

revision = "0001_initial_rfq"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("users", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("username", sa.String(50), nullable=False), sa.Column("email", sa.String(120), nullable=False), sa.Column("password_hash", sa.String(255), nullable=False), sa.Column("role", sa.String(20), server_default="supplier", nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.CheckConstraint("role IN ('buyer', 'supplier')", name="ck_users_role"), sa.UniqueConstraint("username"), sa.UniqueConstraint("email"))
    op.create_table("rfqs", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("reference_id", sa.String(40), nullable=False), sa.Column("name", sa.String(160), nullable=False), sa.Column("buyer_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False), sa.Column("bid_start_at", sa.DateTime(timezone=True), nullable=False), sa.Column("initial_close_at", sa.DateTime(timezone=True), nullable=False), sa.Column("current_close_at", sa.DateTime(timezone=True), nullable=False), sa.Column("forced_close_at", sa.DateTime(timezone=True), nullable=False), sa.Column("pickup_service_date", sa.Date(), nullable=False), sa.Column("trigger_window_minutes", sa.Integer(), nullable=False), sa.Column("extension_duration_minutes", sa.Integer(), nullable=False), sa.Column("trigger_mode", sa.String(30), nullable=False), sa.Column("status", sa.String(20), server_default="active", nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False), sa.CheckConstraint("bid_start_at < initial_close_at", name="ck_rfqs_start_before_initial_close"), sa.CheckConstraint("initial_close_at < forced_close_at", name="ck_rfqs_initial_before_forced_close"), sa.CheckConstraint("current_close_at <= forced_close_at", name="ck_rfqs_current_before_forced_close"), sa.CheckConstraint("trigger_mode IN ('bid_received', 'rank_change', 'l1_change')", name="ck_rfqs_trigger_mode"), sa.CheckConstraint("status IN ('active', 'closed', 'force_closed')", name="ck_rfqs_status"), sa.UniqueConstraint("reference_id"))
    op.create_index("ix_rfqs_buyer_id", "rfqs", ["buyer_id"])
    op.create_index("ix_rfqs_status", "rfqs", ["status"])
    op.create_table("bids", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("rfq_id", sa.Integer(), sa.ForeignKey("rfqs.id", ondelete="CASCADE"), nullable=False), sa.Column("supplier_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False), sa.Column("idempotency_key", sa.String(80), nullable=False), sa.Column("carrier_name", sa.String(160), nullable=False), sa.Column("freight_charges", sa.Numeric(18, 2), nullable=False), sa.Column("origin_charges", sa.Numeric(18, 2), nullable=False), sa.Column("destination_charges", sa.Numeric(18, 2), nullable=False), sa.Column("comparison_total", sa.Numeric(18, 2), nullable=False), sa.Column("transit_time_hours", sa.Integer(), nullable=False), sa.Column("quote_valid_until", sa.DateTime(timezone=True), nullable=False), sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False), sa.Column("accepted", sa.Boolean(), server_default=sa.true(), nullable=False), sa.Column("rejection_reason", sa.Text()), sa.CheckConstraint("freight_charges >= 0 AND origin_charges >= 0 AND destination_charges >= 0", name="ck_bid_charges_nonnegative"), sa.CheckConstraint("comparison_total = freight_charges + origin_charges + destination_charges", name="ck_bid_total_matches_charges"), sa.CheckConstraint("transit_time_hours > 0", name="ck_bid_transit_positive"), sa.UniqueConstraint("rfq_id", "supplier_id", "idempotency_key", name="uq_bid_idempotency"))
    op.create_index("ix_bids_rfq_id", "bids", ["rfq_id"])
    op.create_index("ix_bids_supplier_id", "bids", ["supplier_id"])
    op.create_index("ix_bids_rfq_accepted_total_time", "bids", ["rfq_id", "accepted", "comparison_total", "submitted_at"])
    op.create_table("auction_extensions", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("rfq_id", sa.Integer(), sa.ForeignKey("rfqs.id", ondelete="CASCADE"), nullable=False), sa.Column("bid_id", sa.Integer(), sa.ForeignKey("bids.id", ondelete="SET NULL")), sa.Column("triggered_at", sa.DateTime(timezone=True), nullable=False), sa.Column("previous_close_at", sa.DateTime(timezone=True), nullable=False), sa.Column("new_close_at", sa.DateTime(timezone=True), nullable=False), sa.Column("trigger_reason", sa.String(80), nullable=False))
    op.create_index("ix_auction_extensions_rfq_id", "auction_extensions", ["rfq_id"])
    op.create_table("auction_activities", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("rfq_id", sa.Integer(), sa.ForeignKey("rfqs.id", ondelete="CASCADE"), nullable=False), sa.Column("bid_id", sa.Integer(), sa.ForeignKey("bids.id", ondelete="SET NULL")), sa.Column("actor_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")), sa.Column("event_type", sa.String(40), nullable=False), sa.Column("message", sa.String(255), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_auction_activities_rfq_id", "auction_activities", ["rfq_id"])
    op.create_index("ix_auction_activities_created_at", "auction_activities", ["created_at"])


def downgrade() -> None:
    op.drop_table("auction_activities")
    op.drop_table("auction_extensions")
    op.drop_table("bids")
    op.drop_table("rfqs")
    op.drop_table("users")
