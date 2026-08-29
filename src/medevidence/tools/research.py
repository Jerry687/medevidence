"""Bounded PubMed research service with deterministic claims and final persistence."""

from __future__ import annotations

from typing import Literal, final

from pydantic import BaseModel, ConfigDict, ValidationError

from medevidence.domain import (
    Citation,
    CitationRelationship,
    CitationValidationError,
    ClaimUseContext,
    CorrectionContentDisposition,
    CoverageLimitation,
    CoverageStatus,
    DomainWarning,
    EvidenceClaim,
    ExecutionBounds,
    ExecutionStatus,
    FailureCode,
    PlanningStatus,
    Pmid,
    Provenance,
    PublicationRecord,
    PublicationStatusValue,
    RelationshipResolution,
    ReportWarning,
    ResearchReport,
    ResearchScope,
    ResultStatus,
    SourceFailure,
    SourceOutcome,
    SourcePlanEntry,
    SourcePlanReasonCode,
    SourceType,
    UtcDateTime,
    derive_identity,
)
from medevidence.domain.identifiers import RunIntentId

from .contracts import (
    AcquisitionIntentInput,
    FetchPubMedArticleRequest,
    FetchPubMedArticleResponse,
    ResearchPubMedRequest,
    ResolvedConceptCatalog,
    RunIntentInput,
    SearchPubMedRequest,
    SearchPubMedResponse,
)
from .ports import (
    AcquisitionPersistencePort,
    ConceptCatalogPort,
    PersistedAcquisition,
    PersistedPublicationBinding,
    PubMedExecutionPort,
    PubMedFetchExecution,
    PubMedSearchExecution,
    PubMedSearchProgressRecord,
    PubMedTerminalProgressRecord,
    RunFinalization,
    RunPersistencePort,
    RuntimePort,
)
from .pubmed import build_pubmed_query, query_identity, validate_query_terms


class _PubMedCollectionModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        revalidate_instances="always",
    )


class PubMedCollectionPreparation(_PubMedCollectionModel):
    """Canonical PubMed query context prepared before acquisition effects."""

    request: ResearchPubMedRequest
    catalog: ResolvedConceptCatalog
    query: str
    query_id: str
    run_intent_id: RunIntentId

    def model_post_init(self, __context: object) -> None:
        del __context
        validate_query_terms(self.request.scope)
        expected_query = build_pubmed_query(self.request.scope, self.catalog)
        if self.query != expected_query or self.query_id != query_identity(
            self.request.scope,
            expected_query,
        ):
            raise ValueError("prepared PubMed collection changed canonical query identity")


class PubMedSearchCollection(_PubMedCollectionModel):
    """Persisted search boundary returned before any selected PMID fetch."""

    request: ResearchPubMedRequest
    catalog: ResolvedConceptCatalog
    query: str
    query_id: str
    run_intent_id: RunIntentId
    response: SearchPubMedResponse
    acquisition: PersistedAcquisition
    progress_record: PubMedSearchProgressRecord
    completed_at_utc: UtcDateTime

    def model_post_init(self, __context: object) -> None:
        del __context
        if self.response.query != self.query or self.response.query_id != self.query_id:
            raise ValueError("persisted PubMed search boundary changed query identity")
        if self.acquisition.publication_bindings:
            raise ValueError("persisted PubMed search boundary cannot contain publications")
        if (
            self.progress_record.run_id != self.request.run_id
            or self.progress_record.scope_id != self.request.scope.scope_id
            or self.progress_record.query != self.query
            or self.progress_record.query_id != self.query_id
            or self.progress_record.acquisition_intent_id != self.acquisition.acquisition_intent_id
            or self.progress_record.snapshot_id != self.acquisition.snapshot_id
            or self.progress_record.manifest_id != self.acquisition.manifest_id
            or self.progress_record.pmids != self.response.pmids
            or self.progress_record.search_source_outcome_id
            != derive_identity("source-operation-outcome", self.response.source_outcome)
            or self.progress_record.valid_result_count
            != self.response.source_outcome.valid_result_count
        ):
            raise ValueError("persisted PubMed search progress changed exact search content")


