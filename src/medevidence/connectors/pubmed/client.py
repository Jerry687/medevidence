"""Synchronous, bounded, transport-injected PubMed connector."""

from __future__ import annotations

import random
import re
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from itertools import islice
from typing import Final, Literal, Self

import httpx

from medevidence.domain import (
    AbstractSection,
    CorrectionContentDisposition,
    CoverageStatus,
    DatePrecision,
    DomainWarning,
    ExecutionBounds,
    ExecutionStatus,
    FailureCode,
    IndexingStatus,
    NoticeType,
    PartialDate,
    Provenance,
    PublicationRecord,
    PublicationRelationship,
    PublicationRelationshipType,
    PublicationStatus,
    PublicationStatusValue,
    RelationshipResolution,
    ResultStatus,
    SourceFailure,
    SourceOutcome,
    SourceType,
    derive_identity,
    sha256_digest,
)

from .parsing import (
    IncompletePubMedXmlError,
    InvalidPubMedXmlError,
    MalformedPubMedRecord,
    PubMedArticle,
    PubMedFetchResponse,
    PubMedRelationship,
    parse_fetch_response,
    parse_search_page,
)
from .policy import (
    PUBMED_EFETCH_PATH,
    PUBMED_ESEARCH_PATH,
    PUBMED_ORIGIN,
    RETRYABLE_STATUS_CODES,
    PubMedConnectorConfig,
    PubMedFailure,
    PubMedFailureKind,
    PubMedResultState,
    RawPubMedResponse,
    RetryEvent,
    parse_retry_after,
    resolve_pubmed_redirect,
    retry_delay_seconds,
    validate_pubmed_url,
)

CONNECTOR_VERSION: Final = "m1a-002"
_QUERY_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_MAX_PMID_CHARACTERS: Final = 16
_MAX_FETCH_ID_QUERY_CHARACTERS: Final = 2048
_PMID_PATTERN = re.compile(rf"[1-9][0-9]{{0,{_MAX_PMID_CHARACTERS - 1}}}\Z")
_REDIRECT_STATUS_CODES: Final = frozenset({301, 302, 303, 307, 308})
_SAFE_RESPONSE_HEADERS: Final = frozenset(
    {
        "content-length",
        "content-encoding",
        "content-type",
        "location",
        "retry-after",
        "x-ratelimit-limit",
        "x-ratelimit-remaining",
    }
)

WARNING_BOUNDED_TRUNCATION: Final = "pubmed_bounded_truncation"
WARNING_PARTIAL_FAILURE: Final = "pubmed_partial_failure"
WARNING_SOURCE_UNAVAILABLE: Final = "pubmed_source_unavailable"
WARNING_DUPLICATE_PMIDS: Final = "pubmed_duplicate_pmids"
WARNING_MALFORMED_RECORDS: Final = "pubmed_malformed_records"
WARNING_MISSING_RECORDS: Final = "pubmed_missing_records"
WARNING_UNEXPECTED_RECORDS: Final = "pubmed_unexpected_records"
WARNING_UNSUPPORTED_LANGUAGE: Final = "pubmed_unsupported_language"
WARNING_RECORD_MAPPING: Final = "pubmed_record_mapping_warning"
WARNING_UNKNOWN_INDEXING: Final = "pubmed_unknown_indexing_status"
WARNING_UNSTRUCTURED_DATE: Final = "pubmed_unstructured_publication_date"
WARNING_INVALID_DOI: Final = "pubmed_invalid_doi_omitted"
WARNING_INVALID_PMCID: Final = "pubmed_invalid_pmcid_omitted"
WARNING_STATUS_SIGNAL_UNRESOLVED: Final = "pubmed_publication_status_signal_unresolved"

_WARNING_MESSAGES: Final = {
    WARNING_BOUNDED_TRUNCATION: (
        "The configured PubMed page or record bound was reached before source exhaustion."
    ),
    WARNING_PARTIAL_FAILURE: (
        "PubMed retrieval failed after at least one response page was validated."
    ),
    WARNING_SOURCE_UNAVAILABLE: "PubMed did not yield a validated response page.",
    WARNING_DUPLICATE_PMIDS: (
        "Duplicate PubMed identifiers were detected and handled under the operation's "
        "duplicate policy."
    ),
    WARNING_MALFORMED_RECORDS: ("One or more PubMed records were malformed and were not retained."),
    WARNING_MISSING_RECORDS: "PubMed did not return every requested record.",
    WARNING_UNEXPECTED_RECORDS: "PubMed returned one or more unrequested record identifiers.",
    WARNING_UNSUPPORTED_LANGUAGE: (
        "A record without an English-language designation was not retained."
    ),
    WARNING_RECORD_MAPPING: (
        "One or more provider records could not satisfy the source-neutral publication contract."
    ),
    WARNING_UNKNOWN_INDEXING: "The PubMed indexing status was not recognized.",
    WARNING_UNSTRUCTURED_DATE: (
        "The PubMed publication date was unstructured and was retained without a normalized date."
    ),
    WARNING_INVALID_DOI: "An invalid optional DOI was omitted from the normalized record.",
    WARNING_INVALID_PMCID: "An invalid optional PMCID was omitted from the normalized record.",
    WARNING_STATUS_SIGNAL_UNRESOLVED: (
        "A publication-type status signal lacked a resolvable PubMed notice relationship."
    ),
}


@dataclass(frozen=True, slots=True)
class PubMedClientIdentity:
    """Non-secret NCBI client-identification fields."""

    tool: str = "medevidence"
    email: str | None = None

    def __post_init__(self) -> None:
        if self.tool != "medevidence":
            raise ValueError("M1A PubMed tool identity must be 'medevidence'")
        if self.email is not None:
            candidate = self.email.strip()
            if (
                candidate != self.email
                or len(candidate) > 254
                or "@" not in candidate
                or any(character.isspace() for character in candidate)
            ):
                raise ValueError("email must be a bounded nonblank address")


@dataclass(frozen=True, slots=True)
class PubMedRecordIssue:
    """Payload-free description of a provider-to-domain record rejection."""

    pmid_hint: str | None
    code: str
    message: str

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,127}", self.code):
            raise ValueError("record issue code must be machine readable")
        if not self.message.strip():
            raise ValueError("record issue message must not be blank")


@dataclass(frozen=True, slots=True)
class PubMedSearchResult:
    """Bounded PubMed ESearch result without provider-native objects."""

    state: PubMedResultState
    query: str
    query_id: str | None
    pmids: tuple[str, ...]
    total_available: int | None
    source_outcome: SourceOutcome | None
    failure: PubMedFailure | None
    warning_codes: tuple[str, ...]
    raw_responses: tuple[RawPubMedResponse, ...]
    retry_events: tuple[RetryEvent, ...]
    request_count: int


@dataclass(frozen=True, slots=True)
class PubMedFetchResult:
    """Bounded PubMed EFetch result mapped into publication contracts."""

    state: PubMedResultState
    query_id: str | None
    requested_pmids: tuple[str, ...]
    publications: tuple[PublicationRecord, ...]
    not_retrieved_pmids: tuple[str, ...]
    malformed_records: tuple[MalformedPubMedRecord, ...]
    record_issues: tuple[PubMedRecordIssue, ...]
    source_outcome: SourceOutcome | None
    failure: PubMedFailure | None
    warning_codes: tuple[str, ...]
    raw_responses: tuple[RawPubMedResponse, ...]
    retry_events: tuple[RetryEvent, ...]
    request_count: int


@dataclass(slots=True)
class _OperationContext:
    started_at: float
    raw_responses: list[RawPubMedResponse] = field(default_factory=list)
    retry_events: list[RetryEvent] = field(default_factory=list)
    cumulative_payload_bytes: int = 0
    request_count: int = 0
    pages_completed: int = 0


@dataclass(frozen=True, slots=True)
class _HttpResponse:
    request_url: str
    final_url: str
    status_code: int
    body: bytes
    headers: tuple[tuple[str, str], ...]

    def header(self, name: str) -> str | None:
        expected = name.casefold()
        return next((value for key, value in self.headers if key == expected), None)


