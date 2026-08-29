"""Deterministic PubMed draft orchestration and claim construction tests."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import cast

import pytest
from pydantic import ValidationError

from medevidence.domain import (
    AbstractSection,
    AdverseEventConcept,
    ComparisonIntent,
    CorrectionContentDisposition,
    CoverageStatus,
    DomainWarning,
    DrugConcept,
    ExecutionBounds,
    ExecutionStatus,
    FailureCode,
    IndexingStatus,
    NoticeType,
    PlanningStatus,
    Provenance,
    PublicationRecord,
    PublicationRelationship,
    PublicationRelationshipType,
    PublicationStatus,
    PublicationStatusValue,
    QueryBounds,
    RelationshipResolution,
    ResearchScope,
    ResultBounds,
    ResultStatus,
    SourceFailure,
    SourceOutcome,
    SourceType,
    derive_identity,
    sha256_digest,
)
from medevidence.tools import (
    ResearchPubMedRequest,
    ResolvedConceptCatalog,
    SearchPubMedResponse,
    research_pubmed_draft,
)
from medevidence.tools.contracts import AcquisitionIntentInput, RunIntentInput
from medevidence.tools.ports import (
    PersistedAcquisition,
    PersistedPublicationBinding,
    PersistedPublicationLineageEdge,
    PubMedFetchExecution,
    PubMedSearchExecution,
    PubMedSearchProgressRecord,
    PubMedTerminalProgressRecord,
    ResponseObservation,
    RunFinalization,
)
from medevidence.tools.research import (
    PubMedResearchService,
    _claims_for_publications,
    _composite_outcome,
    _smallest_term_span,
    _with_persisted_publication_binding,
)

NOW = datetime(2026, 8, 7, 12, 0, tzinfo=UTC)
RUN_ID = "run:00000000-0000-4000-8000-000000000002"
REQUEST_ID = "request:00000000-0000-4000-8000-000000000001"
RUN_INTENT_ID = f"run-intent:sha256:{'1' * 64}"
QUERY_ID = "query:fixture"


def _scope() -> ResearchScope:
    return ResearchScope.create(
        drugs=(
            DrugConcept(
                concept_id="m1a.drug.semaglutide",
                preferred_term="semaglutide",
            ),
        ),
        adverse_reactions=(
            AdverseEventConcept(
                concept_id="m1a.event.gastrointestinal",
                preferred_term="gastrointestinal",
            ),
        ),
        date_range=None,
        selected_sources=(SourceType.PUBMED, SourceType.CADEC),
        comparison_intent=ComparisonIntent.SUMMARIZE,
        query_bounds=QueryBounds(
            max_query_characters=512,
            max_pages=1,
            max_total_seconds=30,
        ),
        result_bounds=ResultBounds(max_records=100, max_payload_bytes=5_242_880),
    )


def _catalog() -> ResolvedConceptCatalog:
    scope = _scope()
    return ResolvedConceptCatalog(
        catalog_content_hash=f"sha256:{'a' * 64}",
        drugs=scope.drugs,
        adverse_reactions=scope.adverse_reactions,
    )


def _outcome(
    *,
    result: ResultStatus,
    coverage: CoverageStatus = CoverageStatus.COMPLETE,
    execution: ExecutionStatus = ExecutionStatus.SUCCEEDED,
    count: int = 0,
    failure_id: str | None = None,
) -> SourceOutcome:
    warnings = ()
    if coverage is CoverageStatus.PARTIAL:
        warnings = ("source_coverage_incomplete",)
    elif coverage is CoverageStatus.UNAVAILABLE:
        warnings = ("source_unavailable",)
    return SourceOutcome(
        source=SourceType.PUBMED,
        query_id=QUERY_ID,
        execution_status=execution,
        coverage_status=coverage,
        result_status=result,
        configured_bounds=ExecutionBounds.from_scope(_scope()),
        valid_result_count=count,
        pages_completed=0 if coverage is CoverageStatus.UNAVAILABLE else 1,
        truncated=coverage is CoverageStatus.PARTIAL,
        warning_codes=warnings,
        failure_id=failure_id,
    )


def _status(value: PublicationStatusValue) -> PublicationStatus:
    if value is PublicationStatusValue.CURRENT_OR_NO_KNOWN_NOTICE:
        return PublicationStatus.create(
            status=value,
            status_source="PubMed relationship metadata",
            notice_type=None,
            relationship=None,
            retrieved_as_of=NOW,
        )
    if value is PublicationStatusValue.UNKNOWN_OR_UNVERIFIED:
        return PublicationStatus.create(
            status=value,
            status_source="PubMed relationship metadata",
            notice_type=None,
            relationship=PublicationRelationship(
                relationship_type=PublicationRelationshipType.OTHER,
                upstream_relationship_type="UnknownRelation",
                related_pmid="999",
                resolution=RelationshipResolution.UNRESOLVED,
                content_disposition=CorrectionContentDisposition.NOT_ESTABLISHED,
            ),
            retrieved_as_of=NOW,
        )
    notice = {
        PublicationStatusValue.CORRECTED: NoticeType.CORRECTION,
        PublicationStatusValue.RETRACTED: NoticeType.RETRACTION,
        PublicationStatusValue.EXPRESSION_OF_CONCERN: NoticeType.EXPRESSION_OF_CONCERN,
    }[value]
    relationship = {
        PublicationStatusValue.CORRECTED: PublicationRelationshipType.CORRECTED_BY,
        PublicationStatusValue.RETRACTED: PublicationRelationshipType.RETRACTED_BY,
        PublicationStatusValue.EXPRESSION_OF_CONCERN: (
            PublicationRelationshipType.HAS_EXPRESSION_OF_CONCERN
        ),
    }[value]
    return PublicationStatus.create(
        status=value,
        status_source="PubMed relationship metadata",
        notice_type=notice,
        relationship=PublicationRelationship(
            relationship_type=relationship,
            upstream_relationship_type=relationship.value,
            related_pmid="999",
            resolution=RelationshipResolution.RESOLVED,
            content_disposition=(
                CorrectionContentDisposition.RESOLVED_CURRENT_CONTENT
                if value is PublicationStatusValue.CORRECTED
                else CorrectionContentDisposition.STATUS_CONTEXT_ONLY
            ),
        ),
        retrieved_as_of=NOW,
    )


def _corrected_context_only_status() -> PublicationStatus:
    return PublicationStatus.create(
        status=PublicationStatusValue.CORRECTED,
        status_source="PubMed relationship metadata",
        notice_type=NoticeType.CORRECTION,
        relationship=PublicationRelationship(
            relationship_type=PublicationRelationshipType.CORRECTED_BY,
            upstream_relationship_type="corrected_by",
            related_pmid="999",
            resolution=RelationshipResolution.RESOLVED,
            content_disposition=CorrectionContentDisposition.STATUS_CONTEXT_ONLY,
        ),
        retrieved_as_of=NOW,
    )


def _publication(
    outcome: SourceOutcome,
    *,
    pmid: str = "10",
    status: PublicationStatusValue = PublicationStatusValue.CURRENT_OR_NO_KNOWN_NOTICE,
    abstract: str | None = (
        "😀 semaglutide distant gastrointestinal. semaglutide gastrointestinal"
    ),
) -> PublicationRecord:
    provenance = Provenance(
        source=SourceType.PUBMED,
        source_record_id=pmid,
        query_id=outcome.query_id,
        source_lookup_key=f"pubmed:{pmid}",
        retrieved_at=NOW,
        connector_version="fixture-1.0",
        content_hash=sha256_digest(b"raw"),
        warnings=tuple(
            DomainWarning(code=code, message="Source coverage is incomplete.")
            for code in outcome.warning_codes
        ),
        failure=(
            SourceFailure(
                failure_id=outcome.failure_id or "failure:fixture",
                failure_code=FailureCode.UPSTREAM_UNAVAILABLE,
                retryable=False,
            )
            if outcome.execution_status is ExecutionStatus.FAILED
            else None
        ),
        source_outcome=outcome,
        configured_bounds=outcome.configured_bounds,
    )
    return PublicationRecord.create(
        pmid=pmid,
        doi=None,
        pmcid=None,
        title="Synthetic PubMed fixture",
        abstract_sections=(AbstractSection(text=abstract),) if abstract is not None else (),
        authors=(),
        journal="Fixture Journal",
        publication_types=(),
        publication_date=None,
        publication_status=_status(status),
        indexing_status=IndexingStatus.INDEXED,
        provenance=provenance,
    )


class Catalog:
    def resolve(self, scope_id: str) -> ResolvedConceptCatalog:
        assert scope_id == _scope().scope_id
        return _catalog()


class Execution:
    def __init__(
        self,
        calls: list[str],
        *,
        search_outcome: SourceOutcome | None = None,
        fetch_outcome: SourceOutcome | None = None,
        search_total_available: int | None = None,
        search_pmids: tuple[str, ...] | None = None,
    ) -> None:
        self.calls = calls
        self.search_outcome = search_outcome or _outcome(result=ResultStatus.MATCHES, count=1)
        self.fetch_outcome = fetch_outcome or _outcome(result=ResultStatus.MATCHES, count=1)
        self.search_total_available = search_total_available
        self.search_pmids = search_pmids
        self.publications: list[PublicationRecord] = []

    def search(self, *, query: str, query_id: str) -> PubMedSearchExecution:
        self.calls.append("execute-search")
        response = SearchPubMedResponse(
            query=query,
            query_id=query_id,
            pmids=(
                self.search_pmids
                if self.search_pmids is not None
                else (("10",) if self.search_outcome.result_status is ResultStatus.MATCHES else ())
            ),
            total_available=(
                self.search_total_available
                if self.search_total_available is not None
                else (1 if self.search_outcome.result_status is ResultStatus.MATCHES else 0)
            ),
            source_outcome=self.search_outcome.model_copy(update={"query_id": query_id}),
        )
        failed = response.source_outcome.execution_status is ExecutionStatus.FAILED
        return PubMedSearchExecution(
            response=response,
            started_at_utc=NOW + timedelta(seconds=1),
            completed_at_utc=NOW + timedelta(seconds=2),
            attempts_used=1,
            observations=(
                ()
                if response.source_outcome.coverage_status is CoverageStatus.UNAVAILABLE
                else (
                    ResponseObservation(
                        body=b"<search/>",
                        observed_at_utc=NOW + timedelta(seconds=2),
                        headers=(("content-type", "application/xml"),),
                        http_status=200,
                        body_complete=True,
                        termination_reason="complete_response",
                    ),
                )
            ),
            failure_code="retry_exhausted" if failed else None,
            redacted_detail="synthetic search failure" if failed else None,
        )

    def fetch(self, *, pmid: str, query_id: str) -> PubMedFetchExecution:
        self.calls.append(f"execute-fetch-{pmid}")
        outcome = self.fetch_outcome.model_copy(update={"query_id": query_id})
        publication = (
            _publication(outcome, pmid=pmid)
            if outcome.result_status is ResultStatus.MATCHES
            else None
        )
        if publication is not None:
            self.publications.append(publication)
        failed = outcome.execution_status is ExecutionStatus.FAILED
        return PubMedFetchExecution(
            requested_pmid=pmid,
            query_id=query_id,
            publication=publication,
            source_outcome=outcome,
            started_at_utc=NOW + timedelta(seconds=3),
            completed_at_utc=NOW + timedelta(seconds=4),
            attempts_used=1,
            observations=(
                ResponseObservation(
                    body=b"<article/>",
                    observed_at_utc=NOW + timedelta(seconds=4),
                    headers=(("content-type", "application/xml"),),
                    http_status=200,
                    body_complete=True,
                    termination_reason="complete_response",
                ),
            ),
            failure_code="retry_exhausted" if failed else None,
            redacted_detail="synthetic fetch failure" if failed else None,
        )


class Acquisitions:
    def __init__(
        self,
        calls: list[str],
        *,
        fail_search: bool = False,
        search_binding: bool = False,
        search_result_mode: str = "valid",
        fetch_binding_mode: str = "valid",
    ) -> None:
        self.calls = calls
        self.fail_search = fail_search
        self.search_binding = search_binding
        self.search_result_mode = search_result_mode
        self.fetch_binding_mode = fetch_binding_mode
        self.raw_results: list[object] = []
        self.search_intent_id: str | None = None
        self.search_progress: PubMedSearchProgressRecord | None = None
        self.terminal_progress: PubMedTerminalProgressRecord | None = None

    def persist_search(
        self,
        *,
        intent: AcquisitionIntentInput,
        execution: object,
    ) -> PersistedAcquisition:
        del execution
        self.calls.append("persist-search")
        if self.fail_search:
            raise RuntimeError("synthetic acquisition rollback")
        self.search_intent_id = intent.acquisition_intent_id
        persisted = _persisted(0, acquisition_intent_id=intent.acquisition_intent_id)
        if self.search_binding:
            persisted = persisted.model_copy(
                update={
                    "publication_bindings": (
                        _binding(
                            pmid="99",
                            publication_version_id=f"pubmed:99:sha256:{'9' * 64}",
                            ordinal=0,
                        ),
                    )
                }
            )
        result = _forge_persisted_result(persisted, self.search_result_mode)
        self.raw_results.append(result)
        return cast(PersistedAcquisition, result)

    def persist_fetch(
        self,
        *,
        intent: AcquisitionIntentInput,
        execution: PubMedFetchExecution,
    ) -> PersistedAcquisition:
        self.calls.append(f"persist-fetch-{intent.pmid}")
        persisted = _persisted(
            intent.acquisition_ordinal,
            acquisition_intent_id=intent.acquisition_intent_id,
            publication=execution.publication,
        )
        if self.fetch_binding_mode == "search_intent_reuse":
            assert self.search_intent_id is not None
            result = persisted.model_copy(update={"acquisition_intent_id": self.search_intent_id})
            self.raw_results.append(result)
            return result
        if self.fetch_binding_mode == "missing":
            result: object = persisted.model_copy(update={"publication_bindings": ()})
            self.raw_results.append(result)
            return cast(PersistedAcquisition, result)
        if self.fetch_binding_mode == "unrelated_pmid":
            result = persisted.model_copy(
                update={
                    "publication_bindings": (
                        _binding(
                            pmid="11",
                            publication_version_id=f"pubmed:11:sha256:{'b' * 64}",
                            ordinal=1,
                        ),
                    )
                }
            )
            self.raw_results.append(result)
            return result
        if self.fetch_binding_mode == "wrong_version":
            result = persisted.model_copy(
                update={
                    "publication_bindings": (
                        _binding(
                            pmid="10",
                            publication_version_id=f"pubmed:10:sha256:{'c' * 64}",
                            ordinal=1,
                        ),
                    )
                }
            )
            self.raw_results.append(result)
            return result
        if self.fetch_binding_mode == "unexpected":
            result = persisted.model_copy(
                update={
                    "publication_bindings": (
                        _binding(
                            pmid="10",
                            publication_version_id=f"pubmed:10:sha256:{'d' * 64}",
                            ordinal=1,
                        ),
                    )
                }
            )
            self.raw_results.append(result)
            return result
        result = _forge_persisted_result(persisted, self.fetch_binding_mode)
        self.raw_results.append(result)
        return cast(PersistedAcquisition, result)

    def persist_search_progress(
        self,
        record: PubMedSearchProgressRecord,
    ) -> PubMedSearchProgressRecord:
        self.calls.append("persist-search-progress")
        validated = PubMedSearchProgressRecord.model_validate(record.model_dump(mode="python"))
        if self.search_progress is not None and self.search_progress != validated:
            raise ValueError("synthetic search progress conflict")
        self.search_progress = validated
        return PubMedSearchProgressRecord.model_validate(validated.model_dump(mode="python"))

    def load_search_progress(
        self,
        *,
        run_id: str,
        acquisition_intent_id: str,
    ) -> PubMedSearchProgressRecord:
        self.calls.append("load-search-progress")
        if self.search_progress is None:
            raise ValueError("synthetic search progress missing")
        if (
            self.search_progress.run_id != run_id
            or self.search_progress.acquisition_intent_id != acquisition_intent_id
        ):
            raise ValueError("synthetic search progress belongs to another acquisition")
        return PubMedSearchProgressRecord.model_validate(
            self.search_progress.model_dump(mode="python")
        )

    def persist_terminal_progress(
        self,
        record: PubMedTerminalProgressRecord,
    ) -> PubMedTerminalProgressRecord:
        self.calls.append("persist-terminal-progress")
        validated = PubMedTerminalProgressRecord.model_validate(record.model_dump(mode="python"))
        if self.terminal_progress is not None and self.terminal_progress != validated:
            raise ValueError("synthetic terminal progress conflict")
        self.terminal_progress = validated
        return PubMedTerminalProgressRecord.model_validate(validated.model_dump(mode="python"))

    def load_terminal_progress(
        self,
        *,
        run_id: str,
        attempt_id: str,
    ) -> PubMedTerminalProgressRecord:
        self.calls.append("load-terminal-progress")
        if self.terminal_progress is None:
            raise ValueError("synthetic terminal progress missing")
        if (
            self.terminal_progress.run_id != run_id
            or self.terminal_progress.attempt_id != attempt_id
        ):
            raise ValueError("synthetic terminal progress belongs to another attempt")
        return PubMedTerminalProgressRecord.model_validate(
            self.terminal_progress.model_dump(mode="python")
        )


class Runs:
    def __init__(self, calls: list[str]) -> None:
        self.calls = calls
        self.finalization: RunFinalization | None = None
        self.acquisitions: tuple[PersistedAcquisition, ...] | None = None
        self.run_intent_id: str | None = None

    def resolve_run_intent_id(self, intent: RunIntentInput) -> str:
        return derive_identity("run-intent", intent)

    def persist_run_intent(self, intent: object) -> str:
        self.calls.append("persist-run-intent")
        validated = RunIntentInput.model_validate(intent)
        self.run_intent_id = self.resolve_run_intent_id(validated)
        return self.run_intent_id

    def persist_run_and_report(
        self,
        *,
        finalization: RunFinalization,
        acquisitions: tuple[PersistedAcquisition, ...],
    ) -> None:
        self.calls.append("persist-run-report-envelope")
        self.finalization = finalization
        self.acquisitions = acquisitions
        assert len(acquisitions) >= 1


@dataclass
class Runtime:
    attempt: int = 0
    tick: int = 0

    def new_attempt_id(self) -> str:
        self.attempt += 1
        return f"attempt:00000000-0000-4000-8000-{self.attempt:012d}"

    def utc_now(self) -> datetime:
        self.tick += 1
        return NOW + timedelta(seconds=10 + self.tick)


def _persisted(
    ordinal: int,
    *,
    acquisition_intent_id: str,
    publication: PublicationRecord | None = None,
) -> PersistedAcquisition:
    digest = f"{ordinal + 1:064x}"
    bindings = (
        (
            _binding(
                pmid=publication.pmid,
                publication_version_id=publication.publication_version_id,
                ordinal=ordinal,
            ),
        )
        if publication is not None
        else ()
    )
    return PersistedAcquisition(
        acquisition_intent_id=acquisition_intent_id,
        snapshot_id=f"sha256:{digest}",
        manifest_id=f"sha256:{digest}",
        registration_envelope_id=(f"registration-envelope:acquisition:sha256:{ordinal + 10:064x}"),
        publication_bindings=bindings,
    )


def _binding(
    *,
    pmid: str,
    publication_version_id: str,
    ordinal: int,
) -> PersistedPublicationBinding:
    digest = f"{ordinal + 1:064x}"
    manifest_id = f"sha256:{digest}"
    publication_artifact_id = "sha256:" + publication_version_id.rsplit(":sha256:", maxsplit=1)[1]
    return PersistedPublicationBinding(
        pmid=pmid,
        publication_version_id=publication_version_id,
        publication_artifact_id=publication_artifact_id,
        snapshot_id=manifest_id,
        manifest_id=manifest_id,
        artifact_ids=tuple(sorted((publication_artifact_id, manifest_id))),
        lineage_edges=(
            PersistedPublicationLineageEdge(
                parent_artifact_id=publication_artifact_id,
                child_artifact_id=manifest_id,
            ),
        ),
    )


def _forge_persisted_result(
    persisted: PersistedAcquisition,
    mode: str,
) -> object:
    if mode == "valid":
        return persisted
    if mode == "wrong_type":
        return {"persisted": "wrong-type"}
    if mode == "extra_root":
        return persisted.model_copy(update={"provider_row_id": "forbidden"})
    if mode == "missing_root":
        forged = persisted.model_copy()
        del forged.__dict__["acquisition_intent_id"]
        return forged
    if mode == "malformed_intent_id":
        return persisted.model_copy(update={"acquisition_intent_id": "not-an-intent"})
    if mode == "wrong_intent_id":
        return persisted.model_copy(
            update={"acquisition_intent_id": f"acquisition-intent:sha256:{'f' * 64}"}
        )
    if mode == "wrong_snapshot_kind":
        return persisted.model_copy(update={"snapshot_id": f"artifact-link:sha256:{'f' * 64}"})
    if mode == "wrong_envelope_kind":
        return persisted.model_copy(update={"registration_envelope_id": f"sha256:{'f' * 64}"})
    if mode == "manifest_mismatch":
        return persisted.model_copy(update={"manifest_id": f"sha256:{'f' * 64}"})

    binding = persisted.publication_bindings[0]
    edge = binding.lineage_edges[0]
    if mode == "binding_wrong_type":
        return persisted.model_copy(update={"publication_bindings": ("wrong-binding",)})
    if mode == "binding_extra":
        bad_binding = binding.model_copy(update={"provider_publication_id": "forbidden"})
        return persisted.model_copy(update={"publication_bindings": (bad_binding,)})
    if mode == "binding_missing_field":
        bad_binding = binding.model_copy()
        del bad_binding.__dict__["pmid"]
        return persisted.model_copy(update={"publication_bindings": (bad_binding,)})
    if mode == "binding_duplicate":
        return persisted.model_copy(update={"publication_bindings": (binding, binding)})
    if mode == "edge_wrong_type":
        bad_binding = binding.model_copy(update={"lineage_edges": ("wrong-edge",)})
        return persisted.model_copy(update={"publication_bindings": (bad_binding,)})
    if mode == "edge_extra":
        bad_edge = edge.model_copy(update={"provider_edge_id": "forbidden"})
        bad_binding = binding.model_copy(update={"lineage_edges": (bad_edge,)})
        return persisted.model_copy(update={"publication_bindings": (bad_binding,)})
    if mode == "edge_missing":
        bad_binding = binding.model_copy(update={"lineage_edges": ()})
        return persisted.model_copy(update={"publication_bindings": (bad_binding,)})
    if mode == "edge_duplicate":
        bad_binding = binding.model_copy(update={"lineage_edges": (edge, edge)})
        return persisted.model_copy(update={"publication_bindings": (bad_binding,)})
    edge_updates: dict[str, object] = {
        "edge_lineage_type": {"lineage_type": "manifest_to_publication"},
        "edge_ordinal": {"lineage_ordinal": 1},
        "edge_parent": {"parent_artifact_id": f"sha256:{'e' * 64}"},
        "edge_child": {"child_artifact_id": f"sha256:{'e' * 64}"},
    }.get(mode, {})
    if edge_updates:
        bad_edge = edge.model_copy(update=edge_updates)
        bad_binding = binding.model_copy(update={"lineage_edges": (bad_edge,)})
        return persisted.model_copy(update={"publication_bindings": (bad_binding,)})
    if mode == "other_acquisition":
        other_manifest = f"sha256:{'e' * 64}"
        other_edge = edge.model_copy(update={"child_artifact_id": other_manifest})
        other_binding = binding.model_copy(
            update={
                "snapshot_id": other_manifest,
                "manifest_id": other_manifest,
                "artifact_ids": tuple(sorted((binding.publication_artifact_id, other_manifest))),
                "lineage_edges": (other_edge,),
            }
        )
        return persisted.model_copy(update={"publication_bindings": (other_binding,)})
    raise AssertionError(f"unknown persisted-result fixture mode: {mode}")


def _request() -> ResearchPubMedRequest:
    return ResearchPubMedRequest(
        request_id=REQUEST_ID,
        run_id=RUN_ID,
        created_at_utc=NOW,
        code_revision="b" * 40,
        scope=_scope(),
    )


def _intent(ordinal: int) -> AcquisitionIntentInput:
    return AcquisitionIntentInput.create(
        attempt_id=f"attempt:00000000-0000-4000-8000-{ordinal + 1:012d}",
        run_id=RUN_ID,
        run_intent_id=RUN_INTENT_ID,
        created_at_utc=NOW + timedelta(seconds=ordinal),
        acquisition_ordinal=ordinal,
        operation="search" if ordinal == 0 else "fetch",
        query="fixture" if ordinal == 0 else None,
        pmid=None if ordinal == 0 else "10",
    )


def _service(
    calls: list[str],
    *,
    execution: Execution | None = None,
    acquisitions: Acquisitions | None = None,
) -> tuple[PubMedResearchService, Runs]:
    runs = Runs(calls)
    service = PubMedResearchService(
        catalog=Catalog(),
        execution=execution or Execution(calls),
        acquisitions=acquisitions or Acquisitions(calls),
        runs=runs,
        runtime=Runtime(),
    )
    return service, runs


def test_pubmed_research_service_is_exact_sealed_and_frozen() -> None:
    service, _ = _service([])
    assert type(service) is PubMedResearchService
    assert not hasattr(service, "__dict__")
    for name, replacement in (
        ("_catalog", object()),
        ("_execution", object()),
        ("_acquisitions", object()),
        ("_runs", object()),
        ("_runtime", object()),
        ("load_search_progress", lambda **_values: object()),
        ("load_terminal_progress", lambda **_values: object()),
    ):
        with pytest.raises(AttributeError, match="frozen"):
            setattr(service, name, replacement)
    with pytest.raises(TypeError, match="sealed"):
        type("ForgedPubMedResearchService", (PubMedResearchService,), {})


def test_complete_run_persists_each_acquisition_before_next_and_run_last() -> None:
    calls: list[str] = []
    service, runs = _service(calls)
    report = research_pubmed_draft(_request(), service=service)

    assert calls == [
        "persist-run-intent",
        "execute-search",
        "persist-search",
        "persist-search-progress",
        "execute-fetch-10",
        "persist-fetch-10",
        "persist-run-report-envelope",
    ]
    assert report.status == "draft" and report.exportable is False
    assert report.run_id == RUN_ID
    assert report.catalog_version == "m1a-concepts-v1"
    assert report.catalog_content_hash == _catalog().catalog_content_hash
    assert report.run_intent_id == runs.run_intent_id
    assert len(report.acquisition_snapshot_ids) == 2
    assert report.acquisition_snapshot_ids == report.acquisition_manifest_ids
    publication = report.publications[0]
    manifest_id = report.acquisition_snapshot_ids[1]
    assert publication.provenance.snapshot_id == manifest_id
    assert set(publication.provenance.artifact_ids) == {
        publication.content_hash,
        manifest_id,
    }
    assert publication.provenance.transformation_lineage == (
        publication.content_hash,
        manifest_id,
    )
    assert report.claims[0].claim_text == "semaglutide gastrointestinal"
    assert report.claims[0].claim_text == report.citations[0].exact_quote
    assert report.citations[0].start_offset == 40
    assert runs.finalization is not None
    assert runs.acquisitions is not None
    assert len(runs.acquisitions) == 2
    assert len({item.acquisition_intent_id for item in runs.acquisitions}) == 2
    assert runs.finalization.report_artifact_bytes == report.artifact_bytes()
    assert sha256_digest(report.artifact_bytes()) == report.report_artifact_id


def test_collection_persists_exact_acquisitions_without_final_report() -> None:
    calls: list[str] = []
    service, runs = _service(calls)

    collection = service.collect(_request())

    assert calls == [
        "persist-run-intent",
        "execute-search",
        "persist-search",
        "persist-search-progress",
        "execute-fetch-10",
        "persist-fetch-10",
    ]
    assert runs.finalization is None and runs.acquisitions is None
    assert len(collection.persisted_acquisitions) == 2
    assert collection.fetches[0].publication == collection.publications[0]
    assert collection.publications[0].provenance.snapshot_id == (
        collection.persisted_acquisitions[1].snapshot_id
    )


def test_skipped_source_is_visible_without_fabricated_outcome() -> None:
    report = research_pubmed_draft(_request(), service=_service([])[0])
    by_source = {entry.source: entry for entry in report.source_plan}
    assert by_source[SourceType.CADEC].planning_status is PlanningStatus.SKIPPED_BY_POLICY
    assert tuple(item.source for item in report.source_outcomes) == (SourceType.PUBMED,)


def test_acquisition_failure_propagates_and_final_persistence_does_not_run() -> None:
    calls: list[str] = []
    service, _ = _service(calls, acquisitions=Acquisitions(calls, fail_search=True))
    with pytest.raises(RuntimeError, match="rollback"):
        research_pubmed_draft(_request(), service=service)
    assert calls == ["persist-run-intent", "execute-search", "persist-search"]


def test_search_rejects_unexpected_publication_binding_before_fetch() -> None:
    calls: list[str] = []
    acquisitions = Acquisitions(calls, search_binding=True)
    service, runs = _service(calls, acquisitions=acquisitions)
    with pytest.raises(ValueError, match="search acquisition"):
        research_pubmed_draft(_request(), service=service)
    assert calls == ["persist-run-intent", "execute-search", "persist-search"]
    assert runs.finalization is None


@pytest.mark.parametrize(
    "mode",
    [
        "wrong_type",
        "extra_root",
        "missing_root",
        "malformed_intent_id",
        "wrong_intent_id",
        "wrong_snapshot_kind",
        "wrong_envelope_kind",
        "manifest_mismatch",
    ],
)
def test_search_rejects_untrusted_persisted_result_before_fetch(mode: str) -> None:
    calls: list[str] = []
    acquisitions = Acquisitions(calls, search_result_mode=mode)
    service, runs = _service(calls, acquisitions=acquisitions)

    with pytest.raises(ValueError, match="persist"):
        research_pubmed_draft(_request(), service=service)

    assert calls == ["persist-run-intent", "execute-search", "persist-search"]
    assert runs.finalization is None


@pytest.mark.parametrize(
    "mode",
    [
        "search_intent_reuse",
        "binding_wrong_type",
        "binding_extra",
        "binding_missing_field",
        "binding_duplicate",
        "edge_wrong_type",
        "edge_extra",
        "edge_missing",
        "edge_duplicate",
        "edge_lineage_type",
        "edge_ordinal",
        "edge_parent",
        "edge_child",
        "other_acquisition",
    ],
)
def test_fetch_rejects_forged_nested_persisted_result_before_finalization(
    mode: str,
) -> None:
    calls: list[str] = []
    acquisitions = Acquisitions(calls, fetch_binding_mode=mode)
    service, runs = _service(calls, acquisitions=acquisitions)

    with pytest.raises(ValueError, match="persist"):
        research_pubmed_draft(_request(), service=service)

    assert calls[-2:] == ["execute-fetch-10", "persist-fetch-10"]
    assert "persist-run-report-envelope" not in calls
    assert runs.finalization is None
    assert len(acquisitions.raw_results) == 2
    valid_search = cast(PersistedAcquisition, acquisitions.raw_results[0])
    assert valid_search.acquisition_intent_id == acquisitions.search_intent_id


def test_valid_adapter_results_are_reconstructed_without_mutating_port_values() -> None:
    calls: list[str] = []
    acquisitions = Acquisitions(calls)
    service, runs = _service(calls, acquisitions=acquisitions)

    research_pubmed_draft(_request(), service=service)

    assert runs.acquisitions is not None
    assert len(acquisitions.raw_results) == len(runs.acquisitions) == 2
    for raw, reconstructed in zip(acquisitions.raw_results, runs.acquisitions, strict=True):
        assert raw == reconstructed
        assert raw is not reconstructed
    raw_fetch = cast(PersistedAcquisition, acquisitions.raw_results[1])
    reconstructed_fetch = runs.acquisitions[1]
    assert raw_fetch.publication_bindings[0] is not reconstructed_fetch.publication_bindings[0]
    assert (
        raw_fetch.publication_bindings[0].lineage_edges[0]
        is not reconstructed_fetch.publication_bindings[0].lineage_edges[0]
    )


@pytest.mark.parametrize(
    "mode",
    ["missing", "unrelated_pmid", "wrong_version"],
)
def test_fetch_rejects_missing_or_mismatched_persisted_binding_before_finalization(
    mode: str,
) -> None:
    calls: list[str] = []
    acquisitions = Acquisitions(calls, fetch_binding_mode=mode)
    service, runs = _service(calls, acquisitions=acquisitions)
    with pytest.raises(ValueError, match=r"persisted.*binding"):
        research_pubmed_draft(_request(), service=service)
    assert calls[-2:] == ["execute-fetch-10", "persist-fetch-10"]
    assert "persist-run-report-envelope" not in calls
    assert runs.finalization is None


def test_fetch_without_publication_rejects_unexpected_binding() -> None:
    calls: list[str] = []
    no_publication = _outcome(result=ResultStatus.NO_MATCH)
    execution = Execution(calls, fetch_outcome=no_publication)
    acquisitions = Acquisitions(calls, fetch_binding_mode="unexpected")
    service, runs = _service(calls, execution=execution, acquisitions=acquisitions)
    with pytest.raises(ValueError, match="without a publication"):
        research_pubmed_draft(_request(), service=service)
    assert calls[-2:] == ["execute-fetch-10", "persist-fetch-10"]
    assert runs.finalization is None


def test_fetch_rejects_publication_content_hash_drift_from_persisted_artifact() -> None:
    outcome = _outcome(result=ResultStatus.MATCHES, count=1)
    publication = _publication(outcome)
    acquisition = _persisted(
        1,
        acquisition_intent_id=_intent(1).acquisition_intent_id,
        publication=publication,
    )
    drifted = publication.model_copy(update={"content_hash": f"sha256:{'f' * 64}"})

    with pytest.raises(ValueError, match="persisted publication binding"):
        _with_persisted_publication_binding(drifted, acquisition)


def test_same_inputs_and_port_observations_replay_to_identical_report() -> None:
    first = research_pubmed_draft(_request(), service=_service([])[0])
    second = research_pubmed_draft(_request(), service=_service([])[0])
    assert first.model_dump_json() == second.model_dump_json()


@pytest.mark.parametrize(
    ("status", "claim_count", "expected_context"),
    [
        (PublicationStatusValue.RETRACTED, 0, None),
        (PublicationStatusValue.EXPRESSION_OF_CONCERN, 1, "support_limited"),
        (PublicationStatusValue.UNKNOWN_OR_UNVERIFIED, 1, "support_limited"),
    ],
)
def test_publication_status_policy_is_applied_deterministically(
    status: PublicationStatusValue,
    claim_count: int,
    expected_context: str | None,
) -> None:
    outcome = _outcome(result=ResultStatus.MATCHES, count=1)
    publication = _publication(outcome, status=status)
    citations, claims = _claims_for_publications(
        scope_id=_scope().scope_id,
        publications=(publication,),
        catalog=_catalog(),
    )
    assert len(claims) == claim_count
    assert len(citations) == claim_count
    if expected_context is not None:
        assert claims[0].use_context.value == expected_context
        assert set(claims[0].publication_warning_references) == set(
            publication.publication_status.warning_codes
        )


def test_missing_abstract_or_missing_exact_terms_produces_no_claim() -> None:
    outcome = _outcome(result=ResultStatus.MATCHES, count=1)
    for publication in (
        _publication(outcome, abstract=None),
        _publication(outcome, abstract="No exact requested catalog terms occur here."),
    ):
        citations, claims = _claims_for_publications(
            scope_id=_scope().scope_id,
            publications=(publication,),
            catalog=_catalog(),
        )
        assert citations == ()
        assert claims == ()


def test_corrected_record_without_resolved_current_content_is_retained_without_claim() -> None:
    outcome = _outcome(result=ResultStatus.MATCHES, count=1)
    original = _publication(outcome, status=PublicationStatusValue.CORRECTED)
    publication = PublicationRecord.create(
        pmid=original.pmid,
        doi=original.doi,
        pmcid=original.pmcid,
        title=original.title,
        abstract_sections=original.abstract_sections,
        authors=original.authors,
        journal=original.journal,
        publication_types=original.publication_types,
        publication_date=original.publication_date,
        publication_status=_corrected_context_only_status(),
        indexing_status=original.indexing_status,
        provenance=original.provenance,
        parse_warnings=original.parse_warnings,
    )
    citations, claims = _claims_for_publications(
        scope_id=_scope().scope_id,
        publications=(publication,),
        catalog=_catalog(),
    )
    assert citations == ()
    assert claims == ()
    assert "publication_status_corrected" in publication.publication_status.warning_codes


def test_unicode_code_point_offsets_and_tie_break_are_exact() -> None:
    abstract = "😀 semaglutide gastrointestinal; semaglutide gastrointestinal"
    span = _smallest_term_span(abstract, ("semaglutide",), ("gastrointestinal",))
    assert span == (2, 30)
    assert abstract[slice(*span)] == "semaglutide gastrointestinal"


def test_only_complete_successful_zero_id_search_becomes_no_match() -> None:
    calls: list[str] = []
    complete_empty = _outcome(result=ResultStatus.NO_MATCH)
    report = research_pubmed_draft(
        _request(),
        service=_service(calls, execution=Execution(calls, search_outcome=complete_empty))[0],
    )
    assert report.source_outcomes[0].result_status is ResultStatus.NO_MATCH
    assert report.source_outcomes[0].coverage_status is CoverageStatus.COMPLETE

    failed_empty = _outcome(
        result=ResultStatus.INDETERMINATE,
        coverage=CoverageStatus.UNAVAILABLE,
        execution=ExecutionStatus.FAILED,
        failure_id="failure:search",
    )
    calls = []
    report = research_pubmed_draft(
        _request(),
        service=_service(calls, execution=Execution(calls, search_outcome=failed_empty))[0],
    )
    assert report.source_outcomes[0].result_status is ResultStatus.INDETERMINATE
    assert report.coverage_limitations[0].coverage_status is CoverageStatus.UNAVAILABLE


def test_succeeded_partial_match_preserves_warnings_identity_and_finalizes_last() -> None:
    calls: list[str] = []
    search_outcome = _outcome(
        result=ResultStatus.MATCHES,
        coverage=CoverageStatus.PARTIAL,
        count=1,
    )
    execution = Execution(
        calls,
        search_outcome=search_outcome,
        search_total_available=2,
    )
    service, runs = _service(calls, execution=execution)

    report = research_pubmed_draft(_request(), service=service)

    assert calls == [
        "persist-run-intent",
        "execute-search",
        "persist-search",
        "persist-search-progress",
        "execute-fetch-10",
        "persist-fetch-10",
        "persist-run-report-envelope",
    ]
    composite = report.source_outcomes[0]
    assert (
        composite.execution_status,
        composite.coverage_status,
        composite.result_status,
        composite.truncated,
    ) == (
        ExecutionStatus.SUCCEEDED,
        CoverageStatus.PARTIAL,
        ResultStatus.MATCHES,
        True,
    )
    publication = report.publications[0]
    assert publication.publication_version_id == execution.publications[0].publication_version_id
    assert publication.content_hash == execution.publications[0].content_hash
    assert set(composite.warning_codes).issubset(
        {warning.code for warning in publication.provenance.warnings}
    )
    assert publication.provenance.source_outcome == composite
    assert publication.provenance.snapshot_id == report.acquisition_snapshot_ids[1]
    assert set(publication.provenance.artifact_ids) == {
        publication.content_hash,
        report.acquisition_snapshot_ids[1],
    }
    assert publication.provenance.transformation_lineage == (
        publication.content_hash,
        report.acquisition_snapshot_ids[1],
    )
    assert runs.finalization is not None


def test_failed_partial_match_preserves_warnings_failure_and_finalizes_last() -> None:
    calls: list[str] = []
    fetch_outcome = SourceOutcome(
        source=SourceType.PUBMED,
        query_id=QUERY_ID,
        execution_status=ExecutionStatus.FAILED,
        coverage_status=CoverageStatus.PARTIAL,
        result_status=ResultStatus.MATCHES,
        configured_bounds=ExecutionBounds.from_scope(_scope()),
        valid_result_count=1,
        pages_completed=1,
        truncated=False,
        warning_codes=("source_coverage_incomplete",),
        failure_id="failure:fetch-partial",
    )
    execution = Execution(calls, fetch_outcome=fetch_outcome)
    service, runs = _service(calls, execution=execution)

    report = research_pubmed_draft(_request(), service=service)

    assert calls[-2:] == ["persist-fetch-10", "persist-run-report-envelope"]
    composite = report.source_outcomes[0]
    assert (
        composite.execution_status,
        composite.coverage_status,
        composite.result_status,
        composite.truncated,
    ) == (
        ExecutionStatus.FAILED,
        CoverageStatus.PARTIAL,
        ResultStatus.MATCHES,
        False,
    )
    publication = report.publications[0]
    assert publication.publication_version_id == execution.publications[0].publication_version_id
    assert publication.content_hash == execution.publications[0].content_hash
    assert set(composite.warning_codes).issubset(
        {warning.code for warning in publication.provenance.warnings}
    )
    assert publication.provenance.failure is not None
    assert publication.provenance.failure.failure_id == composite.failure_id
    assert publication.provenance.snapshot_id == report.acquisition_snapshot_ids[1]
    assert set(publication.provenance.artifact_ids) == {
        publication.content_hash,
        report.acquisition_snapshot_ids[1],
    }
    assert publication.provenance.transformation_lineage == (
        publication.content_hash,
        report.acquisition_snapshot_ids[1],
    )
    assert runs.finalization is not None


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("run_intent_id", f"run-intent:sha256:{'f' * 64}", "run intent"),
        ("report_artifact_bytes", b"drift", "artifact bytes"),
        ("completed_at_utc", NOW - timedelta(seconds=1), "completion precedes start"),
        ("warning_codes", ("unexpected_warning",), "warnings must match"),
    ],
)
def test_run_finalization_rejects_incoherent_adapter_input(
    field: str,
    value: object,
    message: str,
) -> None:
    report = research_pubmed_draft(_request(), service=_service([])[0])
    valid = RunFinalization(
        run_intent_id=report.run_intent_id,
        report=report,
        report_artifact_bytes=report.artifact_bytes(),
        started_at_utc=NOW,
        completed_at_utc=NOW + timedelta(seconds=1),
        warning_codes=report.source_outcomes[0].warning_codes,
    )
    payload = valid.model_dump(mode="python")
    payload[field] = value
    with pytest.raises(ValidationError, match=message):
        RunFinalization.model_validate(payload)


def test_run_finalization_rejects_oversize_report_artifact() -> None:
    report = research_pubmed_draft(_request(), service=_service([])[0])
    with pytest.raises(ValidationError, match="at most 2097152"):
        RunFinalization(
            run_intent_id=report.run_intent_id,
            report=report,
            report_artifact_bytes=b"x" * 2_097_153,
            started_at_utc=NOW,
            completed_at_utc=NOW + timedelta(seconds=1),
            warning_codes=report.source_outcomes[0].warning_codes,
        )


def test_composite_emits_exactly_the_seven_accepted_terminal_triples() -> None:
    complete_match = _outcome(result=ResultStatus.MATCHES, count=1)
    complete_empty = _outcome(result=ResultStatus.NO_MATCH)
    partial_match = _outcome(
        result=ResultStatus.MATCHES,
        coverage=CoverageStatus.PARTIAL,
        count=1,
    )
    partial_empty = _outcome(
        result=ResultStatus.INDETERMINATE,
        coverage=CoverageStatus.PARTIAL,
    )
    failed_partial_match = _outcome(
        result=ResultStatus.MATCHES,
        coverage=CoverageStatus.PARTIAL,
        execution=ExecutionStatus.FAILED,
        count=1,
        failure_id="failure:partial-match",
    )
    failed_partial_empty = _outcome(
        result=ResultStatus.INDETERMINATE,
        coverage=CoverageStatus.PARTIAL,
        execution=ExecutionStatus.FAILED,
        failure_id="failure:partial-empty",
    )
    failed_unavailable = _outcome(
        result=ResultStatus.INDETERMINATE,
        coverage=CoverageStatus.UNAVAILABLE,
        execution=ExecutionStatus.FAILED,
        failure_id="failure:unavailable",
    )

    cases = (
        (complete_match, (complete_match,), ("10",), 1),
        (complete_empty, (complete_empty,), (), 0),
        (partial_match, (partial_match,), ("10",), 1),
        (partial_empty, (partial_empty,), (), 0),
        (complete_match, (complete_match, failed_partial_match), ("10",), 1),
        (complete_match, (complete_match, failed_partial_empty), ("10",), 0),
        (failed_unavailable, (failed_unavailable,), (), 0),
    )
    actual = set()
    for search_outcome, children, pmids, valid_count in cases:
        response = SearchPubMedResponse(
            query="fixture",
            query_id=QUERY_ID,
            pmids=pmids,
            total_available=len(pmids),
            source_outcome=search_outcome,
        )
        composite = _composite_outcome(
            scope=_scope(),
            query_id=QUERY_ID,
            search=response,
            children=children,
            valid_publications=valid_count,
        )
        actual.add(
            (
                composite.execution_status.value,
                composite.coverage_status.value,
                composite.result_status.value,
            )
        )
    assert actual == {
        ("succeeded", "complete", "matches"),
        ("succeeded", "complete", "no_match"),
        ("succeeded", "partial", "matches"),
        ("succeeded", "partial", "indeterminate"),
        ("failed", "partial", "matches"),
        ("failed", "partial", "indeterminate"),
        ("failed", "unavailable", "indeterminate"),
    }
