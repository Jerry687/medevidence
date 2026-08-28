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
EXPECTED_TABLES = (*M1A_EXPECTED_TABLES, "m3_validation_receipts")

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


def test_exact_object_counts_and_names() -> None:
    assert tuple(table.name for table in models.TABLE_ORDER) == EXPECTED_TABLES
    assert len(models.metadata.tables) == 31
    assert len(_constraints(sa.CheckConstraint)) == 67
    assert len(_constraints(sa.ForeignKeyConstraint)) == 17
    assert len(_constraints(sa.PrimaryKeyConstraint)) == 14
    assert len(_constraints(sa.UniqueConstraint)) == 23
    assert sum(len(table.indexes) for table in models.TABLE_ORDER) == 12
    assert _constraints(sa.CheckConstraint) == set(models.EXPECTED_CHECK_NAMES)


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


def test_validation_receipt_migration_embeds_exact_application_metadata() -> None:
    module = _m3_validation_receipt_migration_module()
    expected = str(CreateTable(models.m3_validation_receipts).compile(dialect=postgresql.dialect()))
    assert module.revision == "m3validationreceipt001"
    assert module.down_revision == "m1bfaers002001"
    assert module.TABLE_ORDER == ("m3_validation_receipts",)
    assert module._ddl_statements() == (expected,)
    assert "medevidence.persistence" not in Path(module.__file__).read_text(encoding="utf-8")


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


def test_raw_bytes_have_no_postgresql_column() -> None:
    assert all(
        not isinstance(column.type, (sa.LargeBinary,)) and "BYTEA" not in str(column.type).upper()
        for table in models.metadata.tables.values()
        for column in table.columns
    )


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
        )
        for name in module._CREATE_ORDER
    )
    assert module.revision == "m1bdm002001"
    assert module.down_revision == "m1a003b0001"
    assert models.M1B_TABLE_ORDER[: len(module.TABLE_ORDER)] == module.TABLE_ORDER
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


@pytest.mark.parametrize("table_name", EXPECTED_TABLES)
@pytest.mark.parametrize(
    "state",
    ("capacity_minus_one", "full_identical", "full_conflict", "full_new_identity"),
)
def test_capacity_guard_preserves_identity_precedence_for_every_table(
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
