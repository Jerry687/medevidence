"""Frozen M1A journal identities and closed ingestion contracts."""

from __future__ import annotations

import json
from datetime import date
from typing import Annotated, Any, ClassVar, Literal, Self

from pydantic import Field, StringConstraints, model_validator

from medevidence.domain.identifiers import (
    AcquisitionIntentId,
    AcquisitionRegistrationEnvelopeId,
    AdverseEventConceptId,
    ArtifactLinkId,
    AttemptId,
    DrugConceptId,
    DurableModel,
    ReportId,
    RequestId,
    RunId,
    RunIntentId,
    RunRegistrationEnvelopeId,
    ScopeId,
    Sha256Digest,
    UtcDateTime,
    WarningCode,
    derive_m1a_journal_identity,
    m1a_canonical_json_bytes,
    parse_m1a_json_bytes,
)
from medevidence.domain.sources import CoverageStatus, ExecutionStatus, ResultStatus

M1A_CANONICAL_JSON_V1 = "M1A_CANONICAL_JSON_V1"
M1A_CONSTRAINED_V1 = "M1A_CONSTRAINED_V1"

type CodeRevision = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{40}$")]
type MediaType = Annotated[str, StringConstraints(min_length=1, max_length=128)]
type RedactedDetail = Annotated[str, StringConstraints(min_length=1, max_length=512)]


class JournalModel(DurableModel):
    """Base for identity-bearing records under M1A_CANONICAL_JSON_V1."""

    identity_namespace: ClassVar[str]
    identity_prefix: ClassVar[str]
    identity_field: ClassVar[str]

    @classmethod
    def from_json_bytes(cls, raw: bytes) -> Self:
        """Validate strict JSON and require exact complete canonical bytes."""

        parsed = parse_m1a_json_bytes(raw)
        record = cls.model_validate_json(
            json.dumps(parsed, ensure_ascii=False, separators=(",", ":"))
        )
        if record.canonical_bytes() != raw:
            raise ValueError("journal bytes are not canonical M1A JSON")
        return record

    def canonical_bytes(self) -> bytes:
        """Return the complete persisted record with exactly one terminal LF."""

        return m1a_canonical_json_bytes(self)

    def expected_identity(self) -> str:
        """Compute the record's self-field-excluded logical identity."""

        return derive_m1a_journal_identity(
            namespace=self.identity_namespace,
            prefix=self.identity_prefix,
            self_field=self.identity_field,
            value=self,
        )


class RunExecutionLimits(DurableModel):
    """Exact run-wide M1A_CONSTRAINED_V1 limits."""

    page_size: Literal[100] = 100
    max_pages: Literal[1] = 1
    max_attempts: Literal[2] = 2
    max_redirects: Literal[1] = 1
    max_publications: Literal[100] = 100
    max_acquisitions: Literal[101] = 101
    max_raw_responses_per_acquisition: Literal[4] = 4
    max_raw_responses_per_run: Literal[404] = 404
    max_query_characters: Literal[512] = 512
    max_payload_bytes_per_response: Literal[5_242_880] = 5_242_880
    max_cumulative_payload_bytes_per_acquisition: Literal[5_242_880] = 5_242_880
    total_deadline_ms_per_acquisition: Literal[30_000] = 30_000


class AcquisitionExecutionLimits(DurableModel):
    """Exact limits for one search or singular fetch acquisition."""

    base_backoff_ms: Literal[250] = 250
    cache_policy: Literal["none"] = "none"
    connect_timeout_ms: Literal[5_000] = 5_000
    jitter_ms: Literal[100] = 100
    max_attempts: Literal[2] = 2
    max_backoff_ms: Literal[4_000] = 4_000
    max_payload_bytes: Literal[5_242_880] = 5_242_880
    max_redirects: Literal[1] = 1
    max_retry_after_ms: Literal[10_000] = 10_000
    pool_timeout_ms: Literal[5_000] = 5_000
    read_timeout_ms: Literal[10_000] = 10_000
    total_deadline_ms: Literal[30_000] = 30_000
    write_timeout_ms: Literal[5_000] = 5_000


class PubMedSearchRequest(DurableModel):
    """Closed exact ESearch request representation."""

    db: Literal["pubmed"] = "pubmed"
    path: Literal["/entrez/eutils/esearch.fcgi"] = "/entrez/eutils/esearch.fcgi"
    retmax: Literal[100] = 100
    retmode: Literal["xml"] = "xml"
    retstart: Literal[0] = 0
    term: Annotated[str, StringConstraints(min_length=1, max_length=512)]


