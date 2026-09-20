"""Admit one separately named local catalog without relabeling M1A history."""

from alembic import op

revision = "m3localcatalog001"
down_revision = "m3semanticcache001"
branch_labels = None
depends_on = None

_M1A = (
    "catalog_version='m1a-concepts-v1' AND "
    "catalog_content_hash='sha256:eaffc3ee01ecd46a134578838b0304474642bf5e4a0c6e87302825d52be7682e'"
)
_LOCAL = (
    "catalog_version='m3.local-research-input.v1' AND "
    "catalog_content_hash='sha256:60ad5de184b4ab9972ca6179e4df8fd0f56d8e6741852f48331b465772b0e4ba'"
)
_PREFIX = "code_revision ~ '^[0-9a-f]{40}$' AND execution_profile_id='M1A_CONSTRAINED_V1' AND "
_SUFFIX = " AND source='pubmed' AND char_length(pubmed_query) BETWEEN 1 AND 512"
OLD_CHECK = _PREFIX + _M1A + _SUFFIX
NEW_CHECK = _PREFIX + "((" + _M1A + ") OR (" + _LOCAL + "))" + _SUFFIX


def upgrade() -> None:
    op.drop_constraint(
        "ck_research_run_static", "research_run", schema="medevidence", type_="check"
    )
    op.create_check_constraint(
        "ck_research_run_static", "research_run", NEW_CHECK, schema="medevidence"
    )


def downgrade() -> None:
    # Existing local-catalog rows cause the old CHECK to reject the downgrade.
    # They are never silently deleted or relabeled as historical M1A rows.
    op.drop_constraint(
        "ck_research_run_static", "research_run", schema="medevidence", type_="check"
    )
    op.create_check_constraint(
        "ck_research_run_static", "research_run", OLD_CHECK, schema="medevidence"
    )
