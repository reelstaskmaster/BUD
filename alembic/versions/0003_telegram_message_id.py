"""Add Telegram message ids for duplicate update protection."""

from alembic import op
import sqlalchemy as sa

revision = "0003_telegram_message_id"
down_revision = "0002_message_media_mime"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("messages", sa.Column("telegram_message_id", sa.BigInteger(), nullable=True))
    op.create_index(
        "uq_messages_telegram_id",
        "messages",
        ["chat_id", "telegram_message_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_messages_telegram_id", table_name="messages")
    op.drop_column("messages", "telegram_message_id")
