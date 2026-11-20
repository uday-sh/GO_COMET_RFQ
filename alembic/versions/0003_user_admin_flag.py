"""Add a separate admin privilege flag.

Revision ID: 0003_user_admin_flag
Revises: 0002_rfq_remarks
"""

from alembic import op
import sqlalchemy as sa


revision = "0003_user_admin_flag"
down_revision = "0002_rfq_remarks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("is_admin", sa.Boolean(), server_default=sa.false(), nullable=False))
    op.create_index("ix_users_is_admin", "users", ["is_admin"])


def downgrade() -> None:
    op.drop_index("ix_users_is_admin", table_name="users")
    op.drop_column("users", "is_admin")