class PubMedCollectedFetch(_PubMedCollectionModel):
    """One persisted selected-PMID result without transport or raw source bytes."""

    pmid: Pmid
    source_outcome: SourceOutcome
    acquisition: PersistedAcquisition
    publication: PublicationRecord | None = None
    completed_at_utc: UtcDateTime

    def model_post_init(self, __context: object) -> None:
        del __context
        expected_count = 1 if self.publication is not None else 0
        if self.source_outcome.source is not SourceType.PUBMED:
            raise ValueError("collected fetch outcome must be PubMed")
        if self.source_outcome.valid_result_count != expected_count:
            raise ValueError("collected fetch count must match its publication")
        if self.publication is None:
            if self.acquisition.publication_bindings:
                raise ValueError("empty collected fetch cannot expose a publication binding")
        elif (
            self.publication.pmid != self.pmid
            or len(self.acquisition.publication_bindings) != 1
            or self.acquisition.publication_bindings[0].publication_version_id
            != self.publication.publication_version_id
        ):
            raise ValueError("collected fetch must bind its exact persisted publication")


class PubMedFetchStageCollection(_PubMedCollectionModel):
    """Persisted fetch suffix reconstructed from an exact prior search."""

    search_response: SearchPubMedResponse
    fetches: tuple[PubMedCollectedFetch, ...]
    persisted_acquisitions: tuple[PersistedAcquisition, ...]
    publications: tuple[PublicationRecord, ...]

    def model_post_init(self, __context: object) -> None:
        del __context
        if tuple(item.pmid for item in self.fetches) != self.search_response.pmids:
            raise ValueError("fetch stage must equal the exact ordered search PMIDs")
        if self.persisted_acquisitions != tuple(item.acquisition for item in self.fetches):
            raise ValueError("fetch stage acquisitions must equal persisted fetches")
        expected_publications = tuple(
            item.publication for item in self.fetches if item.publication is not None
        )
        if self.publications != expected_publications:
            raise ValueError("fetch stage publications must equal persisted fetch evidence")


class PubMedCollection(_PubMedCollectionModel):
    """Complete persisted PubMed collection with no report or provider-native data."""

    searched: PubMedSearchCollection
    fetches: tuple[PubMedCollectedFetch, ...]
    persisted_acquisitions: tuple[PersistedAcquisition, ...]
    publications: tuple[PublicationRecord, ...]
    source_outcome: SourceOutcome
    retrieval_as_of: UtcDateTime

    def model_post_init(self, __context: object) -> None:
        del __context
        if tuple(item.pmid for item in self.fetches) != self.searched.response.pmids:
            raise ValueError("collected fetches must equal the exact ordered search PMIDs")
        expected_acquisitions = (
            self.searched.acquisition,
            *(item.acquisition for item in self.fetches),
        )
        if self.persisted_acquisitions != expected_acquisitions:
            raise ValueError("collection acquisitions must equal search followed by fetches")
        expected_publications = tuple(
            item.publication for item in self.fetches if item.publication is not None
        )
        if self.publications != expected_publications:
            raise ValueError("collection publications must equal persisted fetch evidence")
        if (
            self.source_outcome.source is not SourceType.PUBMED
            or self.source_outcome.query_id != self.searched.query_id
        ):
            raise ValueError("collection outcome must bind the exact PubMed query")


