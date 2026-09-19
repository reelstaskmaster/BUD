"""Persist source MIME type for media messages."""

from alembic import op
import sqlalchemy as sa

revision = "0002_message_media_mime"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "messages",
        sa.Column("media_mime_type", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("messages", "media_mime_type")
