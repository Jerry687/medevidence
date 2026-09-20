"""Disposable PostgreSQL reads for exact DailyMed and FAERS source parents."""

from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from tests.integration.persistence import test_faers_metadata as faers_fixture
from tests.unit.connectors.test_dailymed_parsing import SETID, VERSION

from medevidence.connectors.dailymed.parsing import parse_spl_document
from medevidence.domain import (
    DailyMedLabelVersion,
    DailyMedMarketingState,
    LabelSection,
    sha256_digest,
)
from medevidence.persistence import PersistenceRepository, PersistenceSettings, models
from medevidence.persistence.config import DATABASE_URL_ENV

DAILY_RUN = "run:00000000-0000-4000-8000-000000000088"
DAILY_ACQUISITION = "acquisition:dailymed-provenance-synthetic"
DAILY_QUERY = "query:dailymed-provenance-synthetic"
DAILY_SNAPSHOT = f"snapshot:{DAILY_QUERY}:fetch"
DAILY_OUTCOME = f"source-outcome:{DAILY_QUERY}:fetch"
NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _repository() -> PersistenceRepository:
    if os.environ.get(DATABASE_URL_ENV) is None:
        pytest.skip(f"{DATABASE_URL_ENV} is required")
    return PersistenceRepository(PersistenceSettings.from_env())


@pytest.fixture(scope="module", autouse=True)
def migrated_database() -> Iterator[None]:
    url = os.environ.get(DATABASE_URL_ENV)
    if url is None:
        pytest.skip(f"{DATABASE_URL_ENV} is required")
    engine = sa.create_engine(url, hide_parameters=True)
    with engine.begin() as connection:
        if connection.dialect.has_table(connection, "m1b_snapshot_artifacts", schema="medevidence"):
            connection.execute(models.m1b_snapshot_artifacts.delete())
    engine.dispose()
    config = Config("alembic.ini")
    command.downgrade(config, "base")
    command.upgrade(config, "head")
    yield


def _artifact(
    digest: str, *, kind: str, source: str, path: str, size: int, schema: str
) -> dict[str, object]:
    return {
        "artifact_id": digest,
        "artifact_kind": kind,
        "source_partition": source,
        "content_hash": digest,
        "byte_size": size,
        "media_type": "application/xml" if source == "dailymed" else "application/json",
        "relative_storage_label": path,
        "schema_version": schema,
        "created_at_utc": NOW,
        "corpus_id": None,
        "corpus_version": None,
        "split": None,
    }


