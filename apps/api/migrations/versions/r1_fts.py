"""Full-text search columns for hybrid retrieval.

Two generated tsvector columns: 'english' (stemmed, stop words removed) for ordinary wording, and
'simple' (no stemming) so exact identifiers and numbers such as "800-61r3" or "HC-412" still match.
Generated columns fill existing rows during the migration and need no ingestion changes.

Revision ID: r1_fts
Revises: 0002
"""

from alembic import op

revision = "r1_fts"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for config in ("english", "simple"):
        op.execute(
            f"ALTER TABLE document_chunks ADD COLUMN fts_{config} tsvector "
            f"GENERATED ALWAYS AS (to_tsvector('{config}'::regconfig, text)) STORED"
        )
        op.execute(
            f"CREATE INDEX ix_document_chunks_fts_{config} "
            f"ON document_chunks USING gin (fts_{config})"
        )


def downgrade() -> None:
    for config in ("english", "simple"):
        op.execute(f"DROP INDEX ix_document_chunks_fts_{config}")
        op.execute(f"ALTER TABLE document_chunks DROP COLUMN fts_{config}")