@final
class PubMedResearchService:
    """Coordinate injected PubMed, catalog, acquisition, and run ports."""

    _acquisitions: AcquisitionPersistencePort
    _catalog: ConceptCatalogPort
    _execution: PubMedExecutionPort
    _runs: RunPersistencePort
    _runtime: RuntimePort
    __slots__ = ("_acquisitions", "_catalog", "_execution", "_runs", "_runtime")

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("PubMedResearchService is a sealed application authority")

    def __setattr__(self, name: str, value: object) -> None:
        del name, value
        raise AttributeError("PubMedResearchService is frozen after construction")

    def __init__(
        self,
        *,
        catalog: ConceptCatalogPort,
        execution: PubMedExecutionPort,
        acquisitions: AcquisitionPersistencePort,
        runs: RunPersistencePort,
        runtime: RuntimePort,
    ) -> None:
        object.__setattr__(self, "_catalog", catalog)
        object.__setattr__(self, "_execution", execution)
        object.__setattr__(self, "_acquisitions", acquisitions)
        object.__setattr__(self, "_runs", runs)
        object.__setattr__(self, "_runtime", runtime)

    def search(self, request: SearchPubMedRequest) -> SearchPubMedResponse:
        """Execute one validated search without constructing concrete adapters."""

        catalog, query, query_id = self._prepare_query(request.scope)
        del catalog
        execution = self._execution.search(query=query, query_id=query_id)
        self._validate_search_execution(request.scope, query, query_id, execution)
        return execution.response

    def fetch(self, request: FetchPubMedArticleRequest) -> FetchPubMedArticleResponse:
        """Execute one validated singular fetch."""

        _, _, expected_query_id = self._prepare_query(request.scope)
        if request.query_id != expected_query_id:
            raise ValueError("fetch query identity does not match the exact resolved query")
        execution = self._execution.fetch(pmid=request.pmid, query_id=request.query_id)
        return self._fetch_response(request, execution)

    def collect(self, request: ResearchPubMedRequest) -> PubMedCollection:
        """Persist bounded PubMed acquisitions without constructing a report."""

        searched = self.collect_search(self.prepare_collection(request))
        return self.collect_fetches(searched)

    def prepare_collection(
        self,
        request: ResearchPubMedRequest,
    ) -> PubMedCollectionPreparation:
        """Resolve the exact bounded query without acquisition side effects."""

        request = ResearchPubMedRequest.model_validate(request.model_dump(mode="python"))
        catalog, query, query_id = self._prepare_query(request.scope)
        run_intent = self._run_intent(request, catalog, query)
        return PubMedCollectionPreparation(
            request=request,
            catalog=catalog,
            query=query,
            query_id=query_id,
            run_intent_id=self._runs.resolve_run_intent_id(run_intent),
        )

    def collect_search(
        self,
        prepared: PubMedCollectionPreparation,
    ) -> PubMedSearchCollection:
        """Persist the exact run intent and search before any PMID fetch."""

        prepared = PubMedCollectionPreparation.model_validate(prepared.model_dump(mode="python"))
        request = prepared.request
        catalog = prepared.catalog
        query = prepared.query
        query_id = prepared.query_id
        run_intent = self._run_intent(request, catalog, query)
        run_intent_id = self._runs.persist_run_intent(run_intent)
        if run_intent_id != prepared.run_intent_id:
            raise ValueError("persisted PubMed run intent changed its exact identity")
        search_intent = self._acquisition_intent(
            run_id=request.run_id,
            run_intent_id=run_intent_id,
            ordinal=0,
            operation="search",
            query=query,
        )
        search_execution = self._execution.search(query=query, query_id=query_id)
        self._validate_search_execution(
            request.scope,
            query,
            query_id,
            search_execution,
        )
        persisted_search = _validated_persisted_acquisition(
            self._acquisitions.persist_search(
                intent=search_intent,
                execution=search_execution,
            ),
            expected_intent=search_intent,
        )
        if persisted_search.publication_bindings:
            raise ValueError("search acquisition must not return publication bindings")
        progress_record = PubMedSearchProgressRecord.create(
            run_id=request.run_id,
            scope_id=request.scope.scope_id,
            query=query,
            query_id=query_id,
            acquisition_intent_id=persisted_search.acquisition_intent_id,
            snapshot_id=persisted_search.snapshot_id,
            manifest_id=persisted_search.manifest_id,
            pmids=search_execution.response.pmids,
            search_source_outcome_id=derive_identity(
                "source-operation-outcome",
                search_execution.response.source_outcome,
            ),
            valid_result_count=search_execution.response.source_outcome.valid_result_count,
        )
        persisted_progress = PubMedSearchProgressRecord.model_validate(
            self._acquisitions.persist_search_progress(progress_record).model_dump(mode="python")
        )
        if persisted_progress != progress_record:
            raise ValueError("persisted PubMed search progress did not echo exact content")

        return PubMedSearchCollection(
            request=request,
            catalog=catalog,
            query=query,
            query_id=query_id,
            run_intent_id=run_intent_id,
            response=search_execution.response,
            acquisition=persisted_search,
            progress_record=persisted_progress,
            completed_at_utc=search_execution.completed_at_utc,
        )

    def load_search_progress(
        self,
        *,
        run_id: str,
        acquisition_intent_id: str,
    ) -> PubMedSearchProgressRecord:
        """Load and reconstruct one exact persisted search membership record."""

        loaded = self._acquisitions.load_search_progress(
            run_id=run_id,
            acquisition_intent_id=acquisition_intent_id,
        )
        return PubMedSearchProgressRecord.model_validate(loaded.model_dump(mode="python"))

    def persist_terminal_progress(
        self,
        record: PubMedTerminalProgressRecord,
    ) -> PubMedTerminalProgressRecord:
        """Persist and reconstruct one exact M3 terminal replay receipt."""

        record = PubMedTerminalProgressRecord.model_validate(record.model_dump(mode="python"))
        persisted = self._acquisitions.persist_terminal_progress(record)
        return PubMedTerminalProgressRecord.model_validate(persisted.model_dump(mode="python"))

    def load_terminal_progress(
        self,
        *,
        run_id: str,
        attempt_id: str,
    ) -> PubMedTerminalProgressRecord:
        """Load and reconstruct one exact M3 terminal replay receipt."""

        loaded = self._acquisitions.load_terminal_progress(
            run_id=run_id,
            attempt_id=attempt_id,
        )
        return PubMedTerminalProgressRecord.model_validate(loaded.model_dump(mode="python"))

    def collect_fetches(self, searched: PubMedSearchCollection) -> PubMedCollection:
        """Persist exactly the ordered PMIDs returned by a validated search."""

        searched = PubMedSearchCollection.model_validate(searched.model_dump(mode="python"))
        prepared = PubMedCollectionPreparation(
            request=searched.request,
            catalog=searched.catalog,
            query=searched.query,
            query_id=searched.query_id,
            run_intent_id=searched.run_intent_id,
        )
        stage = self.collect_fetch_stage(prepared=prepared, search_response=searched.response)
        persisted = (searched.acquisition, *stage.persisted_acquisitions)
        child_outcomes = (
            searched.response.source_outcome,
            *(item.source_outcome for item in stage.fetches),
        )
        composite = _composite_outcome(
            scope=searched.request.scope,
            query_id=searched.query_id,
            search=searched.response,
            children=child_outcomes,
            valid_publications=len(stage.publications),
        )
        retrieval_as_of = max(
            (searched.completed_at_utc, *(fetch.completed_at_utc for fetch in stage.fetches))
        )
        if stage.publications:
            retrieval_as_of = max(
                retrieval_as_of,
                *(item.publication_status.retrieved_as_of for item in stage.publications),
            )
        return PubMedCollection(
            searched=searched,
            fetches=stage.fetches,
            persisted_acquisitions=persisted,
            publications=stage.publications,
            source_outcome=composite,
            retrieval_as_of=retrieval_as_of,
        )

    def collect_fetch_stage(
        self,
        *,
        prepared: PubMedCollectionPreparation,
        search_response: SearchPubMedResponse,
    ) -> PubMedFetchStageCollection:
        """Persist only the fetch suffix reconstructed from checkpointed search state."""

        prepared = PubMedCollectionPreparation.model_validate(prepared.model_dump(mode="python"))
        search_response = SearchPubMedResponse.model_validate(
            search_response.model_dump(mode="python")
        )
        if search_response.query != prepared.query or search_response.query_id != prepared.query_id:
            raise ValueError("PubMed fetch stage must bind the exact prepared query")
        request = prepared.request
        persisted: list[PersistedAcquisition] = []
        publications: list[PublicationRecord] = []
        fetches: list[PubMedCollectedFetch] = []

        for ordinal, pmid in enumerate(search_response.pmids, start=1):
            fetch_intent = self._acquisition_intent(
                run_id=request.run_id,
                run_intent_id=prepared.run_intent_id,
                ordinal=ordinal,
                operation="fetch",
                pmid=pmid,
            )
            fetch_execution = self._execution.fetch(pmid=pmid, query_id=prepared.query_id)
            fetch_response = self._fetch_response(
                FetchPubMedArticleRequest(
                    scope=request.scope,
                    pmid=pmid,
                    query_id=prepared.query_id,
                ),
                fetch_execution,
            )
            persisted_fetch = _validated_persisted_acquisition(
                self._acquisitions.persist_fetch(
                    intent=fetch_intent,
                    execution=fetch_execution,
                ),
                expected_intent=fetch_intent,
            )
            bound_publication = _with_persisted_publication_binding(
                fetch_response.publication,
                persisted_fetch,
            )
            persisted.append(persisted_fetch)
            if bound_publication is not None:
                publications.append(bound_publication)
            fetches.append(
                PubMedCollectedFetch(
                    pmid=pmid,
                    source_outcome=fetch_response.source_outcome,
                    acquisition=persisted_fetch,
                    publication=bound_publication,
                    completed_at_utc=fetch_execution.completed_at_utc,
                )
            )

        return PubMedFetchStageCollection(
            search_response=search_response,
            fetches=tuple(fetches),
            persisted_acquisitions=tuple(persisted),
            publications=tuple(publications),
        )

    def research(self, request: ResearchPubMedRequest) -> ResearchReport:
        """Run collection, construct claims, then persist the draft last."""

        collection = self.collect(request)
        catalog = collection.searched.catalog
        run_intent_id = collection.searched.run_intent_id
        persisted = collection.persisted_acquisitions
        composite = collection.source_outcome
        report_publications = tuple(
            _with_report_outcome(publication, composite) for publication in collection.publications
        )
        citations, claims = _claims_for_publications(
            scope_id=request.scope.scope_id,
            publications=report_publications,
            catalog=catalog,
        )
        source_warnings = tuple(
            ReportWarning.from_publication(publication, code=code)
            for publication in report_publications
            for code in publication.publication_status.warning_codes
        )
        publications_by_id = {
            publication.publication_version_id: publication for publication in report_publications
        }
        claim_warnings = tuple(
            ReportWarning.from_publication(
                publications_by_id[claim.publication_version_id],
                code=code,
                claim=claim,
            )
            for claim in claims
            for code in claim.publication_warning_references
        )
        limitations = (
            (CoverageLimitation.from_outcome(composite),)
            if composite.coverage_status is not CoverageStatus.COMPLETE
            else ()
        )
        report = ResearchReport.create(
            run_id=request.run_id,
            catalog_content_hash=catalog.catalog_content_hash,
            run_intent_id=run_intent_id,
            acquisition_snapshot_ids=tuple(item.snapshot_id for item in persisted),
            acquisition_manifest_ids=tuple(item.manifest_id for item in persisted),
            acquisition_registration_envelope_ids=tuple(
                item.registration_envelope_id for item in persisted
            ),
            scope=request.scope,
            source_plan=_source_plan(request.scope.selected_sources),
            source_outcomes=(composite,),
            publications=report_publications,
            claims=claims,
            citations=citations,
            source_status_warnings=source_warnings,
            claim_status_warnings=claim_warnings,
            coverage_limitations=limitations,
            retrieval_as_of=collection.retrieval_as_of,
        )
        completed_at = self._runtime.utc_now()
        self._runs.persist_run_and_report(
            finalization=RunFinalization(
                run_intent_id=run_intent_id,
                report=report,
                report_artifact_bytes=report.artifact_bytes(),
                started_at_utc=request.created_at_utc,
                completed_at_utc=completed_at,
                warning_codes=composite.warning_codes,
            ),
            acquisitions=tuple(persisted),
        )
        return report

    def _prepare_query(
        self,
        scope: ResearchScope,
    ) -> tuple[ResolvedConceptCatalog, str, str]:
        validate_query_terms(scope)
        catalog = self._catalog.resolve(scope.scope_id)
        query = build_pubmed_query(scope, catalog)
        return catalog, query, query_identity(scope, query)

    @staticmethod
    def _validate_search_execution(
        scope: ResearchScope,
        query: str,
        query_id: str,
        execution: PubMedSearchExecution,
    ) -> None:
        response = execution.response
        if response.query != query or response.query_id != query_id:
            raise ValueError("search execution returned a different query identity")
        if response.source_outcome.configured_bounds != ExecutionBounds.from_scope(scope):
            raise ValueError("search outcome bounds differ from the requested scope")

    @staticmethod
    def _fetch_response(
        request: FetchPubMedArticleRequest,
        execution: PubMedFetchExecution,
    ) -> FetchPubMedArticleResponse:
        if execution.requested_pmid != request.pmid or execution.query_id != request.query_id:
            raise ValueError("fetch execution returned a different request identity")
        if execution.source_outcome.configured_bounds != ExecutionBounds.from_scope(request.scope):
            raise ValueError("fetch outcome bounds differ from the requested scope")
        return FetchPubMedArticleResponse(
            requested_pmid=request.pmid,
            query_id=request.query_id,
            publication=execution.publication,
            source_outcome=execution.source_outcome,
        )

    def _run_intent(
        self,
        request: ResearchPubMedRequest,
        catalog: ResolvedConceptCatalog,
        query: str,
    ) -> RunIntentInput:
        return RunIntentInput(
            run_id=request.run_id,
            request_id=request.request_id,
            created_at_utc=request.created_at_utc,
            code_revision=request.code_revision,
            scope_id=request.scope.scope_id,
            catalog_version=catalog.catalog_version,
            catalog_content_hash=catalog.catalog_content_hash,
            drug_concept_ids=tuple(item.concept_id for item in catalog.drugs),
            adverse_event_concept_ids=tuple(item.concept_id for item in catalog.adverse_reactions),
            start_date=(
                request.scope.date_range.start_date
                if request.scope.date_range is not None
                else None
            ),
            end_date=(
                request.scope.date_range.end_date if request.scope.date_range is not None else None
            ),
            pubmed_query=query,
        )

    def _acquisition_intent(
        self,
        *,
        run_id: str,
        run_intent_id: str,
        ordinal: int,
        operation: Literal["search", "fetch"],
        query: str | None = None,
        pmid: str | None = None,
    ) -> AcquisitionIntentInput:
        return AcquisitionIntentInput.create(
            attempt_id=self._runtime.new_attempt_id(),
            run_id=run_id,
            run_intent_id=run_intent_id,
            created_at_utc=self._runtime.utc_now(),
            operation=operation,
            acquisition_ordinal=ordinal,
            query=query,
            pmid=pmid,
        )


