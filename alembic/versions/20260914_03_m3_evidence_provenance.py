"""Anchor immutable forward evidence-provenance envelopes by run and evidence."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "m3evidenceprov001"
down_revision = "m3reviewexport001"
branch_labels = None
depends_on = None

_UUID4 = "[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}"


def upgrade() -> None:
    op.create_table(
        "m3_evidence_provenance",
        sa.Column("run_id", sa.String(40), nullable=False),
        sa.Column("evidence_id", sa.String(80), nullable=False),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("snapshot_id", sa.String(160), nullable=False),
        sa.Column("envelope_id", sa.String(96), nullable=False),
        sa.Column("envelope_hash", sa.CHAR(71), nullable=False),
        sa.Column("relative_path", sa.String(160), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column(
            "persisted_at_utc",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.PrimaryKeyConstraint("run_id", "evidence_id", name="pk_m3_evidence_provenance"),
        sa.UniqueConstraint("envelope_id", name="uq_m3_evidence_provenance_envelope"),
        sa.CheckConstraint(
            f"run_id ~ '^run:{_UUID4}$' AND evidence_id ~ '^evidence:sha256:[0-9a-f]{{64}}$' "
            "AND envelope_id='evidence-provenance:' || envelope_hash "
            "AND envelope_hash ~ '^sha256:[0-9a-f]{64}$'",
            name="ck_m3_evidence_provenance_identity",
        ),
        sa.CheckConstraint(
            "relative_path='m3/evidence-provenance/' || substr(envelope_hash,8,2) "
            "|| '/' || substr(envelope_hash,8) || '.json' AND byte_size BETWEEN 1 AND 32768",
            name="ck_m3_evidence_provenance_path",
        ),
        sa.CheckConstraint(
            "source IN ('pubmed','dailymed','faers','cadec') "
            "AND char_length(snapshot_id) BETWEEN 1 AND 160",
            name="ck_m3_evidence_provenance_source",
        ),
        schema="medevidence",
    )


def downgrade() -> None:
    op.drop_table("m3_evidence_provenance", schema="medevidence")
