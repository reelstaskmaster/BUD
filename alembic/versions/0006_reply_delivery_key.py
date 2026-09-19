"""add reply delivery idempotency key

Revision ID: 0006_reply_delivery_key
Revises: 0005_reply_deliveries
"""

from alembic import op
import sqlalchemy as sa

revision = "0006_reply_delivery_key"
down_revision = "0005_reply_deliveries"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    op.add_column("reply_deliveries", sa.Column("delivery_key", sa.String(length=64), nullable=True))
    op.execute(
        """
        UPDATE reply_deliveries
        SET delivery_key = encode(
            digest(
                chat_id::text || ':' ||
            (
                SELECT string_agg(value, ',' ORDER BY value)
                FROM json_array_elements_text(source_message_ids)
            )
        )
        """
    )
    op.alter_column("reply_deliveries", "delivery_key", nullable=False)
    op.create_index(
        "uq_reply_deliveries_key",
        "reply_deliveries",
        ["delivery_key"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_reply_deliveries_key", table_name="reply_deliveries")
    op.drop_column("reply_deliveries", "delivery_key")