def research_pubmed_draft(
    request: ResearchPubMedRequest,
    *,
    service: PubMedResearchService,
) -> ResearchReport:
    """Execute the complete deterministic PubMed draft workflow."""

    return service.research(request)


def _source_plan(sources: tuple[SourceType, ...]) -> tuple[SourcePlanEntry, ...]:
    return tuple(
        SourcePlanEntry(
            source=source,
            planning_status=(
                PlanningStatus.SELECTED
                if source is SourceType.PUBMED
                else PlanningStatus.SKIPPED_BY_POLICY
            ),
            reason_code=(
                None
                if source is SourceType.PUBMED
                else SourcePlanReasonCode.SOURCE_EXECUTION_NOT_AUTHORIZED
            ),
            reason=(
                None
                if source is SourceType.PUBMED
                else f"{source.value} execution is not authorized in M1A."
            ),
        )
        for source in sources
    )


def _composite_outcome(
    *,
    scope: ResearchScope,
    query_id: str,
    search: SearchPubMedResponse,
    children: tuple[SourceOutcome, ...],
    valid_publications: int,
) -> SourceOutcome:
    failed = any(item.execution_status is ExecutionStatus.FAILED for item in children)
    all_fetches_valid = valid_publications == len(search.pmids)
    complete = (
        search.source_outcome.coverage_status is CoverageStatus.COMPLETE
        and all_fetches_valid
        and all(item.coverage_status is CoverageStatus.COMPLETE for item in children)
    )
    if complete:
        coverage = CoverageStatus.COMPLETE
    elif search.source_outcome.coverage_status is CoverageStatus.UNAVAILABLE and not search.pmids:
        coverage = CoverageStatus.UNAVAILABLE
    else:
        coverage = CoverageStatus.PARTIAL
    if valid_publications:
        result = ResultStatus.MATCHES
    elif complete and not search.pmids:
        result = ResultStatus.NO_MATCH
    else:
        result = ResultStatus.INDETERMINATE
    warnings = {code for item in children for code in item.warning_codes}
    if coverage is CoverageStatus.PARTIAL:
        warnings.add("source_coverage_incomplete")
    elif coverage is CoverageStatus.UNAVAILABLE:
        warnings.add("source_unavailable")
    return SourceOutcome(
        source=SourceType.PUBMED,
        query_id=query_id,
        execution_status=ExecutionStatus.FAILED if failed else ExecutionStatus.SUCCEEDED,
        coverage_status=coverage,
        result_status=result,
        configured_bounds=ExecutionBounds.from_scope(scope),
        valid_result_count=valid_publications,
        pages_completed=search.source_outcome.pages_completed,
        truncated=any(item.truncated for item in children),
        warning_codes=tuple(sorted(warnings)),
        failure_id=(
            derive_identity(
                "failure",
                tuple(item.failure_id for item in children if item.failure_id is not None),
            )
            if failed
            else None
        ),
    )


