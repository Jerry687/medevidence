"""Bind persisted source-outcome occurrences to their exact run and source."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "m1bsourceoutcomeocc001"
down_revision = "m3dailymedv2members001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint(
        "pk_m1b_source_outcomes",
        "m1b_source_outcomes",
        schema="medevidence",
        type_="primary",
    )
    op.create_primary_key(
        "pk_m1b_source_outcomes",
        "m1b_source_outcomes",
        ("run_id", "source", "acquisition_id", "source_outcome_id"),
        schema="medevidence",
    )


def downgrade() -> None:
    duplicate = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT 1 FROM medevidence.m1b_source_outcomes "
                "GROUP BY source_outcome_id HAVING count(*) > 1 LIMIT 1"
            )
        )
        .scalar_one_or_none()
    )
    if duplicate is not None:
        raise RuntimeError(
            "Cannot restore the legacy outcome key while distinct occurrences share content; "
            "retain the current schema and preserve those records"
        )
    op.drop_constraint(
        "pk_m1b_source_outcomes",
        "m1b_source_outcomes",
        schema="medevidence",
        type_="primary",
    )
    op.create_primary_key(
        "pk_m1b_source_outcomes",
        "m1b_source_outcomes",
        ("source_outcome_id",),
        schema="medevidence",
    )
