"""Real PostgreSQL/LangGraph application with labelled synthetic tool inputs."""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest
from alembic import command
from alembic.config import Config
from tests.unit.orchestration import test_workflow as synthetic

from medevidence.domain import (
    DrugConcept,
    ResearchScope,
    SourceType,
    derive_identity,
    sha256_digest,
)
from medevidence.infrastructure.langgraph_checkpoint import postgres_checkpoint_saver
from medevidence.infrastructure.local_export_writer import LocalExportWriter
from medevidence.infrastructure.review_export_store import ReviewExportStore
from medevidence.infrastructure.runtime_application import ResearchApplicationService
from medevidence.orchestration import (
    CollectionFailureClassification,
    ControlledOrchestrationWorkflow,
)
from medevidence.orchestration.langgraph_runtime import LangGraphOrchestrationRuntime
from medevidence.persistence.config import DATABASE_URL_ENV, PersistenceSettings
from medevidence.persistence.repositories import ReviewExportRepository
from medevidence.persistence.research_jobs import ResearchJobRepository, allocated_ids
from medevidence.tools.report_document import EvidenceProvenanceV1
from medevidence.tools.research_application import (
    ResearchApplicationErrorCode,
    ResearchApplicationFailure,
    ResearchExportFormat,
    ResearchReviewCommand,
    ResearchReviewDecision,
    ResearchRunStatus,
    ResearchSubmission,
)

GENERATED = datetime(2026, 2, 1, tzinfo=UTC)
RETRIEVED = datetime(2026, 1, 1, tzinfo=UTC)


@pytest.fixture(scope="module")
def settings() -> PersistenceSettings:
    url = os.environ.get(DATABASE_URL_ENV)
    if url is None:
        pytest.skip(f"{DATABASE_URL_ENV} is required for disposable PostgreSQL tests")
    config = Config("alembic.ini")
    command.downgrade(config, "base")
    command.upgrade(config, "head")
    return PersistenceSettings(url)


class SyntheticImmutableProvenance:
    """Test-only verified source facts fixed independently before material callback."""

    def __init__(self, run_id: str, evidence: tuple[object, ...]) -> None:
        self.run_id = run_id
        self.rows = tuple(
            EvidenceProvenanceV1(
                item.evidence_id,
                item.source,
                item.source_record_id,
                item.source_version,
                item.snapshot_id,
                item.content_hash,
                "https://example.org/synthetic-source",
                None,
                RETRIEVED,
                ("synthetic verified snapshot",),
            )
            for item in evidence
        )
        self._by_id = {row.evidence_id: row for row in self.rows}

    def load_verified_provenance(
        self,
        *,
        run_id: str,
        evidence_id: str,
        source: SourceType,
        source_record_id: str,
        source_version: str,
        snapshot_id: str,
        content_hash: str,
    ) -> EvidenceProvenanceV1 | None:
        row = self._by_id.get(evidence_id)
        if run_id != self.run_id or row is None:
            return None
        if (
            row.source,
            row.source_record_id,
            row.source_version,
            row.snapshot_id,
            row.content_hash,
        ) != (source, source_record_id, source_version, snapshot_id, content_hash):
            return None
        return row


class SyntheticMultiProvenance:
    """Test-only per-run immutable fact fixture for two persisted jobs."""

    def __init__(self, readers: dict[str, SyntheticImmutableProvenance]) -> None:
        self._readers = readers

    def load_verified_provenance(
        self,
        *,
        run_id: str,
        evidence_id: str,
        source: SourceType,
        source_record_id: str,
        source_version: str,
        snapshot_id: str,
        content_hash: str,
    ) -> EvidenceProvenanceV1 | None:
        reader = self._readers.get(run_id)
        if reader is None:
            return None
        return reader.load_verified_provenance(
            run_id=run_id,
            evidence_id=evidence_id,
            source=source,
            source_record_id=source_record_id,
            source_version=source_version,
            snapshot_id=snapshot_id,
            content_hash=content_hash,
        )


def _key(path: Path) -> str:
    return sha256_digest(str(path))


def _harness(
    monkeypatch: pytest.MonkeyPatch,
    key: str,
    *,
    blocked: bool = False,
    validation_passed: bool = True,
    source_failure: bool = False,
) -> synthetic.Harness:
    ids = allocated_ids(key)
    monkeypatch.setattr(synthetic, "RUN_ID", ids["run_id"])
    monkeypatch.setattr(synthetic, "REPORT_ID", ids["report_id"])
    harness = synthetic.Harness(
        blocked=blocked,
        validation_passed=validation_passed,
        typed_failures=(
            {SourceType.PUBMED: [CollectionFailureClassification.PERMANENT]}
            if source_failure
            else None
        ),
    )
    return harness