class PubMedFetchRequest(DurableModel):
    """Closed exact singular EFetch request representation."""

    db: Literal["pubmed"] = "pubmed"
    id: Annotated[str, StringConstraints(pattern=r"^[1-9][0-9]{0,15}$")]
    path: Literal["/entrez/eutils/efetch.fcgi"] = "/entrez/eutils/efetch.fcgi"
    retmode: Literal["xml"] = "xml"
    rettype: Literal["abstract"] = "abstract"


class RunIntent(JournalModel):
    """Immutable complete run intent."""

    identity_namespace = "medevidence:m1a:run-intent:v1"
    identity_prefix = "run-intent:sha256:"
    identity_field = "run_intent_id"

    schema_version: Literal["1.0"] = "1.0"
    run_intent_id: RunIntentId
    run_id: RunId
    request_id: RequestId
    created_at_utc: UtcDateTime
    code_revision: CodeRevision
    scope_id: ScopeId
    execution_profile_id: Literal["M1A_CONSTRAINED_V1"] = "M1A_CONSTRAINED_V1"
    catalog_version: Literal["m1a-concepts-v1"] = "m1a-concepts-v1"
    source: Literal["pubmed"] = "pubmed"
    drug_concept_ids: tuple[DrugConceptId, ...] = Field(min_length=1, max_length=4)
    adverse_event_concept_ids: tuple[AdverseEventConceptId, ...] = Field(
        min_length=1,
        max_length=4,
    )
    start_date: date | None = None
    end_date: date | None = None
    pubmed_query: Annotated[str, StringConstraints(min_length=1, max_length=512)]
    execution_limits: RunExecutionLimits

    @model_validator(mode="after")
    def validate_contract(self) -> Self:
        for values in (self.drug_concept_ids, self.adverse_event_concept_ids):
            if values != tuple(sorted(values)) or len(set(values)) != len(values):
                raise ValueError("concept IDs must be sorted and unique")
        if (self.start_date is None) != (self.end_date is None):
            raise ValueError("start_date and end_date must be both present or both absent")
        if (
            self.start_date is not None
            and self.end_date is not None
            and self.start_date > self.end_date
        ):
            raise ValueError("start_date must not exceed end_date")
        if self.run_intent_id != self.expected_identity():
            raise ValueError("run_intent_id does not match content")
        return self


class AcquisitionIntent(JournalModel):
    """Immutable complete acquisition intent."""

    identity_namespace = "medevidence:m1a:acquisition-intent:v1"
    identity_prefix = "acquisition-intent:sha256:"
    identity_field = "acquisition_intent_id"

    schema_version: Literal["1.0"] = "1.0"
    acquisition_intent_id: AcquisitionIntentId
    attempt_id: AttemptId
    run_id: RunId
    run_intent_id: RunIntentId
    created_at_utc: UtcDateTime
    execution_profile_id: Literal["M1A_CONSTRAINED_V1"] = "M1A_CONSTRAINED_V1"
    source: Literal["pubmed"] = "pubmed"
    operation: Literal["search", "fetch"]
    acquisition_ordinal: int = Field(ge=0, le=100)
    request: PubMedSearchRequest | PubMedFetchRequest
    execution_limits: AcquisitionExecutionLimits

    @model_validator(mode="after")
    def validate_contract(self) -> Self:
        expected_request = PubMedSearchRequest if self.operation == "search" else PubMedFetchRequest
        if not isinstance(self.request, expected_request):
            raise ValueError("request shape must match operation")
        if self.operation == "search" and self.acquisition_ordinal != 0:
            raise ValueError("search acquisition ordinal must be zero")
        if self.operation == "fetch" and not 1 <= self.acquisition_ordinal <= 100:
            raise ValueError("fetch acquisition ordinal must be between 1 and 100")
        if self.acquisition_intent_id != self.expected_identity():
            raise ValueError("acquisition_intent_id does not match content")
        return self


class ArtifactLink(JournalModel):
    """Identity-bearing observation of one exact raw PubMed body."""

    identity_namespace = "medevidence:m1a:artifact-link:v1"
    identity_prefix = "artifact-link:sha256:"
    identity_field = "link_id"

    schema_version: Literal["1.0"] = "1.0"
    link_id: ArtifactLinkId
    acquisition_intent_id: AcquisitionIntentId
    ordinal: int = Field(ge=0, le=3)
    artifact_id: Sha256Digest
    artifact_kind: Literal["pubmed_http_response"] = "pubmed_http_response"
    media_type: MediaType
    content_encoding: MediaType | None = None
    http_status: int = Field(ge=100, le=599)
    byte_size: int = Field(ge=0, le=5_242_880)
    body_complete: bool
    termination_reason: Literal[
        "complete_response",
        "payload_limit",
        "stream_error",
        "deadline_exceeded",
    ]
    observed_at_utc: UtcDateTime

    @property
    def filename(self) -> str:
        """Return the only valid persisted filename for this ordinal."""

        return f"artifact-link-{self.ordinal:04d}.json"

    @model_validator(mode="after")
    def validate_contract(self) -> Self:
        if self.body_complete != (self.termination_reason == "complete_response"):
            raise ValueError("body_complete must match termination_reason")
        if self.link_id != self.expected_identity():
            raise ValueError("link_id does not match content")
        return self


