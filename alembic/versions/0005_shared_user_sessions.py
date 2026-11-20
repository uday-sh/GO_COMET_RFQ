"""Persist revocable login sessions across application replicas."""

from alembic import op
import sqlalchemy as sa


revision = "0005_shared_user_sessions"
down_revision = "0004_freight_categories"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_sessions",
        sa.Column("id", sa.String(length=80), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_user_sessions_expires_at", "user_sessions", ["expires_at"])
    op.create_index("ix_user_sessions_user_expires", "user_sessions", ["user_id", "expires_at"])


def downgrade() -> None:
    op.drop_index("ix_user_sessions_user_expires", table_name="user_sessions")
    op.drop_index("ix_user_sessions_expires_at", table_name="user_sessions")
    op.drop_table("user_sessions")