@contextmanager
def _service(
    settings: PersistenceSettings,
    harness: synthetic.Harness,
    root: Path,
) -> Iterator[ResearchApplicationService]:
    jobs = ResearchJobRepository(settings)
    repository = ReviewExportRepository(settings)
    reader = SyntheticImmutableProvenance(
        synthetic.RUN_ID, cast(tuple[object, ...], harness.registry.evidence)
    )
    review_export = ReviewExportStore(
        repository,
        receipt_store=repository,
        provenance_store=reader,
        writer=LocalExportWriter._for_testing(root),
    )
    workflow = ControlledOrchestrationWorkflow(
        scope_safety=harness.scope_safety,
        source_planning=harness.planner,
        evidence_collection=harness.collector,
        synthesis=harness.synthesis,
        validation_registry=harness.registry,
        semantic_result_provider=harness.semantic,
        validation_receipt_store=repository,
        draft_persistence=review_export,
        export_approval=review_export,
        export=review_export,
    )

    def material_provider(state: object):
        request = workflow._build_validation_request(state, include_stored=True)
        return request, reader.rows, GENERATED

    with postgres_checkpoint_saver(settings, setup=True) as saver:

        def runtime_factory(
            *,
            run_id: str,
            scope: ResearchScope,
            report_id: str,
            checkpoint_id: str,
            destination_id: str,
        ) -> LangGraphOrchestrationRuntime:
            assert run_id == synthetic.RUN_ID
            assert scope == harness.scope
            assert report_id == synthetic.REPORT_ID
            assert destination_id.startswith("destination:sha256:")
            assert checkpoint_id.startswith("checkpoint:sha256:")
            return LangGraphOrchestrationRuntime(workflow=workflow, checkpointer=saver)

        service = ResearchApplicationService(
            runtime_factory=runtime_factory,
            scope_safety=harness.scope_safety,
            jobs=jobs,
            review_export=review_export,
            material_provider=material_provider,
            receipt_store=repository,
        )
        try:
            yield service
        finally:
            service.close()
            jobs.close()
            repository.close()


@contextmanager
def _multi_service(
    settings: PersistenceSettings,
    harnesses: dict[str, synthetic.Harness],
    root: Path,
) -> Iterator[ResearchApplicationService]:
    jobs = ResearchJobRepository(settings)
    repository = ReviewExportRepository(settings)
    readers = {
        run_id: SyntheticImmutableProvenance(
            run_id, cast(tuple[object, ...], harness.registry.evidence)
        )
        for run_id, harness in harnesses.items()
    }
    provenance = SyntheticMultiProvenance(readers)
    review_export = ReviewExportStore(
        repository,
        receipt_store=repository,
        provenance_store=provenance,
        writer=LocalExportWriter._for_testing(root),
    )
    workflows = {
        run_id: ControlledOrchestrationWorkflow(
            scope_safety=harness.scope_safety,
            source_planning=harness.planner,
            evidence_collection=harness.collector,
            synthesis=harness.synthesis,
            validation_registry=harness.registry,
            semantic_result_provider=harness.semantic,
            validation_receipt_store=repository,
            draft_persistence=review_export,
            export_approval=review_export,
            export=review_export,
        )
        for run_id, harness in harnesses.items()
    }
    with postgres_checkpoint_saver(settings, setup=True) as saver:

        def runtime_factory(
            *,
            run_id: str,
            scope: ResearchScope,
            report_id: str,
            checkpoint_id: str,
            destination_id: str,
        ) -> LangGraphOrchestrationRuntime:
            harness = harnesses[run_id]
            assert scope == harness.scope
            assert report_id == derive_identity("report", {"run_id": run_id})
            synthetic.RUN_ID = run_id
            synthetic.REPORT_ID = report_id
            return LangGraphOrchestrationRuntime(workflow=workflows[run_id], checkpointer=saver)

        def material_provider(state: object):
            request = workflows[state.run_id]._build_validation_request(state, include_stored=True)
            return request, readers[state.run_id].rows, GENERATED

        service = ResearchApplicationService(
            runtime_factory=runtime_factory,
            scope_safety=next(iter(harnesses.values())).scope_safety,
            jobs=jobs,
            review_export=review_export,
            material_provider=material_provider,
            receipt_store=repository,
        )
        try:
            yield service
        finally:
            service.close()
            jobs.close()
            repository.close()


