"""Structural tests for the exact frozen Core and private migration metadata."""

from __future__ import annotations

import ast
import importlib.util
import json
import re
from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path
from types import ModuleType
from typing import cast

import pytest
import sqlalchemy as sa
from sqlalchemy import Connection
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable
from tests.unit.tools import test_report_validation as validation_fixtures

from medevidence.domain import (
    FAERS_MANDATORY_LIMITATIONS,
    CoverageStatus,
    ExecutionBounds,
    ExecutionStatus,
    FaersAggregateBucketV1,
    FaersAggregateQueryV1,
    FaersAggregateRequestV1,
    FaersAggregateResult,
    FaersExecutionBoundsV1,
    FaersIdentityStrategy,
    FaersInclusiveDateRangeV1,
    ResultStatus,
    SourceOutcome,
    SourceType,
)
from medevidence.persistence import models
from medevidence.persistence import repositories as repository_module
from medevidence.persistence.repositories import (
    PersistenceCapacityError,
    PersistenceConflict,
    PersistenceRepository,
    ResearchRunAttemptRow,
    SourceSnapshotRow,
    ValidatedArtifactLink,
    ValidatedManifest,
    ValidatedManifestFile,
)
from medevidence.persistence.semantic_cache import semantic_evaluation_events
from medevidence.tools.provider_attempt_framing import (
    PERSISTED_AUTHORITY_FIELDS,
    MutationKind,
    apply_persisted_mutations,
    build_framing_observation,
    build_unavailable_observation,
    canonical_observation_projection,
    generated_consumer_mutation_witness,
    generated_contract_cases,
    generated_mutation_witness,
    normalize_approved_headers,
    render_postgres_contract,
    render_v1_immutability_predicate,
    validate_generated_mutation_case,
)
from medevidence.tools.report_validation import (
    ValidationReceipt,
    canonical_validation_receipt_payload,
    validation_receipt_from_payload,
)

M1A_EXPECTED_TABLES = (
    "artifact",
    "source_snapshot",
    "snapshot_file",
    "source_snapshot_file",
    "snapshot_warning",
    "publication_version",
    "source_snapshot_publication",
    "artifact_lineage",
    "research_run",
    "research_run_attempt",
    "research_report",
    "artifact_integrity_event",
    "registration_observation",
)
EXPECTED_TABLES = (
    *M1A_EXPECTED_TABLES,
    "m3_validation_receipts",
    "m3_stage1_receipts",
    "m3_provider_attempt_events",
    "m3_report_documents",
    "m3_pending_drafts",
    "m3_review_records",
    "m3_exports",
    "m3_evidence_provenance",
    "m3_dailymed_v2_records",
    "m3_dailymed_v2_members",
)
_WINDOWS_RESERVED_PROVIDER_PATH_NAMES = (
    "AUX",
    "CLOCK$",
    *(f"COM{index}" for index in range(1, 10)),
    "CON",
    *(f"LPT{index}" for index in range(1, 10)),
    "NUL",
    "PRN",
)
_NONCANONICAL_PROVIDER_PATHS = (
    "",
    ".",
    "..",
    "raw//case.bin",
    "C:/outside.bin",
    "C:outside.bin",
    "raw/case.bin:stream",
    "//server/share/case.bin",
    "\\\\server\\share\\case.bin",
    "/absolute/case.bin",
    "../outside.bin",
    "raw/../outside.bin",
    "raw/case.bin.",
    "raw/case.bin ",
    "raw./case.bin",
    "raw /case.bin",
    *(f"raw/{name}" for name in _WINDOWS_RESERVED_PROVIDER_PATH_NAMES),
    *(f"raw/{name.lower()}.json" for name in _WINDOWS_RESERVED_PROVIDER_PATH_NAMES),
)

EXPECTED_IDENTITY_CONSTRAINTS = {
    "artifact": "pk_artifact",
    "source_snapshot": "pk_source_snapshot",
    "snapshot_file": "pk_snapshot_file",
    "source_snapshot_file": "pk_source_snapshot_file",
    "snapshot_warning": "pk_snapshot_warning",
    "publication_version": "pk_publication_version",
    "source_snapshot_publication": "pk_source_snapshot_publication",
    "artifact_lineage": "pk_artifact_lineage",
    "research_run": "pk_research_run",
    "research_run_attempt": "pk_research_run_attempt",
    "research_report": "pk_research_report",
    "artifact_integrity_event": "uq_integrity_event_natural",
    "registration_observation": "uq_registration_observation_natural",
    "m3_validation_receipts": "pk_m3_validation_receipts",
    "m3_stage1_receipts": "pk_m3_stage1_receipts",
    "m3_provider_attempt_events": "pk_m3_provider_attempt_events",
    "m3_report_documents": "pk_m3_report_documents",
    "m3_pending_drafts": "pk_m3_pending_drafts",
    "m3_review_records": "pk_m3_review_records",
    "m3_exports": "pk_m3_exports",
    "m3_evidence_provenance": "pk_m3_evidence_provenance",
}


def _constraints(kind: type[sa.Constraint]) -> set[str]:
    return {
        constraint.name
        for table in models.TABLE_ORDER
        for constraint in table.constraints
        if isinstance(constraint, kind) and constraint.name is not None
    }