class ArtifactLinkReference(DurableModel):
    """Exact acquisition-envelope link reference."""

    ordinal: int = Field(ge=0, le=3)
    link_id: ArtifactLinkId


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


class AcquisitionRegistrationEnvelope(JournalModel):
    """Closed acquisition registration record for later database insertion."""

    identity_namespace = "medevidence:m1a:registration-envelope:acquisition:v1"
    identity_prefix = "registration-envelope:acquisition:sha256:"
    identity_field = "registration_envelope_id"

    schema_version: Literal["1.0"] = "1.0"
    registration_envelope_id: AcquisitionRegistrationEnvelopeId
    envelope_kind: Literal["acquisition"] = "acquisition"
    acquisition_intent_id: AcquisitionIntentId
    acquisition_ordinal: int = Field(ge=0, le=100)
    attempt_id: AttemptId
    run_id: RunId
    source: Literal["pubmed"] = "pubmed"
    operation: Literal["search", "fetch"]
    started_at_utc: UtcDateTime
    completed_at_utc: UtcDateTime
    execution_status: ExecutionStatus
    coverage_status: CoverageStatus
    result_status: ResultStatus
    valid_result_count: int = Field(ge=0, le=100)
    pages_completed: int = Field(ge=0, le=1)
    attempts_used: int = Field(ge=1, le=2)
    truncated: bool
    warning_codes: tuple[WarningCode, ...] = Field(max_length=128)
    failure_code: AcquisitionFailureCode | None = None
    redacted_detail: RedactedDetail | None = None
    artifact_links: tuple[ArtifactLinkReference, ...] = Field(max_length=4)
    manifest_id: Sha256Digest
    registration_state: Literal["ready_for_insert"] = "ready_for_insert"

    @model_validator(mode="after")
    def validate_contract(self) -> Self:
        valid_triples = {
            ("succeeded", "complete", "matches"),
            ("succeeded", "complete", "no_match"),
            ("succeeded", "partial", "matches"),
            ("succeeded", "partial", "indeterminate"),
            ("failed", "partial", "matches"),
            ("failed", "partial", "indeterminate"),
            ("failed", "unavailable", "indeterminate"),
        }
        triple = (
            self.execution_status.value,
            self.coverage_status.value,
            self.result_status.value,
        )
        if triple not in valid_triples:
            raise ValueError("invalid terminal outcome triple")
        failed = self.execution_status is ExecutionStatus.FAILED
        if failed != (self.failure_code is not None and self.redacted_detail is not None):
            raise ValueError(
                "failure_code and redacted_detail are required exactly for failed execution"
            )
        if self.completed_at_utc < self.started_at_utc:
            raise ValueError("completion precedes start")
        if self.operation == "search" and self.acquisition_ordinal != 0:
            raise ValueError("search acquisition ordinal must be zero")
        if self.operation == "fetch" and not 1 <= self.acquisition_ordinal <= 100:
            raise ValueError("fetch acquisition ordinal must be between 1 and 100")
        if self.warning_codes != tuple(sorted(set(self.warning_codes))):
            raise ValueError("warning codes must be sorted and unique")
        ordinals = tuple(reference.ordinal for reference in self.artifact_links)
        if ordinals != tuple(range(len(self.artifact_links))):
            raise ValueError("artifact links must be ascending and contiguous from zero")
        link_ids = tuple(reference.link_id for reference in self.artifact_links)
        if len(set(link_ids)) != len(link_ids):
            raise ValueError("artifact link IDs must be unique")
        if self.coverage_status is CoverageStatus.UNAVAILABLE and (
            self.pages_completed != 0 or self.valid_result_count != 0 or self.artifact_links
        ):
            raise ValueError("unavailable acquisition cannot claim results or artifact links")
        if self.result_status is ResultStatus.MATCHES and self.valid_result_count == 0:
            raise ValueError("matches requires at least one valid result")
        if self.result_status is ResultStatus.MATCHES and not self.artifact_links:
            raise ValueError("matches requires retained artifact links")
        if self.result_status is not ResultStatus.MATCHES and self.valid_result_count != 0:
            raise ValueError("non-match result requires zero valid results")
        if self.coverage_status is CoverageStatus.COMPLETE and self.truncated:
            raise ValueError("complete coverage forbids truncation")
        if self.coverage_status is CoverageStatus.COMPLETE and (
            self.pages_completed != 1 or not self.artifact_links
        ):
            raise ValueError(
                "complete coverage requires one completed page and retained artifact links"
            )
        if self.registration_envelope_id != self.expected_identity():
            raise ValueError("registration_envelope_id does not match content")
        return self


