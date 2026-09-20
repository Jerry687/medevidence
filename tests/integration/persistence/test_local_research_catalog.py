"""PostgreSQL evaluates the actual installed two-catalog CHECK without source I/O."""

import os

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config

from medevidence.domain.catalogs import LOCAL_RESEARCH_CATALOG_HASH, M1A_CATALOG_HASH
from medevidence.persistence.config import DATABASE_URL_ENV


def test_installed_catalog_constraint_admits_only_exact_version_hash_pairs() -> None:
    url = os.environ.get(DATABASE_URL_ENV)
    if url is None:
        pytest.skip("disposable PostgreSQL URL required")
    command.upgrade(Config("alembic.ini"), "head")
    engine = sa.create_engine(url)
    try:
        with engine.connect() as connection:
            expression = connection.scalar(
                sa.text(
                    "SELECT pg_get_expr(c.conbin,c.conrelid) FROM pg_constraint c "
                    "JOIN pg_class t ON t.oid=c.conrelid "
                    "JOIN pg_namespace n ON n.oid=t.relnamespace "
                    "WHERE n.nspname='medevidence' AND t.relname='research_run' "
                    "AND c.conname='ck_research_run_static'"
                )
            )
            assert isinstance(expression, str)
            # Evaluate the installed CHECK; values are ordinary bound parameters.
            statement = sa.text(
                "SELECT " + expression + " FROM (SELECT "
                "CAST(:revision AS text) AS code_revision, "
                "'M1A_CONSTRAINED_V1'::text AS execution_profile_id, "
                "CAST(:version AS text) AS catalog_version, "
                "CAST(:digest AS text) AS catalog_content_hash, "
                "'pubmed'::text AS source, 'bounded query'::text AS pubmed_query) AS candidate"
            )
            cases = (
                ("m1a-concepts-v1", M1A_CATALOG_HASH, True),
                ("m3.local-research-input.v1", LOCAL_RESEARCH_CATALOG_HASH, True),
                ("m1a-concepts-v1", LOCAL_RESEARCH_CATALOG_HASH, False),
                ("m3.local-research-input.v1", M1A_CATALOG_HASH, False),
                ("unapproved", LOCAL_RESEARCH_CATALOG_HASH, False),
                ("m3.local-research-input.v1", "sha256:" + "0" * 64, False),
            )
            for version, digest, expected in cases:
                assert (
                    connection.scalar(
                        statement, {"revision": "a" * 40, "version": version, "digest": digest}
                    )
                    is expected
                )
    finally:
        engine.dispose()
