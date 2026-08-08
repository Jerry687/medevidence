"""Offline injected-port integration for the PubMed no-match draft path."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from medevidence.domain import (
    AdverseEventConcept,
    ComparisonIntent,
    CoverageStatus,
    DrugConcept,
    ExecutionBounds,
    ExecutionStatus,
    QueryBounds,
    ResearchScope,
    ResultBounds,
    ResultStatus,
    SourceOutcome,
    SourceType,
)
from medevidence.tools import (
    PubMedResearchService,
    ResearchPubMedRequest,
    ResolvedConceptCatalog,
    SearchPubMedResponse,
    research_pubmed_draft,
)
from medevidence.tools.contracts import AcquisitionIntentInput
from medevidence.tools.ports import (
    PersistedAcquisition,
    PubMedSearchExecution,
    ResponseObservation,
    RunFinalization,
)

NOW = datetime(2026, 8, 7, 15, 0, tzinfo=UTC)


def _scope() -> ResearchScope:
    return ResearchScope.create(
        drugs=(DrugConcept(concept_id="m1a.drug.synthetic", preferred_term="drug-x"),),
        adverse_reactions=(
            AdverseEventConcept(
                concept_id="m1a.event.synthetic",
                preferred_term="event-y",
            ),
        ),
        date_range=None,
        selected_sources=(SourceType.PUBMED,),
        comparison_intent=ComparisonIntent.SUMMARIZE,
        query_bounds=QueryBounds(
            max_query_characters=512,
            max_pages=1,
            max_total_seconds=30,
        ),
        result_bounds=ResultBounds(max_records=100, max_payload_bytes=5_242_880),
    )


class Catalog:
    def resolve(self, scope_id: str) -> ResolvedConceptCatalog:
        scope = _scope()
        assert scope_id == scope.scope_id
        return ResolvedConceptCatalog(
            catalog_content_hash=f"sha256:{'a' * 64}",
            drugs=scope.drugs,
            adverse_reactions=scope.adverse_reactions,
        )


class Execution:
    def search(self, *, query: str, query_id: str) -> PubMedSearchExecution:
        outcome = SourceOutcome(
            source=SourceType.PUBMED,
            query_id=query_id,
            execution_status=ExecutionStatus.SUCCEEDED,
            coverage_status=CoverageStatus.COMPLETE,
            result_status=ResultStatus.NO_MATCH,
            configured_bounds=ExecutionBounds.from_scope(_scope()),
            valid_result_count=0,
            pages_completed=1,
            truncated=False,
        )
        return PubMedSearchExecution(
            response=SearchPubMedResponse(
                query=query,
                query_id=query_id,
                pmids=(),
                total_available=0,
                source_outcome=outcome,
            ),
            started_at_utc=NOW + timedelta(seconds=1),
            completed_at_utc=NOW + timedelta(seconds=2),
            attempts_used=1,
            observations=(
                ResponseObservation(
                    body=b"<search-result/>",
                    observed_at_utc=NOW + timedelta(seconds=2),
                    headers=(("content-type", "application/xml"),),
                    http_status=200,
                    body_complete=True,
                    termination_reason="complete_response",
                ),
            ),
        )

    def fetch(self, *, pmid: str, query_id: str) -> object:
        raise AssertionError(f"no fetch expected for {pmid} in {query_id}")


class Acquisitions:
    def persist_search(
        self,
        *,
        intent: AcquisitionIntentInput,
        execution: object,
    ) -> PersistedAcquisition:
        del execution
        return PersistedAcquisition(
            acquisition_intent_id=intent.acquisition_intent_id,
            snapshot_id=f"sha256:{'b' * 64}",
            manifest_id=f"sha256:{'b' * 64}",
            registration_envelope_id=(f"registration-envelope:acquisition:sha256:{'c' * 64}"),
        )

    def persist_fetch(
        self,
        *,
        intent: AcquisitionIntentInput,
        execution: object,
    ) -> PersistedAcquisition:
        raise AssertionError("no fetch persistence expected")


class Runs:
    def __init__(self) -> None:
        self.finalization: RunFinalization | None = None
        self.acquisitions: tuple[PersistedAcquisition, ...] | None = None

    def persist_run_intent(self, intent: object) -> str:
        del intent
        return f"run-intent:sha256:{'d' * 64}"

    def persist_run_and_report(
        self,
        *,
        finalization: RunFinalization,
        acquisitions: tuple[PersistedAcquisition, ...],
    ) -> None:
        assert len(acquisitions) == 1
        self.acquisitions = acquisitions
        self.finalization = finalization


class Runtime:
    def __init__(self) -> None:
        self.tick = 0

    def new_attempt_id(self) -> str:
        return "attempt:00000000-0000-4000-8000-000000000003"

    def utc_now(self) -> datetime:
        self.tick += 1
        return NOW + timedelta(seconds=10 + self.tick)


def test_offline_no_match_flow_persists_one_search_and_final_draft() -> None:
    runs = Runs()
    service = PubMedResearchService(
        catalog=Catalog(),
        execution=Execution(),
        acquisitions=Acquisitions(),
        runs=runs,
        runtime=Runtime(),
    )
    report = research_pubmed_draft(
        ResearchPubMedRequest(
            request_id="request:00000000-0000-4000-8000-000000000001",
            run_id="run:00000000-0000-4000-8000-000000000002",
            created_at_utc=NOW,
            code_revision="e" * 40,
            scope=_scope(),
        ),
        service=service,
    )

    assert report.source_outcomes[0].result_status is ResultStatus.NO_MATCH
    assert report.publications == report.claims == report.citations == ()
    assert report.status == "draft" and report.exportable is False
    assert runs.finalization is not None
    assert runs.finalization.report.report_id == report.report_id
    assert runs.acquisitions is not None
    assert runs.acquisitions[0].acquisition_intent_id.startswith("acquisition-intent:sha256:")