def test_start_interrupt_restart_approve_export_and_read_only_download(
    settings: PersistenceSettings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    key = _key(tmp_path / "approve")
    harness = _harness(monkeypatch, key)
    submission = ResearchSubmission(scope=harness.scope, idempotency_key=key)
    with _service(settings, harness, tmp_path) as service:
        submitted = service.submit(submission)
        assert submitted.status is ResearchRunStatus.SUBMITTED
    with _service(settings, harness, tmp_path) as restarted:
        pending = restarted.get_run(submitted.run_id)
        assert pending.status is ResearchRunStatus.PENDING_REVIEW
        report = restarted.get_report(submitted.run_id)
        assert report.document.render_document_hash == pending.render_document_hash
        assert pending.pending_draft_id is not None
        assert pending.report_content_hash is not None
        assert pending.render_document_hash is not None
        command = ResearchReviewCommand(
            run_id=pending.run_id,
            report_id=pending.report_id,
            report_content_hash=pending.report_content_hash,
            render_document_hash=pending.render_document_hash,
            pending_draft_id=pending.pending_draft_id,
            destination_id=pending.destination_id,
            reviewer_id="local-reviewer:synthetic",
            decision=ResearchReviewDecision.APPROVE,
            idempotency_key=sha256_digest("synthetic approval"),
        )
        exported = restarted.review(command)
        assert exported.status is ResearchRunStatus.EXPORTED
        artifact = restarted.download_export(exported.run_id, ResearchExportFormat.JSON)
        assert json.loads(artifact.content)["marker"] == "MEDEVIDENCE_APPROVED_EXPORT_V1"
        assert restarted.review(command) == exported
        assert restarted.download_export(exported.run_id, ResearchExportFormat.JSON) == artifact


def test_safety_rejection_never_persists_scope_or_checkpoint(
    settings: PersistenceSettings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    key = _key(tmp_path / "phi")
    harness = _harness(monkeypatch, key, blocked=True)
    original = harness.scope
    scope = ResearchScope.create(
        drugs=(
            DrugConcept(
                concept_id=original.drugs[0].concept_id,
                preferred_term="Synthetic patient Example",
            ),
        ),
        adverse_reactions=original.adverse_reactions,
        date_range=original.date_range,
        selected_sources=original.selected_sources,
        comparison_intent=original.comparison_intent,
        query_bounds=original.query_bounds,
        result_bounds=original.result_bounds,
    )
    submission = ResearchSubmission(scope=scope, idempotency_key=key)
    with _service(settings, harness, tmp_path) as service:
        with pytest.raises(ResearchApplicationFailure) as captured:
            service.submit(submission)
        assert captured.value.code is ResearchApplicationErrorCode.SCOPE_REJECTED
        with pytest.raises(ResearchApplicationFailure) as repeated:
            service.submit(submission)
        assert repeated.value.code is ResearchApplicationErrorCode.SCOPE_REJECTED
        assert service._jobs.load(allocated_ids(key)["run_id"]) is None


def test_validation_blocked_has_checkpoint_and_no_export(
    settings: PersistenceSettings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    key = _key(tmp_path / "validation")
    harness = _harness(monkeypatch, key, validation_passed=False)
    submission = ResearchSubmission(scope=harness.scope, idempotency_key=key)
    with _service(settings, harness, tmp_path) as service:
        submitted = service.submit(submission)
    with _service(settings, harness, tmp_path) as restarted:
        blocked = restarted.get_run(submitted.run_id)
        assert blocked.status is ResearchRunStatus.BLOCKED
        with pytest.raises(ResearchApplicationFailure):
            restarted.download_export(blocked.run_id, ResearchExportFormat.JSON)
        assert list(tmp_path.iterdir()) == []


def test_source_failure_has_checkpoint_and_no_export(
    settings: PersistenceSettings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    key = _key(tmp_path / "source-failure")
    harness = _harness(monkeypatch, key, source_failure=True)
    with _service(settings, harness, tmp_path) as service:
        submitted = service.submit(ResearchSubmission(scope=harness.scope, idempotency_key=key))
    with _service(settings, harness, tmp_path) as restarted:
        blocked = restarted.get_run(submitted.run_id)
        assert blocked.status is ResearchRunStatus.BLOCKED
        with pytest.raises(ResearchApplicationFailure):
            restarted.get_report(blocked.run_id)
        assert list(tmp_path.iterdir()) == []


def test_same_submission_converges_and_foreign_scope_conflicts(
    settings: PersistenceSettings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    key = _key(tmp_path / "idempotency")
    harness = _harness(monkeypatch, key)
    submission = ResearchSubmission(scope=harness.scope, idempotency_key=key)
    with _service(settings, harness, tmp_path) as service:
        with ThreadPoolExecutor(max_workers=2) as pool:
            views = tuple(pool.map(service.submit, (submission, submission)))
        assert views[0].run_id == views[1].run_id
        assert service._jobs.load(views[0].run_id) is not None
        foreign = ResearchSubmission(scope=synthetic._scope(SourceType.FAERS), idempotency_key=key)
        with pytest.raises(ResearchApplicationFailure) as captured:
            service.submit(foreign)
        assert captured.value.code is ResearchApplicationErrorCode.CONFLICT


def test_concurrent_identical_review_has_one_export_effect(
    settings: PersistenceSettings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    key = _key(tmp_path / "concurrent-review")
    harness = _harness(monkeypatch, key)
    with _service(settings, harness, tmp_path) as first:
        submitted = first.submit(ResearchSubmission(scope=harness.scope, idempotency_key=key))
    with _service(settings, harness, tmp_path) as restarted:
        pending = restarted.get_run(submitted.run_id)
        assert pending.status is ResearchRunStatus.PENDING_REVIEW
        assert pending.report_content_hash is not None
        assert pending.render_document_hash is not None
        assert pending.pending_draft_id is not None
        command = ResearchReviewCommand(
            run_id=pending.run_id,
            report_id=pending.report_id,
            report_content_hash=pending.report_content_hash,
            render_document_hash=pending.render_document_hash,
            pending_draft_id=pending.pending_draft_id,
            destination_id=pending.destination_id,
            reviewer_id="local-reviewer:synthetic",
            decision=ResearchReviewDecision.APPROVE,
            idempotency_key=sha256_digest("synthetic concurrent approval"),
        )
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = tuple(pool.map(restarted.review, (command, command)))
        assert len(results) == 2
        assert restarted.get_run(pending.run_id).status is ResearchRunStatus.EXPORTED
        assert len(tuple(tmp_path.glob("export-*.json"))) == 1
        assert len(tuple(tmp_path.glob("export-*.md"))) == 1


def test_two_runs_list_and_reopen_with_per_job_fixed_synthetic_registries(
    settings: PersistenceSettings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    first_key = _key(tmp_path / "run-one")
    second_key = _key(tmp_path / "run-two")
    first_harness = _harness(monkeypatch, first_key)
    second_harness = _harness(monkeypatch, second_key)
    harnesses = {
        allocated_ids(first_key)["run_id"]: first_harness,
        allocated_ids(second_key)["run_id"]: second_harness,
    }
    inventory = ResearchJobRepository(settings)
    try:
        prior_count = len(inventory.list(limit=50, offset=0))
    finally:
        inventory.close()
    with _multi_service(settings, harnesses, tmp_path) as service:
        first = service.submit(
            ResearchSubmission(scope=first_harness.scope, idempotency_key=first_key)
        )
        second = service.submit(
            ResearchSubmission(scope=second_harness.scope, idempotency_key=second_key)
        )
        assert first.run_id != second.run_id
    with _multi_service(settings, harnesses, tmp_path) as restarted:
        listing = restarted.list_runs(limit=2, offset=prior_count)
        assert {item.run_id for item in listing.items} == {first.run_id, second.run_id}
        assert all(item.status is ResearchRunStatus.PENDING_REVIEW for item in listing.items)
        assert restarted.get_report(first.run_id).run.report_id == first.report_id
        assert restarted.get_report(second.run_id).run.report_id == second.report_id


def test_prepared_material_reopens_without_regenerating_timestamp(
    settings: PersistenceSettings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    key = _key(tmp_path / "material-recovery")
    harness = _harness(monkeypatch, key)
    with _service(settings, harness, tmp_path) as first:
        submitted = first.submit(ResearchSubmission(scope=harness.scope, idempotency_key=key))
    with _service(settings, harness, tmp_path) as restarted:
        before = restarted.get_report(submitted.run_id)
        row = restarted._jobs.load(submitted.run_id)
        assert row is not None
        state = restarted._runtime_for(row).inspect(submitted.run_id).state

        def no_regeneration(_state: object):
            pytest.fail("persisted verified report must not be regenerated on recovery")

        monkeypatch.setattr(restarted, "_material_provider", no_regeneration)
        restarted._prepare_material(state)
        assert restarted.get_report(submitted.run_id) == before