@dataclass(frozen=True, slots=True)
class _BodyRead:
    body: bytes
    body_complete: bool
    termination_reason: Literal[
        "complete_response",
        "payload_limit",
        "stream_error",
        "deadline_exceeded",
    ]
    failure_kind: PubMedFailureKind | None = None


@dataclass(frozen=True, slots=True)
class _HttpResult:
    response: _HttpResponse | None = None
    failure: PubMedFailure | None = None

    def __post_init__(self) -> None:
        if (self.response is None) == (self.failure is None):
            raise ValueError("HTTP result requires exactly one response or failure")


@dataclass(frozen=True, slots=True)
class _PreparedArticle:
    pmid: str
    doi: str | None
    pmcid: str | None
    title: str
    abstract_sections: tuple[AbstractSection, ...]
    authors: tuple[str, ...]
    journal: str
    publication_types: tuple[str, ...]
    publication_date: PartialDate | None
    publication_status: PublicationStatus
    indexing_status: IndexingStatus
    parse_warnings: tuple[DomainWarning, ...]
    response_content_hash: str
    retrieved_at: datetime


class PubMedConnector:
    """Bounded synchronous PubMed adapter.

    The connector owns the HTTPX client and the injected transport. Closing the
    connector closes both. The general constructor never creates a real
    transport; only :meth:`for_production` does so explicitly.
    """

    def __init__(
        self,
        transport: httpx.BaseTransport,
        config: PubMedConnectorConfig | None = None,
        *,
        identity: PubMedClientIdentity | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        utc_now: Callable[[], datetime] | None = None,
        sleep: Callable[[float], None] = time.sleep,
        jitter: Callable[[], float] | None = None,
    ) -> None:
        if not isinstance(transport, httpx.BaseTransport):
            raise TypeError("transport must implement httpx.BaseTransport")
        self._config = config or PubMedConnectorConfig()
        self._identity = identity or PubMedClientIdentity()
        self._monotonic = monotonic
        self._utc_now = utc_now or (lambda: datetime.now(UTC))
        self._sleep = sleep
        self._jitter = jitter or (lambda: random.uniform(0.0, self._config.jitter_seconds))
        self._client = httpx.Client(
            transport=transport,
            follow_redirects=False,
            trust_env=False,
            headers={
                "Accept": "application/xml",
                "Accept-Encoding": "identity",
                "User-Agent": "medevidence/m1a-002",
            },
        )
        self._closed = False

    @classmethod
    def for_production(
        cls,
        *,
        email: str,
        config: PubMedConnectorConfig | None = None,
    ) -> Self:
        """Create the only connector path that instantiates real HTTP transport."""

        identity = PubMedClientIdentity(email=email)
        transport = httpx.HTTPTransport(retries=0)
        return cls(transport, config, identity=identity)

    @property
    def config(self) -> PubMedConnectorConfig:
        """Return the immutable execution policy."""

        return self._config

    def close(self) -> None:
        """Close the owned HTTP client and transport."""

        if not self._closed:
            self._client.close()
            self._closed = True

    def __enter__(self) -> Self:
        if self._closed:
            raise RuntimeError("closed PubMedConnector cannot be reused")
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def search(self, query: str, *, query_id: str | None = None) -> PubMedSearchResult:
        """Execute one bounded ESearch operation through the injected transport."""

        canonical_query, resolved_query_id, input_failure = self._prepare_search_input(
            query,
            query_id,
        )
        if input_failure is not None:
            return PubMedSearchResult(
                state=PubMedResultState.FAILED,
                query=canonical_query,
                query_id=resolved_query_id,
                pmids=(),
                total_available=None,
                source_outcome=None,
                failure=input_failure,
                warning_codes=(),
                raw_responses=(),
                retry_events=(),
                request_count=0,
            )
        active_query_id = _require_query_id(resolved_query_id)

        context = _OperationContext(started_at=self._monotonic())
        pmids: list[str] = []
        seen_pmids: set[str] = set()
        warnings: set[str] = set()
        total_available: int | None = None
        retstart = 0

        while context.pages_completed < self._config.max_pages:
            remaining_record_slots = self._config.max_records - len(pmids)
            if remaining_record_slots <= 0:
                warnings.add(WARNING_BOUNDED_TRUNCATION)
                return self._complete_search(
                    context=context,
                    query=canonical_query,
                    query_id=active_query_id,
                    pmids=pmids,
                    total_available=total_available,
                    warnings=warnings,
                    state=PubMedResultState.BOUNDED_TRUNCATION,
                    truncated=True,
                )

            requested_retmax = min(self._config.page_size, remaining_record_slots)
            result = self._get(
                context,
                path=PUBMED_ESEARCH_PATH,
                params={
                    "db": "pubmed",
                    "term": canonical_query,
                    "retmode": "xml",
                    "retstart": str(retstart),
                    "retmax": str(requested_retmax),
                },
                page_number=context.pages_completed + 1,
            )
            if result.failure is not None:
                return self._failed_search(
                    context=context,
                    query=canonical_query,
                    query_id=active_query_id,
                    pmids=pmids,
                    total_available=total_available,
                    warnings=warnings,
                    failure=result.failure,
                )
            response = _require_response(result)

            try:
                page = parse_search_page(
                    response.body,
                    expected_retstart=retstart,
                    max_items=requested_retmax,
                )
            except InvalidPubMedXmlError:
                failure = _failure(
                    PubMedFailureKind.INVALID_XML,
                    "PubMed search response XML was malformed or unsafe.",
                )
                return self._failed_search(
                    context,
                    canonical_query,
                    active_query_id,
                    pmids,
                    total_available,
                    warnings,
                    failure,
                )
            except IncompletePubMedXmlError:
                failure = _failure(
                    PubMedFailureKind.INCOMPLETE_XML,
                    "PubMed search response XML was semantically incomplete.",
                )
                return self._failed_search(
                    context,
                    canonical_query,
                    active_query_id,
                    pmids,
                    total_available,
                    warnings,
                    failure,
                )

            if self._remaining_seconds(context) <= 0:
                return self._failed_search(
                    context,
                    canonical_query,
                    active_query_id,
                    pmids,
                    total_available,
                    warnings,
                    _failure(
                        PubMedFailureKind.TIMEOUT,
                        "PubMed total operation deadline expired while parsing a search page.",
                    ),
                )
            if page.retmax > requested_retmax:
                failure = _failure(
                    PubMedFailureKind.INTERNAL_CONTRACT,
                    "PubMed returned more search identifiers than requested.",
                )
                return self._failed_search(
                    context,
                    canonical_query,
                    active_query_id,
                    pmids,
                    total_available,
                    warnings,
                    failure,
                )
            if total_available is None:
                total_available = page.count
            elif page.count != total_available:
                failure = _failure(
                    PubMedFailureKind.INCOMPLETE_XML,
                    "PubMed search Count changed between pages.",
                )
                return self._failed_search(
                    context,
                    canonical_query,
                    active_query_id,
                    pmids,
                    total_available,
                    warnings,
                    failure,
                )

            context.pages_completed += 1
            for pmid in page.pmids:
                if pmid in seen_pmids:
                    warnings.add(WARNING_DUPLICATE_PMIDS)
                    continue
                if len(pmids) == self._config.max_records:
                    break
                seen_pmids.add(pmid)
                pmids.append(pmid)
            retstart += page.retmax

            if self._remaining_seconds(context) <= 0:
                return self._failed_search(
                    context,
                    canonical_query,
                    active_query_id,
                    pmids,
                    total_available,
                    warnings,
                    _failure(
                        PubMedFailureKind.TIMEOUT,
                        "PubMed total operation deadline expired while aggregating a search page.",
                    ),
                )
            if retstart >= page.count:
                state = (
                    PubMedResultState.EMPTY_SUCCESS
                    if not pmids
                    else PubMedResultState.COMPLETE_SUCCESS
                )
                return self._complete_search(
                    context,
                    canonical_query,
                    active_query_id,
                    pmids,
                    total_available,
                    warnings,
                    state,
                    truncated=False,
                )
            if len(pmids) >= self._config.max_records:
                warnings.add(WARNING_BOUNDED_TRUNCATION)
                return self._complete_search(
                    context,
                    canonical_query,
                    active_query_id,
                    pmids,
                    total_available,
                    warnings,
                    PubMedResultState.BOUNDED_TRUNCATION,
                    truncated=True,
                )

        warnings.add(WARNING_BOUNDED_TRUNCATION)
        return self._complete_search(
            context,
            canonical_query,
            active_query_id,
            pmids,
            total_available,
            warnings,
            PubMedResultState.BOUNDED_TRUNCATION,
            truncated=True,
        )

    def fetch(
        self,
        pmids: Sequence[str],
        *,
        query_id: str | None = None,
    ) -> PubMedFetchResult:
        """Fetch bounded PubMed records and map valid records into domain contracts."""

        requested, resolved_query_id, input_failure, duplicate_input = self._prepare_fetch_input(
            pmids,
            query_id,
        )
        if input_failure is not None:
            return PubMedFetchResult(
                state=PubMedResultState.FAILED,
                query_id=resolved_query_id,
                requested_pmids=requested,
                publications=(),
                not_retrieved_pmids=requested,
                malformed_records=(),
                record_issues=(),
                source_outcome=None,
                failure=input_failure,
                warning_codes=(),
                raw_responses=(),
                retry_events=(),
                request_count=0,
            )
        active_query_id = _require_query_id(resolved_query_id)

        context = _OperationContext(started_at=self._monotonic())
        warnings: set[str] = set()
        if duplicate_input:
            warnings.add(WARNING_DUPLICATE_PMIDS)
        prepared: list[_PreparedArticle] = []
        malformed_records: list[MalformedPubMedRecord] = []
        record_issues: list[PubMedRecordIssue] = []
        processed_pmids: set[str] = set()
        seen_provider_pmids: set[str] = set()
        conflicted_provider_pmids: set[str] = set()
        bounded_requested = requested[: self._config.max_records]
        not_retrieved = list(requested[len(bounded_requested) :])
        if not_retrieved:
            warnings.add(WARNING_BOUNDED_TRUNCATION)

        for batch_start in range(0, len(bounded_requested), self._config.page_size):
            if context.pages_completed >= self._config.max_pages:
                not_retrieved.extend(bounded_requested[batch_start:])
                warnings.add(WARNING_BOUNDED_TRUNCATION)
                break
            batch = bounded_requested[
                batch_start : min(batch_start + self._config.page_size, len(bounded_requested))
            ]
            result = self._get(
                context,
                path=PUBMED_EFETCH_PATH,
                params={
                    "db": "pubmed",
                    "id": ",".join(batch),
                    "retmode": "xml",
                    "rettype": "abstract",
                },
                page_number=context.pages_completed + 1,
            )
            if result.failure is not None:
                not_retrieved.extend(
                    pmid for pmid in bounded_requested[batch_start:] if pmid not in processed_pmids
                )
                return self._failed_fetch(
                    context=context,
                    query_id=active_query_id,
                    requested=requested,
                    prepared=prepared,
                    not_retrieved=not_retrieved,
                    malformed_records=malformed_records,
                    record_issues=record_issues,
                    warnings=warnings,
                    failure=result.failure,
                )
            response = _require_response(result)
            try:
                response_retrieved_at = self._require_utc_now()
            except (TypeError, ValueError):
                not_retrieved.extend(
                    pmid for pmid in bounded_requested[batch_start:] if pmid not in processed_pmids
                )
                return self._failed_fetch(
                    context,
                    active_query_id,
                    requested,
                    prepared,
                    not_retrieved,
                    malformed_records,
                    record_issues,
                    warnings,
                    _failure(
                        PubMedFailureKind.INTERNAL_CONTRACT,
                        "Injected UTC clock did not return an aware timestamp.",
                    ),
                )
            try:
                parsed = parse_fetch_response(
                    response.body,
                    expected_pmids=batch,
                    max_items=len(batch),
                )
            except InvalidPubMedXmlError:
                failure = _failure(
                    PubMedFailureKind.INVALID_XML,
                    "PubMed fetch response XML was malformed or unsafe.",
                )
                not_retrieved.extend(
                    pmid for pmid in bounded_requested[batch_start:] if pmid not in processed_pmids
                )
                return self._failed_fetch(
                    context,
                    active_query_id,
                    requested,
                    prepared,
                    not_retrieved,
                    malformed_records,
                    record_issues,
                    warnings,
                    failure,
                )
            except IncompletePubMedXmlError:
                failure = _failure(
                    PubMedFailureKind.INCOMPLETE_XML,
                    "PubMed fetch response XML was semantically incomplete.",
                )
                not_retrieved.extend(
                    pmid for pmid in bounded_requested[batch_start:] if pmid not in processed_pmids
                )
                return self._failed_fetch(
                    context,
                    active_query_id,
                    requested,
                    prepared,
                    not_retrieved,
                    malformed_records,
                    record_issues,
                    warnings,
                    failure,
                )

            if self._remaining_seconds(context) <= 0:
                not_retrieved.extend(
                    pmid for pmid in bounded_requested[batch_start:] if pmid not in processed_pmids
                )
                return self._failed_fetch(
                    context,
                    active_query_id,
                    requested,
                    prepared,
                    not_retrieved,
                    malformed_records,
                    record_issues,
                    warnings,
                    _failure(
                        PubMedFailureKind.TIMEOUT,
                        "PubMed total operation deadline expired while parsing a fetch page.",
                    ),
                )
            context.pages_completed += 1
            processed_pmids.update(batch)
            observed_pmids = _observed_fetch_pmids(parsed)
            repeated_pmids = {pmid for pmid in observed_pmids if pmid in seen_provider_pmids}
            new_conflicts = repeated_pmids.union(parsed.duplicate_pmids)
            if new_conflicts:
                conflicted_provider_pmids.update(new_conflicts)
                warnings.add(WARNING_DUPLICATE_PMIDS)
                conflicted_requested = [pmid for pmid in requested if pmid in new_conflicts]
                if conflicted_requested:
                    not_retrieved.extend(conflicted_requested)
                    warnings.add(WARNING_MISSING_RECORDS)
                prepared = [item for item in prepared if item.pmid not in new_conflicts]
            seen_provider_pmids.update(observed_pmids)
            self._collect_fetch_defects(
                parsed,
                malformed_records=malformed_records,
                not_retrieved=not_retrieved,
                warnings=warnings,
            )
            response_hash = sha256_digest(response.body)
            for article in parsed.records:
                if article.pmid in conflicted_provider_pmids:
                    continue
                item, issue = self._prepare_article(
                    article,
                    retrieved_at=response_retrieved_at,
                    response_content_hash=response_hash,
                )
                if issue is not None:
                    record_issues.append(issue)
                    not_retrieved.append(article.pmid)
                    warnings.add(issue.code)
                else:
                    prepared.append(_require_prepared(item))

            if self._remaining_seconds(context) <= 0:
                not_retrieved.extend(
                    pmid
                    for pmid in bounded_requested[batch_start + len(batch) :]
                    if pmid not in processed_pmids
                )
                return self._failed_fetch(
                    context,
                    active_query_id,
                    requested,
                    prepared,
                    not_retrieved,
                    malformed_records,
                    record_issues,
                    warnings,
                    _failure(
                        PubMedFailureKind.TIMEOUT,
                        "PubMed total operation deadline expired while mapping a fetch page.",
                    ),
                )

        canonical_not_retrieved = _stable_unique(not_retrieved)
        partial = bool(
            canonical_not_retrieved
            or malformed_records
            or record_issues
            or WARNING_UNEXPECTED_RECORDS in warnings
            or WARNING_BOUNDED_TRUNCATION in warnings
        )
        state = (
            PubMedResultState.BOUNDED_TRUNCATION
            if WARNING_BOUNDED_TRUNCATION in warnings
            else PubMedResultState.PARTIAL_SUCCESS
            if partial
            else PubMedResultState.COMPLETE_SUCCESS
        )
        outcome = self._source_outcome(
            query_id=active_query_id,
            execution_status=ExecutionStatus.SUCCEEDED,
            coverage_status=CoverageStatus.PARTIAL if partial else CoverageStatus.COMPLETE,
            result_status=ResultStatus.MATCHES if prepared else ResultStatus.INDETERMINATE,
            valid_result_count=len(prepared),
            pages_completed=context.pages_completed,
            truncated=state is PubMedResultState.BOUNDED_TRUNCATION,
            warning_codes=warnings,
            failure=None,
        )
        publications, build_issues = self._build_publications(
            prepared,
            outcome=outcome,
            failure=None,
        )
        if build_issues:
            record_issues.extend(build_issues)
            warnings.add(WARNING_RECORD_MAPPING)
            failed_pmids = {issue.pmid_hint for issue in build_issues if issue.pmid_hint}
            canonical_not_retrieved = _stable_unique((*canonical_not_retrieved, *failed_pmids))
            retained = [item for item in prepared if item.pmid not in failed_pmids]
            state = (
                PubMedResultState.BOUNDED_TRUNCATION
                if WARNING_BOUNDED_TRUNCATION in warnings
                else PubMedResultState.PARTIAL_SUCCESS
            )
            outcome = self._source_outcome(
                query_id=active_query_id,
                execution_status=ExecutionStatus.SUCCEEDED,
                coverage_status=CoverageStatus.PARTIAL,
                result_status=ResultStatus.MATCHES if retained else ResultStatus.INDETERMINATE,
                valid_result_count=len(retained),
                pages_completed=context.pages_completed,
                truncated=state is PubMedResultState.BOUNDED_TRUNCATION,
                warning_codes=warnings,
                failure=None,
            )
            publications, second_issues = self._build_publications(
                retained,
                outcome=outcome,
                failure=None,
            )
            if second_issues:
                raise RuntimeError("validated publication mapping was not deterministic")
            prepared = retained

        if self._remaining_seconds(context) <= 0:
            return self._failed_fetch(
                context,
                active_query_id,
                requested,
                prepared,
                list(canonical_not_retrieved),
                malformed_records,
                record_issues,
                warnings,
                _failure(
                    PubMedFailureKind.TIMEOUT,
                    "PubMed total operation deadline expired before fetch finalization.",
                ),
            )

        return PubMedFetchResult(
            state=state,
            query_id=active_query_id,
            requested_pmids=requested,
            publications=publications,
            not_retrieved_pmids=canonical_not_retrieved,
            malformed_records=tuple(malformed_records),
            record_issues=tuple(record_issues),
            source_outcome=outcome,
            failure=None,
            warning_codes=_sorted_warnings(warnings),
            raw_responses=tuple(context.raw_responses),
            retry_events=tuple(context.retry_events),
            request_count=context.request_count,
        )

    def _prepare_search_input(
        self,
        query: str,
        query_id: str | None,
    ) -> tuple[str, str | None, PubMedFailure | None]:
        if self._closed:
            return (
                "",
                None,
                _failure(
                    PubMedFailureKind.INTERNAL_CONTRACT,
                    "A closed PubMed connector cannot execute a request.",
                ),
            )
        if query_id is not None and (
            not isinstance(query_id, str)
            or len(query_id) > 128
            or _QUERY_ID_PATTERN.fullmatch(query_id) is None
        ):
            return (
                "",
                None,
                _failure(
                    PubMedFailureKind.INVALID_INPUT,
                    "query_id is not a stable bounded identifier.",
                ),
            )
        if not isinstance(query, str):
            return (
                "",
                None,
                _failure(PubMedFailureKind.INVALID_INPUT, "PubMed query must be text."),
            )
        if len(query) > self._config.max_query_characters:
            return (
                "",
                None,
                _failure(
                    PubMedFailureKind.INVALID_INPUT,
                    "PubMed query exceeds the configured character bound.",
                ),
            )
        try:
            query.encode("utf-8")
        except UnicodeEncodeError:
            return (
                "",
                None,
                _failure(
                    PubMedFailureKind.INVALID_INPUT,
                    "PubMed query must be valid UTF-8 text.",
                ),
            )
        canonical = query.strip()
        if not canonical:
            return (
                "",
                None,
                _failure(PubMedFailureKind.INVALID_INPUT, "PubMed query must not be blank."),
            )
        derived = query_id or derive_identity("pubmed-query", {"query": canonical})
        return canonical, derived, None

    def _prepare_fetch_input(
        self,
        pmids: Sequence[str],
        query_id: str | None,
    ) -> tuple[tuple[str, ...], str | None, PubMedFailure | None, bool]:
        if self._closed:
            return (
                (),
                None,
                _failure(
                    PubMedFailureKind.INTERNAL_CONTRACT,
                    "A closed PubMed connector cannot execute a request.",
                ),
                False,
            )
        if query_id is not None and (
            not isinstance(query_id, str)
            or len(query_id) > 128
            or _QUERY_ID_PATTERN.fullmatch(query_id) is None
        ):
            return (
                (),
                None,
                _failure(
                    PubMedFailureKind.INVALID_INPUT,
                    "query_id is not a stable bounded identifier.",
                ),
                False,
            )
        if isinstance(pmids, (str, bytes)) or not isinstance(pmids, Sequence):
            return (
                (),
                None,
                _failure(
                    PubMedFailureKind.INVALID_INPUT,
                    "PubMed fetch identifiers must be a sequence.",
                ),
                False,
            )
        try:
            declared_count = len(pmids)
        except (OverflowError, TypeError):
            declared_count = self._config.max_records + 1
        if declared_count < 1 or declared_count > self._config.max_records:
            return (
                (),
                None,
                _failure(
                    PubMedFailureKind.INVALID_INPUT,
                    "PubMed fetch identifier count exceeds the configured record bound.",
                ),
                False,
            )
        requested_values = tuple(islice(pmids, self._config.max_records + 1))
        if not requested_values or any(
            not isinstance(pmid, str) or _PMID_PATTERN.fullmatch(pmid) is None
            for pmid in requested_values
        ):
            return (
                (),
                None,
                _failure(
                    PubMedFailureKind.INVALID_INPUT,
                    "PubMed fetch requires one or more bounded valid PMIDs.",
                ),
                False,
            )
        if (
            len(requested_values) != declared_count
            or len(",".join(requested_values)) > _MAX_FETCH_ID_QUERY_CHARACTERS
        ):
            return (
                (),
                None,
                _failure(
                    PubMedFailureKind.INVALID_INPUT,
                    "PubMed fetch identifiers exceed the bounded request size.",
                ),
                False,
            )
        requested = _stable_unique(requested_values)
        duplicate_input = len(requested) != len(requested_values)
        derived = query_id or derive_identity("pubmed-fetch", {"pmids": requested})
        return requested, derived, None, duplicate_input

    def _get(
        self,
        context: _OperationContext,
        *,
        path: str,
        params: dict[str, str],
        page_number: int,
    ) -> _HttpResult:
        request_params = dict(params)
        request_params["tool"] = self._identity.tool
        if self._identity.email is not None:
            request_params["email"] = self._identity.email
        try:
            current_url = str(httpx.URL(f"{PUBMED_ORIGIN}{path}", params=request_params))
            current_url = validate_pubmed_url(current_url, path)
        except (httpx.InvalidURL, ValueError):
            return _HttpResult(
                failure=_failure(
                    PubMedFailureKind.INTERNAL_CONTRACT,
                    "Constructed PubMed request violated the fixed endpoint policy.",
                )
            )

        redirect_count = 0
        while True:
            attempt_result = self._send_with_retries(
                context,
                url=current_url,
                expected_path=path,
                page_number=page_number,
            )
            if attempt_result.failure is not None:
                return attempt_result
            response = _require_response(attempt_result)
            if response.status_code in _REDIRECT_STATUS_CODES:
                if redirect_count >= self._config.max_redirects:
                    return _HttpResult(
                        failure=_failure(
                            PubMedFailureKind.REDIRECT_REJECTED,
                            "PubMed redirect bound was exhausted.",
                            status_code=response.status_code,
                        )
                    )
                location = response.header("location")
                try:
                    current_url = resolve_pubmed_redirect(
                        response.final_url,
                        location or "",
                        path,
                    )
                except ValueError:
                    return _HttpResult(
                        failure=_failure(
                            PubMedFailureKind.REDIRECT_REJECTED,
                            "PubMed redirect violated the exact origin or path policy.",
                            status_code=response.status_code,
                        )
                    )
                redirect_count += 1
                continue
            if 200 <= response.status_code <= 299:
                return attempt_result
            if 400 <= response.status_code <= 499:
                return _HttpResult(
                    failure=_failure(
                        PubMedFailureKind.CLIENT_ERROR,
                        "PubMed rejected the request with a non-retryable client error.",
                        status_code=response.status_code,
                    )
                )
            if 500 <= response.status_code <= 599:
                return _HttpResult(
                    failure=_failure(
                        PubMedFailureKind.SERVER_ERROR,
                        "PubMed returned a non-retryable server error.",
                        status_code=response.status_code,
                    )
                )
            return _HttpResult(
                failure=_failure(
                    PubMedFailureKind.INTERNAL_CONTRACT,
                    "PubMed returned an unsupported HTTP response status.",
                    status_code=response.status_code,
                )
            )

    def _send_with_retries(
        self,
        context: _OperationContext,
        *,
        url: str,
        expected_path: str,
        page_number: int,
    ) -> _HttpResult:
        for attempt_number in range(1, self._config.max_attempts + 1):
            attempt_result = self._send_once(
                context,
                url=url,
                expected_path=expected_path,
                page_number=page_number,
                attempt_number=attempt_number,
            )
            if attempt_result.failure is not None:
                return attempt_result
            response = _require_response(attempt_result)
            if response.status_code not in RETRYABLE_STATUS_CODES:
                return attempt_result

            cause_kind = (
                PubMedFailureKind.RATE_LIMITED
                if response.status_code == 429
                else PubMedFailureKind.RETRYABLE_SERVER_ERROR
            )
            if attempt_number == self._config.max_attempts:
                return _HttpResult(
                    failure=_failure(
                        PubMedFailureKind.RETRY_EXHAUSTED,
                        "PubMed retry attempt budget was exhausted.",
                        status_code=response.status_code,
                        cause_kind=cause_kind,
                    )
                )

            try:
                retry_after = parse_retry_after(
                    response.header("retry-after"),
                    now=self._require_utc_now(),
                    cap_seconds=self._config.max_retry_after_seconds,
                )
                delay = (
                    retry_after
                    if retry_after is not None
                    else retry_delay_seconds(
                        attempt_number,
                        config=self._config,
                        jitter=self._jitter(),
                    )
                )
            except (TypeError, ValueError):
                return _HttpResult(
                    failure=_failure(
                        PubMedFailureKind.INTERNAL_CONTRACT,
                        "Injected retry jitter violated the configured bound.",
                    )
                )
            if delay > self._remaining_seconds(context):
                return _HttpResult(
                    failure=_failure(
                        PubMedFailureKind.RETRY_EXHAUSTED,
                        "PubMed retry delay would exceed the total deadline.",
                        status_code=response.status_code,
                        cause_kind=cause_kind,
                    )
                )
            context.retry_events.append(
                RetryEvent(
                    attempt_number=attempt_number,
                    delay_seconds=delay,
                    failure_kind=cause_kind,
                    status_code=response.status_code,
                    used_retry_after=retry_after is not None,
                )
            )
            self._sleep(delay)
            if self._remaining_seconds(context) <= 0:
                return _HttpResult(
                    failure=_failure(
                        PubMedFailureKind.RETRY_EXHAUSTED,
                        "PubMed total deadline expired during retry backoff.",
                        status_code=response.status_code,
                        cause_kind=cause_kind,
                    )
                )
        raise RuntimeError("bounded retry loop terminated without a result")

    def _send_once(
        self,
        context: _OperationContext,
        *,
        url: str,
        expected_path: str,
        page_number: int,
        attempt_number: int,
    ) -> _HttpResult:
        remaining = self._remaining_seconds(context)
        if remaining <= 0:
            return _HttpResult(
                failure=_failure(
                    PubMedFailureKind.TIMEOUT,
                    "PubMed total operation deadline expired before the request.",
                )
            )
        try:
            canonical_url = validate_pubmed_url(url, expected_path)
        except ValueError:
            return _HttpResult(
                failure=_failure(
                    PubMedFailureKind.REDIRECT_REJECTED,
                    "PubMed request URL violated the exact origin or path policy.",
                )
            )
        timeout = httpx.Timeout(
            connect=min(self._config.connect_timeout_seconds, remaining),
            read=min(self._config.read_timeout_seconds, remaining),
            write=min(self._config.write_timeout_seconds, remaining),
            pool=min(self._config.pool_timeout_seconds, remaining),
        )
        request = self._client.build_request("GET", canonical_url, timeout=timeout)
        try:
            validate_pubmed_url(str(request.url), expected_path)
        except ValueError:
            return _HttpResult(
                failure=_failure(
                    PubMedFailureKind.INTERNAL_CONTRACT,
                    "HTTPX request construction violated the fixed endpoint policy.",
                )
            )

        context.request_count += 1
        response: httpx.Response | None = None
        try:
            response = self._client.send(request, stream=True, follow_redirects=False)
            final_url = validate_pubmed_url(str(response.url), expected_path)
            body_read = self._read_bounded_body(response, context)
            operational_headers = tuple(
                sorted(
                    (name.casefold(), value)
                    for name, value in response.headers.multi_items()
                    if name.casefold() in _SAFE_RESPONSE_HEADERS
                )
            )
            evidence_headers = tuple(
                (name, value) for name, value in operational_headers if name != "location"
            )
            raw: RawPubMedResponse | None = None
            if body_read.body_complete or body_read.body:
                raw = RawPubMedResponse(
                    request_url=_redacted_evidence_url(str(request.url)),
                    final_url=_redacted_evidence_url(final_url),
                    status_code=response.status_code,
                    body=body_read.body,
                    observed_at_utc=self._require_utc_now(),
                    body_complete=body_read.body_complete,
                    termination_reason=body_read.termination_reason,
                    headers=evidence_headers,
                    page_number=page_number,
                    attempt_count=attempt_number,
                )
                context.raw_responses.append(raw)
            if not body_read.body_complete:
                failure_kind = body_read.failure_kind or PubMedFailureKind.TRANSPORT
                message = {
                    PubMedFailureKind.PAYLOAD_LIMIT: (
                        "PubMed cumulative response payload exceeded the configured bound."
                    ),
                    PubMedFailureKind.TIMEOUT: (
                        "PubMed total operation deadline expired while receiving a response."
                    ),
                }.get(
                    failure_kind,
                    "PubMed response streaming failed after a bounded prefix arrived.",
                )
                return _HttpResult(failure=_failure(failure_kind, message))
            if raw is None:
                raise RuntimeError("complete response did not produce raw response material")
            result = _HttpResponse(
                request_url=str(request.url),
                final_url=final_url,
                status_code=raw.status_code,
                body=raw.body,
                headers=operational_headers,
            )
            if self._remaining_seconds(context) <= 0:
                return _HttpResult(
                    failure=_failure(
                        PubMedFailureKind.TIMEOUT,
                        "PubMed total operation deadline expired while receiving a response.",
                    )
                )
            return _HttpResult(response=result)
        except httpx.TimeoutException:
            return _HttpResult(
                failure=_failure(
                    PubMedFailureKind.TIMEOUT,
                    "PubMed transport timed out within the configured request bound.",
                )
            )
        except httpx.TransportError:
            return _HttpResult(
                failure=_failure(
                    PubMedFailureKind.TRANSPORT,
                    "PubMed transport failed before a validated response completed.",
                )
            )
        except ValueError:
            return _HttpResult(
                failure=_failure(
                    PubMedFailureKind.REDIRECT_REJECTED,
                    "PubMed final response URL violated the exact origin or path policy.",
                )
            )
        finally:
            if response is not None:
                response.close()

    def _read_bounded_body(
        self,
        response: httpx.Response,
        context: _OperationContext,
    ) -> _BodyRead:
        remaining_bytes = (
            self._config.max_cumulative_payload_bytes - context.cumulative_payload_bytes
        )
        if response.is_stream_consumed:
            consumed_body = response.content
            if len(consumed_body) > remaining_bytes:
                prefix = consumed_body[:remaining_bytes]
                context.cumulative_payload_bytes += len(prefix)
                return _BodyRead(
                    prefix,
                    False,
                    "payload_limit",
                    PubMedFailureKind.PAYLOAD_LIMIT,
                )
            context.cumulative_payload_bytes += len(consumed_body)
            return _BodyRead(consumed_body, True, "complete_response")

        body = bytearray()
        try:
            for chunk in response.iter_raw(chunk_size=min(65_536, max(1, remaining_bytes))):
                available = remaining_bytes - len(body)
                if len(chunk) > available:
                    body.extend(chunk[:available])
                    context.cumulative_payload_bytes += len(body)
                    return _BodyRead(
                        bytes(body),
                        False,
                        "payload_limit",
                        PubMedFailureKind.PAYLOAD_LIMIT,
                    )
                body.extend(chunk)
                if self._remaining_seconds(context) <= 0:
                    context.cumulative_payload_bytes += len(body)
                    return _BodyRead(
                        bytes(body),
                        False,
                        "deadline_exceeded",
                        PubMedFailureKind.TIMEOUT,
                    )
        except httpx.TimeoutException:
            context.cumulative_payload_bytes += len(body)
            return _BodyRead(
                bytes(body),
                False,
                "deadline_exceeded",
                PubMedFailureKind.TIMEOUT,
            )
        except httpx.TransportError:
            context.cumulative_payload_bytes += len(body)
            return _BodyRead(
                bytes(body),
                False,
                "stream_error",
                PubMedFailureKind.TRANSPORT,
            )
        context.cumulative_payload_bytes += len(body)
        return _BodyRead(bytes(body), True, "complete_response")

    def _remaining_seconds(self, context: _OperationContext) -> float:
        elapsed = self._monotonic() - context.started_at
        return max(0.0, self._config.total_deadline_seconds - elapsed)

    def _require_utc_now(self) -> datetime:
        value = self._utc_now()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("utc_now must return a timezone-aware timestamp")
        return value.astimezone(UTC)

    def _execution_bounds(self) -> ExecutionBounds:
        return ExecutionBounds(
            max_query_characters=self._config.max_query_characters,
            max_pages=self._config.max_pages,
            max_records=self._config.max_records,
            max_payload_bytes=self._config.max_payload_bytes,
            max_total_seconds=self._config.total_deadline_seconds,
        )

    def _source_outcome(
        self,
        *,
        query_id: str,
        execution_status: ExecutionStatus,
        coverage_status: CoverageStatus,
        result_status: ResultStatus,
        valid_result_count: int,
        pages_completed: int,
        truncated: bool,
        warning_codes: set[str],
        failure: PubMedFailure | None,
    ) -> SourceOutcome:
        failure_id = (
            derive_identity(
                "failure",
                {
                    "source": SourceType.PUBMED,
                    "query_id": query_id,
                    "kind": failure.kind,
                    "cause_kind": failure.cause_kind,
                    "status_code": failure.status_code,
                    "pages_completed": pages_completed,
                },
            )
            if failure is not None
            else None
        )
        return SourceOutcome(
            source=SourceType.PUBMED,
            query_id=query_id,
            execution_status=execution_status,
            coverage_status=coverage_status,
            result_status=result_status,
            configured_bounds=self._execution_bounds(),
            valid_result_count=valid_result_count,
            pages_completed=pages_completed,
            truncated=truncated,
            warning_codes=_sorted_warnings(warning_codes),
            failure_id=failure_id,
        )

    def _complete_search(
        self,
        context: _OperationContext,
        query: str,
        query_id: str,
        pmids: list[str],
        total_available: int | None,
        warnings: set[str],
        state: PubMedResultState,
        *,
        truncated: bool,
    ) -> PubMedSearchResult:
        partial = state is PubMedResultState.BOUNDED_TRUNCATION
        result_status = (
            ResultStatus.MATCHES
            if pmids
            else ResultStatus.INDETERMINATE
            if partial
            else ResultStatus.NO_MATCH
        )
        outcome = self._source_outcome(
            query_id=query_id,
            execution_status=ExecutionStatus.SUCCEEDED,
            coverage_status=CoverageStatus.PARTIAL if partial else CoverageStatus.COMPLETE,
            result_status=result_status,
            valid_result_count=len(pmids),
            pages_completed=context.pages_completed,
            truncated=truncated,
            warning_codes=warnings,
            failure=None,
        )
        return PubMedSearchResult(
            state=state,
            query=query,
            query_id=query_id,
            pmids=tuple(pmids),
            total_available=total_available,
            source_outcome=outcome,
            failure=None,
            warning_codes=_sorted_warnings(warnings),
            raw_responses=tuple(context.raw_responses),
            retry_events=tuple(context.retry_events),
            request_count=context.request_count,
        )

    def _failed_search(
        self,
        context: _OperationContext,
        query: str,
        query_id: str,
        pmids: list[str],
        total_available: int | None,
        warnings: set[str],
        failure: PubMedFailure,
    ) -> PubMedSearchResult:
        partial = context.pages_completed > 0
        warnings.add(WARNING_PARTIAL_FAILURE if partial else WARNING_SOURCE_UNAVAILABLE)
        outcome = self._source_outcome(
            query_id=query_id,
            execution_status=ExecutionStatus.FAILED,
            coverage_status=CoverageStatus.PARTIAL if partial else CoverageStatus.UNAVAILABLE,
            result_status=ResultStatus.MATCHES if pmids else ResultStatus.INDETERMINATE,
            valid_result_count=len(pmids),
            pages_completed=context.pages_completed,
            truncated=False,
            warning_codes=warnings,
            failure=failure,
        )
        return PubMedSearchResult(
            state=PubMedResultState.PARTIAL_FAILURE if partial else PubMedResultState.FAILED,
            query=query,
            query_id=query_id,
            pmids=tuple(pmids),
            total_available=total_available,
            source_outcome=outcome,
            failure=failure,
            warning_codes=_sorted_warnings(warnings),
            raw_responses=tuple(context.raw_responses),
            retry_events=tuple(context.retry_events),
            request_count=context.request_count,
        )

    def _failed_fetch(
        self,
        context: _OperationContext,
        query_id: str,
        requested: tuple[str, ...],
        prepared: list[_PreparedArticle],
        not_retrieved: list[str],
        malformed_records: list[MalformedPubMedRecord],
        record_issues: list[PubMedRecordIssue],
        warnings: set[str],
        failure: PubMedFailure,
    ) -> PubMedFetchResult:
        partial = context.pages_completed > 0
        warnings.add(WARNING_PARTIAL_FAILURE if partial else WARNING_SOURCE_UNAVAILABLE)
        outcome = self._source_outcome(
            query_id=query_id,
            execution_status=ExecutionStatus.FAILED,
            coverage_status=CoverageStatus.PARTIAL if partial else CoverageStatus.UNAVAILABLE,
            result_status=ResultStatus.MATCHES if prepared else ResultStatus.INDETERMINATE,
            valid_result_count=len(prepared),
            pages_completed=context.pages_completed,
            truncated=False,
            warning_codes=warnings,
            failure=failure,
        )
        publications, build_issues = self._build_publications(
            prepared,
            outcome=outcome,
            failure=failure,
        )
        if build_issues:
            raise RuntimeError("prepared publication failed final failed-outcome mapping")
        return PubMedFetchResult(
            state=PubMedResultState.PARTIAL_FAILURE if partial else PubMedResultState.FAILED,
            query_id=query_id,
            requested_pmids=requested,
            publications=publications,
            not_retrieved_pmids=_stable_unique(not_retrieved),
            malformed_records=tuple(malformed_records),
            record_issues=tuple(record_issues),
            source_outcome=outcome,
            failure=failure,
            warning_codes=_sorted_warnings(warnings),
            raw_responses=tuple(context.raw_responses),
            retry_events=tuple(context.retry_events),
            request_count=context.request_count,
        )

    def _collect_fetch_defects(
        self,
        parsed: PubMedFetchResponse,
        *,
        malformed_records: list[MalformedPubMedRecord],
        not_retrieved: list[str],
        warnings: set[str],
    ) -> None:
        malformed_records.extend(parsed.malformed_records)
        not_retrieved.extend(parsed.missing_expected_pmids)
        if parsed.malformed_records:
            warnings.add(WARNING_MALFORMED_RECORDS)
        if parsed.duplicate_pmids:
            warnings.add(WARNING_DUPLICATE_PMIDS)
        if parsed.unexpected_pmids:
            warnings.add(WARNING_UNEXPECTED_RECORDS)
        if parsed.missing_expected_pmids:
            warnings.add(WARNING_MISSING_RECORDS)

    def _prepare_article(
        self,
        article: PubMedArticle,
        *,
        retrieved_at: datetime,
        response_content_hash: str,
    ) -> tuple[_PreparedArticle | None, PubMedRecordIssue | None]:
        if not any(language.casefold() in {"eng", "en"} for language in article.languages):
            return None, PubMedRecordIssue(
                pmid_hint=article.pmid,
                code=WARNING_UNSUPPORTED_LANGUAGE,
                message="Record did not declare English as an article language.",
            )
        parse_warnings: list[DomainWarning] = []
        doi = article.doi
        if doi is not None and re.fullmatch(r"10\.[0-9]{4,9}/\S+", doi) is None:
            doi = None
            parse_warnings.append(_domain_warning(WARNING_INVALID_DOI))
        pmcid = article.pmcid
        if pmcid is not None and re.fullmatch(r"PMC[1-9][0-9]*", pmcid) is None:
            pmcid = None
            parse_warnings.append(_domain_warning(WARNING_INVALID_PMCID))
        try:
            sections = tuple(
                AbstractSection(label=section.label, text=_canonical_text(section.text))
                for section in article.abstract_sections
            )
            publication_date, date_warning = _map_publication_date(article)
            if date_warning is not None:
                parse_warnings.append(_domain_warning(date_warning))
            publication_status = _map_publication_status(
                article.relationships,
                publication_types=article.publication_types,
                retrieved_at=retrieved_at,
            )
            indexing_status, indexing_warning = _map_indexing_status(article.medline_status)
            if indexing_warning is not None:
                parse_warnings.append(_domain_warning(indexing_warning))
            prepared = _PreparedArticle(
                pmid=article.pmid,
                doi=doi,
                pmcid=pmcid,
                title=_canonical_text(article.title),
                abstract_sections=sections,
                authors=tuple(_canonical_text(author.display_name) for author in article.authors),
                journal=_canonical_text(article.journal),
                publication_types=tuple(
                    _canonical_text(value) for value in article.publication_types
                ),
                publication_date=publication_date,
                publication_status=publication_status,
                indexing_status=indexing_status,
                parse_warnings=tuple(sorted(parse_warnings, key=lambda item: item.code)),
                response_content_hash=response_content_hash,
                retrieved_at=retrieved_at,
            )
        except ValueError:
            return None, PubMedRecordIssue(
                pmid_hint=article.pmid,
                code=WARNING_RECORD_MAPPING,
                message="Provider record could not satisfy the normalized publication contract.",
            )
        return prepared, None

    def _build_publications(
        self,
        prepared: Sequence[_PreparedArticle],
        *,
        outcome: SourceOutcome,
        failure: PubMedFailure | None,
    ) -> tuple[tuple[PublicationRecord, ...], tuple[PubMedRecordIssue, ...]]:
        source_failure = (
            SourceFailure(
                failure_id=outcome.failure_id,
                failure_code=_domain_failure_code(failure),
                retryable=failure.retryable,
            )
            if failure is not None and outcome.failure_id is not None
            else None
        )
        outcome_warnings = tuple(_domain_warning(code) for code in outcome.warning_codes)
        records: list[PublicationRecord] = []
        issues: list[PubMedRecordIssue] = []
        for item in prepared:
            provenance = Provenance(
                source=SourceType.PUBMED,
                source_record_id=item.pmid,
                query_id=outcome.query_id,
                source_lookup_key=f"pmid:{item.pmid}",
                retrieved_at=item.retrieved_at,
                connector_version=CONNECTOR_VERSION,
                content_hash=item.response_content_hash,
                warnings=outcome_warnings,
                failure=source_failure,
                source_outcome=outcome,
                configured_bounds=outcome.configured_bounds,
            )
            try:
                records.append(
                    PublicationRecord.create(
                        pmid=item.pmid,
                        doi=item.doi,
                        pmcid=item.pmcid,
                        title=item.title,
                        abstract_sections=item.abstract_sections,
                        authors=item.authors,
                        journal=item.journal,
                        publication_types=item.publication_types,
                        publication_date=item.publication_date,
                        publication_status=item.publication_status,
                        indexing_status=item.indexing_status,
                        provenance=provenance,
                        parse_warnings=item.parse_warnings,
                    )
                )
            except ValueError:
                issues.append(
                    PubMedRecordIssue(
                        pmid_hint=item.pmid,
                        code=WARNING_RECORD_MAPPING,
                        message="Validated provider record failed final publication construction.",
                    )
                )
        return tuple(records), tuple(issues)


