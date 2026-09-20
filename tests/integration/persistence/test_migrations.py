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
from dataclasses import fields, replace
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

from medevidence.persistence.config import DATABASE_URL_ENV
from medevidence.persistence.models import m3_provider_attempt_events
from medevidence.persistence.repositories import (
    ProviderAttemptLedgerRepository,
    _provider_event_payload,
    canonical_provider_attempt_event_id,
    make_provider_attempt_event,
)
from medevidence.tools.provider_attempt_framing import (
    build_framing_observation,
    normalize_approved_headers,
)

ROOT = Path(__file__).resolve().parents[3]
MIGRATION_DIR = ROOT / "alembic" / "versions"
M3_MIGRATION = MIGRATION_DIR / "20260827_01_m3_validation_receipt.py"
M3_REVISION = "m3validationreceipt001"
M3_DOWN_REVISION = "m1bfaers002001"
LEDGER_MIGRATION = MIGRATION_DIR / "20260831_01_m3_provider_attempt_ledger.py"
LEDGER_REVISION = "m3providerattempt001"
FRAMING_MIGRATION = MIGRATION_DIR / "20260901_02_m3_provider_attempt_framing_v2.py"
FRAMING_REVISION = "m3providerframing002"
STAGE1_MIGRATION = MIGRATION_DIR / "20260914_01_m3_stage1_receipt_v2.py"
STAGE1_REVISION = "m3stage1receiptv2001"
REVIEW_EXPORT_MIGRATION = MIGRATION_DIR / "20260914_02_m3_review_export.py"
REVIEW_EXPORT_REVISION = "m3reviewexport001"
PROVENANCE_MIGRATION = MIGRATION_DIR / "20260914_03_m3_evidence_provenance.py"
PROVENANCE_REVISION = "m3evidenceprov001"
JOBS_MIGRATION = MIGRATION_DIR / "20260914_04_m3_research_jobs.py"
JOBS_REVISION = "m3researchjob001"
CACHE_MIGRATION = MIGRATION_DIR / "20260915_01_m3_semantic_evaluation_cache.py"
CACHE_REVISION = "m3semanticcache001"
CATALOG_MIGRATION = MIGRATION_DIR / "20260915_02_local_research_catalog.py"
CATALOG_REVISION = "m3localcatalog001"
SOURCE_LIFECYCLE_MIGRATION = MIGRATION_DIR / "20260915_03_m1b_source_lifecycle.py"
SOURCE_LIFECYCLE_REVISION = "m3sourcelifecycle001"
DAILYMED_V2_MIGRATION = MIGRATION_DIR / "20260916_01_m3_dailymed_v2_execution.py"
DAILYMED_V2_REVISION = "m3dailymedv2exec001"
DAILYMED_V2_MEMBERS_MIGRATION = MIGRATION_DIR / "20260916_02_m3_dailymed_v2_members.py"
DAILYMED_V2_MEMBERS_REVISION = "m3dailymedv2members001"
SOURCE_OUTCOME_OCCURRENCE_MIGRATION = MIGRATION_DIR / "20260920_01_m1b_source_outcome_occurrence.py"
SOURCE_OUTCOME_OCCURRENCE_REVISION = "m1bsourceoutcomeocc001"
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
    "m3_stage1_receipts",
    "m3_report_documents",
    "m3_pending_drafts",
    "m3_review_records",
    "m3_exports",
    "m3_evidence_provenance",
    "m3_research_jobs",
    "m3_semantic_evaluation_events",
    "m3_dailymed_v2_records",
    "m3_dailymed_v2_members",
    "m3_provider_attempt_events",
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
        (LEDGER_MIGRATION.name, LEDGER_REVISION, M3_REVISION),
        (FRAMING_MIGRATION.name, FRAMING_REVISION, LEDGER_REVISION),
        (STAGE1_MIGRATION.name, STAGE1_REVISION, FRAMING_REVISION),
        (REVIEW_EXPORT_MIGRATION.name, REVIEW_EXPORT_REVISION, STAGE1_REVISION),
        (PROVENANCE_MIGRATION.name, PROVENANCE_REVISION, REVIEW_EXPORT_REVISION),
        (JOBS_MIGRATION.name, JOBS_REVISION, PROVENANCE_REVISION),
        (CACHE_MIGRATION.name, CACHE_REVISION, JOBS_REVISION),
        (CATALOG_MIGRATION.name, CATALOG_REVISION, CACHE_REVISION),
        (
            SOURCE_LIFECYCLE_MIGRATION.name,
            SOURCE_LIFECYCLE_REVISION,
            CATALOG_REVISION,
        ),
        (DAILYMED_V2_MIGRATION.name, DAILYMED_V2_REVISION, SOURCE_LIFECYCLE_REVISION),
        (
            DAILYMED_V2_MEMBERS_MIGRATION.name,
            DAILYMED_V2_MEMBERS_REVISION,
            DAILYMED_V2_REVISION,
        ),
        (
            SOURCE_OUTCOME_OCCURRENCE_MIGRATION.name,
            SOURCE_OUTCOME_OCCURRENCE_REVISION,
            DAILYMED_V2_MEMBERS_REVISION,
        ),
    )

    actual_chain = []
    for filename, _revision, _down_revision in expected_chain:
        module = _load_migration(MIGRATION_DIR / filename)
        actual_chain.append((filename, module.revision, module.down_revision))
        assert module.branch_labels is None
        assert module.depends_on is None

    assert tuple(actual_chain) == expected_chain
    script = ScriptDirectory.from_config(Config("alembic.ini"))
    assert script.get_heads() == [SOURCE_OUTCOME_OCCURRENCE_REVISION]
    assert script.get_current_head() == SOURCE_OUTCOME_OCCURRENCE_REVISION


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


