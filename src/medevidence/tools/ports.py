"""Consumer-owned injected ports for PubMed tools and run persistence."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, Protocol, Self

from pydantic import AfterValidator, Field, StringConstraints, model_validator

from medevidence.domain import (
    AcquisitionRegistrationEnvelopeId,
    ArtifactId,
    DailyMedCandidateLabel,
    ExecutionStatus,
    LabelSelectionDecision,
    Pmid,
    PublicationRecord,
    PublicationVersionId,
    QueryId,
    ResearchReport,
    RunIntentId,
    Sha256Digest,
    SourceOutcome,
    UtcDateTime,
    WarningCode,
    sha256_digest,
)
from medevidence.domain.identifiers import AcquisitionIntentId, DurableModel

from .contracts import (
    AcquisitionIntentInput,
    DailyMedDiscoveryRequest,
    DailyMedDiscoveryResponse,
    DailyMedFetchRequest,
    DailyMedFetchResponse,
    ResolvedConceptCatalog,
    RunIntentInput,
    SearchPubMedResponse,
)

MAX_RESPONSE_BYTES = 5_242_880
MAX_RESEARCH_REPORT_BYTES = 2_097_152
SAFE_EVIDENCE_HEADERS = frozenset(
    {
        "content-encoding",
        "content-length",
        "content-type",
        "retry-after",
        "x-ratelimit-limit",
        "x-ratelimit-remaining",
    }
)
type HeaderValue = Annotated[str, StringConstraints(min_length=1, max_length=512)]


def _validate_redacted_detail(value: str) -> str:
    if value != value.strip() or not value.strip():
        raise ValueError("redacted detail must be trimmed and nonblank")
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise ValueError("redacted detail must be a control-free single line")
    folded = value.casefold()
    credential_markers = (
        "access-token",
        "access_token",
        "api-key",
        "api_key",
        "authorization",
        "bearer",
        "cookie",
        "password",
        "passwd",
        "proxy-authorization",
        "refresh-token",
        "refresh_token",
        "secret",
        "session=",
        "set-cookie",
    )
    if any(marker in folded for marker in credential_markers):
        raise ValueError("redacted detail contains credential-like material")
    return value


type RedactedDetail = Annotated[
    str,
    StringConstraints(min_length=1, max_length=512),
    AfterValidator(_validate_redacted_detail),
]
type AcquisitionFailureCode = Literal[
    "invalid_input",
    "rate_limited",
    "client_error",
    "retryable_server_error",
    "retry_exhausted",
    "server_error",
    "timeout",
    "transport",
    "invalid_xml",
    "incomplete_xml",
    "payload_limit",
    "redirect_rejected",
    "internal_contract",
]


class ResponseObservation(DurableModel):
    """Exact transport-neutral response material mapped by composition."""

    body: Annotated[bytes, Field(max_length=MAX_RESPONSE_BYTES)]
    observed_at_utc: UtcDateTime
    headers: tuple[tuple[str, HeaderValue], ...] = Field(max_length=6)
    http_status: int = Field(ge=100, le=599)
    body_complete: bool
    termination_reason: Literal[
        "complete_response",
        "payload_limit",
        "stream_error",
        "deadline_exceeded",
    ]

    @model_validator(mode="after")
    def validate_observation(self) -> Self:
        if not self.body_complete and not self.body:
            raise ValueError("an incomplete observation requires a retained nonempty prefix")
        if self.body_complete != (self.termination_reason == "complete_response"):
            raise ValueError("body_complete must match termination_reason")
        names = tuple(name for name, _ in self.headers)
        if names != tuple(sorted(names)) or len(names) != len(set(names)):
            raise ValueError("evidence headers must be sorted and unique")
        if not set(names).issubset(SAFE_EVIDENCE_HEADERS):
            raise ValueError("response contains a forbidden evidence header")
        for name, value in self.headers:
            if name != name.casefold() or name != name.strip():
                raise ValueError("evidence header names must be canonical lowercase")
            if value != value.strip() or any(
                ord(character) < 32 or ord(character) == 127 for character in value
            ):
                raise ValueError("evidence header values must be trimmed and control-free")
        return self


class PubMedSearchExecution(DurableModel):
    """One connector execution plus exact source material for persistence."""

    response: SearchPubMedResponse
    started_at_utc: UtcDateTime
    completed_at_utc: UtcDateTime
    attempts_used: int = Field(ge=1, le=2)
    observations: tuple[ResponseObservation, ...] = Field(max_length=4)
    failure_code: AcquisitionFailureCode | None = None
    redacted_detail: RedactedDetail | None = None

    @model_validator(mode="after")
    def validate_execution(self) -> Self:
        _validate_execution_contract(
            started_at_utc=self.started_at_utc,
            completed_at_utc=self.completed_at_utc,
            observations=self.observations,
            outcome=self.response.source_outcome,
            failure_code=self.failure_code,
            redacted_detail=self.redacted_detail,
        )
        return self


class PubMedFetchExecution(DurableModel):
    """One singular connector fetch plus exact source material."""

    requested_pmid: Pmid
    query_id: QueryId
    publication: PublicationRecord | None
    source_outcome: SourceOutcome
    started_at_utc: UtcDateTime
    completed_at_utc: UtcDateTime
    attempts_used: int = Field(ge=1, le=2)
    observations: tuple[ResponseObservation, ...] = Field(max_length=4)
    failure_code: AcquisitionFailureCode | None = None
    redacted_detail: RedactedDetail | None = None

    @model_validator(mode="after")
    def validate_execution(self) -> Self:
        _validate_execution_contract(
            started_at_utc=self.started_at_utc,
            completed_at_utc=self.completed_at_utc,
            observations=self.observations,
            outcome=self.source_outcome,
            failure_code=self.failure_code,
            redacted_detail=self.redacted_detail,
        )
        if self.query_id != self.source_outcome.query_id:
            raise ValueError("fetch execution query identity must match its outcome")
        expected_count = 1 if self.publication is not None else 0
        if self.source_outcome.valid_result_count != expected_count:
            raise ValueError("fetch execution count must match its publication")
        if self.publication is not None and (
            self.publication.pmid != self.requested_pmid
            or self.publication.provenance.query_id != self.query_id
            or self.publication.provenance.source_outcome != self.source_outcome
        ):
            raise ValueError("fetch publication provenance must match the execution")
        return self


class PersistedPublicationLineageEdge(DurableModel):
    """Exact persisted publication-to-manifest lineage for one fetch."""

    schema_version: Literal["1.0"] = "1.0"
    parent_artifact_id: ArtifactId
    child_artifact_id: ArtifactId
    lineage_type: Literal["publication_to_manifest"] = "publication_to_manifest"
    lineage_ordinal: Literal[0] = 0

    @model_validator(mode="after")
    def validate_endpoints(self) -> Self:
        if self.parent_artifact_id == self.child_artifact_id:
            raise ValueError("publication lineage endpoints must be distinct")
        return self


class PersistedPublicationBinding(DurableModel):
    """Exact persisted source evidence for one singular publication version."""

    pmid: Pmid
    publication_version_id: PublicationVersionId
    publication_artifact_id: Sha256Digest
    snapshot_id: Sha256Digest
    manifest_id: Sha256Digest
    artifact_ids: tuple[ArtifactId, ...] = Field(min_length=2, max_length=8)
    lineage_edges: tuple[PersistedPublicationLineageEdge, ...] = Field(
        min_length=1,
        max_length=1,
    )

    @model_validator(mode="after")
    def validate_binding(self) -> Self:
        if not self.publication_version_id.startswith(f"pubmed:{self.pmid}:sha256:"):
            raise ValueError("publication binding PMID must match its version identity")
        expected_artifact_id = (
            "sha256:"
            + self.publication_version_id.rsplit(
                ":sha256:",
                maxsplit=1,
            )[1]
        )
        if self.publication_artifact_id != expected_artifact_id:
            raise ValueError("publication artifact must match its version content identity")
        if self.snapshot_id != self.manifest_id:
            raise ValueError("publication binding snapshot must equal manifest identity")
        if self.artifact_ids != tuple(sorted(set(self.artifact_ids))):
            raise ValueError("publication artifact identities must be sorted and unique")
        if not {self.publication_artifact_id, self.manifest_id}.issubset(self.artifact_ids):
            raise ValueError("publication artifacts must include publication and manifest")
        edge = self.lineage_edges[0]
        if (
            edge.parent_artifact_id != self.publication_artifact_id
            or edge.child_artifact_id != self.manifest_id
        ):
            raise ValueError("publication lineage must bind exact publication and manifest")
        return self


class PersistedAcquisition(DurableModel):
    """Exact immutable identities returned after full acquisition persistence."""

    acquisition_intent_id: AcquisitionIntentId
    snapshot_id: Sha256Digest
    manifest_id: Sha256Digest
    registration_envelope_id: AcquisitionRegistrationEnvelopeId
    publication_bindings: tuple[PersistedPublicationBinding, ...] = Field(
        default=(),
        max_length=1,
    )

    @model_validator(mode="after")
    def validate_bindings(self) -> Self:
        if self.snapshot_id != self.manifest_id:
            raise ValueError("persisted snapshot identity must equal manifest identity")
        for binding in self.publication_bindings:
            if binding.snapshot_id != self.snapshot_id or binding.manifest_id != self.manifest_id:
                raise ValueError("publication binding must belong to its acquisition")
        return self


class RunFinalization(DurableModel):
    """Consumer-owned input for final report artifact/run/envelope persistence."""

    run_intent_id: RunIntentId
    report: ResearchReport
    report_artifact_bytes: Annotated[bytes, Field(max_length=MAX_RESEARCH_REPORT_BYTES)]
    started_at_utc: UtcDateTime
    completed_at_utc: UtcDateTime
    warning_codes: tuple[WarningCode, ...] = Field(max_length=128)

    @model_validator(mode="after")
    def validate_finalization(self) -> Self:
        if self.completed_at_utc < self.started_at_utc:
            raise ValueError("run finalization completion precedes start")
        if self.run_intent_id != self.report.run_intent_id:
            raise ValueError("finalization run intent must match the report")
        if self.report_artifact_bytes != self.report.artifact_bytes() or (
            sha256_digest(self.report_artifact_bytes) != self.report.report_artifact_id
        ):
            raise ValueError("finalization artifact bytes must match the report hash")
        expected_warnings = tuple(
            sorted(
                {code for outcome in self.report.source_outcomes for code in outcome.warning_codes}
            )
        )
        if self.warning_codes != expected_warnings:
            raise ValueError("finalization warnings must match report source outcomes")
        return self


def _validate_execution_contract(
    *,
    started_at_utc: datetime,
    completed_at_utc: datetime,
    observations: tuple[ResponseObservation, ...],
    outcome: SourceOutcome,
    failure_code: AcquisitionFailureCode | None,
    redacted_detail: str | None,
) -> None:
    if completed_at_utc < started_at_utc:
        raise ValueError("execution completion precedes start")
    observation_times = tuple(item.observed_at_utc for item in observations)
    if observation_times != tuple(sorted(observation_times)):
        raise ValueError("response observations must be chronologically ordered")
    if any(
        observed < started_at_utc or observed > completed_at_utc for observed in observation_times
    ):
        raise ValueError("response observation falls outside execution time bounds")
    if sum(len(item.body) for item in observations) > MAX_RESPONSE_BYTES:
        raise ValueError("acquisition response bodies exceed 5,242,880 bytes")
    failed = outcome.execution_status is ExecutionStatus.FAILED
    if failed != (failure_code is not None and redacted_detail is not None):
        raise ValueError(
            "failure_code and redacted_detail are required exactly for failed execution"
        )
    if not observations and not (failed and outcome.coverage_status.value == "unavailable"):
        raise ValueError("zero observations are permitted only for failed unavailable execution")
    if outcome.coverage_status.value == "complete":
        effective = observations[-1]
        if (
            not effective.body_complete
            or not effective.body
            or not 200 <= effective.http_status <= 299
        ):
            raise ValueError(
                "complete coverage requires a final nonempty complete HTTP 2xx observation"
            )
    if outcome.result_status.value == "matches" and not any(
        item.body and 200 <= item.http_status <= 299 for item in observations
    ):
        raise ValueError("matches requires retained nonempty HTTP 2xx evidence")


class ConceptCatalogPort(Protocol):
    """Resolve caller concepts against one exact immutable catalog."""

    def resolve(self, scope_id: str) -> ResolvedConceptCatalog:
        """Return exact terms and catalog identity for the scope."""


class PubMedExecutionPort(Protocol):
    """Execute bounded operations without exposing provider or transport objects."""

    def search(self, *, query: str, query_id: str) -> PubMedSearchExecution:
        """Execute one constrained ESearch acquisition."""

    def fetch(self, *, pmid: str, query_id: str) -> PubMedFetchExecution:
        """Execute one constrained singular EFetch acquisition."""


class DailyMedExecutionPort(Protocol):
    """Execute frozen DailyMed operations behind a source-neutral boundary."""

    def discover(
        self, request: DailyMedDiscoveryRequest
    ) -> tuple[
        DailyMedDiscoveryResponse,
        tuple[DailyMedCandidateLabel, ...],
        LabelSelectionDecision | None,
    ]:
        """Execute, snapshot, and register one bounded discovery."""

    def fetch(self, request: DailyMedFetchRequest) -> DailyMedFetchResponse:
        """Execute, snapshot, and register one exact selected-label fetch."""


class AcquisitionPersistencePort(Protocol):
    """Capture and atomically register each completed acquisition."""

    def persist_search(
        self,
        *,
        intent: AcquisitionIntentInput,
        execution: PubMedSearchExecution,
    ) -> PersistedAcquisition:
        """Persist exact search bytes, manifest, journal, and metadata."""

    def persist_fetch(
        self,
        *,
        intent: AcquisitionIntentInput,
        execution: PubMedFetchExecution,
    ) -> PersistedAcquisition:
        """Persist exact fetch bytes, manifest, journal, and metadata."""


class RunPersistencePort(Protocol):
    """Persist run intent first and report/run/envelope in the final action."""

    def persist_run_intent(self, intent: RunIntentInput) -> RunIntentId:
        """Persist the mapped immutable run intent and return its exact identity."""

    def persist_run_and_report(
        self,
        *,
        finalization: RunFinalization,
        acquisitions: tuple[PersistedAcquisition, ...],
    ) -> None:
        """Persist report artifact, final run metadata, and run envelope last."""


class RuntimePort(Protocol):
    """Inject runtime UUID4 attempt identities and UTC timestamps."""

    def new_attempt_id(self) -> str:
        """Return one `attempt:<uuid4>` identity."""

    def utc_now(self) -> datetime:
        """Return one timezone-aware UTC timestamp."""