def _map_publication_date(article: PubMedArticle) -> tuple[PartialDate | None, str | None]:
    source = article.publication_date
    if source is None:
        return None, None
    if source.year is None:
        return None, WARNING_UNSTRUCTURED_DATE
    year = int(source.year)
    if source.month is None:
        return PartialDate(year=year, precision=DatePrecision.YEAR), None
    month = _month_number(source.month)
    if month is None:
        return None, WARNING_UNSTRUCTURED_DATE
    if source.day is None:
        return PartialDate(year=year, month=month, precision=DatePrecision.MONTH), None
    if not source.day.isascii() or not source.day.isdigit():
        return None, WARNING_UNSTRUCTURED_DATE
    return (
        PartialDate(
            year=year,
            month=month,
            day=int(source.day),
            precision=DatePrecision.DAY,
        ),
        None,
    )


def _month_number(value: str) -> int | None:
    months = {
        "jan": 1,
        "january": 1,
        "feb": 2,
        "february": 2,
        "mar": 3,
        "march": 3,
        "apr": 4,
        "april": 4,
        "may": 5,
        "jun": 6,
        "june": 6,
        "jul": 7,
        "july": 7,
        "aug": 8,
        "august": 8,
        "sep": 9,
        "sept": 9,
        "september": 9,
        "oct": 10,
        "october": 10,
        "nov": 11,
        "november": 11,
        "dec": 12,
        "december": 12,
    }
    canonical = value.strip().casefold()
    if canonical in months:
        return months[canonical]
    if canonical.isascii() and canonical.isdigit() and 1 <= int(canonical) <= 12:
        return int(canonical)
    return None