def _migration_module() -> ModuleType:
    path = Path("alembic/versions/20260806_01_m1a_003b_snapshot_metadata.py")
    spec = importlib.util.spec_from_file_location("m1a003b_revision", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _m1b_migration_module() -> ModuleType:
    path = Path("alembic/versions/20260809_01_m1b_dailymed.py")
    spec = importlib.util.spec_from_file_location("m1bdm002_revision", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _faers_migration_module() -> ModuleType:
    path = Path("alembic/versions/20260809_02_m1b_faers.py")
    spec = importlib.util.spec_from_file_location("m1bfaers002_revision", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _m3_validation_receipt_migration_module() -> ModuleType:
    path = Path("alembic/versions/20260827_01_m3_validation_receipt.py")
    spec = importlib.util.spec_from_file_location("m3validationreceipt_revision", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _provider_attempt_migration_module() -> ModuleType:
    path = Path("alembic/versions/20260831_01_m3_provider_attempt_ledger.py")
    spec = importlib.util.spec_from_file_location("m3providerattempt_revision", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _provider_framing_migration_module() -> ModuleType:
    path = Path("alembic/versions/20260901_02_m3_provider_attempt_framing_v2.py")
    spec = importlib.util.spec_from_file_location("m3providerframing_revision", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_exact_object_counts_and_names() -> None:
    assert tuple(table.name for table in models.TABLE_ORDER) == EXPECTED_TABLES
    assert (
        models.metadata.tables["medevidence.m3_semantic_evaluation_events"]
        is semantic_evaluation_events
    )
    assert len(models.metadata.tables) == 41
    assert len(_constraints(sa.CheckConstraint)) == 102
    assert len(_constraints(sa.ForeignKeyConstraint)) == 28
    assert len(_constraints(sa.PrimaryKeyConstraint)) == 23
    assert len(_constraints(sa.UniqueConstraint)) == 34
    assert sum(len(table.indexes) for table in models.TABLE_ORDER) == 12
    assert _constraints(sa.CheckConstraint) == set(models.EXPECTED_CHECK_NAMES) | {
        "ck_m3_dailymed_v2_record_schema",
        "ck_m3_dailymed_v2_record_kind",
        "ck_m3_dailymed_v2_record_identity",
        "ck_m3_dailymed_v2_record_bounds",
        "ck_m3_dailymed_v2_member_bounds",
        "ck_m3_dailymed_v2_member_identity",
    }


def _passing_validation_receipt() -> ValidationReceipt:
    audit, provider = validation_fixtures._assess(validation_fixtures._empty_request())
    assert audit.summary.passed
    assert provider.calls == []
    assert audit.receipt is not None
    return audit.receipt


def test_validation_receipt_table_is_exact_and_immutable() -> None:
    table = models.m3_validation_receipts
    assert tuple(column.name for column in table.columns) == (
        "receipt_id",
        "schema_version",
        "receipt_content_hash",
        "run_id",
        "report_id",
        "report_content_hash",
        "validation_input_hash",
        "task_binding_hash",
        "evaluator_method",
        "evaluator_version",
        "policy_version",
        "configuration_version",
        "receipt_payload",
        "persisted_at_utc",
    )
    assert tuple(str(column.type) for column in table.columns) == (
        "VARCHAR(128)",
        "VARCHAR(32)",
        "CHAR(71)",
        "VARCHAR(128)",
        "VARCHAR(128)",
        "CHAR(71)",
        "CHAR(71)",
        "CHAR(71)",
        "VARCHAR(512)",
        "VARCHAR(512)",
        "VARCHAR(512)",
        "VARCHAR(512)",
        "JSONB",
        "DATETIME",
    )
    assert all(not column.nullable for column in table.columns)
    assert all(column.server_default is None for column in table.columns[:-1])
    assert str(table.c.persisted_at_utc.server_default.arg) == "CURRENT_TIMESTAMP"
    assert isinstance(table.c.receipt_payload.type, postgresql.JSONB)
    assert isinstance(table.c.persisted_at_utc.type, sa.DateTime)
    assert table.c.persisted_at_utc.type.timezone is True

    primary_key = next(
        constraint
        for constraint in table.constraints
        if isinstance(constraint, sa.PrimaryKeyConstraint)
    )
    unique = next(
        constraint
        for constraint in table.constraints
        if isinstance(constraint, sa.UniqueConstraint)
    )
    checks = {
        constraint.name: str(constraint.sqltext)
        for constraint in table.constraints
        if isinstance(constraint, sa.CheckConstraint)
    }
    assert primary_key.name == "pk_m3_validation_receipts"
    assert tuple(column.name for column in primary_key.columns) == ("receipt_id",)
    assert unique.name == "uq_m3_validation_receipts_content_hash"
    assert tuple(column.name for column in unique.columns) == ("receipt_content_hash",)
    assert checks == {
        name: models.CHECK_SQL[name]
        for name in models.EXPECTED_CHECK_NAMES
        if name.startswith("ck_m3_validation_receipts_")
    }


def test_provider_attempt_ledger_is_single_insert_only_event_table() -> None:
    table = models.m3_provider_attempt_events
    assert tuple(column.name for column in table.columns) == (
        "event_id",
        "schema_version",
        "provider_run_id",
        "case_id",
        "case_ordinal",
        "attempt_ordinal",
        "event_kind",
        "event_slot",
        "start_event_id",
        "start_event_kind",
        "provider",
        "endpoint",
        "model",
        "configuration_hash",
        "request_hash",
        "started_at_utc",
        "completed_at_utc",
        "http_status",
        "disposition",
        "error_code",
        "credential_echo",
        "body_complete",
        "body_byte_count",
        "body_hash",
        "body_relative_path",
        "observed_body_bytes_lower_bound",
        "approved_header_names",
        "persisted_at_utc",
        "approved_header_names_identity",
        "normalized_header_names",
        "normalized_content_encoding_values",
        "normalized_content_length_values",
        "normalized_content_type_values",
        "normalized_transfer_encoding_values",
        "normalized_x_request_id_values",
        "normalized_header_facts_identity",
        "raw_header_field_count",
        "framing_contract_identity",
        "framing_input_identity",
        "http_version_state",
        "observed_http_version",
        "header_surface_state",
        "content_length_state",
        "content_length_value",
        "transfer_encoding_state",
        "content_encoding_state",
        "content_type_state",
        "actual_body_byte_count",
        "raw_evidence_state",
        "raw_body_hash",
        "raw_relative_path",
        "raw_artifact_identity",
        "framing_status",
        "accepted_framing_class",
        "framing_rejection_code",
    )
    checks = {
        constraint.name
        for constraint in table.constraints
        if isinstance(constraint, sa.CheckConstraint)
    }
    assert checks == {
        name
        for name in models.EXPECTED_CHECK_NAMES
        if name.startswith("ck_m3_provider_attempt_events_")
    }
    headers_check = models.CHECK_SQL["ck_m3_provider_attempt_events_headers"]
    assert "approved_header_names <@ ARRAY" in headers_check
    assert "::varchar[]" in headers_check
    assert "::text[]" not in headers_check
    assert all(
        table.c[name].type.length == 128
        for name in (
            "approved_header_names_identity",
            "normalized_header_facts_identity",
            "framing_contract_identity",
            "framing_input_identity",
            "raw_artifact_identity",
        )
    )
    unique = next(
        item
        for item in table.constraints
        if isinstance(item, sa.UniqueConstraint)
        and item.name == "uq_m3_provider_attempt_event_slot"
    )
    assert unique.name == "uq_m3_provider_attempt_event_slot"
    assert tuple(column.name for column in unique.columns) == (
        "provider_run_id",
        "case_ordinal",
        "attempt_ordinal",
        "event_slot",
    )
    start_binding = next(
        item
        for item in table.constraints
        if isinstance(item, sa.UniqueConstraint)
        and item.name == "uq_m3_provider_attempt_event_start_binding"
    )
    assert tuple(column.name for column in start_binding.columns) == (
        "event_id",
        "event_kind",
        "schema_version",
        "provider_run_id",
        "case_ordinal",
        "attempt_ordinal",
        "configuration_hash",
        "request_hash",
    )
    start_reference = next(
        item
        for item in table.constraints
        if isinstance(item, sa.ForeignKeyConstraint)
        and item.name == "fk_m3_provider_attempt_event_start"
    )
    assert tuple(element.parent.name for element in start_reference.elements) == (
        "start_event_id",
        "start_event_kind",
        "schema_version",
        "provider_run_id",
        "case_ordinal",
        "attempt_ordinal",
        "configuration_hash",
        "request_hash",
    )
    assert tuple(element.column.name for element in start_reference.elements) == (
        "event_id",
        "event_kind",
        "schema_version",
        "provider_run_id",
        "case_ordinal",
        "attempt_ordinal",
        "configuration_hash",
        "request_hash",
    )
    assert not hasattr(repository_module.ProviderAttemptLedgerRepository, "update")
    assert not hasattr(repository_module.ProviderAttemptLedgerRepository, "delete")


def test_provider_attempt_migration_is_single_table_after_receipts() -> None:
    module = _provider_attempt_migration_module()
    assert module.revision == "m3providerattempt001"
    assert module.down_revision == "m3validationreceipt001"
    assert module.TABLE_ORDER == ("m3_provider_attempt_events",)
    assert len(module._ddl_statements()) == 1
    statement = module._ddl_statements()[0]
    assert "approved_header_names <@ ARRAY" in statement
    assert "::varchar[]" in statement
    assert "::text[]" not in statement
    assert "'provider_rejected','candidate_invalid','evidence_persistence_failure')" in statement
    source = Path(module.__file__).read_text(encoding="utf-8")
    assert source.count("_DDL = _DDL.replace(") == 1
    assert (
        source.count("'provider_rejected','candidate_invalid','evidence_persistence_failure')") == 1
    )
    balance = 0
    for character in statement:
        balance += (character == "(") - (character == ")")
        assert balance >= 0
    assert balance == 0
    assert "medevidence.persistence" not in Path(module.__file__).read_text(encoding="utf-8")


def test_provider_framing_migration_is_one_exact_contract_snapshot() -> None:
    module = _provider_framing_migration_module()
    source = Path(module.__file__).read_text(encoding="utf-8")
    assert module.revision == "m3providerframing002"
    assert module.down_revision == "m3providerattempt001"
    assert module.TABLE_ORDER == ("m3_provider_attempt_events",)
    assert module._CONTRACT_SNAPSHOT_SHA256 == (
        "656724de18a35eb3000a4fc966ac4578e496661c0b2d71101c20facf29f04687"
    )
    assert module._contract_snapshot() == {
        "canonical_decision_check": render_postgres_contract().canonical_decision_check,
        "fact_free_v2_event_predicate": (render_postgres_contract().fact_free_v2_event_predicate),
        "v1_immutability_predicate": render_v1_immutability_predicate(),
        "v2_facts_absent_predicate": render_postgres_contract().v2_facts_absent_predicate,
    }
    assert module._V1_SHAPE_PREDICATE == models.PROVIDER_V1_SHAPE_SQL
    assert module._VERSIONED_SHAPE_PREDICATE == models.PROVIDER_VERSIONED_SHAPE_SQL
    statements = module._upgrade_statements()
    drop_fk = (
        "ALTER TABLE medevidence.m3_provider_attempt_events DROP CONSTRAINT "
        "fk_m3_provider_attempt_event_start"
    )
    drop_unique = (
        "ALTER TABLE medevidence.m3_provider_attempt_events DROP CONSTRAINT "
        "uq_m3_provider_attempt_event_start_binding"
    )
    add_unique = next(
        statement
        for statement in statements
        if "ADD CONSTRAINT uq_m3_provider_attempt_event_start_binding" in statement
    )
    add_fk = next(
        statement
        for statement in statements
        if "ADD CONSTRAINT fk_m3_provider_attempt_event_start" in statement
    )
    assert statements.index(drop_fk) < statements.index(drop_unique)
    assert statements.index(drop_unique) < statements.index(add_unique)
    assert statements.index(add_unique) < statements.index(add_fk)
    assert "event_id, event_kind, schema_version, provider_run_id" in add_unique
    assert "start_event_id, start_event_kind, schema_version, provider_run_id" in add_fk
    assert any(
        statement.endswith(f"CHECK ({models.CHECK_SQL['ck_m3_provider_attempt_events_shape']})")
        for statement in module._upgrade_statements()
    )
    assert module._upgrade_statements()[-2].endswith(
        f"CHECK ({models.CHECK_SQL['ck_m3_provider_attempt_events_v1_immutable']})"
    )
    assert module._upgrade_statements()[-1].endswith(
        f"CHECK ({models.CHECK_SQL['ck_m3_provider_attempt_events_framing_v2']})"
    )
    assert source.count("_CONTRACT_SNAPSHOT_B85: Final[str] =") == 1
    assert source.count("base64.b85decode(_CONTRACT_SNAPSHOT_B85)") == 1
    assert not any(
        statement.lstrip().upper().startswith(("UPDATE ", "DELETE ", "INSERT "))
        for statement in statements
    )
    assert "medevidence.tools" not in source


def test_v1_terminal_dispositions_are_the_exact_original_frozen_tuple() -> None:
    expected = (
        "success",
        "retryable_status",
        "transport_unavailable",
        "deadline_exceeded",
        "response_invalid",
        "response_too_large",
        "credential_echo",
        "authentication_failed",
        "provider_rejected",
        "candidate_invalid",
        "evidence_persistence_failure",
    )
    assert expected == models.PROVIDER_V1_TERMINAL_DISPOSITIONS
    assert (
        *expected,
        "validation_internal_failure",
    ) == models.PROVIDER_V2_TERMINAL_DISPOSITIONS

    digest = "sha256:" + "b" * 64
    now = datetime(2026, 8, 31, tzinfo=UTC)
    for ordinal, disposition in enumerate(expected, start=1):
        start = repository_module.make_provider_attempt_event(
            provider_run_id="provider-attempt-run:sha256:" + "a" * 64,
            case_id=f"M3-008B-CAL-{ordinal:03d}",
            case_ordinal=ordinal,
            attempt_ordinal=1,
            event_kind="START",
            configuration_hash=digest,
            request_hash=digest,
            started_at_utc=now,
        )
        credential_echo = disposition == "credential_echo"
        success = disposition == "success"
        terminal = repository_module.make_provider_attempt_event(
            provider_run_id=start.provider_run_id,
            case_id=start.case_id,
            case_ordinal=ordinal,
            attempt_ordinal=1,
            event_kind="TERMINAL",
            start_event=start,
            configuration_hash=digest,
            request_hash=digest,
            started_at_utc=now,
            completed_at_utc=now,
            http_status=200,
            disposition=disposition,
            error_code=None if success else disposition,
            credential_echo=credential_echo,
            body_complete=True if success else None,
            body_byte_count=2 if success else None,
            body_hash=digest if success else None,
            body_relative_path="raw/response.json" if success else None,
            observed_body_bytes_lower_bound=2 if success else None,
            approved_header_names=("content-type",) if success else (),
        )
        assert repository_module.validate_provider_attempt_event(terminal) is terminal


@pytest.mark.parametrize(
    "disposition",
    ("started", "interrupted_unknown_after_start", "validation_internal_failure"),
)
def test_v1_terminal_rejects_nonterminal_and_v2_only_dispositions_before_identity(
    disposition: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    digest = "sha256:" + "b" * 64
    now = datetime(2026, 8, 31, tzinfo=UTC)
    start = repository_module.make_provider_attempt_event(
        provider_run_id="provider-attempt-run:sha256:" + "a" * 64,
        case_id="M3-008B-CAL-001",
        case_ordinal=1,
        attempt_ordinal=1,
        event_kind="START",
        configuration_hash=digest,
        request_hash=digest,
        started_at_utc=now,
    )
    valid = repository_module.make_provider_attempt_event(
        provider_run_id=start.provider_run_id,
        case_id=start.case_id,
        case_ordinal=1,
        attempt_ordinal=1,
        event_kind="TERMINAL",
        start_event=start,
        configuration_hash=digest,
        request_hash=digest,
        started_at_utc=now,
        completed_at_utc=now,
        http_status=200,
        disposition="response_invalid",
        error_code="response_invalid",
    )

    def identity_must_not_run(_payload: object) -> str:
        raise AssertionError("identity must be unreachable")

    monkeypatch.setattr(
        repository_module,
        "canonical_provider_attempt_event_id",
        identity_must_not_run,
    )
    with pytest.raises(ValueError, match="invalid for schema version"):
        repository_module.make_provider_attempt_event(
            provider_run_id=start.provider_run_id,
            case_id=start.case_id,
            case_ordinal=1,
            attempt_ordinal=1,
            event_kind="TERMINAL",
            start_event=start,
            configuration_hash=digest,
            request_hash=digest,
            started_at_utc=now,
            completed_at_utc=now,
            http_status=200,
            disposition=disposition,
            error_code=disposition,
        )
    with pytest.raises(ValueError, match="invalid for schema version"):
        repository_module.validate_provider_attempt_event(
            replace(valid, disposition=disposition, error_code=disposition)
        )


def test_v2_evidence_persistence_failure_remains_canonical() -> None:
    digest = "sha256:" + "b" * 64
    now = datetime(2026, 9, 1, tzinfo=UTC)
    start = repository_module.make_provider_attempt_event(
        provider_run_id="provider-attempt-run:sha256:" + "a" * 64,
        case_id="M3-008B-CAL-001",
        case_ordinal=1,
        attempt_ordinal=1,
        event_kind="START",
        configuration_hash=digest,
        request_hash=digest,
        started_at_utc=now,
        schema_version="M3_PROVIDER_ATTEMPT_EVENT_V2",
    )
    observation = build_unavailable_observation(
        disposition="evidence_persistence_failure",
        http_status=200,
    )
    terminal = repository_module.make_provider_attempt_event(
        provider_run_id=start.provider_run_id,
        case_id=start.case_id,
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
        schema_version="M3_PROVIDER_ATTEMPT_EVENT_V2",
        framing_observation=observation,
    )
    assert repository_module.validate_provider_attempt_event(terminal) is terminal


def test_v2_validation_internal_failure_binds_safe_raw_framing_facts() -> None:
    digest = "sha256:" + "b" * 64
    now = datetime(2026, 9, 1, tzinfo=UTC)
    start = repository_module.make_provider_attempt_event(
        provider_run_id="provider-attempt-run:sha256:" + "a" * 64,
        case_id="M3-008B-CAL-001",
        case_ordinal=1,
        attempt_ordinal=1,
        event_kind="START",
        configuration_hash=digest,
        request_hash=digest,
        started_at_utc=now,
        schema_version="M3_PROVIDER_ATTEMPT_EVENT_V2",
    )
    observation = build_framing_observation(
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
    terminal = repository_module.make_provider_attempt_event(
        provider_run_id=start.provider_run_id,
        case_id=start.case_id,
        case_ordinal=1,
        attempt_ordinal=1,
        event_kind="TERMINAL",
        start_event=start,
        configuration_hash=digest,
        request_hash=digest,
        started_at_utc=now,
        completed_at_utc=now,
        http_status=200,
        disposition="validation_internal_failure",
        error_code="validation_internal_failure",
        schema_version="M3_PROVIDER_ATTEMPT_EVENT_V2",
        framing_observation=observation,
    )
    assert repository_module.validate_provider_attempt_event(terminal) is terminal
    assert terminal.body_complete is True
    assert terminal.body_hash == digest
    assert terminal.body_relative_path == "raw/validation-internal-failure.json"
    assert terminal.framing_status == "accepted"
    assert terminal.accepted_framing_class == "http_2_data"
    assert terminal.framing_rejection_code is None


def test_v2_provider_event_is_derived_from_and_reconstructs_one_contract_observation() -> None:
    run_id = "provider-attempt-run:sha256:" + "a" * 64
    digest = "sha256:" + "b" * 64
    now = datetime(2026, 9, 1, tzinfo=UTC)
    start = repository_module.make_provider_attempt_event(
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
    observation = build_framing_observation(
        disposition="response_invalid",
        http_status=200,
        http_version="HTTP/2",
        headers=normalize_approved_headers(
            (("content-type", "application/json"), ("x-request-id", "request-1")),
            raw_header_field_count=2,
        ),
        raw_header_field_count=2,
        body_complete=True,
        actual_body_byte_count=2,
        raw_body_hash=digest,
        raw_relative_path="raw/case-001.json",
    )
    event = repository_module.make_provider_attempt_event(
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
        disposition="response_invalid",
        error_code="response_invalid",
        schema_version="M3_PROVIDER_ATTEMPT_EVENT_V2",
        framing_observation=observation,
    )
    projection = canonical_observation_projection(observation)
    assert event.framing_status == projection["framing_status"] == "accepted"
    assert event.normalized_content_type_values == ("application/json",)
    assert event.normalized_x_request_id_values == ("request-1",)
    assert repository_module.validate_provider_attempt_event(event) is event

    payload = repository_module._provider_event_payload(event)
    tampered = replace(event, framing_status="rejected")
    tampered_payload = {
        **payload,
        "framing_status": "rejected",
    }
    tampered = replace(
        tampered,
        event_id=repository_module.canonical_provider_attempt_event_id(tampered_payload),
    )
    with pytest.raises(ValueError, match="projection drift"):
        repository_module.validate_provider_attempt_event(tampered)


def test_every_generated_noncanonical_raw_projection_fails_python_reconstruction() -> None:
    run_id = "provider-attempt-run:sha256:" + "a" * 64
    digest = "sha256:" + "b" * 64
    now = datetime(2026, 9, 1, tzinfo=UTC)
    cases = generated_contract_cases()
    pairs = [
        (case, variant)
        for case in cases
        for variant in case.noncanonical_variants
        if "repository" in variant.consumers
    ]
    declared_repository_targets = sum(
        target.consumer == "repository"
        for case in cases
        for variant in case.noncanonical_variants
        for target in variant.consumer_targets
    )
    assert pairs
    assert {
        variant.target_authority_field
        for _case, variant in pairs
        if variant.case_id.startswith("primitive:")
    } == set(PERSISTED_AUTHORITY_FIELDS)
    assert set(PERSISTED_AUTHORITY_FIELDS) <= set(
        repository_module.ProviderAttemptEvent.__dataclass_fields__
    )
    assert set(PERSISTED_AUTHORITY_FIELDS) <= set(models.m3_provider_attempt_events.c.keys())
    assert len(pairs) == declared_repository_targets
    assert len({variant.case_id for _case, variant in pairs}) == len(pairs)
    declared_case_ids = tuple(variant.case_id for _case, variant in pairs)
    executed_case_ids: list[str] = []
    for index, (case, variant) in enumerate(pairs):
        observation = case.observation
        validate_generated_mutation_case(variant)
        assert (
            variant.expected_first_match_rule,
            variant.expected_status,
            variant.expected_class,
            variant.expected_code,
        ) == (
            case.rule_key,
            case.expected_status,
            case.expected_class,
            case.expected_code,
        )
        mutation_fields = tuple(mutation.field for mutation in variant.mutations)
        repository_target = next(
            target for target in variant.consumer_targets if target.consumer == "repository"
        )
        assert repository_target.authority_fields == mutation_fields
        assert repository_target.direct_target_paths == tuple(
            f"ProviderAttemptEvent.{field}" for field in mutation_fields
        )
        case_ordinal = index % 36 + 1
        attempt_ordinal = (index // 36) % 3 + 1
        case_id = f"M3-008B-CAL-{case_ordinal:03d}"
        start = repository_module.make_provider_attempt_event(
            provider_run_id=run_id,
            case_id=case_id,
            case_ordinal=case_ordinal,
            attempt_ordinal=attempt_ordinal,
            event_kind="START",
            configuration_hash=digest,
            request_hash=digest,
            started_at_utc=now,
            schema_version="M3_PROVIDER_ATTEMPT_EVENT_V2",
        )
        event = repository_module.make_provider_attempt_event(
            provider_run_id=run_id,
            case_id=case_id,
            case_ordinal=case_ordinal,
            attempt_ordinal=attempt_ordinal,
            event_kind="TERMINAL",
            start_event=start,
            configuration_hash=digest,
            request_hash=digest,
            started_at_utc=now,
            completed_at_utc=now,
            http_status=observation.http_status,
            disposition=observation.disposition,
            error_code=None if observation.disposition == "success" else observation.disposition,
            credential_echo=observation.disposition == "credential_echo",
            schema_version="M3_PROVIDER_ATTEMPT_EVENT_V2",
            framing_observation=observation,
        )
        event_values = {
            field: getattr(event, field) for field in repository_module._PROVIDER_EVENT_FIELDS
        }
        consumer_mutations = generated_consumer_mutation_witness(
            variant,
            "repository",
            event_values,
        )
        assert tuple(item.field for item in consumer_mutations) == mutation_fields
        assert tuple(item.direct_target_path for item in consumer_mutations) == (
            repository_target.direct_target_paths
        )
        assert all(item.case_id == variant.case_id for item in consumer_mutations)
        assert all(item.consumer == "repository" for item in consumer_mutations)
        assert all(
            item.target_authority_field == variant.target_authority_field
            for item in consumer_mutations
        )
        changed_values = dict(event_values)
        for mutation in consumer_mutations:
            assert mutation.field in event_values
            assert mutation.field in repository_module.ProviderAttemptEvent.__dataclass_fields__
            assert type(event_values[mutation.field]) is type(mutation.canonical_value)
            assert event_values[mutation.field] == mutation.canonical_value
            if mutation.operation == "remove":
                del changed_values[mutation.field]
                assert mutation.field not in changed_values
            else:
                changed_values[mutation.field] = mutation.mutated_value
                assert changed_values[mutation.field] is mutation.mutated_value
                assert not (
                    type(mutation.mutated_value) is type(mutation.canonical_value)
                    and mutation.mutated_value == mutation.canonical_value
                )
        try:
            changed = repository_module.ProviderAttemptEvent(**changed_values)  # type: ignore[arg-type]
        except TypeError:
            assert any(mutation.operation == "remove" for mutation in consumer_mutations)
            continue
        for mutation in consumer_mutations:
            if mutation.operation == "set":
                assert getattr(changed, mutation.field) is mutation.mutated_value
        if repository_module._provider_attempt_event_primitives_are_exact(changed):
            payload = repository_module._provider_event_payload(changed)
            changed = replace(
                changed,
                event_id=repository_module.canonical_provider_attempt_event_id(payload),
            )
        with pytest.raises(ValueError):
            repository_module.validate_provider_attempt_event(changed)
        executed_case_ids.append(variant.case_id)
    assert tuple(executed_case_ids) == declared_case_ids


def test_generated_missing_mutations_remove_the_declared_named_authority() -> None:
    missing = [
        (case, variant)
        for case in generated_contract_cases()
        for variant in case.noncanonical_variants
        if variant.mutation_kind is MutationKind.MISSING
    ]
    assert missing
    for case, variant in missing:
        validate_generated_mutation_case(variant)
        assert (
            variant.expected_first_match_rule,
            variant.expected_status,
            variant.expected_class,
            variant.expected_code,
        ) == (
            case.rule_key,
            case.expected_status,
            case.expected_class,
            case.expected_code,
        )
        assert {"repository", "postgres"}.isdisjoint(variant.consumers)
        for consumer in variant.consumers:
            consumer_mutations = generated_consumer_mutation_witness(variant, consumer)
            values = {item.field: item.canonical_value for item in consumer_mutations}
            assert values
            for item in consumer_mutations:
                assert item.case_id == variant.case_id
                assert item.consumer == consumer
                assert item.target_authority_field == variant.target_authority_field
                assert item.operation == "remove"
                assert item.field in values
                del values[item.field]
                assert item.field not in values


def test_every_generated_primitive_variant_fails_before_payload_identity_or_transaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_id = "provider-attempt-run:sha256:" + "a" * 64
    digest = "sha256:" + "b" * 64
    now = datetime(2026, 9, 1, tzinfo=UTC)
    pairs = [
        (case.observation, variant)
        for case in generated_contract_cases()
        for variant in case.noncanonical_variants
        if "repository" in variant.consumers
        and variant.case_id.startswith("primitive:")
        and variant.mutation_kind is MutationKind.TYPE
    ]
    assert pairs
    assert len(pairs) == sum(
        variant.mutation_kind is MutationKind.TYPE
        for case in generated_contract_cases()
        for variant in case.noncanonical_variants
        if "repository" in variant.consumers and variant.case_id.startswith("primitive:")
    )
    invalid_events = []
    for index, (observation, variant) in enumerate(pairs):
        case_ordinal = index % 36 + 1
        attempt_ordinal = (index // 36) % 3 + 1
        case_id = f"M3-008B-CAL-{case_ordinal:03d}"
        start = repository_module.make_provider_attempt_event(
            provider_run_id=run_id,
            case_id=case_id,
            case_ordinal=case_ordinal,
            attempt_ordinal=attempt_ordinal,
            event_kind="START",
            configuration_hash=digest,
            request_hash=digest,
            started_at_utc=now,
            schema_version="M3_PROVIDER_ATTEMPT_EVENT_V2",
        )
        terminal = repository_module.make_provider_attempt_event(
            provider_run_id=run_id,
            case_id=case_id,
            case_ordinal=case_ordinal,
            attempt_ordinal=attempt_ordinal,
            event_kind="TERMINAL",
            start_event=start,
            configuration_hash=digest,
            request_hash=digest,
            started_at_utc=now,
            completed_at_utc=now,
            http_status=observation.http_status,
            disposition=observation.disposition,
            error_code=None if observation.disposition == "success" else observation.disposition,
            credential_echo=observation.disposition == "credential_echo",
            schema_version="M3_PROVIDER_ATTEMPT_EVENT_V2",
            framing_observation=observation,
        )
        projection = apply_persisted_mutations(
            generated_mutation_witness(observation),
            variant.mutations,
        )
        invalid_events.append(
            replace(
                terminal,
                **{mutation.field: projection[mutation.field] for mutation in variant.mutations},
            )
        )

    def forbidden_payload(_event: object) -> dict[str, object]:
        raise AssertionError("event payload construction must be unreachable")

    def forbidden_identity(_payload: object) -> str:
        raise AssertionError("event identity construction must be unreachable")

    monkeypatch.setattr(repository_module, "_provider_event_payload", forbidden_payload)
    monkeypatch.setattr(
        repository_module,
        "canonical_provider_attempt_event_id",
        forbidden_identity,
    )
    engine = sa.create_engine("sqlite://")
    repository = repository_module.ProviderAttemptLedgerRepository._from_engine_for_testing(engine)
    transaction_calls = 0
    original_begin = engine.begin

    def forbidden_transaction() -> object:
        nonlocal transaction_calls
        transaction_calls += 1
        return original_begin()

    monkeypatch.setattr(engine, "begin", forbidden_transaction)
    try:
        for event in invalid_events:
            with pytest.raises(ValueError, match="primitive type is invalid"):
                repository_module.validate_provider_attempt_event(event)
            with pytest.raises(ValueError, match="primitive type is invalid"):
                repository.append(event)
    finally:
        repository.close()
    assert transaction_calls == 0


def test_provider_event_primitive_gate_covers_every_field_with_exact_builtin_types() -> None:
    class NoncanonicalString(str):
        pass

    class NoncanonicalTuple(tuple[object, ...]):
        pass

    class NoncanonicalDatetime(datetime):
        pass

    classified_fields = {
        *repository_module._PROVIDER_REQUIRED_STR_FIELDS,
        *repository_module._PROVIDER_OPTIONAL_STR_FIELDS,
        *repository_module._PROVIDER_REQUIRED_INT_FIELDS,
        *repository_module._PROVIDER_OPTIONAL_INT_FIELDS,
        "credential_echo",
        "body_complete",
        "approved_header_names",
        *repository_module._PROVIDER_OPTIONAL_STR_TUPLE_FIELDS,
        "started_at_utc",
        "completed_at_utc",
    }
    assert classified_fields == set(repository_module._PROVIDER_EVENT_FIELDS)

    digest = "sha256:" + "b" * 64
    now = datetime(2026, 9, 1, tzinfo=UTC)
    start = repository_module.make_provider_attempt_event(
        provider_run_id="provider-attempt-run:sha256:" + "a" * 64,
        case_id="M3-008B-CAL-001",
        case_ordinal=1,
        attempt_ordinal=1,
        event_kind="START",
        configuration_hash=digest,
        request_hash=digest,
        started_at_utc=now,
        schema_version="M3_PROVIDER_ATTEMPT_EVENT_V2",
    )
    observation = build_framing_observation(
        disposition="success",
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
        raw_relative_path="raw/case-001.json",
    )
    event = repository_module.make_provider_attempt_event(
        provider_run_id=start.provider_run_id,
        case_id=start.case_id,
        case_ordinal=1,
        attempt_ordinal=1,
        event_kind="TERMINAL",
        start_event=start,
        configuration_hash=digest,
        request_hash=digest,
        started_at_utc=now,
        completed_at_utc=now,
        http_status=200,
        disposition="success",
        schema_version="M3_PROVIDER_ATTEMPT_EVENT_V2",
        framing_observation=observation,
    )
    mutations: list[dict[str, object]] = []
    mutations.extend(
        {name: NoncanonicalString(cast(str, getattr(event, name)))}
        for name in repository_module._PROVIDER_REQUIRED_STR_FIELDS
    )
    mutations.extend(
        {name: NoncanonicalString(cast(str | None, getattr(event, name)) or "noncanonical")}
        for name in repository_module._PROVIDER_OPTIONAL_STR_FIELDS
    )
    mutations.extend(
        {name: True}
        for name in (
            *repository_module._PROVIDER_REQUIRED_INT_FIELDS,
            *repository_module._PROVIDER_OPTIONAL_INT_FIELDS,
        )
    )
    mutations.extend(({"credential_echo": 0}, {"body_complete": 1}))
    for name in (
        "approved_header_names",
        *repository_module._PROVIDER_OPTIONAL_STR_TUPLE_FIELDS,
    ):
        values = cast(tuple[str, ...], getattr(event, name))
        mutations.append({name: NoncanonicalTuple(values)})
        mutations.append({name: (NoncanonicalString(values[0] if values else "noncanonical"),)})
    mutations.extend(
        (
            {"started_at_utc": NoncanonicalDatetime(2026, 9, 1, tzinfo=UTC)},
            {"completed_at_utc": NoncanonicalDatetime(2026, 9, 1, tzinfo=UTC)},
        )
    )
    for changes in mutations:
        with pytest.raises(ValueError, match="primitive type is invalid"):
            repository_module.validate_provider_attempt_event(replace(event, **changes))


def test_generated_integer_credential_metadata_fails_before_event_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    variants = [
        (case.observation, variant)
        for case in generated_contract_cases()
        for variant in case.noncanonical_variants
        if variant.case_id
        in {
            "event_metadata:credential_echo_integer_zero",
            "event_metadata:credential_echo_integer_one",
        }
    ]
    assert [variant.case_id for _, variant in variants] == [
        "event_metadata:credential_echo_integer_one",
        "event_metadata:credential_echo_integer_zero",
    ]
    digest = "sha256:" + "b" * 64
    now = datetime(2026, 9, 1, tzinfo=UTC)
    starts = [
        repository_module.make_provider_attempt_event(
            provider_run_id="provider-attempt-run:sha256:" + "a" * 64,
            case_id=f"M3-008B-CAL-{index:03d}",
            case_ordinal=index,
            attempt_ordinal=1,
            event_kind="START",
            configuration_hash=digest,
            request_hash=digest,
            started_at_utc=now,
            schema_version="M3_PROVIDER_ATTEMPT_EVENT_V2",
        )
        for index in range(1, len(variants) + 1)
    ]
    terminals = [
        repository_module.make_provider_attempt_event(
            provider_run_id=start.provider_run_id,
            case_id=start.case_id,
            case_ordinal=start.case_ordinal,
            attempt_ordinal=start.attempt_ordinal,
            event_kind="TERMINAL",
            start_event=start,
            configuration_hash=digest,
            request_hash=digest,
            started_at_utc=now,
            completed_at_utc=now,
            http_status=observation.http_status,
            disposition=observation.disposition,
            error_code=(None if observation.disposition == "success" else observation.disposition),
            credential_echo=observation.disposition == "credential_echo",
            schema_version="M3_PROVIDER_ATTEMPT_EVENT_V2",
            framing_observation=observation,
        )
        for (observation, _variant), start in zip(variants, starts, strict=True)
    ]

    def identity_must_not_be_reached(_payload: object) -> str:
        raise AssertionError("event identity construction must be unreachable")

    monkeypatch.setattr(
        repository_module,
        "canonical_provider_attempt_event_id",
        identity_must_not_be_reached,
    )
    for index, ((observation, variant), start) in enumerate(
        zip(variants, starts, strict=True), start=1
    ):
        mutation = variant.mutations[0]
        assert mutation.field == "credential_echo" and type(mutation.value) is int
        with pytest.raises(ValueError, match="primitive type is invalid"):
            repository_module.make_provider_attempt_event(
                provider_run_id="provider-attempt-run:sha256:" + "a" * 64,
                case_id=f"M3-008B-CAL-{index:03d}",
                case_ordinal=index,
                attempt_ordinal=1,
                event_kind="TERMINAL",
                start_event=start,
                configuration_hash=digest,
                request_hash=digest,
                started_at_utc=now,
                completed_at_utc=now,
                http_status=observation.http_status,
                disposition=observation.disposition,
                error_code=(
                    None if observation.disposition == "success" else observation.disposition
                ),
                credential_echo=mutation.value,
                schema_version="M3_PROVIDER_ATTEMPT_EVENT_V2",
                framing_observation=observation,
            )
    repository = repository_module.ProviderAttemptLedgerRepository._from_engine_for_testing(
        sa.create_engine("sqlite://")
    )
    try:
        for terminal, (_observation, variant) in zip(terminals, variants, strict=True):
            invalid = replace(terminal, credential_echo=variant.mutations[0].value)
            with pytest.raises(ValueError, match="primitive type is invalid"):
                repository.append(invalid)
    finally:
        repository.close()


def test_make_provider_event_rejects_all_caller_primitive_classes_before_authorities(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class NoncanonicalString(str):
        pass

    class ExplosiveString(str):
        def __eq__(self, other: object) -> bool:
            raise AssertionError("START binding equality must be unreachable")

    class NoncanonicalTuple(tuple[object, ...]):
        pass

    class NoncanonicalDatetime(datetime):
        pass

    digest = "sha256:" + "b" * 64
    run_id = "provider-attempt-run:sha256:" + "a" * 64
    now = datetime(2026, 9, 1, tzinfo=UTC)
    start = repository_module.make_provider_attempt_event(
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
    observation = build_framing_observation(
        disposition="success",
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
        raw_relative_path="raw/case-001.json",
    )
    base: dict[str, object] = {
        "provider_run_id": run_id,
        "case_id": "M3-008B-CAL-001",
        "case_ordinal": 1,
        "attempt_ordinal": 1,
        "event_kind": "TERMINAL",
        "start_event": start,
        "configuration_hash": digest,
        "request_hash": digest,
        "started_at_utc": now,
        "completed_at_utc": now,
        "http_status": 200,
        "disposition": "success",
        "schema_version": "M3_PROVIDER_ATTEMPT_EVENT_V2",
        "framing_observation": observation,
    }
    cases: tuple[tuple[str, dict[str, object]], ...] = (
        ("provider_run_id", {"provider_run_id": NoncanonicalString(run_id)}),
        ("case_id", {"case_id": NoncanonicalString("M3-008B-CAL-001")}),
        ("case_ordinal", {"case_ordinal": True}),
        ("attempt_ordinal", {"attempt_ordinal": True}),
        ("event_kind", {"event_kind": NoncanonicalString("TERMINAL")}),
        ("configuration_hash", {"configuration_hash": NoncanonicalString(digest)}),
        ("request_hash", {"request_hash": NoncanonicalString(digest)}),
        ("started_at_utc", {"started_at_utc": NoncanonicalDatetime(2026, 9, 1, tzinfo=UTC)}),
        (
            "completed_at_utc",
            {"completed_at_utc": NoncanonicalDatetime(2026, 9, 1, tzinfo=UTC)},
        ),
        ("http_status", {"http_status": True}),
        ("disposition", {"disposition": NoncanonicalString("success")}),
        ("error_code", {"error_code": NoncanonicalString("success")}),
        ("credential_echo", {"credential_echo": 0}),
        ("body_complete", {"body_complete": 1}),
        ("body_byte_count", {"body_byte_count": True}),
        ("body_hash", {"body_hash": NoncanonicalString(digest)}),
        (
            "body_relative_path",
            {"body_relative_path": NoncanonicalString("raw/case-001.json")},
        ),
        ("observed_body_bytes_lower_bound", {"observed_body_bytes_lower_bound": True}),
        ("approved_header_names_tuple", {"approved_header_names": NoncanonicalTuple()}),
        (
            "approved_header_names_item",
            {"approved_header_names": (NoncanonicalString("content-type"),)},
        ),
        ("schema_version", {"schema_version": NoncanonicalString("M3_PROVIDER_ATTEMPT_EVENT_V2")}),
        ("start_event_type", {"start_event": object()}),
        ("start_event_event_slot", {"start_event": replace(start, event_slot=True)}),
        (
            "start_event_string_equality",
            {"start_event": replace(start, provider_run_id=ExplosiveString(run_id))},
        ),
        (
            "observation_http_status",
            {"framing_observation": replace(observation, http_status=True)},
        ),
        (
            "observation_string",
            {
                "framing_observation": replace(
                    observation,
                    disposition=NoncanonicalString("success"),
                )
            },
        ),
        (
            "observation_enum",
            {"framing_observation": replace(observation, http_version_state="http_2")},
        ),
        (
            "observation_header_tuple_item",
            {
                "framing_observation": replace(
                    observation,
                    headers=replace(
                        observation.headers,
                        observed_names=(NoncanonicalString("content-type"),),
                    ),
                )
            },
        ),
    )

    reached: list[str] = []

    def forbidden(name: str) -> object:
        def callback(*_args: object, **_kwargs: object) -> object:
            reached.append(name)
            raise AssertionError(f"{name} must be unreachable")

        return callback

    monkeypatch.setattr(
        repository_module,
        "canonical_observation_projection",
        forbidden("projection"),
    )
    monkeypatch.setattr(repository_module, "_provider_event_payload", forbidden("payload"))
    monkeypatch.setattr(
        repository_module,
        "canonical_provider_attempt_event_id",
        forbidden("identity"),
    )
    monkeypatch.setattr(repository_module, "v2_event_metadata_matches", forbidden("metadata"))
    monkeypatch.setattr(
        repository_module,
        "canonical_fact_free_v2_event_projection",
        forbidden("fact_free_projection"),
    )
    monkeypatch.setattr(repository_module, "legacy_v2_raw_projection", forbidden("raw_projection"))

    for name, changes in cases:
        with pytest.raises(ValueError, match="primitive type is invalid"):
            repository_module.make_provider_attempt_event(**{**base, **changes})  # type: ignore[arg-type]
        assert reached == [], name

    engine = sa.create_engine("sqlite://")
    repository = repository_module.ProviderAttemptLedgerRepository._from_engine_for_testing(engine)
    transaction_calls = 0

    def forbidden_transaction() -> object:
        nonlocal transaction_calls
        transaction_calls += 1
        raise AssertionError("transaction must be unreachable")

    monkeypatch.setattr(engine, "begin", forbidden_transaction)
    with pytest.raises(ValueError, match="primitive type is invalid"):
        repository.append(replace(start, event_slot=True))
    repository.close()
    assert transaction_calls == 0
    assert reached == []


def test_v1_event_identity_and_projection_remain_free_of_every_v2_field() -> None:
    digest = "sha256:" + "b" * 64
    event = repository_module.make_provider_attempt_event(
        provider_run_id="provider-attempt-run:sha256:" + "a" * 64,
        case_id="M3-008B-CAL-001",
        case_ordinal=1,
        attempt_ordinal=1,
        event_kind="START",
        configuration_hash=digest,
        request_hash=digest,
        started_at_utc=datetime(2026, 8, 31, tzinfo=UTC),
    )
    payload = repository_module._provider_event_payload(event)
    assert not (set(payload) & repository_module._PROVIDER_V2_FIELDS)
    assert event.event_id == repository_module.canonical_provider_attempt_event_id(payload)


@pytest.mark.parametrize(
    "relative_path",
    _NONCANONICAL_PROVIDER_PATHS,
)
def test_v1_legacy_body_path_rejects_noncanonical_forms_before_ledger_admission(
    relative_path: str,
) -> None:
    digest = "sha256:" + "b" * 64
    now = datetime(2026, 8, 31, tzinfo=UTC)
    start = repository_module.make_provider_attempt_event(
        provider_run_id="provider-attempt-run:sha256:" + "a" * 64,
        case_id="M3-008B-CAL-001",
        case_ordinal=1,
        attempt_ordinal=1,
        event_kind="START",
        configuration_hash=digest,
        request_hash=digest,
        started_at_utc=now,
    )
    with pytest.raises(ValueError, match="body relative path is noncanonical"):
        repository_module.make_provider_attempt_event(
            provider_run_id=start.provider_run_id,
            case_id=start.case_id,
            case_ordinal=1,
            attempt_ordinal=1,
            event_kind="TERMINAL",
            start_event=start,
            configuration_hash=digest,
            request_hash=digest,
            started_at_utc=now,
            completed_at_utc=now,
            http_status=200,
            disposition="success",
            body_complete=True,
            body_byte_count=2,
            body_hash=digest,
            body_relative_path=relative_path,
            observed_body_bytes_lower_bound=2,
            approved_header_names=("content-type",),
        )


@pytest.mark.parametrize(
    "claims",
    (
        {"approved_header_names": ("content-type",)},
        {"credential_echo": True},
        {"body_complete": False},
        {"body_hash": "sha256:" + "f" * 64},
        {"observed_body_bytes_lower_bound": 0},
    ),
)
def test_v2_fact_free_start_rejects_every_fabricated_legacy_claim(
    claims: dict[str, object],
) -> None:
    digest = "sha256:" + "b" * 64
    with pytest.raises(ValueError, match=r"fact-free event|metadata differs"):
        repository_module.make_provider_attempt_event(
            provider_run_id="provider-attempt-run:sha256:" + "a" * 64,
            case_id="M3-008B-CAL-001",
            case_ordinal=1,
            attempt_ordinal=1,
            event_kind="START",
            configuration_hash=digest,
            request_hash=digest,
            started_at_utc=datetime(2026, 9, 1, tzinfo=UTC),
            schema_version="M3_PROVIDER_ATTEMPT_EVENT_V2",
            **claims,  # type: ignore[arg-type]
        )


def test_v2_fact_free_terminal_rejects_non_governed_disposition() -> None:
    digest = "sha256:" + "b" * 64
    now = datetime(2026, 9, 1, tzinfo=UTC)
    start = repository_module.make_provider_attempt_event(
        provider_run_id="provider-attempt-run:sha256:" + "a" * 64,
        case_id="M3-008B-CAL-001",
        case_ordinal=1,
        attempt_ordinal=1,
        event_kind="START",
        configuration_hash=digest,
        request_hash=digest,
        started_at_utc=now,
        schema_version="M3_PROVIDER_ATTEMPT_EVENT_V2",
    )
    with pytest.raises(ValueError, match="topology"):
        repository_module.make_provider_attempt_event(
            provider_run_id=start.provider_run_id,
            case_id=start.case_id,
            case_ordinal=1,
            attempt_ordinal=1,
            event_kind="TERMINAL",
            start_event=start,
            configuration_hash=digest,
            request_hash=digest,
            started_at_utc=now,
            completed_at_utc=now,
            disposition="retryable_status",
            error_code="retryable_status",
            schema_version="M3_PROVIDER_ATTEMPT_EVENT_V2",
        )


def test_validation_receipt_migration_remains_frozen_v1() -> None:
    module = _m3_validation_receipt_migration_module()
    original = module._ddl_statements()[0]
    assert module.revision == "m3validationreceipt001"
    assert module.down_revision == "m1bfaers002001"
    assert module.TABLE_ORDER == ("m3_validation_receipts",)
    assert "schema_version='M3_VALIDATION_RECEIPT_V1'" in original
    assert "validation-receipt-v2" not in original
    assert "medevidence.persistence" not in Path(module.__file__).read_text(encoding="utf-8")


def test_stage1_v2_migration_matches_new_table_and_widened_final_checks() -> None:
    path = Path("alembic/versions/20260914_01_m3_stage1_receipt_v2.py")
    spec = importlib.util.spec_from_file_location("m3stage1receiptv2_revision", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.revision == "m3stage1receiptv2001"
    assert module.down_revision == "m3providerframing002"
    assert module.TABLE_ORDER == ("m3_stage1_receipts",)
    statements = module._statements(module._UPGRADE_B85, module._UPGRADE_SHA256)
    assert statements[-1] == str(
        CreateTable(models.m3_stage1_receipts).compile(dialect=postgresql.dialect())
    )
    assert models.CHECK_SQL["ck_m3_validation_receipts_schema"] in statements[2]
    assert models.CHECK_SQL["ck_m3_validation_receipts_identities"] in statements[3]
    assert "medevidence.persistence" not in path.read_text(encoding="utf-8")


def test_review_export_migration_freezes_four_additive_tables() -> None:
    path = Path("alembic/versions/20260914_02_m3_review_export.py")
    spec = importlib.util.spec_from_file_location("m3reviewexport_revision", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    names = (
        "m3_report_documents",
        "m3_pending_drafts",
        "m3_review_records",
        "m3_exports",
    )
    assert module.revision == "m3reviewexport001"
    assert module.down_revision == "m3stage1receiptv2001"
    assert names == module.TABLE_ORDER
    assert module._statements(module._UPGRADE_B85, module._UPGRADE_SHA256) == tuple(
        str(CreateTable(getattr(models, name)).compile(dialect=postgresql.dialect()))
        for name in names
    )
    assert module._statements(module._DOWNGRADE_B85, module._DOWNGRADE_SHA256) == tuple(
        f'DROP TABLE medevidence."{name}"' for name in reversed(names)
    )
    assert "medevidence.persistence" not in path.read_text(encoding="utf-8")


def test_validation_receipt_spec_excludes_operational_timestamp_from_semantics() -> None:
    spec = repository_module._SPECS["m3_validation_receipts"]
    receipt = _passing_validation_receipt()
    payload = canonical_validation_receipt_payload(receipt)
    values = PersistenceRepository._validation_receipt_values(payload)
    assert spec.table is models.m3_validation_receipts
    assert spec.identity_columns == ("receipt_id",)
    assert spec.capacity == 1_000
    assert spec.generated_id is None
    assert set(spec.comparison_columns) == set(values)
    assert "persisted_at_utc" not in spec.comparison_columns

    stored = {**values, "persisted_at_utc": datetime(2026, 8, 27, tzinfo=UTC)}
    assert repository_module._same_persisted_row(spec, stored, values)
    stored["persisted_at_utc"] = datetime(2026, 8, 28, tzinfo=UTC)
    assert repository_module._same_persisted_row(spec, stored, values)
    stored["evaluator_version"] = "different"
    assert not repository_module._same_persisted_row(spec, stored, values)


def test_validation_receipt_projection_roundtrips_exact_canonical_payload() -> None:
    receipt = _passing_validation_receipt()
    payload = canonical_validation_receipt_payload(receipt)
    values = PersistenceRepository._validation_receipt_values(payload)
    assert set(values) == {
        column.name
        for column in models.m3_validation_receipts.columns
        if column.name != "persisted_at_utc"
    }
    assert values["receipt_payload"] == payload
    returned = PersistenceRepository._receipt_payload_from_persisted_row(values)
    assert returned == payload
    assert validation_receipt_from_payload(returned) == receipt


def test_validation_receipt_helpers_fail_closed_on_noncanonical_input() -> None:
    receipt = _passing_validation_receipt()
    payload = canonical_validation_receipt_payload(receipt)
    invalid_hash = {**payload, "receipt_content_hash": f"sha256:{'g' * 64}"}
    with pytest.raises(ValueError, match="receipt_content_hash is invalid"):
        PersistenceRepository._validation_receipt_values(invalid_hash)

    with pytest.raises(
        repository_module.PersistenceIntegrityError,
        match="payload violates the bounded storage contract",
    ):
        PersistenceRepository._receipt_payload_from_persisted_row({})

    values = PersistenceRepository._validation_receipt_values(payload)
    malformed = {**values, "receipt_payload": {"marker": "M3_VALIDATION_RECEIPT_V1"}}
    with pytest.raises(
        repository_module.PersistenceIntegrityError,
        match="payload violates the bounded storage contract",
    ):
        PersistenceRepository._receipt_payload_from_persisted_row(malformed)

    drifted = {**values, "configuration_version": "different"}
    with pytest.raises(
        repository_module.PersistenceIntegrityError,
        match="projections differ from canonical payload",
    ):
        PersistenceRepository._receipt_payload_from_persisted_row(drifted)


def test_persistence_package_does_not_import_the_tools_layer() -> None:
    violations: list[tuple[str, int, str]] = []
    for path in sorted(Path("src/medevidence/persistence").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if module == "medevidence.tools.provider_attempt_framing" and path.name in {
                    "models.py",
                    "repositories.py",
                }:
                    continue
                absolute_tools = module == "medevidence.tools" or module.startswith(
                    "medevidence.tools."
                )
                relative_tools = node.level > 0 and (
                    module == "tools"
                    or module.startswith("tools.")
                    or (not module and any(alias.name == "tools" for alias in node.names))
                )
                if absolute_tools or relative_tools:
                    violations.append((path.name, node.lineno, module))
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "medevidence.tools" or alias.name.startswith(
                        "medevidence.tools."
                    ):
                        violations.append((path.name, node.lineno, alias.name))
    assert violations == []


def test_every_foreign_key_is_restrict_and_only_run_report_is_deferred() -> None:
    foreign_keys = [
        constraint for table in models.TABLE_ORDER for constraint in table.foreign_key_constraints
    ]

    assert all(item.onupdate == "RESTRICT" and item.ondelete == "RESTRICT" for item in foreign_keys)
    assert {item.name for item in foreign_keys if item.deferrable or item.initially} == {
        "fk_research_run_report"
    }
    deferred = next(item for item in foreign_keys if item.name == "fk_research_run_report")
    assert deferred.deferrable is True
    assert deferred.initially == "DEFERRED"


def test_migration_embeds_equivalent_private_metadata_without_application_import() -> None:
    module = _migration_module()
    private = module._metadata

    assert module.revision == "m1a003b0001"
    assert module.down_revision is None
    assert tuple(module._ORDER) == M1A_EXPECTED_TABLES
    inherited = {
        f"{models.SCHEMA}.{name}": models.metadata.tables[f"{models.SCHEMA}.{name}"]
        for name in M1A_EXPECTED_TABLES
    }
    assert set(private.tables) == set(inherited)
    for key, table in inherited.items():
        migrated = private.tables[key]
        assert tuple(column.name for column in migrated.columns) == tuple(
            column.name for column in table.columns
        )
        assert tuple(
            (str(column.type), column.nullable, str(column.server_default))
            for column in migrated.columns
        ) == tuple(
            (str(column.type), column.nullable, str(column.server_default))
            for column in table.columns
        )
        assert {constraint.name for constraint in migrated.constraints} == {
            constraint.name for constraint in table.constraints
        }
        assert {
            (
                constraint.name,
                tuple(column.name for column in constraint.columns),
                constraint.onupdate,
                constraint.ondelete,
                constraint.deferrable,
                constraint.initially,
            )
            for constraint in migrated.foreign_key_constraints
        } == {
            (
                constraint.name,
                tuple(column.name for column in constraint.columns),
                constraint.onupdate,
                constraint.ondelete,
                constraint.deferrable,
                constraint.initially,
            )
            for constraint in table.foreign_key_constraints
        }
        assert {index.name for index in migrated.indexes} == {index.name for index in table.indexes}
    source = Path(module.__file__).read_text(encoding="utf-8")
    assert "medevidence.persistence" not in source


def test_medical_source_raw_bytes_have_no_postgresql_column() -> None:
    binary_columns = {
        (table.name, column.name)
        for table in models.metadata.tables.values()
        for column in table.columns
        if isinstance(column.type, sa.LargeBinary) or "BYTEA" in str(column.type).upper()
    }
    assert binary_columns == {("m3_semantic_evaluation_events", "raw_body_bytes")}


def test_m1b_dm002_exact_frozen_inventory_and_counts() -> None:
    dm_table_order = (
        "m1b_artifacts",
        "m1b_artifact_lineage",
        "m1b_acquisitions",
        "m1b_source_outcomes",
        "m1b_snapshots",
        "m1b_snapshot_artifacts",
        "m1b_runs",
        "m1b_run_sources",
        "m1b_reports",
        "m1b_report_sections",
        "m1b_report_source_outcomes",
        "m1b_dailymed_selection_decisions",
        "m1b_dailymed_label_versions",
        "m1b_dailymed_sections",
        "m1b_dailymed_label_supersession",
    )
    assert models.M1B_TABLE_ORDER[: len(dm_table_order)] == dm_table_order
    tables = [models.metadata.tables[f"{models.SCHEMA}.{name}"] for name in dm_table_order]
    assert sum(len(table.columns) for table in tables) == 201
    assert (
        sum(
            isinstance(constraint, sa.CheckConstraint)
            for table in tables
            for constraint in table.constraints
        )
        == 59
    )
    assert sum(len(table.foreign_key_constraints) for table in tables) == 36
    assert (
        sum(
            isinstance(constraint, sa.PrimaryKeyConstraint)
            for table in tables
            for constraint in table.constraints
        )
        == 15
    )
    assert (
        sum(
            isinstance(constraint, sa.UniqueConstraint)
            for table in tables
            for constraint in table.constraints
        )
        == 40
    )
    assert all(
        fk.onupdate == "RESTRICT" and fk.ondelete == "RESTRICT"
        for table in tables
        for fk in table.foreign_key_constraints
    )
    assert all(column.server_default is None for table in tables for column in table.columns)


def test_m1b_migration_embeds_exact_immutable_postgresql_ddl() -> None:
    module = _m1b_migration_module()
    statements = module._ddl_statements()
    expected = tuple(
        str(
            CreateTable(models.metadata.tables[f"{models.SCHEMA}.{name}"]).compile(
                dialect=postgresql.dialect()
            )
        ).replace("'stream_error','read_timeout',", "'stream_error',")
        if name == "m1b_snapshot_artifacts"
        else str(
            CreateTable(models.metadata.tables[f"{models.SCHEMA}.{name}"]).compile(
                dialect=postgresql.dialect()
            )
        ).replace(
            "status IN ('running','completed','degraded','failed') AND "
            "(status<>'running' OR completed_at_utc IS NULL)",
            "status IN ('completed','degraded','failed')",
        )
        if name == "m1b_runs"
        else str(
            CreateTable(models.metadata.tables[f"{models.SCHEMA}.{name}"]).compile(
                dialect=postgresql.dialect()
            )
        ).replace(
            "operation IN ('search','fetch') OR (source='dailymed' AND operation='packaging')",
            "operation IN ('search','fetch')",
        )
        if name in {"m1b_acquisitions", "m1b_source_outcomes"}
        else str(
            CreateTable(models.metadata.tables[f"{models.SCHEMA}.{name}"]).compile(
                dialect=postgresql.dialect()
            )
        )
        for name in module._CREATE_ORDER
    )
    assert module.revision == "m1bdm002001"
    assert module.down_revision == "m1a003b0001"
    assert models.M1B_TABLE_ORDER[: len(module.TABLE_ORDER)] == module.TABLE_ORDER
    # The historical DDL stays immutable; the occurrence key is a later migration.
    expected = tuple(
        statement.replace(
            "CONSTRAINT pk_m1b_source_outcomes PRIMARY KEY "
            "(run_id, source, acquisition_id, source_outcome_id)",
            "CONSTRAINT pk_m1b_source_outcomes PRIMARY KEY (source_outcome_id)",
        )
        for statement in expected
    )
    assert statements == expected
    source = Path(module.__file__).read_text(encoding="utf-8")
    assert "medevidence.persistence" not in source


def test_m1b_faers002_exact_frozen_inventory_and_migration() -> None:
    assert models.M1B_TABLE_ORDER[-2:] == ("m1b_faers_queries", "m1b_faers_buckets")
    query = models.m1b_faers_queries
    buckets = models.m1b_faers_buckets
    assert len(query.columns) == 27
    assert len(buckets.columns) == 10
    assert {column.name for column in query.columns if column.nullable} == {"role_predicate_json"}
    assert not any(column.nullable for column in buckets.columns)
    assert len(query.foreign_key_constraints) == 2
    assert len(buckets.foreign_key_constraints) == 1
    assert {
        constraint.name
        for constraint in query.constraints
        if isinstance(constraint, sa.UniqueConstraint)
    } == {"uq_m1b_faers_queries_binding"}
    assert {
        constraint.name
        for constraint in buckets.constraints
        if isinstance(constraint, sa.UniqueConstraint)
    } == {"uq_m1b_faers_buckets_pt"}
    assert all(
        fk.onupdate == "RESTRICT" and fk.ondelete == "RESTRICT"
        for table in (query, buckets)
        for fk in table.foreign_key_constraints
    )
    module = _faers_migration_module()
    expected = tuple(
        str(
            CreateTable(models.metadata.tables[f"{models.SCHEMA}.{name}"]).compile(
                dialect=postgresql.dialect()
            )
        )
        for name in module._CREATE_ORDER
    )
    termination_projection = (
        "ALTER TABLE medevidence.m1b_snapshot_artifacts "
        "DROP CONSTRAINT ck_member_termination, ADD CONSTRAINT ck_member_termination "
        "CHECK (termination_reason IN "
        "('complete_response','payload_limit','stream_error','read_timeout','deadline_exceeded'))"
    )
    assert module.revision == "m1bfaers002001"
    assert module.down_revision == "m1bdm002001"
    assert models.M1B_TABLE_ORDER[-2:] == module.TABLE_ORDER
    assert module._ddl_statements() == (termination_projection, *expected)
    assert "medevidence.persistence" not in Path(module.__file__).read_text(encoding="utf-8")


def test_faers_snapshot_membership_rejects_duplicate_artifact_identity() -> None:
    membership = models.m1b_snapshot_artifacts
    unique_columns = {
        constraint.name: tuple(column.name for column in constraint.columns)
        for constraint in membership.constraints
        if isinstance(constraint, sa.UniqueConstraint)
    }
    assert unique_columns["uq_m1b_snapshot_artifacts_membership"] == (
        "run_id",
        "source",
        "acquisition_id",
        "snapshot_id",
        "artifact_id",
    )
    assert "content_hash" in membership.c
    assert any(
        tuple(element.parent.name for element in constraint.elements)
        == (
            "artifact_id",
            "source",
            "content_hash",
        )
        for constraint in membership.foreign_key_constraints
    )


def test_faers_snapshot_persistence_rejects_third_response_membership() -> None:
    for ordinal in (0, 1):
        PersistenceRepository._validate_m1b_row(
            "m1b_snapshot_artifacts",
            {"source": "faers", "ordinal": ordinal},
        )
    with pytest.raises(ValueError, match="two-attempt profile"):
        PersistenceRepository._validate_m1b_row(
            "m1b_snapshot_artifacts",
            {"source": "faers", "ordinal": 2},
        )


def test_faers_read_timeout_is_the_only_additive_persisted_termination() -> None:
    membership = models.m1b_snapshot_artifacts
    check = next(
        constraint
        for constraint in membership.constraints
        if isinstance(constraint, sa.CheckConstraint) and constraint.name == "ck_member_termination"
    )
    assert str(check.sqltext) == (
        "termination_reason IN "
        "('complete_response','payload_limit','stream_error','read_timeout','deadline_exceeded')"
    )


def test_faers_migration_executes_valid_closed_bounds_json_without_bind_rewriting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _faers_migration_module()
    statements: list[str] = []

    class DriverConnection:
        def exec_driver_sql(self, statement: str) -> None:
            statements.append(statement)

    monkeypatch.setattr(module.op, "get_bind", lambda: DriverConnection())
    module.upgrade()
    assert statements == list(module._ddl_statements())
    assert statements[0].startswith("ALTER TABLE medevidence.m1b_snapshot_artifacts")
    assert "'read_timeout'" in statements[0]
    query_ddl = statements[1]
    match = re.search(r"bounds_json = '(\{[^']+\})'::jsonb", query_ddl)
    assert match is not None
    assert json.loads(match.group(1)) == {
        "max_query_characters": 512,
        "max_pages": 5,
        "page_size": 100,
        "max_returned_raw_records": 100,
        "max_response_bytes": 5_242_880,
        "max_cumulative_bytes": 5_242_880,
        "effective_total_deadline_ms": 30_000,
        "generic_total_deadline_ceiling_ms": 60_000,
    }


def test_m1b_dm002_nullability_matches_the_exact_freeze() -> None:
    nullable = {
        f"{table.name}.{column.name}"
        for table in (
            models.metadata.tables[f"{models.SCHEMA}.{name}"] for name in models.M1B_TABLE_ORDER
        )
        for column in table.columns
        if column.nullable
    }
    assert nullable == {
        "m1b_artifacts.corpus_id",
        "m1b_artifacts.corpus_version",
        "m1b_artifacts.split",
        "m1b_artifact_lineage.parent_corpus_id",
        "m1b_artifact_lineage.parent_corpus_version",
        "m1b_artifact_lineage.parent_split",
        "m1b_artifact_lineage.child_corpus_id",
        "m1b_artifact_lineage.child_corpus_version",
        "m1b_artifact_lineage.child_split",
        "m1b_acquisitions.completed_at_utc",
        "m1b_source_outcomes.failure_id",
        "m1b_snapshot_artifacts.http_status",
        "m1b_snapshot_artifacts.corpus_id",
        "m1b_snapshot_artifacts.corpus_version",
        "m1b_snapshot_artifacts.split",
        "m1b_runs.completed_at_utc",
        "m1b_run_sources.reason_code",
        "m1b_run_sources.reason",
        "m1b_dailymed_selection_decisions.selected_candidate_id",
        "m1b_dailymed_selection_decisions.selected_setid",
        "m1b_dailymed_selection_decisions.selected_spl_version",
        "m1b_dailymed_selection_decisions.selected_member_ordinal",
        "m1b_dailymed_selection_decisions.selected_link_id",
        "m1b_dailymed_selection_decisions.selected_raw_artifact_id",
        "m1b_dailymed_selection_decisions.selected_raw_content_hash",
        "m1b_dailymed_selection_decisions.selected_body_complete",
        "m1b_dailymed_selection_decisions.selected_termination_reason",
        "m1b_dailymed_selection_decisions.selected_candidate_ordinal",
        "m1b_dailymed_label_versions.effective_date",
        "m1b_dailymed_label_versions.published_date",
        "m1b_dailymed_sections.parent_section_id",
        "m1b_dailymed_label_supersession.observed_run_id",
        "m1b_dailymed_label_supersession.observed_acquisition_id",
        "m1b_dailymed_label_supersession.observed_acquisition_ordinal",
        "m1b_dailymed_label_supersession.observed_acquisition_intent_id",
        "m1b_dailymed_label_supersession.observed_operation",
        "m1b_dailymed_label_supersession.observed_query_id",
        "m1b_dailymed_label_supersession.observed_snapshot_id",
        "m1b_dailymed_label_supersession.observed_manifest_id",
        "m1b_faers_queries.role_predicate_json",
    }


@pytest.mark.parametrize(
    "table_name",
    (
        "m1b_dailymed_selection_decisions",
        "m1b_dailymed_label_versions",
        "m1b_dailymed_sections",
        "m1b_dailymed_label_supersession",
        "m1b_faers_queries",
        "m1b_faers_buckets",
    ),
)
def test_generic_m1b_repository_rejects_specialized_dailymed_tables(
    table_name: str,
) -> None:
    repository = PersistenceRepository._from_engine_for_testing(sa.create_engine("sqlite://"))
    try:
        with pytest.raises(ValueError, match="specialized authoritative repository method"):
            repository.insert_or_verify_m1b(table_name, {})
    finally:
        repository.close()


def _faers_result() -> FaersAggregateResult:
    query = FaersAggregateQueryV1.create(
        FaersAggregateRequestV1(
            drug_concept_id="drug:synthetic",
            identity_strategy=FaersIdentityStrategy.HARMONIZED_SUBSTANCE,
            identity_exact_value="SYNTHETIC",
            pt_values=("DIARRHOEA", "NAUSEA", "VOMITING"),
            inclusive_date_range=FaersInclusiveDateRangeV1(
                start_date=date(2025, 1, 1), end_date=date(2025, 12, 31)
            ),
            statistical_unit="provider_count_occurrence",
            execution_bounds=FaersExecutionBoundsV1(
                max_date_difference_days=365,
                max_inclusive_calendar_dates=366,
            ),
        )
    )
    buckets = tuple(
        FaersAggregateBucketV1(
            query_id=query.query_id,
            bucket_ordinal=ordinal,
            reaction_pt=pt,
            report_count=count,
            identity_stratum=query.identity_stratum,
        )
        for ordinal, (pt, count) in enumerate((("NAUSEA", 8), ("VOMITING", 4)))
    )
    outcome = SourceOutcome(
        source=SourceType.FAERS,
        query_id=query.query_id,
        execution_status=ExecutionStatus.SUCCEEDED,
        coverage_status=CoverageStatus.COMPLETE,
        result_status=ResultStatus.MATCHES,
        configured_bounds=ExecutionBounds(
            max_query_characters=512,
            max_pages=5,
            max_records=100,
            max_payload_bytes=5_242_880,
            max_total_seconds=30,
        ),
        valid_result_count=2,
        pages_completed=1,
        truncated=False,
    )
    return FaersAggregateResult(
        query=query,
        buckets=buckets,
        source_outcome=outcome,
        retrieved_at_utc=datetime(2026, 8, 12, tzinfo=UTC),
        provider_as_of_utc=None,
        snapshot_id="snapshot:faers",
        manifest_id="manifest:faers",
        limitations=FAERS_MANDATORY_LIMITATIONS,
    )


def test_faers_persistence_projection_is_exact_and_closed() -> None:
    result = _faers_result()
    row = PersistenceRepository._faers_query_row(
        run_id="run:00000000-0000-4000-8000-000000000001",
        acquisition_id="acquisition:faers",
        result=result,
    )
    assert set(row) == {column.name for column in models.m1b_faers_queries.columns}
    assert row["pt_values"] == ["DIARRHOEA", "NAUSEA", "VOMITING"]
    assert isinstance(row["role_predicate_json"], sa.sql.elements.Null)
    assert row["date_field"] == "receivedate"
    assert row["endpoint_mode"] == "provider_count_occurrence"
    assert row["bounds_json"] == {
        "max_query_characters": 512,
        "max_pages": 5,
        "page_size": 100,
        "max_returned_raw_records": 100,
        "max_response_bytes": 5_242_880,
        "max_cumulative_bytes": 5_242_880,
        "effective_total_deadline_ms": 30_000,
        "generic_total_deadline_ceiling_ms": 60_000,
    }


class _CapacityResult:
    def __init__(self, existing: dict[str, object] | None) -> None:
        self._existing = existing

    def mappings(self) -> _CapacityResult:
        return self

    def one_or_none(self) -> dict[str, object] | None:
        return self._existing


class _CapacityConnection:
    def __init__(self, count: int, existing: dict[str, object] | None) -> None:
        self._count = count
        self._existing = existing
        self.execute_calls = 0

    def execute(self, _statement: object) -> _CapacityResult:
        self.execute_calls += 1
        return _CapacityResult(self._existing)

    def scalar(self, _statement: object) -> int:
        return self._count


@pytest.mark.parametrize(
    "table_name",
    tuple(
        # These adapters have dedicated persistence APIs, not the generic _SPECS path.
        name
        for name in EXPECTED_TABLES
        if name
        not in {
            "m3_provider_attempt_events",
            "m3_exports",
            "m3_dailymed_v2_records",
            "m3_dailymed_v2_members",
        }
    ),
)
@pytest.mark.parametrize(
    "state",
    ("capacity_minus_one", "full_identical", "full_conflict", "full_new_identity"),
)
def test_capacity_guard_preserves_identity_precedence_for_generic_repository_tables(
    table_name: str,
    state: str,
) -> None:
    spec = repository_module._SPECS[table_name]
    values: dict[str, object] = {
        column: f"synthetic:{table_name}:{column}" for column in spec.comparison_columns
    }
    existing: dict[str, object] | None = None
    if state in {"full_identical", "full_conflict"}:
        existing = dict(values)
    if state == "full_conflict":
        divergent_column = next(
            column for column in spec.comparison_columns if column not in spec.identity_columns
        )
        assert existing is not None
        existing[divergent_column] = f"different:{table_name}:{divergent_column}"
    count = spec.capacity - 1 if state == "capacity_minus_one" else spec.capacity
    fake = _CapacityConnection(count, existing)
    connection = cast(Connection, cast(object, fake))
    repository = cast(PersistenceRepository, object.__new__(PersistenceRepository))

    if state == "capacity_minus_one":
        assert repository._lock_and_check_capacity(connection, spec, values) is None
        assert fake.execute_calls == 1
    elif state == "full_identical":
        assert repository._lock_and_check_capacity(connection, spec, values) == values
        assert fake.execute_calls == 2
    elif state == "full_conflict":
        with pytest.raises(PersistenceConflict) as captured:
            repository._lock_and_check_capacity(connection, spec, values)
        assert captured.value.table == table_name
        assert captured.value.constraint == EXPECTED_IDENTITY_CONSTRAINTS[table_name]
        assert fake.execute_calls == 2
    else:
        with pytest.raises(
            PersistenceCapacityError,
            match=f"frozen capacity reached for {table_name}: {spec.capacity}",
        ):
            repository._lock_and_check_capacity(connection, spec, values)
        assert fake.execute_calls == 2


NOW = datetime(2026, 8, 7, 15, 0, tzinfo=UTC)
DIGEST = f"sha256:{'a' * 64}"
INTENT = f"acquisition-intent:sha256:{'b' * 64}"


def _manifest() -> ValidatedManifest:
    return ValidatedManifest(
        manifest_id=DIGEST,
        manifest_schema_version="1.0",
        retention_policy_id="M1A-LIVE-RETENTION-v1",
        source_type="pubmed",
        acquisition_intent_id=INTENT,
        request_identity="bounded request",
        started_at_utc=NOW,
        completed_at_utc=NOW,
        record_count=0,
        execution_status="succeeded",
        coverage_status="complete",
        result_status="no_match",
        attempts_used=1,
        pages_completed=1,
        truncated=False,
        warning_codes=(),
        files=(),
        connector_name="medevidence.connectors.pubmed",
        connector_version="m1a-002",
        source_record_schema_version="1.0",
        code_revision="c" * 40,
    )


def _snapshot() -> SourceSnapshotRow:
    return SourceSnapshotRow(
        snapshot_id=DIGEST,
        source="pubmed",
        acquisition_intent_id=INTENT,
        request_identity="bounded request",
        execution_status="succeeded",
        coverage_status="complete",
        result_status="no_match",
        record_count=0,
        attempts_used=1,
        pages_completed=1,
        truncated=False,
        manifest_artifact_id=DIGEST,
        manifest_artifact_kind="snapshot_manifest",
        manifest_source_partition="pubmed",
        manifest_content_hash=DIGEST,
        started_at_utc=NOW,
        completed_at_utc=NOW,
        connector_name="medevidence.connectors.pubmed",
        connector_version="m1a-002",
        manifest_schema_version="1.0",
        source_record_schema_version="1.0",
        code_revision="c" * 40,
        retention_policy_id="M1A-LIVE-RETENTION-v1",
    )


MANIFEST_SNAPSHOT_MUTATIONS = (
    ("snapshot_id", f"sha256:{'d' * 64}"),
    ("source", "other"),
    ("acquisition_intent_id", f"acquisition-intent:sha256:{'d' * 64}"),
    ("request_identity", "different"),
    ("execution_status", "failed"),
    ("coverage_status", "partial"),
    ("result_status", "indeterminate"),
    ("record_count", 1),
    ("attempts_used", 2),
    ("pages_completed", 0),
    ("truncated", True),
    ("started_at_utc", datetime(2026, 8, 7, 14, 59, tzinfo=UTC)),
    ("completed_at_utc", datetime(2026, 8, 7, 15, 1, tzinfo=UTC)),
    ("connector_name", "different.connector"),
    ("connector_version", "different"),
    ("manifest_schema_version", "2.0"),
    ("source_record_schema_version", "2.0"),
    ("code_revision", "d" * 40),
    ("retention_policy_id", "different"),
)


@pytest.mark.parametrize("column,value", MANIFEST_SNAPSHOT_MUTATIONS)
def test_every_manifest_snapshot_projection_mismatch_is_rejected(
    column: str,
    value: object,
) -> None:
    snapshot = _snapshot()
    snapshot[column] = value  # type: ignore[literal-required]

    with pytest.raises(ValueError, match="validated manifest"):
        PersistenceRepository._compare_manifest_snapshot(
            _manifest(), snapshot, error_type=ValueError
        )


def _attempt() -> ResearchRunAttemptRow:
    return ResearchRunAttemptRow(
        attempt_id="attempt:00000000-0000-4000-8000-000000000001",
        run_id="run:00000000-0000-4000-8000-000000000001",
        acquisition_ordinal=0,
        acquisition_intent_id=INTENT,
        registration_envelope_id=f"registration-envelope:acquisition:sha256:{'e' * 64}",
        source="pubmed",
        operation="search",
        intent_created_at_utc=NOW,
        request_identity="bounded request",
        execution_profile_id="M1A_CONSTRAINED_V1",
        started_at_utc=NOW,
        completed_at_utc=NOW,
        execution_status="succeeded",
        coverage_status="complete",
        result_status="no_match",
        valid_result_count=0,
        pages_completed=1,
        attempts_used=1,
        truncated=False,
        warning_codes=(),
        failure_code=None,
        redacted_detail=None,
        registration_state="ready_for_insert",
        manifest_id=DIGEST,
        envelope_artifact_id=f"sha256:{'e' * 64}",
        envelope_artifact_kind="acquisition_registration_envelope",
        envelope_source_partition="pubmed",
        envelope_content_hash=f"sha256:{'e' * 64}",
        intent_schema_version="1.0",
        envelope_schema_version="1.0",
    )


ATTEMPT_MANIFEST_MUTATIONS = (
    ("manifest_id", f"sha256:{'d' * 64}"),
    ("acquisition_intent_id", f"acquisition-intent:sha256:{'d' * 64}"),
    ("source", "other"),
    ("request_identity", "different"),
    ("started_at_utc", datetime(2026, 8, 7, 14, 59, tzinfo=UTC)),
    ("completed_at_utc", datetime(2026, 8, 7, 15, 1, tzinfo=UTC)),
    ("execution_status", "failed"),
    ("coverage_status", "partial"),
    ("result_status", "indeterminate"),
    ("valid_result_count", 1),
    ("pages_completed", 0),
    ("attempts_used", 2),
    ("truncated", True),
    ("warning_codes", ("different",)),
)


@pytest.mark.parametrize("column,value", ATTEMPT_MANIFEST_MUTATIONS)
def test_every_attempt_manifest_projection_mismatch_is_rejected(
    column: str,
    value: object,
) -> None:
    attempt = _attempt()
    attempt[column] = value  # type: ignore[literal-required]

    with pytest.raises(ValueError, match="validated attempt"):
        PersistenceRepository._compare_attempt_manifest(
            attempt, _manifest(), _snapshot(), error_type=ValueError
        )


@pytest.mark.parametrize(
    "field,value",
    (
        ("ordinal", 1),
        ("link_id", f"artifact-link:sha256:{'d' * 64}"),
        ("artifact_id", f"sha256:{'d' * 64}"),
        ("byte_size", 2),
        ("media_type", "application/octet-stream"),
        ("content_encoding", "gzip"),
        ("http_status", 500),
        ("body_complete", False),
        ("termination_reason", "stream_error"),
    ),
)
def test_every_manifest_file_link_projection_mismatch_is_rejected(
    field: str,
    value: object,
) -> None:
    file = ValidatedManifestFile(
        ordinal=0,
        link_id=f"artifact-link:sha256:{'f' * 64}",
        artifact_id=f"sha256:{'f' * 64}",
        relative_path=f"pubmed/sha256/ff/{'f' * 64}.bin",
        byte_size=1,
        media_type="application/xml",
        content_encoding=None,
        http_status=200,
        body_complete=True,
        termination_reason="complete_response",
    )
    link = ValidatedArtifactLink(
        link_id=file.link_id,
        acquisition_intent_id=INTENT,
        ordinal=0,
        artifact_id=file.artifact_id,
        artifact_kind="pubmed_http_response",
        media_type=file.media_type,
        content_encoding=None,
        http_status=200,
        byte_size=1,
        body_complete=True,
        termination_reason="complete_response",
        observed_at_utc=NOW,
        schema_version="1.0",
    )
    mutated = replace(file, **{field: value})

    with pytest.raises(ValueError, match="artifact link differs"):
        PersistenceRepository._expected_file_rows(
            replace(_manifest(), files=(mutated,)), (link,), _snapshot()
        )