class AcquisitionRegistrationReference(DurableModel):
    """Exact run-envelope acquisition reference."""

    acquisition_registration_envelope_id: AcquisitionRegistrationEnvelopeId
    run_ordinal: int = Field(ge=0, le=100)


class RunRegistrationEnvelope(JournalModel):
    """Closed completed-run registration record."""

    identity_namespace = "medevidence:m1a:registration-envelope:run:v1"
    identity_prefix = "registration-envelope:run:sha256:"
    identity_field = "registration_envelope_id"

    schema_version: Literal["1.0"] = "1.0"
    registration_envelope_id: RunRegistrationEnvelopeId
    envelope_kind: Literal["run"] = "run"
    run_intent_id: RunIntentId
    run_id: RunId
    started_at_utc: UtcDateTime
    completed_at_utc: UtcDateTime
    run_status: Literal["completed", "degraded"]
    coverage_status: CoverageStatus
    result_status: ResultStatus
    acquisition_registrations: tuple[AcquisitionRegistrationReference, ...] = Field(
        min_length=1,
        max_length=101,
    )
    report_id: ReportId
    report_artifact_id: Sha256Digest
    report_media_type: Literal["application/json"] = "application/json"
    report_byte_size: int = Field(ge=0, le=4_294_967_296)
    report_status: Literal["draft"] = "draft"
    warning_codes: tuple[WarningCode, ...] = Field(max_length=128)
    registration_state: Literal["ready_for_insert"] = "ready_for_insert"

    @model_validator(mode="after")
    def validate_contract(self) -> Self:
        if self.completed_at_utc < self.started_at_utc:
            raise ValueError("completion precedes start")
        if self.run_status == "completed" and self.coverage_status is not CoverageStatus.COMPLETE:
            raise ValueError("completed run requires complete coverage")
        if self.run_status == "degraded" and self.coverage_status is CoverageStatus.COMPLETE:
            raise ValueError("degraded run requires incomplete coverage")
        if self.result_status is ResultStatus.NO_MATCH and (
            self.coverage_status is not CoverageStatus.COMPLETE
        ):
            raise ValueError("no_match requires complete coverage")
        if self.coverage_status is CoverageStatus.COMPLETE and (
            self.result_status is ResultStatus.INDETERMINATE
        ):
            raise ValueError("complete coverage forbids indeterminate result")
        if self.coverage_status is CoverageStatus.UNAVAILABLE and (
            self.result_status is not ResultStatus.INDETERMINATE
        ):
            raise ValueError("unavailable coverage requires indeterminate result")
        ordinals = tuple(item.run_ordinal for item in self.acquisition_registrations)
        if ordinals != tuple(range(len(self.acquisition_registrations))):
            raise ValueError("acquisition registrations must be contiguous from zero")
        envelope_ids = tuple(
            item.acquisition_registration_envelope_id for item in self.acquisition_registrations
        )
        if len(set(envelope_ids)) != len(envelope_ids):
            raise ValueError("acquisition registration IDs must be unique")
        if self.warning_codes != tuple(sorted(set(self.warning_codes))):
            raise ValueError("warning codes must be sorted and unique")
        if self.registration_envelope_id != self.expected_identity():
            raise ValueError("registration_envelope_id does not match content")
        return self


def with_computed_identity(model: type[JournalModel], payload: dict[str, Any]) -> JournalModel:
    """Construct one journal model from an ID-stripped validated payload."""

    if model.identity_field in payload:
        raise ValueError("payload must omit its logical identity field")
    provisional = dict(payload)
    provisional[model.identity_field] = f"{model.identity_prefix}{'0' * 64}"
    identity = derive_m1a_journal_identity(
        namespace=model.identity_namespace,
        prefix=model.identity_prefix,
        self_field=model.identity_field,
        value=provisional,
    )
    provisional[model.identity_field] = identity
    return model.model_validate_json(
        json.dumps(provisional, ensure_ascii=False, separators=(",", ":"))
    )
