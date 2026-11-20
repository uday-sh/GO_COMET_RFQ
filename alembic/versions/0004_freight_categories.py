"""Add freight locations and supplier-matching categories."""

from alembic import op
import sqlalchemy as sa


revision = "0004_freight_categories"
down_revision = "0003_user_admin_flag"
branch_labels = None
depends_on = None


TRANSPORT_MODES = "'road', 'air', 'ocean', 'rail', 'multimodal', 'courier'"
SERVICES = "'ftl', 'ltl', 'fcl', 'lcl', 'reefer', 'hazmat', 'oversized', 'express', 'customs', 'warehousing', 'last_mile'"


def upgrade() -> None:
    op.add_column("rfqs", sa.Column("origin", sa.String(length=160), nullable=True))
    op.add_column("rfqs", sa.Column("destination", sa.String(length=160), nullable=True))

    op.create_table(
        "rfq_transport_modes",
        sa.Column("rfq_id", sa.Integer(), sa.ForeignKey("rfqs.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("mode", sa.String(length=30), primary_key=True),
        sa.CheckConstraint(f"mode IN ({TRANSPORT_MODES})", name="ck_rfq_transport_mode"),
    )
    op.create_table(
        "rfq_services",
        sa.Column("rfq_id", sa.Integer(), sa.ForeignKey("rfqs.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("service", sa.String(length=30), primary_key=True),
        sa.CheckConstraint(f"service IN ({SERVICES})", name="ck_rfq_service"),
    )
    op.create_table(
        "supplier_transport_modes",
        sa.Column("supplier_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("mode", sa.String(length=30), primary_key=True),
        sa.CheckConstraint(f"mode IN ({TRANSPORT_MODES})", name="ck_supplier_transport_mode"),
    )
    op.create_table(
        "supplier_services",
        sa.Column("supplier_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("service", sa.String(length=30), primary_key=True),
        sa.CheckConstraint(f"service IN ({SERVICES})", name="ck_supplier_service"),
    )
    # Give legacy RFQs a broad default so they remain visible to suppliers.
    op.execute("INSERT INTO rfq_transport_modes (rfq_id, mode) SELECT id, 'road' FROM rfqs")


def downgrade() -> None:
    op.drop_table("supplier_services")
    op.drop_table("supplier_transport_modes")
    op.drop_table("rfq_services")
    op.drop_table("rfq_transport_modes")
    op.drop_column("rfqs", "destination")
    op.drop_column("rfqs", "origin")