def _with_report_outcome(
    publication: PublicationRecord,
    outcome: SourceOutcome,
) -> PublicationRecord:
    warnings_by_code = {warning.code: warning for warning in publication.provenance.warnings}
    for code in outcome.warning_codes:
        warnings_by_code.setdefault(
            code,
            DomainWarning(
                code=code,
                message=f"Composite PubMed outcome warning: {code}.",
            ),
        )
    failure = None
    if outcome.execution_status is ExecutionStatus.FAILED:
        if outcome.failure_id is None:
            raise ValueError("failed composite outcome requires a failure identity")
        prior_failure = publication.provenance.failure
        failure = SourceFailure(
            failure_id=outcome.failure_id,
            failure_code=(
                prior_failure.failure_code if prior_failure is not None else FailureCode.UNKNOWN
            ),
            retryable=prior_failure.retryable if prior_failure is not None else False,
        )
    provenance = publication.provenance.model_copy(
        update={
            "query_id": outcome.query_id,
            "source_outcome": outcome,
            "configured_bounds": outcome.configured_bounds,
            "warnings": tuple(warnings_by_code[code] for code in sorted(warnings_by_code)),
            "failure": failure,
        }
    )
    payload = publication.model_dump(mode="python")
    payload["provenance"] = Provenance.model_validate(provenance)
    report_publication = PublicationRecord.model_validate(payload)
    if (
        report_publication.publication_version_id != publication.publication_version_id
        or report_publication.content_hash != publication.content_hash
    ):
        raise ValueError("report outcome rebinding changed publication content identity")
    return report_publication


