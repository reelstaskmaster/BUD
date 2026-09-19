"""Add durable outbound reply delivery records."""

from alembic import op
import sqlalchemy as sa

revision = "0005_reply_deliveries"
down_revision = "0004_chat_processing_lease"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "reply_deliveries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("media_type", sa.String(length=32), nullable=False),
        sa.Column("image_bytes", sa.LargeBinary(), nullable=True),
        sa.Column("source_message_ids", sa.JSON(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["chat_id"], ["chats.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_reply_deliveries_chat_status",
        "reply_deliveries",
        ["chat_id", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_reply_deliveries_chat_status", table_name="reply_deliveries")
    op.drop_table("reply_deliveries")
