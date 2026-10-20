"""Durable ingestion jobs and document index versions.

Revision ID: r3_ingest_jobs
Revises: r2_sentences
"""

import sqlalchemy as sa
from alembic import op

revision = "r3_ingest_jobs"
down_revision = "r2_sentences"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("index_version", sa.String(200), nullable=True))
    op.create_table(
        "ingest_jobs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "document_id",
            sa.Uuid(),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("index_version", sa.String(200), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("stage", sa.String(40), nullable=False),
        sa.Column("progress", sa.Integer(), nullable=False),
        sa.Column(
            "run_after", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("lease_owner", sa.String(100), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('queued','running','succeeded','failed')", name="ingest_job_status"
        ),
        sa.CheckConstraint("kind IN ('ingest','reindex')", name="ingest_job_kind"),
    )
    op.create_index("ix_ingest_jobs_document_id", "ingest_jobs", ["document_id"])
    op.create_index("ix_ingest_jobs_claim", "ingest_jobs", ["status", "run_after"])
    op.create_index(
        "uq_ingest_jobs_active_document",
        "ingest_jobs",
        ["document_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('queued','running')"),
    )


def downgrade() -> None:
    op.drop_table("ingest_jobs")
    op.drop_column("documents", "index_version")
