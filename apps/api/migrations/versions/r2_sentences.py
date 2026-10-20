"""Store sentence-level citations with assistant messages.

Revision ID: r2_sentences
Revises: r1_fts
"""

from alembic import op

revision = "r2_sentences"
down_revision = "r1_fts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE messages ADD COLUMN sentences jsonb NOT NULL DEFAULT '[]'::jsonb")


def downgrade() -> None:
    op.execute("ALTER TABLE messages DROP COLUMN sentences")