def _map_indexing_status(status: str) -> tuple[IndexingStatus, str | None]:
    canonical = status.strip().casefold()
    if canonical == "medline":
        return IndexingStatus.INDEXED, None
    if canonical in {
        "in-data-review",
        "publisher",
        "pubmed-as-supplied",
        "pubmed-not-medline",
    }:
        return IndexingStatus.NOT_INDEXED, None
    return IndexingStatus.UNKNOWN, WARNING_UNKNOWN_INDEXING


def _map_publication_status(
    relationships: Sequence[PubMedRelationship],
    *,
    publication_types: Sequence[str],
    retrieved_at: datetime,
) -> PublicationStatus:
    publication_type_statuses = {
        signal
        for value in publication_types
        if (
            signal := {
                "corrected and republished article": PublicationStatusValue.CORRECTED,
                "expression of concern": PublicationStatusValue.EXPRESSION_OF_CONCERN,
                "published erratum": PublicationStatusValue.CORRECTED,
                "retracted publication": PublicationStatusValue.RETRACTED,
                "retraction of publication": PublicationStatusValue.RETRACTED,
            }.get(value.strip().casefold())
        )
        is not None
    }
    if not relationships:
        if publication_type_statuses:
            signal_text = next(
                value
                for value in publication_types
                if value.strip().casefold()
                in {
                    "corrected and republished article",
                    "expression of concern",
                    "published erratum",
                    "retracted publication",
                    "retraction of publication",
                }
            )
            return PublicationStatus.create(
                status=PublicationStatusValue.UNKNOWN_OR_UNVERIFIED,
                status_source="PubMed PublicationType",
                notice_type=None,
                relationship=PublicationRelationship(
                    relationship_type=PublicationRelationshipType.OTHER,
                    upstream_relationship_type=f"PublicationType:{signal_text}",
                    related_pmid=None,
                    resolution=RelationshipResolution.UNRESOLVED,
                    content_disposition=CorrectionContentDisposition.NOT_ESTABLISHED,
                ),
                retrieved_as_of=retrieved_at,
                additional_warning_codes=(WARNING_STATUS_SIGNAL_UNRESOLVED,),
            )
        return PublicationStatus.create(
            status=PublicationStatusValue.CURRENT_OR_NO_KNOWN_NOTICE,
            status_source="PubMed CommentsCorrections",
            notice_type=None,
            relationship=None,
            retrieved_as_of=retrieved_at,
        )

    mapping = {
        "correctionin": (
            PublicationStatusValue.CORRECTED,
            NoticeType.CORRECTION,
            PublicationRelationshipType.CORRECTED_BY,
        ),
        "erratumin": (
            PublicationStatusValue.CORRECTED,
            NoticeType.CORRECTION,
            PublicationRelationshipType.CORRECTED_BY,
        ),
        "erratumfor": (
            PublicationStatusValue.CORRECTED,
            NoticeType.CORRECTION,
            PublicationRelationshipType.CORRECTION_OF,
        ),
        "retractionin": (
            PublicationStatusValue.RETRACTED,
            NoticeType.RETRACTION,
            PublicationRelationshipType.RETRACTED_BY,
        ),
        "retractionof": (
            PublicationStatusValue.RETRACTED,
            NoticeType.RETRACTION,
            PublicationRelationshipType.RETRACTION_OF,
        ),
        "expressionofconcernin": (
            PublicationStatusValue.EXPRESSION_OF_CONCERN,
            NoticeType.EXPRESSION_OF_CONCERN,
            PublicationRelationshipType.HAS_EXPRESSION_OF_CONCERN,
        ),
        "expressionofconcernfor": (
            PublicationStatusValue.EXPRESSION_OF_CONCERN,
            NoticeType.EXPRESSION_OF_CONCERN,
            PublicationRelationshipType.EXPRESSION_OF_CONCERN_FOR,
        ),
    }
    first = relationships[0]
    recognized = mapping.get(first.reference_type.strip().casefold())
    signal_is_consistent = not publication_type_statuses or (
        recognized is not None and publication_type_statuses == {recognized[0]}
    )
    if (
        len(relationships) == 1
        and recognized is not None
        and first.related_pmid is not None
        and signal_is_consistent
    ):
        status, notice_type, relationship_type = recognized
        return PublicationStatus.create(
            status=status,
            status_source="PubMed CommentsCorrections",
            notice_type=notice_type,
            relationship=PublicationRelationship(
                relationship_type=relationship_type,
                upstream_relationship_type=first.reference_type,
                related_pmid=first.related_pmid,
                resolution=RelationshipResolution.RESOLVED,
                content_disposition=CorrectionContentDisposition.STATUS_CONTEXT_ONLY,
            ),
            retrieved_as_of=retrieved_at,
        )

    relationship_type = (
        recognized[2] if recognized is not None else PublicationRelationshipType.OTHER
    )
    resolution = (
        RelationshipResolution.CONFLICTING
        if len(relationships) > 1 or not signal_is_consistent
        else RelationshipResolution.UNRESOLVED
    )
    return PublicationStatus.create(
        status=PublicationStatusValue.UNKNOWN_OR_UNVERIFIED,
        status_source=(
            "PubMed CommentsCorrections and PublicationType"
            if publication_type_statuses
            else "PubMed CommentsCorrections"
        ),
        notice_type=None,
        relationship=PublicationRelationship(
            relationship_type=relationship_type,
            upstream_relationship_type=first.reference_type,
            related_pmid=first.related_pmid,
            resolution=resolution,
            content_disposition=CorrectionContentDisposition.NOT_ESTABLISHED,
        ),
        retrieved_as_of=retrieved_at,
        additional_warning_codes=(
            (WARNING_STATUS_SIGNAL_UNRESOLVED,) if publication_type_statuses else ()
        ),
    )