def _with_persisted_publication_binding(
    publication: PublicationRecord | None,
    acquisition: PersistedAcquisition,
) -> PublicationRecord | None:
    bindings = acquisition.publication_bindings
    if publication is None:
        if bindings:
            raise ValueError("fetch without a publication must not return a publication binding")
        return None
    if len(bindings) != 1:
        raise ValueError("fetched publication requires exactly one persisted binding")
    binding: PersistedPublicationBinding = bindings[0]
    if (
        binding.pmid != publication.pmid
        or binding.publication_version_id != publication.publication_version_id
        or binding.publication_artifact_id != publication.content_hash
        or binding.snapshot_id != acquisition.snapshot_id
        or binding.manifest_id != acquisition.manifest_id
    ):
        raise ValueError("persisted publication binding does not match fetched publication")
    edge = binding.lineage_edges[0]
    if (
        edge.parent_artifact_id != publication.content_hash
        or edge.child_artifact_id != acquisition.manifest_id
    ):
        raise ValueError("persisted publication lineage endpoints do not match fetched evidence")
    provenance = publication.provenance.model_copy(
        update={
            "snapshot_id": binding.snapshot_id,
            "artifact_ids": binding.artifact_ids,
            "transformation_lineage": (
                edge.parent_artifact_id,
                edge.child_artifact_id,
            ),
        }
    )
    payload = publication.model_dump(mode="python")
    payload["provenance"] = Provenance.model_validate(provenance)
    rebound = PublicationRecord.model_validate(payload)
    if (
        rebound.publication_version_id != publication.publication_version_id
        or rebound.content_hash != publication.content_hash
    ):
        raise ValueError("persisted provenance rebinding changed publication content identity")
    return rebound