def test_dailymed_binding_reads_exact_section_and_three_parents() -> None:
    repository = _repository()
    try:
        spl = Path("tests/fixtures/dailymed/spl-valid.xml").read_bytes()
        spl_hash = sha256_digest(spl)
        raw_bytes = spl + b"\n"
        raw_hash = sha256_digest(raw_bytes)
        manifest_hash = sha256_digest(b"manifest")
        parsed = parse_spl_document(spl, expected_setid=SETID, expected_spl_version=VERSION)
        section = parsed.sections[0]
        for row in (
            _artifact(
                manifest_hash,
                kind="dailymed_snapshot_manifest",
                source="dailymed",
                path="dailymed/test/manifest.json",
                size=8,
                schema="m1b.dailymed.snapshot-manifest.v1",
            ),
            _artifact(
                raw_hash,
                kind="dailymed_http_response",
                source="dailymed",
                path="dailymed/test/raw.xml",
                size=len(raw_bytes),
                schema="m1b.dailymed.raw-response.v1",
            ),
            _artifact(
                spl_hash,
                kind="dailymed_spl_xml",
                source="dailymed",
                path=f"dailymed/sha256/{spl_hash.removeprefix('sha256:')}.xml",
                size=len(spl),
                schema="m1b.dailymed.spl-artifact.v1",
            ),
        ):
            repository.insert_or_verify_m1b_artifact(row)
        repository.insert_or_verify_m1b(
            "m1b_runs",
            {
                "run_id": DAILY_RUN,
                "request_id": "request:00000000-0000-4000-8000-000000000088",
                "scope_id": "scope:sha256:" + "8" * 64,
                "status": "completed",
                "created_at_utc": NOW,
                "completed_at_utc": NOW,
                "schema_version": "m1b.run.v1",
            },
        )
        intent = "acquisition-intent:sha256:" + "8" * 64
        attempt = "attempt:00000000-0000-4000-8000-000000000088"
        repository.insert_or_verify_m1b(
            "m1b_acquisitions",
            {
                "acquisition_intent_id": intent,
                "acquisition_ordinal": 0,
                "attempt_id": attempt,
                "run_id": DAILY_RUN,
                "acquisition_id": DAILY_ACQUISITION,
                "source": "dailymed",
                "operation": "fetch",
                "request_identity": DAILY_QUERY,
                "query_id": DAILY_QUERY,
                "execution_profile_id": "DAILYMED_M1B_CONSTRAINED_V1",
                "started_at_utc": NOW,
                "completed_at_utc": NOW,
                "schema_version": "m1b.acquisition.v1",
            },
        )
        repository.insert_or_verify_m1b(
            "m1b_snapshots",
            {
                "query_id": DAILY_QUERY,
                "acquisition_intent_id": intent,
                "acquisition_ordinal": 0,
                "attempt_id": attempt,
                "run_id": DAILY_RUN,
                "snapshot_id": DAILY_SNAPSHOT,
                "acquisition_id": DAILY_ACQUISITION,
                "source": "dailymed",
                "manifest_artifact_id": manifest_hash,
                "retrieved_at_utc": NOW,
                "connector_version": "test",
                "schema_version": "m1b.dailymed.snapshot.v1",
            },
        )
        repository.insert_or_verify_m1b(
            "m1b_source_outcomes",
            {
                "source_outcome_id": DAILY_OUTCOME,
                "snapshot_id": DAILY_SNAPSHOT,
                "run_id": DAILY_RUN,
                "query_id": DAILY_QUERY,
                "acquisition_id": DAILY_ACQUISITION,
                "source": "dailymed",
                "acquisition_intent_id": intent,
                "acquisition_ordinal": 0,
                "operation": "fetch",
                "execution_status": "succeeded",
                "coverage_status": "complete",
                "result_status": "matches",
                "max_query_characters": 512,
                "max_pages": 5,
                "max_records": 100,
                "max_payload_bytes": 5_242_880,
                "max_total_seconds": 30,
                "valid_result_count": 1,
                "pages_completed": 1,
                "truncated": False,
                "failure_id": None,
                "warning_codes": [],
                "schema_version": "1.0",
            },
        )
        repository.insert_or_verify_m1b(
            "m1b_snapshot_artifacts",
            {
                "acquisition_id": DAILY_ACQUISITION,
                "source": "dailymed",
                "run_id": DAILY_RUN,
                "snapshot_id": DAILY_SNAPSHOT,
                "ordinal": 0,
                "link_id": "artifact-link:sha256:" + "8" * 64,
                "artifact_id": raw_hash,
                "content_hash": raw_hash,
                "body_complete": True,
                "termination_reason": "complete_response",
                "http_status": 200,
                "observed_at_utc": NOW,
                "corpus_id": None,
                "corpus_version": None,
                "split": None,
                "artifact_kind": "dailymed_http_response",
            },
        )
        version = DailyMedLabelVersion.create(
            setid=SETID,
            spl_version=VERSION,
            marketing_state=DailyMedMarketingState.ACTIVE,
            effective_date=None,
            published_date=None,
            content_hash=spl_hash,
            spl_artifact_id=spl_hash,
        )
        version_row = version.model_dump(mode="python")
        version_row.update(
            source="dailymed", setid=UUID(SETID), spl_version=int(VERSION), marketing_state="active"
        )
        repository.insert_or_verify_dailymed_label_version(version_row)
        label_section = LabelSection.create(
            setid=SETID,
            label_version_id=version.label_version_id,
            spl_version=VERSION,
            section_ordinal=section.section_ordinal,
            section_code=section.section_code,
            title=section.title,
            parent_section_id=None,
            xml_path=section.xml_path,
            text_start=section.text_start,
            text_end=section.text_end,
            text_hash=sha256_digest(section.text.encode()),
            spl_artifact_id=spl_hash,
        )
        section_row = label_section.model_dump(mode="python")
        section_row.update(source="dailymed", setid=UUID(SETID), spl_version=int(VERSION))
        repository.insert_or_verify_dailymed_section(section_row)
        binding = repository.get_dailymed_evidence_binding(
            run_id=DAILY_RUN,
            acquisition_id=DAILY_ACQUISITION,
            query_id=DAILY_QUERY,
            source_outcome_id=DAILY_OUTCOME,
            snapshot_id=DAILY_SNAPSHOT,
            label_version_id=version.label_version_id,
            section_id=label_section.section_id,
        )
        assert binding is not None
        assert binding.text_hash == sha256_digest(section.text.encode())
        assert binding.raw.content_hash == raw_hash
        assert binding.manifest.content_hash == manifest_hash
    finally:
        repository.close()


def test_faers_binding_reads_query_bucket_and_complete_raw_parent() -> None:
    repository = _repository()
    try:
        result = faers_fixture._result()
        faers_fixture._register_parents(repository, result)
        raw_hash = sha256_digest(b"raw")
        repository.insert_or_verify_m1b_artifact(
            _artifact(
                raw_hash,
                kind="faers_http_response",
                source="faers",
                path="faers/test/raw.json",
                size=3,
                schema="m1b.faers.raw-response.v1",
            )
        )
        repository.insert_or_verify_m1b(
            "m1b_snapshot_artifacts",
            {
                "acquisition_id": faers_fixture.ACQUISITION_ID,
                "source": "faers",
                "run_id": faers_fixture.RUN_ID,
                "snapshot_id": faers_fixture.SNAPSHOT_ID,
                "ordinal": 0,
                "link_id": "artifact-link:sha256:" + "5" * 64,
                "artifact_id": raw_hash,
                "content_hash": raw_hash,
                "body_complete": True,
                "termination_reason": "complete_response",
                "http_status": 200,
                "observed_at_utc": NOW,
                "corpus_id": None,
                "corpus_version": None,
                "split": None,
                "artifact_kind": "faers_http_response",
            },
        )
        repository.insert_or_verify_faers_result(
            run_id=faers_fixture.RUN_ID,
            acquisition_id=faers_fixture.ACQUISITION_ID,
            result=result,
        )
        binding = repository.get_faers_evidence_binding(
            run_id=faers_fixture.RUN_ID,
            acquisition_id=faers_fixture.ACQUISITION_ID,
            query_id=result.query.query_id,
            source_outcome_id="source-outcome:faers-persistence-synthetic",
            snapshot_id=result.snapshot_id,
            bucket_ordinal=0,
        )
        assert binding is not None
        assert binding.reaction_pt == "NAUSEA"
        assert binding.report_count == 8
        assert binding.raw.content_hash == raw_hash
        assert binding.manifest.content_hash == "sha256:" + "9" * 64
    finally:
        repository.close()
