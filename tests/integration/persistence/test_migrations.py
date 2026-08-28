"""Disposable PostgreSQL migration and frozen catalog integration tests."""

from __future__ import annotations

import base64
import hashlib
import importlib.util
import io
import json
import os
import re
import zlib
from pathlib import Path
from types import ModuleType

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

from medevidence.persistence.config import DATABASE_URL_ENV

ROOT = Path(__file__).resolve().parents[3]
MIGRATION_DIR = ROOT / "alembic" / "versions"
M3_MIGRATION = MIGRATION_DIR / "20260827_01_m3_validation_receipt.py"
M3_REVISION = "m3validationreceipt001"
M3_DOWN_REVISION = "m1bfaers002001"
M3_DDL_PAYLOAD_SHA256 = "9d531079f5b73a7a4c2b32f20c6b8a07a23d77756785223e4ab5b7f59fda41c3"
RECEIPT_TABLE = "m3_validation_receipts"

EXPECTED_TABLE_NAMES = {
    "artifact",
    "artifact_integrity_event",
    "artifact_lineage",
    "m1b_acquisitions",
    "m1b_artifact_lineage",
    "m1b_artifacts",
    "m1b_dailymed_label_supersession",
    "m1b_dailymed_label_versions",
    "m1b_dailymed_sections",
    "m1b_dailymed_selection_decisions",
    "m1b_faers_buckets",
    "m1b_faers_queries",
    "m1b_report_sections",
    "m1b_report_source_outcomes",
    "m1b_reports",
    "m1b_run_sources",
    "m1b_runs",
    "m1b_snapshot_artifacts",
    "m1b_snapshots",
    "m1b_source_outcomes",
    RECEIPT_TABLE,
    "publication_version",
    "registration_observation",
    "research_report",
    "research_run",
    "research_run_attempt",
    "snapshot_file",
    "snapshot_warning",
    "source_snapshot",
    "source_snapshot_file",
    "source_snapshot_publication",
}

EXPECTED_RECEIPT_COLUMN_DDL = (
    "receipt_id VARCHAR(128) NOT NULL",
    "schema_version VARCHAR(32) NOT NULL",
    "receipt_content_hash CHAR(71) NOT NULL",
    "run_id VARCHAR(128) NOT NULL",
    "report_id VARCHAR(128) NOT NULL",
    "report_content_hash CHAR(71) NOT NULL",
    "validation_input_hash CHAR(71) NOT NULL",
    "task_binding_hash CHAR(71) NOT NULL",
    "evaluator_method VARCHAR(512) NOT NULL",
    "evaluator_version VARCHAR(512) NOT NULL",
    "policy_version VARCHAR(512) NOT NULL",
    "configuration_version VARCHAR(512) NOT NULL",
    "receipt_payload JSONB NOT NULL",
    "persisted_at_utc TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL",
)

EXPECTED_RECEIPT_CONSTRAINTS = {
    "ck_m3_validation_receipts_hashes": "c",
    "ck_m3_validation_receipts_identities": "c",
    "ck_m3_validation_receipts_payload": "c",
    "ck_m3_validation_receipts_schema": "c",
    "ck_m3_validation_receipts_versions": "c",
    "pk_m3_validation_receipts": "p",
    "uq_m3_validation_receipts_content_hash": "u",
}

EXPECTED_RECEIPT_CATALOG_COLUMNS = (
    ("receipt_id", "character varying", 128, "NO", None),
    ("schema_version", "character varying", 32, "NO", None),
    ("receipt_content_hash", "character", 71, "NO", None),
    ("run_id", "character varying", 128, "NO", None),
    ("report_id", "character varying", 128, "NO", None),
    ("report_content_hash", "character", 71, "NO", None),
    ("validation_input_hash", "character", 71, "NO", None),
    ("task_binding_hash", "character", 71, "NO", None),
    ("evaluator_method", "character varying", 512, "NO", None),
    ("evaluator_version", "character varying", 512, "NO", None),
    ("policy_version", "character varying", 512, "NO", None),
    ("configuration_version", "character varying", 512, "NO", None),
    ("receipt_payload", "jsonb", None, "NO", None),
    ("persisted_at_utc", "timestamp with time zone", None, "NO", "CURRENT_TIMESTAMP"),
)


class _RecordingConnection:
    def __init__(self) -> None:
        self.statements: list[str] = []

    def exec_driver_sql(self, statement: str) -> None:
        self.statements.append(statement)


