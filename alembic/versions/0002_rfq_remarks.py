"""Add buyer remarks to RFQs.

Revision ID: 0002_rfq_remarks
Revises: 0001_initial_rfq
"""

from alembic import op
import sqlalchemy as sa


revision = "0002_rfq_remarks"
down_revision = "0001_initial_rfq"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("rfqs", sa.Column("remarks", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("rfqs", "remarks")
