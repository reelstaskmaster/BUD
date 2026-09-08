"""Add purchase terms acceptance to user profiles."""

from alembic import op
import sqlalchemy as sa

revision = "0004_terms_acceptance"
down_revision = "0003_settings_payments"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user_profiles",
        sa.Column("terms_accepted", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("user_profiles", "terms_accepted")