def _validated_persisted_acquisition(
    value: object,
    *,
    expected_intent: AcquisitionIntentInput,
) -> PersistedAcquisition:
    """Reconstruct and validate one untrusted persistence-port result."""

    if type(value) is not PersistedAcquisition:
        raise ValueError("persistence adapter must return PersistedAcquisition")
    payload = _untrusted_payload(value)
    if not isinstance(payload, dict):
        raise ValueError("persisted acquisition payload must be an object")
    try:
        reconstructed = PersistedAcquisition.model_validate(payload)
    except ValidationError as error:
        raise ValueError("persisted acquisition output failed closed validation") from error
    if reconstructed.acquisition_intent_id != expected_intent.acquisition_intent_id:
        raise ValueError("persisted acquisition does not belong to the expected intent")
    return reconstructed


def _untrusted_payload(value: object) -> object:
    """Expose all model-copy fields before strict recursive reconstruction."""

    if isinstance(value, BaseModel):
        fields = {key: _untrusted_payload(item) for key, item in vars(value).items()}
        extra = value.__pydantic_extra__
        if extra:
            fields.update({key: _untrusted_payload(item) for key, item in extra.items()})
        return fields
    if isinstance(value, tuple):
        return tuple(_untrusted_payload(item) for item in value)
    if isinstance(value, list):
        return [_untrusted_payload(item) for item in value]
    if isinstance(value, dict):
        return {key: _untrusted_payload(item) for key, item in value.items()}
    return value


