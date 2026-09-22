"""Switch memory embeddings to a free 2048-dimensional family."""

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

revision = "0008_free_embeddings"
down_revision = "0007_reply_delivery_retry"
branch_labels = None
depends_on = None

EMBEDDING_DIMS = 2048


def upgrade() -> None:
    # Existing 1536-dim vectors cannot be cast into the new embedding space.
    # Keep all durable facts/summaries but regenerate vectors lazily as they are used.
    op.execute("DROP INDEX IF EXISTS ix_facts_embedding")
    op.execute("DROP INDEX IF EXISTS ix_summaries_embedding")
    op.execute("UPDATE facts SET embedding = NULL")
    op.execute("UPDATE summaries SET embedding = NULL")
    op.alter_column(
        "facts",
        "embedding",
        existing_type=Vector(1536),
        type_=Vector(EMBEDDING_DIMS),
        existing_nullable=True,
    )
    op.alter_column(
        "summaries",
        "embedding",
        existing_type=Vector(1536),
        type_=Vector(EMBEDDING_DIMS),
        existing_nullable=True,
    )
    op.execute(
        "CREATE INDEX ix_facts_embedding ON facts "
        "USING hnsw (embedding vector_cosine_ops)"
    )
    op.execute(
        "CREATE INDEX ix_summaries_embedding ON summaries "
        "USING hnsw (embedding vector_cosine_ops)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_facts_embedding")
    op.execute("DROP INDEX IF EXISTS ix_summaries_embedding")
    op.execute("UPDATE facts SET embedding = NULL")
    op.execute("UPDATE summaries SET embedding = NULL")
    op.alter_column(
        "facts",
        "embedding",
        existing_type=Vector(EMBEDDING_DIMS),
        type_=Vector(1536),
        existing_nullable=True,
    )
    op.alter_column(
        "summaries",
        "embedding",
        existing_type=Vector(EMBEDDING_DIMS),
        type_=Vector(1536),
        existing_nullable=True,
    )
    op.execute(
        "CREATE INDEX ix_facts_embedding ON facts "
        "USING hnsw (embedding vector_cosine_ops)"
    )
    op.execute(
        "CREATE INDEX ix_summaries_embedding ON summaries "
        "USING hnsw (embedding vector_cosine_ops)"
    )