def _domain_failure_code(failure: PubMedFailure | None) -> FailureCode:
    if failure is None:
        return FailureCode.UNKNOWN
    effective = failure.cause_kind or failure.kind
    return {
        PubMedFailureKind.INVALID_INPUT: FailureCode.INVALID_INPUT,
        PubMedFailureKind.RATE_LIMITED: FailureCode.RATE_LIMITED,
        PubMedFailureKind.CLIENT_ERROR: FailureCode.INVALID_INPUT,
        PubMedFailureKind.RETRYABLE_SERVER_ERROR: FailureCode.UPSTREAM_UNAVAILABLE,
        PubMedFailureKind.RETRY_EXHAUSTED: FailureCode.UPSTREAM_UNAVAILABLE,
        PubMedFailureKind.SERVER_ERROR: FailureCode.UPSTREAM_UNAVAILABLE,
        PubMedFailureKind.TIMEOUT: FailureCode.TIMEOUT,
        PubMedFailureKind.TRANSPORT: FailureCode.UPSTREAM_UNAVAILABLE,
        PubMedFailureKind.INVALID_XML: FailureCode.MALFORMED_RESPONSE,
        PubMedFailureKind.INCOMPLETE_XML: FailureCode.MALFORMED_RESPONSE,
        PubMedFailureKind.PAYLOAD_LIMIT: FailureCode.INTEGRITY_FAILURE,
        PubMedFailureKind.REDIRECT_REJECTED: FailureCode.INTEGRITY_FAILURE,
        PubMedFailureKind.INTERNAL_CONTRACT: FailureCode.INTEGRITY_FAILURE,
    }[effective]