class _FakeOperations:
    def __init__(self, connection: _RecordingConnection) -> None:
        self._connection = connection

    def get_bind(self) -> _RecordingConnection:
        return self._connection


def _database_url() -> str:
    value = os.environ.get(DATABASE_URL_ENV)
    if value is None:
        pytest.skip(f"{DATABASE_URL_ENV} is required for disposable PostgreSQL tests")
    return value


def _load_migration(path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(f"test_{path.stem}", path)
    if spec is None or spec.loader is None:
        raise AssertionError(f"unable to load migration: {path.name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _receipt_exists(engine: sa.Engine) -> bool:
    with engine.connect() as connection:
        return (
            connection.scalar(
                sa.text("SELECT to_regclass('medevidence.m3_validation_receipts') IS NOT NULL")
            )
            is True
        )


def test_migration_chain_imports_and_has_exact_head() -> None:
    expected_chain = (
        ("20260806_01_m1a_003b_snapshot_metadata.py", "m1a003b0001", None),
        ("20260809_01_m1b_dailymed.py", "m1bdm002001", "m1a003b0001"),
        ("20260809_02_m1b_faers.py", M3_DOWN_REVISION, "m1bdm002001"),
        (M3_MIGRATION.name, M3_REVISION, M3_DOWN_REVISION),
    )

    actual_chain = []
    for filename, _revision, _down_revision in expected_chain:
        module = _load_migration(MIGRATION_DIR / filename)
        actual_chain.append((filename, module.revision, module.down_revision))
        assert module.branch_labels is None
        assert module.depends_on is None

    assert tuple(actual_chain) == expected_chain
    script = ScriptDirectory.from_config(Config("alembic.ini"))
    assert script.get_heads() == [M3_REVISION]
    assert script.get_current_head() == M3_REVISION


def test_m3_embedded_ddl_is_exact_and_receipt_only() -> None:
    migration = _load_migration(M3_MIGRATION)

    assert migration.revision == M3_REVISION
    assert migration.down_revision == M3_DOWN_REVISION
    assert migration.TABLE_ORDER == (RECEIPT_TABLE,)
    assert migration._CREATE_ORDER == (RECEIPT_TABLE,)
    assert migration._DDL_PAYLOAD_SHA256 == M3_DDL_PAYLOAD_SHA256

    raw_payload = base64.b85decode(migration._DDL_PAYLOAD_B85)
    raw_json = zlib.decompress(raw_payload)
    assert hashlib.sha256(raw_json).hexdigest() == M3_DDL_PAYLOAD_SHA256
    decoded = json.loads(raw_json)
    assert tuple(decoded) == migration._ddl_statements()
    assert len(decoded) == 1

    statement = decoded[0]
    assert re.findall(r"CREATE TABLE\s+medevidence\.([a-z0-9_]+)", statement) == [RECEIPT_TABLE]
    upper_statement = statement.upper()
    assert upper_statement.count("CREATE TABLE") == 1
    assert "FOREIGN KEY" not in upper_statement
    for prohibited in (
        "ALTER TABLE",
        "CREATE INDEX",
        "CREATE MATERIALIZED VIEW",
        "CREATE VIEW",
        "CREATE FUNCTION",
        "CREATE TRIGGER",
        "DELETE FROM",
        "DROP ",
        "GRANT ",
        "INSERT INTO",
        "REVOKE ",
        "TRUNCATE ",
        "UPDATE ",
    ):
        assert prohibited not in upper_statement

    ddl_lines = tuple(line.strip().removesuffix(",") for line in statement.splitlines())
    column_lines = tuple(
        line for line in ddl_lines if line and line != ")" and not line.startswith("CONSTRAINT ")
    )[1:]
    assert column_lines == EXPECTED_RECEIPT_COLUMN_DDL

    constraint_lines = tuple(line for line in ddl_lines if line.startswith("CONSTRAINT "))
    constraint_names = tuple(line.split()[1] for line in constraint_lines)
    assert constraint_names == (
        "pk_m3_validation_receipts",
        "uq_m3_validation_receipts_content_hash",
        "ck_m3_validation_receipts_schema",
        "ck_m3_validation_receipts_identities",
        "ck_m3_validation_receipts_hashes",
        "ck_m3_validation_receipts_versions",
        "ck_m3_validation_receipts_payload",
    )
    assert sum(" PRIMARY KEY " in line for line in constraint_lines) == 1
    assert sum(" UNIQUE " in line for line in constraint_lines) == 1
    assert sum(" CHECK " in line for line in constraint_lines) == 5
    assert "PRIMARY KEY (receipt_id)" in statement
    assert "UNIQUE (receipt_content_hash)" in statement
    assert "schema_version='M3_VALIDATION_RECEIPT_V1'" in statement
    assert "jsonb_typeof(receipt_payload)='object'" in statement


def test_m3_upgrade_and_downgrade_emit_only_exact_statements(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migration = _load_migration(M3_MIGRATION)
    connection = _RecordingConnection()
    monkeypatch.setattr(migration, "op", _FakeOperations(connection))

    migration.upgrade()
    migration.downgrade()

    assert tuple(connection.statements) == (
        *migration._ddl_statements(),
        'DROP TABLE medevidence."m3_validation_receipts"',
    )


def test_full_offline_sql_is_blocked_by_existing_faers_mock_connection_limitation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Do not claim full ``--sql`` while the inherited FAERS migration blocks it."""
    monkeypatch.setenv(
        DATABASE_URL_ENV,
        "postgresql+psycopg://offline:offline@127.0.0.1:1/offline",
    )
    output = io.StringIO()
    config = Config("alembic.ini", output_buffer=output)

    with pytest.raises(AttributeError, match=r"MockConnection.*exec_driver_sql"):
        command.upgrade(config, "head", sql=True)

    rendered = output.getvalue()
    assert "m1bfaers002001" in rendered
    assert RECEIPT_TABLE not in rendered


def test_upgrade_downgrade_upgrade_and_exact_catalog() -> None:
    url = _database_url()
    config = Config("alembic.ini")
    engine = sa.create_engine(url)

    try:
        command.upgrade(config, "head")
        assert _receipt_exists(engine)
        command.downgrade(config, "base")
        assert not _receipt_exists(engine)
        command.upgrade(config, "head")
        assert _receipt_exists(engine)

        with engine.connect() as connection:
            table_names = {
                row["table_name"]
                for row in connection.execute(
                    sa.text(
                        "SELECT table_name FROM information_schema.tables "
                        "WHERE table_schema='medevidence' AND table_type='BASE TABLE'"
                    )
                )
                .mappings()
                .all()
            }
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
            receipt_constraints = {
                row["conname"]: row["contype"]
                for row in connection.execute(
                    sa.text(
                        "SELECT c.conname, c.contype FROM pg_constraint c "
                        "JOIN pg_class t ON t.oid=c.conrelid "
                        "JOIN pg_namespace n ON n.oid=t.relnamespace "
                        "WHERE n.nspname='medevidence' "
                        "AND t.relname='m3_validation_receipts' "
                        "AND c.contype IN ('c','p','u','f')"
                    )
                )
                .mappings()
                .all()
            }
            receipt_columns = tuple(
                (
                    row["column_name"],
                    row["data_type"],
                    row["character_maximum_length"],
                    row["is_nullable"],
                    row["column_default"],
                )
                for row in connection.execute(
                    sa.text(
                        "SELECT column_name, data_type, character_maximum_length, "
                        "is_nullable, column_default FROM information_schema.columns "
                        "WHERE table_schema='medevidence' "
                        "AND table_name='m3_validation_receipts' ORDER BY ordinal_position"
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
            faers_termination_check = connection.scalar(
                sa.text(
                    "SELECT pg_get_constraintdef(c.oid) FROM pg_constraint c "
                    "JOIN pg_class t ON t.oid=c.conrelid "
                    "JOIN pg_namespace n ON n.oid=t.relnamespace "
                    "WHERE n.nspname='medevidence' "
                    "AND t.relname='m1b_snapshot_artifacts' "
                    "AND c.conname='ck_member_termination'"
                )
            )
    finally:
        engine.dispose()

    assert table_names == EXPECTED_TABLE_NAMES
    assert constraint_counts == {"c": 138, "f": 56, "p": 31, "u": 64}
    assert secondary_indexes == 12
    assert len(fk_rows) == 56
    assert all(row["confupdtype"] == "r" and row["confdeltype"] == "r" for row in fk_rows)
    assert {row["conname"] for row in fk_rows if row["condeferrable"] or row["condeferred"]} == {
        "fk_research_run_report"
    }
    assert receipt_constraints == EXPECTED_RECEIPT_CONSTRAINTS
    assert receipt_columns == EXPECTED_RECEIPT_CATALOG_COLUMNS
    assert version == M3_REVISION
    assert version_schema == "public"
    assert forbidden_objects == 0
    assert raw_byte_columns == 0
    assert longest_identifier is not None and longest_identifier <= 63
    assert faers_termination_check is not None
    assert "read_timeout" in faers_termination_check
