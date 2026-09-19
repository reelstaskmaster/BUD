"""Add a database lease for per-chat processing."""

from alembic import op
import sqlalchemy as sa

revision = "0004_chat_processing_lease"
down_revision = "0003_telegram_message_id"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("chats", sa.Column("processing_owner", sa.String(length=64), nullable=True))
    op.add_column("chats", sa.Column("processing_until", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("chats", "processing_until")
    op.drop_column("chats", "processing_owner")