def _domain_warning(code: str) -> DomainWarning:
    return DomainWarning(code=code, message=_WARNING_MESSAGES[code])


def _canonical_text(value: str) -> str:
    return value.replace("\r\n", "\n").replace("\r", "\n")


def _stable_unique(values: Sequence[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))


def _observed_fetch_pmids(parsed: PubMedFetchResponse) -> tuple[str, ...]:
    """Return bounded canonical provider identifiers observed in one fetch page."""

    values = [article.pmid for article in parsed.records]
    values.extend(parsed.unexpected_pmids)
    values.extend(parsed.duplicate_pmids)
    values.extend(
        record.pmid_hint
        for record in parsed.malformed_records
        if record.pmid_hint is not None and _PMID_PATTERN.fullmatch(record.pmid_hint) is not None
    )
    return _stable_unique(values)


def _redacted_evidence_url(url: str) -> str:
    """Remove personal client identification from returned request metadata."""

    parsed = httpx.URL(url)
    retained_params = [
        (name, value) for name, value in parsed.params.multi_items() if name.casefold() != "email"
    ]
    return str(parsed.copy_with(params=httpx.QueryParams(tuple(retained_params))))


def _sorted_warnings(warnings: set[str]) -> tuple[str, ...]:
    return tuple(sorted(warnings))


def _failure(
    kind: PubMedFailureKind,
    message: str,
    *,
    retryable: bool = False,
    status_code: int | None = None,
    cause_kind: PubMedFailureKind | None = None,
) -> PubMedFailure:
    return PubMedFailure(
        kind=kind,
        message=message,
        retryable=retryable,
        status_code=status_code,
        cause_kind=cause_kind,
    )


def _require_response(result: _HttpResult) -> _HttpResponse:
    if result.response is None:
        raise RuntimeError("HTTP success path did not contain a response")
    return result.response


def _require_prepared(value: _PreparedArticle | None) -> _PreparedArticle:
    if value is None:
        raise RuntimeError("record preparation succeeded without a record")
    return value


def _require_query_id(value: str | None) -> str:
    if value is None:
        raise RuntimeError("validated PubMed input did not produce a query identity")
    return value


__all__ = [
    "CONNECTOR_VERSION",
    "PubMedClientIdentity",
    "PubMedConnector",
    "PubMedFetchResult",
    "PubMedRecordIssue",
    "PubMedSearchResult",
]
