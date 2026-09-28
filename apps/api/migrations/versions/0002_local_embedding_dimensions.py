"""Use 1024-dimensional vectors for the local Qwen embedding model.

Revision ID: 0002
Revises: 0001
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Different dimensions cannot share one pgvector column. Preserve legacy vectors for a
    # controlled reindex/export instead of deleting user data. New rows use the new column.
    op.execute("ALTER TABLE document_chunks RENAME COLUMN embedding TO embedding_legacy_1536")
    op.execute("ALTER TABLE document_chunks ALTER COLUMN embedding_legacy_1536 DROP NOT NULL")
    op.execute("ALTER TABLE document_chunks ADD COLUMN embedding vector(1024)")


def downgrade() -> None:
    op.execute("ALTER TABLE document_chunks DROP COLUMN embedding")
    op.execute("ALTER TABLE document_chunks RENAME COLUMN embedding_legacy_1536 TO embedding")