def _claims_for_publications(
    *,
    scope_id: str,
    publications: tuple[PublicationRecord, ...],
    catalog: ResolvedConceptCatalog,
) -> tuple[tuple[Citation, ...], tuple[EvidenceClaim, ...]]:
    citations: list[Citation] = []
    claims: list[EvidenceClaim] = []
    drug_terms = tuple(item.preferred_term for item in catalog.drugs)
    event_terms = tuple(item.preferred_term for item in catalog.adverse_reactions)
    for publication in publications:
        span = _smallest_term_span(publication.canonical_abstract, drug_terms, event_terms)
        if (
            span is None
            or publication.publication_status.status is PublicationStatusValue.RETRACTED
        ):
            continue
        use_context = _eligible_use_context(publication)
        if use_context is None:
            continue
        try:
            citation = Citation.from_publication(
                publication,
                start_offset=span[0],
                end_offset=span[1],
                relationship=CitationRelationship.SUPPORTS,
            )
        except CitationValidationError:
            continue
        claim = EvidenceClaim.from_citation(
            scope_id=scope_id,
            citation=citation,
            publication=publication,
            use_context=use_context,
        )
        citations.append(citation)
        claims.append(claim)
    return (
        tuple(sorted(citations, key=lambda item: item.citation_id)),
        tuple(sorted(claims, key=lambda item: item.claim_id)),
    )


def _eligible_use_context(publication: PublicationRecord) -> ClaimUseContext | None:
    status = publication.publication_status.status
    if status is PublicationStatusValue.RETRACTED:
        return None
    if status in {
        PublicationStatusValue.EXPRESSION_OF_CONCERN,
        PublicationStatusValue.UNKNOWN_OR_UNVERIFIED,
    }:
        return ClaimUseContext.SUPPORT_LIMITED
    if status is PublicationStatusValue.CORRECTED:
        relationship = publication.publication_status.relationship
        if (
            relationship is None
            or relationship.resolution is not RelationshipResolution.RESOLVED
            or relationship.content_disposition
            is not CorrectionContentDisposition.RESOLVED_CURRENT_CONTENT
        ):
            return None
    return ClaimUseContext.AFFIRMATIVE_SUPPORT


def _smallest_term_span(
    abstract: str | None,
    drug_terms: tuple[str, ...],
    event_terms: tuple[str, ...],
) -> tuple[int, int] | None:
    if abstract is None:
        return None
    candidates: list[tuple[int, int, int, int, int, int, int]] = []
    for drug_index, drug in enumerate(drug_terms):
        for drug_start in _occurrences(abstract, drug):
            for event_index, event in enumerate(event_terms):
                for event_start in _occurrences(abstract, event):
                    start = min(drug_start, event_start)
                    end = max(drug_start + len(drug), event_start + len(event))
                    candidates.append(
                        (
                            end - start,
                            start,
                            end,
                            drug_index,
                            event_index,
                            drug_start,
                            event_start,
                        )
                    )
    if not candidates:
        return None
    _, start, end, *_ = min(candidates)
    return start, end


def _occurrences(text: str, term: str) -> tuple[int, ...]:
    starts: list[int] = []
    cursor = 0
    while True:
        found = text.find(term, cursor)
        if found < 0:
            return tuple(starts)
        starts.append(found)
        cursor = found + 1
