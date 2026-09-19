"""add reply delivery retry schedule

Revision ID: 0007_reply_delivery_retry
Revises: 0006_reply_delivery_key
"""

from alembic import op
import sqlalchemy as sa

revision = "0007_reply_delivery_retry"
down_revision = "0006_reply_delivery_key"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "reply_deliveries",
        sa.Column(
            "next_attempt_at",
            sa.DateTime(timezone=True),
            nullable=True,
            server_default=sa.text("now()"),
        ),
    )
    op.execute(
        "UPDATE reply_deliveries SET next_attempt_at = COALESCE(created_at, now())"
    )
    op.alter_column("reply_deliveries", "next_attempt_at", nullable=False)


def downgrade() -> None:
    op.drop_column("reply_deliveries", "next_attempt_at")