def test_provider_framing_upgrade_is_additive_and_never_rewrites_v1(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migration = _load_migration(FRAMING_MIGRATION)
    connection = _RecordingConnection()
    monkeypatch.setattr(migration, "op", _FakeOperations(connection))

    migration.upgrade()

    assert tuple(connection.statements) == migration._upgrade_statements()
    assert len(connection.statements) == len(migration._COLUMN_DDL) + 10
    upper = "\n".join(connection.statements).upper()
    assert not any(
        statement.lstrip().upper().startswith(("UPDATE ", "DELETE ", "INSERT "))
        for statement in connection.statements
    )
    assert upper.count("_CONTRACT_SNAPSHOT_B85") == 0


def _provider_attempt_catalog(engine: sa.Engine) -> tuple[tuple[object, ...], dict[str, str]]:
    with engine.connect() as connection:
        columns = tuple(
            tuple(row)
            for row in connection.execute(
                sa.text(
                    "SELECT column_name, data_type, character_maximum_length, is_nullable "
                    "FROM information_schema.columns WHERE table_schema='medevidence' "
                    "AND table_name='m3_provider_attempt_events' ORDER BY ordinal_position"
                )
            )
        )
        constraints = {
            row[0]: row[1]
            for row in connection.execute(
                sa.text(
                    "SELECT c.conname, pg_get_constraintdef(c.oid, true) "
                    "FROM pg_constraint c JOIN pg_class t ON t.oid=c.conrelid "
                    "JOIN pg_namespace n ON n.oid=t.relnamespace "
                    "WHERE n.nspname='medevidence' AND t.relname='m3_provider_attempt_events' "
                    "ORDER BY c.conname"
                )
            )
        }
    return columns, constraints


def _event_values(event: object) -> dict[str, object]:
    return {field.name: getattr(event, field.name) for field in fields(event)}


def test_clean_database_base_to_head_preserves_exact_v1_and_admits_v2_validation_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_url = sa.engine.make_url(_database_url())
    database_name = f"medevidence_m3_clean_{uuid4().hex}"
    admin_url = source_url.set(database="postgres")
    fresh_url = source_url.set(database=database_name)
    admin = sa.create_engine(admin_url, isolation_level="AUTOCOMMIT")
    fresh_engine: sa.Engine | None = None

    with admin.connect() as connection:
        connection.exec_driver_sql(f'CREATE DATABASE "{database_name}"')
    try:
        monkeypatch.setenv(DATABASE_URL_ENV, fresh_url.render_as_string(hide_password=False))
        config = Config("alembic.ini")
        command.upgrade(config, "head")
        fresh_engine = sa.create_engine(fresh_url)
        head_columns, head_constraints = _provider_attempt_catalog(fresh_engine)
        assert head_constraints["uq_m3_provider_attempt_event_start_binding"] == (
            "UNIQUE (event_id, event_kind, schema_version, provider_run_id, "
            "case_ordinal, attempt_ordinal, configuration_hash, request_hash)"
        )
        assert head_constraints["fk_m3_provider_attempt_event_start"] == (
            "FOREIGN KEY (start_event_id, start_event_kind, schema_version, "
            "provider_run_id, case_ordinal, attempt_ordinal, configuration_hash, "
            "request_hash) REFERENCES medevidence.m3_provider_attempt_events(event_id, "
            "event_kind, schema_version, provider_run_id, case_ordinal, attempt_ordinal, "
            "configuration_hash, request_hash) ON UPDATE RESTRICT ON DELETE RESTRICT"
        )
        assert "ck_m3_provider_attempt_events_shape" in head_constraints
        assert (
            "evidence_persistence_failure"
            in head_constraints["ck_m3_provider_attempt_events_shape"]
        )
        assert (
            "validation_internal_failure" in head_constraints["ck_m3_provider_attempt_events_shape"]
        )

        digest = "sha256:" + "b" * 64
        run_id = "provider-attempt-run:sha256:" + "a" * 64
        now = datetime(2026, 9, 1, tzinfo=UTC)
        repository = ProviderAttemptLedgerRepository._from_engine_for_testing(fresh_engine)
        v2_start = make_provider_attempt_event(
            provider_run_id=run_id,
            case_id="M3-008B-CAL-001",
            case_ordinal=1,
            attempt_ordinal=1,
            event_kind="START",
            configuration_hash=digest,
            request_hash=digest,
            started_at_utc=now,
            schema_version="M3_PROVIDER_ATTEMPT_EVENT_V2",
        )
        validation_observation = build_framing_observation(
            disposition="validation_internal_failure",
            http_status=200,
            http_version="HTTP/2",
            headers=normalize_approved_headers(
                (("content-type", "application/json"),),
                raw_header_field_count=1,
            ),
            raw_header_field_count=1,
            body_complete=True,
            actual_body_byte_count=2,
            raw_body_hash=digest,
            raw_relative_path="raw/validation-internal-failure.json",
        )
        v2_terminal = make_provider_attempt_event(
            provider_run_id=run_id,
            case_id="M3-008B-CAL-001",
            case_ordinal=1,
            attempt_ordinal=1,
            event_kind="TERMINAL",
            start_event=v2_start,
            configuration_hash=digest,
            request_hash=digest,
            started_at_utc=now,
            completed_at_utc=now,
            http_status=200,
            disposition="validation_internal_failure",
            error_code="validation_internal_failure",
            schema_version="M3_PROVIDER_ATTEMPT_EVENT_V2",
            framing_observation=validation_observation,
        )
        repository.append(v2_start)
        repository.append(v2_terminal)
        persisted_v2_terminal = repository.list_events(run_id)[1]
        assert persisted_v2_terminal.disposition == "validation_internal_failure"
        assert persisted_v2_terminal.body_hash == digest
        assert persisted_v2_terminal.framing_status == "accepted"
        assert persisted_v2_terminal.accepted_framing_class == "http_2_data"

        for ordinal, forbidden in enumerate(
            ("started", "interrupted_unknown_after_start", "validation_internal_failure"),
            start=2,
        ):
            v1_start = make_provider_attempt_event(
                provider_run_id=run_id,
                case_id=f"M3-008B-CAL-{ordinal:03d}",
                case_ordinal=ordinal,
                attempt_ordinal=1,
                event_kind="START",
                configuration_hash=digest,
                request_hash=digest,
                started_at_utc=now,
            )
            repository.append(v1_start)
            valid_terminal = make_provider_attempt_event(
                provider_run_id=run_id,
                case_id=f"M3-008B-CAL-{ordinal:03d}",
                case_ordinal=ordinal,
                attempt_ordinal=1,
                event_kind="TERMINAL",
                start_event=v1_start,
                configuration_hash=digest,
                request_hash=digest,
                started_at_utc=now,
                completed_at_utc=now,
                http_status=200,
                disposition="response_invalid",
                error_code="response_invalid",
            )
            invalid = replace(
                valid_terminal,
                disposition=forbidden,
                error_code=forbidden,
            )
            invalid = replace(
                invalid,
                event_id=canonical_provider_attempt_event_id(_provider_event_payload(invalid)),
            )
            with (
                pytest.raises(sa.exc.IntegrityError) as failure,
                fresh_engine.begin() as connection,
            ):
                connection.execute(
                    m3_provider_attempt_events.insert().values(**_event_values(invalid))
                )
            assert getattr(failure.value.orig, "diag", None).constraint_name == (
                "ck_m3_provider_attempt_events_shape"
            )

        with fresh_engine.begin() as connection:
            connection.execute(sa.text("DELETE FROM medevidence.m3_provider_attempt_events"))
        repository.close()
        fresh_engine.dispose()
        fresh_engine = None

        command.downgrade(config, LEDGER_REVISION)
        fresh_engine = sa.create_engine(fresh_url)
        v1_columns, v1_constraints = _provider_attempt_catalog(fresh_engine)
        assert v1_constraints["uq_m3_provider_attempt_event_start_binding"] == (
            "UNIQUE (event_id, event_kind, provider_run_id, case_ordinal, "
            "attempt_ordinal, configuration_hash, request_hash)"
        )
        assert v1_constraints["fk_m3_provider_attempt_event_start"] == (
            "FOREIGN KEY (start_event_id, start_event_kind, provider_run_id, "
            "case_ordinal, attempt_ordinal, configuration_hash, request_hash) "
            "REFERENCES medevidence.m3_provider_attempt_events(event_id, event_kind, "
            "provider_run_id, case_ordinal, attempt_ordinal, configuration_hash, "
            "request_hash) ON UPDATE RESTRICT ON DELETE RESTRICT"
        )
        assert len(head_columns) == len(v1_columns) + 27
        assert (
            "evidence_persistence_failure" in v1_constraints["ck_m3_provider_attempt_events_shape"]
        )
        assert (
            "validation_internal_failure"
            not in v1_constraints["ck_m3_provider_attempt_events_shape"]
        )
        assert (
            "M3_PROVIDER_ATTEMPT_EVENT_V2"
            not in v1_constraints["ck_m3_provider_attempt_events_schema"]
        )
        downgraded_table = sa.Table(
            "m3_provider_attempt_events",
            sa.MetaData(),
            schema="medevidence",
            autoload_with=fresh_engine,
        )
        downgraded_start = make_provider_attempt_event(
            provider_run_id=run_id,
            case_id="M3-008B-CAL-005",
            case_ordinal=5,
            attempt_ordinal=1,
            event_kind="START",
            configuration_hash=digest,
            request_hash=digest,
            started_at_utc=now,
        )
        downgraded_columns = tuple(
            column.name for column in downgraded_table.columns if column.name != "persisted_at_utc"
        )
        with fresh_engine.begin() as connection:
            connection.execute(
                downgraded_table.insert().values(
                    **{name: _event_values(downgraded_start)[name] for name in downgraded_columns}
                )
            )
        valid_v1_terminal = make_provider_attempt_event(
            provider_run_id=run_id,
            case_id="M3-008B-CAL-005",
            case_ordinal=5,
            attempt_ordinal=1,
            event_kind="TERMINAL",
            start_event=downgraded_start,
            configuration_hash=digest,
            request_hash=digest,
            started_at_utc=now,
            completed_at_utc=now,
            http_status=200,
            disposition="evidence_persistence_failure",
            error_code="evidence_persistence_failure",
        )
        invalid_v1_terminal = replace(
            valid_v1_terminal,
            disposition="validation_internal_failure",
            error_code="validation_internal_failure",
        )
        invalid_v1_terminal = replace(
            invalid_v1_terminal,
            event_id=canonical_provider_attempt_event_id(
                _provider_event_payload(invalid_v1_terminal)
            ),
        )
        with (
            pytest.raises(sa.exc.IntegrityError) as failure,
            fresh_engine.begin() as connection,
        ):
            connection.execute(
                downgraded_table.insert().values(
                    **{
                        name: _event_values(invalid_v1_terminal)[name]
                        for name in downgraded_columns
                    }
                )
            )
        assert getattr(failure.value.orig, "diag", None).constraint_name == (
            "ck_m3_provider_attempt_events_shape"
        )
        with fresh_engine.begin() as connection:
            connection.execute(sa.text("DELETE FROM medevidence.m3_provider_attempt_events"))
        fresh_engine.dispose()
        fresh_engine = None

        command.downgrade(config, "base")
        command.upgrade(config, LEDGER_REVISION)
        fresh_engine = sa.create_engine(fresh_url)
        assert _provider_attempt_catalog(fresh_engine) == (v1_columns, v1_constraints)
        fresh_engine.dispose()
        fresh_engine = None

        command.upgrade(config, "head")
        fresh_engine = sa.create_engine(fresh_url)
        assert _provider_attempt_catalog(fresh_engine) == (head_columns, head_constraints)
    finally:
        if fresh_engine is not None:
            fresh_engine.dispose()
        with admin.connect() as connection:
            connection.exec_driver_sql(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                f"WHERE datname='{database_name}' AND pid<>pg_backend_pid()"
            )
            connection.exec_driver_sql(f'DROP DATABASE IF EXISTS "{database_name}"')
        admin.dispose()


def test_baseline_v1_persistence_failure_survives_ledger_to_head_exactly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_url = sa.engine.make_url(_database_url())
    database_name = f"medevidence_m3_v1_roundtrip_{uuid4().hex}"
    admin_url = source_url.set(database="postgres")
    fresh_url = source_url.set(database=database_name)
    admin = sa.create_engine(admin_url, isolation_level="AUTOCOMMIT")
    engine: sa.Engine | None = None

    with admin.connect() as connection:
        connection.exec_driver_sql(f'CREATE DATABASE "{database_name}"')
    try:
        monkeypatch.setenv(DATABASE_URL_ENV, fresh_url.render_as_string(hide_password=False))
        config = Config("alembic.ini")
        command.upgrade(config, LEDGER_REVISION)
        engine = sa.create_engine(fresh_url)
        digest = "sha256:" + "b" * 64
        run_id = "provider-attempt-run:sha256:" + "a" * 64
        now = datetime(2026, 9, 1, tzinfo=UTC)
        start = make_provider_attempt_event(
            provider_run_id=run_id,
            case_id="M3-008B-CAL-001",
            case_ordinal=1,
            attempt_ordinal=1,
            event_kind="START",
            configuration_hash=digest,
            request_hash=digest,
            started_at_utc=now,
        )
        terminal = make_provider_attempt_event(
            provider_run_id=run_id,
            case_id="M3-008B-CAL-001",
            case_ordinal=1,
            attempt_ordinal=1,
            event_kind="TERMINAL",
            start_event=start,
            configuration_hash=digest,
            request_hash=digest,
            started_at_utc=now,
            completed_at_utc=now,
            http_status=200,
            disposition="evidence_persistence_failure",
            error_code="evidence_persistence_failure",
        )
        ledger_catalog = _provider_attempt_catalog(engine)
        ledger_table = sa.Table(
            "m3_provider_attempt_events",
            sa.MetaData(),
            schema="medevidence",
            autoload_with=engine,
        )
        ledger_column_names = tuple(column.name for column in ledger_table.columns)
        insert_columns = tuple(name for name in ledger_column_names if name != "persisted_at_utc")
        with engine.begin() as connection:
            connection.execute(
                ledger_table.insert().values(
                    **{name: getattr(start, name) for name in insert_columns}
                )
            )
            connection.execute(
                ledger_table.insert().values(
                    **{name: getattr(terminal, name) for name in insert_columns}
                )
            )
            ledger_rows_before = tuple(
                dict(row)
                for row in connection.execute(
                    sa.select(ledger_table).order_by(ledger_table.c.event_slot)
                ).mappings()
            )
        assert tuple(row["event_id"] for row in ledger_rows_before) == (
            start.event_id,
            terminal.event_id,
        )
        engine.dispose()
        engine = None

        command.upgrade(config, "head")
        engine = sa.create_engine(fresh_url)
        head_catalog = _provider_attempt_catalog(engine)
        assert len(head_catalog[0]) == len(ledger_catalog[0]) + 27
        assert "ck_m3_provider_attempt_events_framing_v2" in head_catalog[1]
        with engine.connect() as connection:
            head_rows_after = tuple(
                dict(row)
                for row in connection.execute(
                    sa.select(m3_provider_attempt_events).order_by(
                        m3_provider_attempt_events.c.event_slot
                    )
                ).mappings()
            )
        assert (
            tuple({name: row[name] for name in ledger_column_names} for row in head_rows_after)
            == ledger_rows_before
        )
        assert tuple(row["event_id"] for row in head_rows_after) == (
            start.event_id,
            terminal.event_id,
        )
        v2_column_names = set(m3_provider_attempt_events.c.keys()) - set(ledger_column_names)
        assert v2_column_names
        assert all(row[name] is None for row in head_rows_after for name in v2_column_names)
        repository = ProviderAttemptLedgerRepository._from_engine_for_testing(engine)
        try:
            reconstructed = repository.list_events(run_id)
        finally:
            repository.close()
            engine = None
        assert reconstructed == (start, terminal)
        assert tuple(_provider_event_payload(item) for item in reconstructed) == (
            _provider_event_payload(start),
            _provider_event_payload(terminal),
        )
    finally:
        if engine is not None:
            engine.dispose()
        with admin.connect() as connection:
            connection.exec_driver_sql(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                f"WHERE datname='{database_name}' AND pid<>pg_backend_pid()"
            )
            connection.exec_driver_sql(f'DROP DATABASE IF EXISTS "{database_name}"')
        admin.dispose()


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
        with engine.begin() as connection:
            connection.execute(sa.text("DELETE FROM medevidence.m3_provider_attempt_events"))
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
            raw_byte_columns = tuple(
                connection.execute(
                    sa.text(
                        "SELECT table_name,column_name FROM information_schema.columns "
                        "WHERE table_schema='medevidence' "
                        "AND data_type IN ('bytea','binary','varbinary')"
                    )
                ).all()
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
    assert constraint_counts == {"c": 185, "f": 70, "p": 42, "u": 78}
    assert secondary_indexes == 13
    assert len(fk_rows) == 70
    assert all(row["confupdtype"] == "r" and row["confdeltype"] == "r" for row in fk_rows)
    assert {row["conname"] for row in fk_rows if row["condeferrable"] or row["condeferred"]} == {
        "fk_research_run_report"
    }
    assert receipt_constraints == EXPECTED_RECEIPT_CONSTRAINTS
    assert receipt_columns == EXPECTED_RECEIPT_CATALOG_COLUMNS
    assert version == SOURCE_OUTCOME_OCCURRENCE_REVISION
    assert version_schema == "public"
    assert forbidden_objects == 0
    # Only the reviewed, bounded model-response cache may store binary bytes.
    # Medical-source raw bytes remain outside PostgreSQL.
    assert raw_byte_columns == (("m3_semantic_evaluation_events", "raw_body_bytes"),)
    assert longest_identifier is not None and longest_identifier <= 63
    assert faers_termination_check is not None
    assert "read_timeout" in faers_termination_check
