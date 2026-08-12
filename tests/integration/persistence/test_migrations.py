"""Disposable PostgreSQL migration and frozen catalog integration tests."""

from __future__ import annotations

import os

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config

from medevidence.persistence.config import DATABASE_URL_ENV


def _database_url() -> str:
    value = os.environ.get(DATABASE_URL_ENV)
    if value is None:
        pytest.skip(f"{DATABASE_URL_ENV} is required for disposable PostgreSQL tests")
    return value


def test_upgrade_downgrade_upgrade_and_exact_catalog() -> None:
    url = _database_url()
    config = Config("alembic.ini")

    command.upgrade(config, "head")
    command.downgrade(config, "base")
    command.upgrade(config, "head")

    engine = sa.create_engine(url)
    try:
        with engine.connect() as connection:
            table_count = connection.scalar(
                sa.text(
                    "SELECT count(*) FROM information_schema.tables "
                    "WHERE table_schema='medevidence' AND table_type='BASE TABLE'"
                )
            )
            constraint_counts = {
                row["contype"]: row["object_count"]
                for row in connection.execute(
                    sa.text(
                        "SELECT contype, count(*) AS object_count FROM pg_constraint c "
                        "JOIN pg_namespace n ON n.oid=c.connamespace "
                        "WHERE n.nspname='medevidence' AND contype IN ('c','f','p','u') "
                        "GROUP BY contype"
                    )
                )
                .mappings()
                .all()
            }
            secondary_indexes = connection.scalar(
                sa.text(
                    "SELECT count(*) FROM pg_index i "
                    "JOIN pg_class t ON t.oid=i.indrelid "
                    "JOIN pg_namespace n ON n.oid=t.relnamespace "
                    "WHERE n.nspname='medevidence' "
                    "AND NOT EXISTS (SELECT 1 FROM pg_constraint c WHERE c.conindid=i.indexrelid)"
                )
            )
            fk_rows = (
                connection.execute(
                    sa.text(
                        "SELECT conname, confupdtype, confdeltype, condeferrable, condeferred "
                        "FROM pg_constraint c JOIN pg_namespace n ON n.oid=c.connamespace "
                        "WHERE n.nspname='medevidence' AND contype='f'"
                    )
                )
                .mappings()
                .all()
            )
            version = connection.scalar(sa.text("SELECT version_num FROM public.alembic_version"))
            version_schema = connection.scalar(
                sa.text(
                    "SELECT table_schema FROM information_schema.tables "
                    "WHERE table_name='alembic_version'"
                )
            )
            forbidden_objects = connection.execute(
                sa.text(
                    "SELECT "
                    "(SELECT count(*) FROM information_schema.views "
                    " WHERE table_schema='medevidence') "
                    "+ (SELECT count(*) FROM pg_matviews WHERE schemaname='medevidence') "
                    "+ (SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace "
                    "   WHERE n.nspname='medevidence') "
                    "+ (SELECT count(*) FROM pg_trigger g JOIN pg_class c ON c.oid=g.tgrelid "
                    "   JOIN pg_namespace n ON n.oid=c.relnamespace "
                    "   WHERE n.nspname='medevidence' AND NOT g.tgisinternal) AS object_count"
                )
            ).scalar_one()
            raw_byte_columns = connection.scalar(
                sa.text(
                    "SELECT count(*) FROM information_schema.columns "
                    "WHERE table_schema='medevidence' "
                    "AND data_type IN ('bytea','binary','varbinary')"
                )
            )
            longest_identifier = connection.scalar(
                sa.text(
                    "SELECT max(length(name)) FROM ("
                    "SELECT conname AS name FROM pg_constraint c "
                    "JOIN pg_namespace n ON n.oid=c.connamespace WHERE n.nspname='medevidence' "
                    "UNION ALL SELECT indexname FROM pg_indexes WHERE schemaname='medevidence'"
                    ") AS names"
                )
            )
    finally:
        engine.dispose()

    assert table_count == 28
    assert constraint_counts == {"c": 121, "f": 53, "p": 28, "u": 62}
    assert secondary_indexes == 12
    assert len(fk_rows) == 53
    assert all(row["confupdtype"] == "r" and row["confdeltype"] == "r" for row in fk_rows)
    assert {row["conname"] for row in fk_rows if row["condeferrable"] or row["condeferred"]} == {
        "fk_research_run_report"
    }
    assert version == "m1bdm002001"
    assert version_schema == "public"
    assert forbidden_objects == 0
    assert raw_byte_columns == 0
    assert longest_identifier is not None and longest_identifier <= 63
