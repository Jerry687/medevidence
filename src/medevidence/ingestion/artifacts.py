"""Canonical manifests, source-neutral capture, and replay integrity checks."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from pathlib import Path, PurePosixPath
from typing import Annotated, Literal, Self, cast

from pydantic import Field, StringConstraints, model_validator

from medevidence.domain.identifiers import (
    AcquisitionId,
    AcquisitionIntentId,
    ArtifactLinkId,
    CanonicalSetId,
    CanonicalSplVersion,
    DurableModel,
    QueryId,
    RunId,
    Sha256Digest,
    SnapshotId,
    UtcDateTime,
    WarningCode,
    m1a_canonical_json_bytes,
    parse_m1a_json_bytes,
)
from medevidence.domain.scope import ExecutionBounds, SourceType
from medevidence.domain.sources import (
    CoverageStatus,
    ExecutionStatus,
    FaersAggregateBucketV1,
    FaersAggregateQueryV1,
    ResultStatus,
    SourceOutcome,
)

from .contracts import (
    AcquisitionIntent,
    AcquisitionRegistrationEnvelope,
    ArtifactLink,
    JournalModel,
    MediaType,
    RunIntent,
    RunRegistrationEnvelope,
    with_computed_identity,
)
from .snapshots import (
    RAW_RESPONSE_BYTE_CAPACITY,
    SnapshotContainmentError,
    SnapshotIntegrityError,
    SnapshotStore,
)

MAX_MANIFEST_BYTES = 1_048_576
type CodeRevision = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{40}$")]
type TerminationReason = Literal[
    "complete_response",
    "payload_limit",
    "stream_error",
    "read_timeout",
    "deadline_exceeded",
]


@dataclass(frozen=True, slots=True)
class RawResponseObservation:
    """Source-neutral exact response material accepted by ingestion."""

    body: bytes
    observed_at_utc: datetime
    media_type: str
    content_encoding: str | None
    http_status: int
    body_complete: bool
    termination_reason: TerminationReason

    def __post_init__(self) -> None:
        if len(self.body) > RAW_RESPONSE_BYTE_CAPACITY:
            raise ValueError("response observation exceeds 5,242,880 bytes")
        if not self.body_complete and not self.body:
            raise ValueError("an incomplete observation requires a retained nonempty prefix")
        offset = self.observed_at_utc.utcoffset()
        if self.observed_at_utc.tzinfo is None or offset is None:
            raise ValueError("observed_at_utc must be timezone-aware UTC")
        if offset.total_seconds() != 0:
            raise ValueError("observed_at_utc must be UTC")
        if not 100 <= self.http_status <= 599:
            raise ValueError("http_status must be an HTTP status")
        if self.body_complete != (self.termination_reason == "complete_response"):
            raise ValueError("body_complete must match termination_reason")
        if not 1 <= len(self.media_type) <= 128:
            raise ValueError("media_type must be bounded and nonblank")
        if self.content_encoding is not None and not 1 <= len(self.content_encoding) <= 128:
            raise ValueError("content_encoding must be bounded and nonblank")


@dataclass(frozen=True, slots=True)
class CapturedAcquisition:
    """Verified outputs of one lock-held acquisition capture."""

    manifest: SnapshotManifest
    manifest_path: Path
    artifact_links: tuple[ArtifactLink, ...]
    artifact_link_paths: tuple[Path, ...]


class DailyMedManifestMember(DurableModel):
    """One exact response or stable SPL member in a DailyMed manifest."""

    ordinal: int = Field(ge=0, le=127)
    link_id: ArtifactLinkId
    artifact_id: Sha256Digest
    content_hash: Sha256Digest
    artifact_kind: Literal["dailymed_http_response", "dailymed_spl_xml"]
    relative_path: str
    byte_size: int = Field(ge=0, le=RAW_RESPONSE_BYTE_CAPACITY)
    media_type: MediaType
    http_status: int = Field(ge=100, le=599)
    body_complete: bool
    termination_reason: TerminationReason

    @model_validator(mode="after")
    def validate_member(self) -> Self:
        if self.artifact_id != self.content_hash:
            raise ValueError("DailyMed member artifact and content identities must match")
        digest = self.artifact_id.removeprefix("sha256:")
        expected = (
            f"dailymed/sha256/{digest}.xml"
            if self.artifact_kind == "dailymed_spl_xml"
            else f"dailymed/raw/sha256/{digest[:2]}/{digest}.bin"
        )
        if self.relative_path != expected:
            raise ValueError("DailyMed member path must match its exact content identity")
        if self.body_complete != (self.termination_reason == "complete_response"):
            raise ValueError("DailyMed member completion must match termination reason")
        if self.artifact_kind == "dailymed_spl_xml" and (
            self.byte_size == 0 or not self.body_complete
        ):
            raise ValueError("stable SPL evidence must be nonempty and complete")
        return self


class DailyMedSnapshotManifest(DurableModel):
    """Canonical immutable manifest for one bounded DailyMed acquisition."""

    manifest_schema_version: Literal["m1b.dailymed.snapshot-manifest.v1"] = (
        "m1b.dailymed.snapshot-manifest.v1"
    )
    source_type: Literal["dailymed"] = "dailymed"
    run_id: RunId
    acquisition_id: AcquisitionId
    acquisition_intent_id: AcquisitionIntentId
    acquisition_ordinal: int = Field(ge=0, le=7)
    query_id: QueryId
    snapshot_id: SnapshotId
    operation: Literal["search", "fetch"]
    request_identity: Annotated[str, StringConstraints(min_length=1, max_length=1024)]
    selected_setid: CanonicalSetId | None = None
    selected_spl_version: CanonicalSplVersion | None = None
    started_at_utc: UtcDateTime
    completed_at_utc: UtcDateTime
    execution_status: ExecutionStatus
    coverage_status: CoverageStatus
    result_status: ResultStatus
    record_count: int = Field(ge=0, le=100)
    pages_completed: int = Field(ge=0, le=5)
    attempts_used: int = Field(ge=1, le=2)
    truncated: bool
    warning_codes: tuple[WarningCode, ...] = Field(max_length=128)
    members: tuple[DailyMedManifestMember, ...] = Field(max_length=6)
    connector_name: Literal["medevidence.connectors.dailymed"] = "medevidence.connectors.dailymed"
    connector_version: Literal["m1b-dm-002"] = "m1b-dm-002"
    source_record_schema_version: Literal["m1b.dailymed.label.v1"] = "m1b.dailymed.label.v1"
    code_revision: CodeRevision

    @classmethod
    def from_json_bytes(cls, raw: bytes) -> Self:
        """Parse strict JSON and require exact complete canonical bytes."""

        if len(raw) > MAX_MANIFEST_BYTES:
            raise ValueError("DailyMed manifest exceeds 1,048,576 bytes")
        parsed = parse_m1a_json_bytes(raw)
        manifest = cls.model_validate_json(
            json.dumps(parsed, ensure_ascii=False, separators=(",", ":"))
        )
        if manifest.canonical_bytes() != raw:
            raise ValueError("DailyMed manifest bytes are not canonical JSON")
        return manifest

    def canonical_bytes(self) -> bytes:
        """Return exact canonical UTF-8 bytes with one terminal LF."""

        raw = m1a_canonical_json_bytes(self)
        if len(raw) > MAX_MANIFEST_BYTES:
            raise ValueError("DailyMed manifest exceeds 1,048,576 bytes")
        return raw

    @property
    def manifest_id(self) -> Sha256Digest:
        """Identify the exact complete canonical manifest bytes."""

        return f"sha256:{sha256(self.canonical_bytes()).hexdigest()}"

    @model_validator(mode="after")
    def validate_manifest(self) -> Self:
        triple = (
            self.execution_status.value,
            self.coverage_status.value,
            self.result_status.value,
        )
        if triple not in {
            ("succeeded", "complete", "matches"),
            ("succeeded", "complete", "no_match"),
            ("succeeded", "partial", "matches"),
            ("succeeded", "partial", "indeterminate"),
            ("failed", "partial", "matches"),
            ("failed", "partial", "indeterminate"),
            ("failed", "unavailable", "indeterminate"),
        }:
            raise ValueError("DailyMed manifest has an invalid terminal outcome triple")
        if self.completed_at_utc < self.started_at_utc:
            raise ValueError("DailyMed manifest completion precedes start")
        if self.warning_codes != tuple(sorted(set(self.warning_codes))):
            raise ValueError("DailyMed manifest warnings must be sorted and unique")
        ordinals = tuple(member.ordinal for member in self.members)
        if ordinals != tuple(range(len(self.members))):
            raise ValueError("DailyMed manifest members must be contiguous from zero")
        if len({member.link_id for member in self.members}) != len(self.members):
            raise ValueError("DailyMed manifest member links must be unique")
        selected = self.selected_setid is not None or self.selected_spl_version is not None
        if selected != (self.selected_setid is not None and self.selected_spl_version is not None):
            raise ValueError("selected DailyMed SETID/version are both-or-neither")
        stable_members = tuple(
            member for member in self.members if member.artifact_kind == "dailymed_spl_xml"
        )
        if selected != (len(stable_members) == 1):
            raise ValueError("selected identity exists exactly with one stable SPL member")
        if selected and self.operation != "fetch":
            raise ValueError("only a fetch manifest may retain stable SPL evidence")
        if self.coverage_status is CoverageStatus.COMPLETE and self.truncated:
            raise ValueError("complete DailyMed coverage forbids truncation")
        response_members = tuple(
            member for member in self.members if member.artifact_kind == "dailymed_http_response"
        )
        if sum(member.byte_size for member in response_members) > RAW_RESPONSE_BYTE_CAPACITY:
            raise ValueError("DailyMed response bodies exceed the cumulative 5,242,880-byte bound")
        if self.coverage_status is CoverageStatus.UNAVAILABLE and (
            self.record_count != 0 or self.pages_completed != 0 or response_members
        ):
            raise ValueError("unavailable DailyMed manifest has no retained response")
        if self.coverage_status is CoverageStatus.COMPLETE:
            if self.pages_completed < 1 or not response_members:
                raise ValueError("complete DailyMed coverage requires a completed response")
            effective = response_members[-1]
            if (
                effective.byte_size == 0
                or not effective.body_complete
                or not 200 <= effective.http_status <= 299
            ):
                raise ValueError("complete DailyMed coverage requires nonempty complete 2xx")
        if self.result_status is ResultStatus.MATCHES and self.record_count == 0:
            raise ValueError("DailyMed matches requires at least one valid record")
        if self.result_status is not ResultStatus.MATCHES and self.record_count != 0:
            raise ValueError("DailyMed non-match outcome requires zero valid records")
        if stable_members and triple != ("succeeded", "complete", "matches"):
            raise ValueError("stable SPL evidence requires succeeded/complete/matches")
        return self


@dataclass(frozen=True, slots=True)
class CapturedDailyMedSnapshot:
    """Verified immutable files for one DailyMed acquisition."""

    manifest: DailyMedSnapshotManifest
    manifest_path: Path
    member_paths: tuple[Path, ...]


class FaersManifestMember(DurableModel):
    """One exact retained aggregate response in a FAERS snapshot manifest."""

    ordinal: int = Field(ge=0, le=1)
    link_id: ArtifactLinkId
    artifact_id: Sha256Digest
    content_hash: Sha256Digest
    artifact_kind: Literal["faers_http_response"] = "faers_http_response"
    relative_path: Annotated[
        str,
        StringConstraints(pattern=r"^faers/raw/sha256/[0-9a-f]{2}/[0-9a-f]{64}\.bin$"),
    ]
    byte_size: int = Field(ge=0, le=RAW_RESPONSE_BYTE_CAPACITY)
    media_type: MediaType
    http_status: int = Field(ge=100, le=599)
    observed_at_utc: UtcDateTime
    body_complete: bool
    termination_reason: TerminationReason

    @model_validator(mode="after")
    def validate_member(self) -> Self:
        if self.artifact_id != self.content_hash:
            raise ValueError("FAERS artifact and content identities must match")
        digest = self.artifact_id.removeprefix("sha256:")
        if self.relative_path != f"faers/raw/sha256/{digest[:2]}/{digest}.bin":
            raise ValueError("FAERS response path must match its exact content identity")
        if self.body_complete != (self.termination_reason == "complete_response"):
            raise ValueError("FAERS member completion must match termination reason")
        return self


class FaersSnapshotManifest(DurableModel):
    """Canonical immutable manifest for one bounded FAERS aggregate acquisition."""

    manifest_schema_version: Literal["m1b.faers.snapshot-manifest.v1"] = (
        "m1b.faers.snapshot-manifest.v1"
    )
    source_type: Literal["faers"] = "faers"
    run_id: RunId
    acquisition_id: AcquisitionId
    acquisition_intent_id: AcquisitionIntentId
    acquisition_ordinal: int = Field(ge=0, le=100)
    query: FaersAggregateQueryV1
    snapshot_id: SnapshotId
    started_at_utc: UtcDateTime
    completed_at_utc: UtcDateTime
    source_outcome: SourceOutcome
    retrieved_at_utc: UtcDateTime
    provider_as_of_utc: UtcDateTime | None = None
    attempts_used: int = Field(ge=1, le=2)
    buckets: tuple[FaersAggregateBucketV1, ...] = Field(max_length=100)
    members: tuple[FaersManifestMember, ...] = Field(max_length=2)
    connector_name: Literal["medevidence.connectors.faers"] = "medevidence.connectors.faers"
    connector_version: Literal["m1b-faers-002"] = "m1b-faers-002"
    source_record_schema_version: Literal["m1b.faers.aggregate.v1"] = "m1b.faers.aggregate.v1"
    code_revision: CodeRevision

    @classmethod
    def from_json_bytes(cls, raw: bytes) -> Self:
        """Parse strict JSON and require exact complete canonical bytes."""

        if len(raw) > MAX_MANIFEST_BYTES:
            raise ValueError("FAERS manifest exceeds 1,048,576 bytes")
        parsed = parse_m1a_json_bytes(raw)
        manifest = cls.model_validate_json(
            json.dumps(parsed, ensure_ascii=False, separators=(",", ":"))
        )
        if manifest.canonical_bytes() != raw:
            raise ValueError("FAERS manifest bytes are not canonical JSON")
        return manifest

    def canonical_bytes(self) -> bytes:
        """Return exact canonical UTF-8 bytes with one terminal LF."""

        raw = m1a_canonical_json_bytes(self)
        if len(raw) > MAX_MANIFEST_BYTES:
            raise ValueError("FAERS manifest exceeds 1,048,576 bytes")
        return raw

    @property
    def manifest_id(self) -> Sha256Digest:
        """Identify the exact complete canonical manifest bytes."""

        return f"sha256:{sha256(self.canonical_bytes()).hexdigest()}"

    @model_validator(mode="after")
    def validate_manifest(self) -> Self:
        if self.completed_at_utc < self.started_at_utc:
            raise ValueError("FAERS manifest completion precedes start")
        if self.source_outcome.source is not SourceType.FAERS:
            raise ValueError("FAERS manifest outcome source must be faers")
        if self.source_outcome.configured_bounds != ExecutionBounds(
            max_query_characters=512,
            max_pages=5,
            max_records=100,
            max_payload_bytes=5_242_880,
            max_total_seconds=30,
        ):
            raise ValueError("FAERS manifest outcome bounds must equal the named profile")
        if self.source_outcome.query_id != self.query.query_id:
            raise ValueError("FAERS manifest outcome must bind the exact query")
        if len(self.buckets) != self.source_outcome.valid_result_count:
            raise ValueError("FAERS manifest buckets must equal valid_result_count")
        expected_order = tuple(
            sorted(self.buckets, key=lambda item: (-item.report_count, item.reaction_pt))
        )
        if self.buckets != expected_order:
            raise ValueError("FAERS manifest buckets must use canonical ordering")
        if tuple(bucket.bucket_ordinal for bucket in self.buckets) != tuple(
            range(len(self.buckets))
        ):
            raise ValueError("FAERS manifest bucket ordinals must be contiguous")
        if len({bucket.reaction_pt for bucket in self.buckets}) != len(self.buckets):
            raise ValueError("FAERS manifest bucket reaction PT values must be unique")
        for bucket in self.buckets:
            bucket.validate_against(self.query)
        if tuple(member.ordinal for member in self.members) != tuple(range(len(self.members))):
            raise ValueError("FAERS manifest members must be contiguous from zero")
        if len(self.members) > self.attempts_used:
            raise ValueError("FAERS response members cannot exceed attempts_used")
        if len({member.link_id for member in self.members}) != len(self.members):
            raise ValueError("FAERS manifest member links must be unique")
        _validate_unique_faers_member_artifacts(self.members, error_type=ValueError)
        for member in self.members:
            if member.link_id != _faers_member_link_id(member):
                raise ValueError("FAERS member link must bind its exact ordered response evidence")
            if not self.started_at_utc <= member.observed_at_utc <= self.completed_at_utc:
                raise ValueError("FAERS member observation must be within acquisition time")
        if tuple(member.observed_at_utc for member in self.members) != tuple(
            sorted(member.observed_at_utc for member in self.members)
        ):
            raise ValueError("FAERS member observations must follow response order")
        if any(not _faers_member_permits_retry(member) for member in self.members[:-1]):
            raise ValueError("FAERS terminal response cannot precede another retained response")
        if sum(member.byte_size for member in self.members) > RAW_RESPONSE_BYTE_CAPACITY:
            raise ValueError("FAERS responses exceed the cumulative 5,242,880-byte bound")
        if self.source_outcome.coverage_status is CoverageStatus.UNAVAILABLE and (
            self.members or self.buckets
        ):
            raise ValueError("unavailable FAERS acquisition retains no response or bucket")
        if self.source_outcome.coverage_status is CoverageStatus.COMPLETE:
            if not self.members:
                raise ValueError("complete FAERS coverage requires a retained response")
            effective = self.members[-1]
            if (
                not effective.body_complete
                or effective.byte_size == 0
                or not 200 <= effective.http_status <= 299
            ):
                raise ValueError("complete FAERS coverage requires nonempty complete 2xx")
        return self


@dataclass(frozen=True, slots=True)
class CapturedFaersSnapshot:
    """Verified immutable files for one FAERS aggregate acquisition."""

    manifest: FaersSnapshotManifest
    manifest_path: Path
    member_paths: tuple[Path, ...]


class ManifestFile(DurableModel):
    """One ordered immutable raw-body reference in a snapshot manifest."""

    ordinal: int = Field(ge=0, le=3)
    link_id: ArtifactLinkId
    artifact_id: Sha256Digest
    relative_path: Annotated[
        str,
        StringConstraints(pattern=r"^pubmed/sha256/[0-9a-f]{2}/[0-9a-f]{64}\.bin$"),
    ]
    byte_size: int = Field(ge=0, le=RAW_RESPONSE_BYTE_CAPACITY)
    media_type: MediaType
    content_encoding: MediaType | None = None
    http_status: int = Field(ge=100, le=599)
    body_complete: bool
    termination_reason: TerminationReason

    @model_validator(mode="after")
    def validate_identity_path(self) -> Self:
        digest = self.artifact_id.removeprefix("sha256:")
        expected = f"pubmed/sha256/{digest[:2]}/{digest}.bin"
        if self.relative_path != expected:
            raise ValueError("manifest path must match artifact identity")
        if self.body_complete != (self.termination_reason == "complete_response"):
            raise ValueError("body_complete must match termination_reason")
        return self


class SnapshotManifest(DurableModel):
    """Closed canonical manifest for one acquisition."""

    manifest_schema_version: Literal["1.0"] = "1.0"
    retention_policy_id: Literal["M1A-LIVE-RETENTION-v1"] = "M1A-LIVE-RETENTION-v1"
    source_type: Literal["pubmed"] = "pubmed"
    acquisition_intent_id: AcquisitionIntentId
    request_identity: Annotated[str, StringConstraints(min_length=1, max_length=512)]
    started_at_utc: UtcDateTime
    completed_at_utc: UtcDateTime
    record_count: int = Field(ge=0, le=100)
    execution_status: ExecutionStatus
    coverage_status: CoverageStatus
    result_status: ResultStatus
    attempts_used: int = Field(ge=1, le=2)
    pages_completed: int = Field(ge=0, le=1)
    truncated: bool
    warning_codes: tuple[WarningCode, ...] = Field(max_length=128)
    files: tuple[ManifestFile, ...] = Field(max_length=4)
    connector_name: Literal["medevidence.connectors.pubmed"] = "medevidence.connectors.pubmed"
    connector_version: Literal["m1a-002"] = "m1a-002"
    source_record_schema_version: Literal["1.0"] = "1.0"
    code_revision: CodeRevision

    @classmethod
    def from_json_bytes(cls, raw: bytes) -> Self:
        """Parse strict JSON and require exact canonical manifest bytes."""

        if len(raw) > MAX_MANIFEST_BYTES:
            raise ValueError("manifest exceeds 1,048,576 bytes")
        parsed = parse_m1a_json_bytes(raw)
        manifest = cls.model_validate_json(
            json.dumps(parsed, ensure_ascii=False, separators=(",", ":"))
        )
        if manifest.canonical_bytes() != raw:
            raise ValueError("manifest bytes are not canonical M1A JSON")
        return manifest

    def canonical_bytes(self) -> bytes:
        """Return exact canonical UTF-8 manifest bytes."""

        raw = m1a_canonical_json_bytes(self)
        if len(raw) > MAX_MANIFEST_BYTES:
            raise ValueError("manifest exceeds 1,048,576 bytes")
        return raw

    @property
    def manifest_id(self) -> Sha256Digest:
        """Identify the exact complete canonical manifest bytes."""

        return f"sha256:{sha256(self.canonical_bytes()).hexdigest()}"

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
        if (
            self.execution_status.value,
            self.coverage_status.value,
            self.result_status.value,
        ) not in valid_triples:
            raise ValueError("manifest has an invalid terminal outcome triple")
        if self.completed_at_utc < self.started_at_utc:
            raise ValueError("manifest completion precedes start")
        if self.warning_codes != tuple(sorted(set(self.warning_codes))):
            raise ValueError("manifest warnings must be sorted and unique")
        ordinals = tuple(item.ordinal for item in self.files)
        if ordinals != tuple(range(len(self.files))):
            raise ValueError("manifest files must be contiguous from ordinal zero")
        link_ids = tuple(item.link_id for item in self.files)
        if len(set(link_ids)) != len(link_ids):
            raise ValueError("manifest link IDs must be unique")
        if sum(item.byte_size for item in self.files) > RAW_RESPONSE_BYTE_CAPACITY:
            raise ValueError("manifest raw bytes exceed the acquisition payload ceiling")
        if self.coverage_status is CoverageStatus.UNAVAILABLE and (
            self.record_count != 0 or self.pages_completed != 0 or self.files
        ):
            raise ValueError("unavailable manifest must be a zero-file manifest")
        if self.result_status is ResultStatus.MATCHES and self.record_count == 0:
            raise ValueError("matches requires at least one record")
        if self.result_status is ResultStatus.MATCHES and not self.files:
            raise ValueError("matches requires retained source evidence")
        if self.result_status is not ResultStatus.MATCHES and self.record_count != 0:
            raise ValueError("non-match status requires zero records")
        if self.coverage_status is CoverageStatus.COMPLETE:
            if self.truncated:
                raise ValueError("complete coverage forbids truncation")
            if self.pages_completed != 1 or not self.files:
                raise ValueError("complete coverage requires one completed page and retained files")
            effective = self.files[-1]
            if (
                not effective.body_complete
                or effective.byte_size == 0
                or not 200 <= effective.http_status <= 299
            ):
                raise ValueError(
                    "complete coverage requires a terminal nonempty complete 2xx response"
                )
        if self.result_status is ResultStatus.MATCHES and not any(
            200 <= item.http_status <= 299 and item.byte_size > 0 for item in self.files
        ):
            raise ValueError("matches requires nonempty retained HTTP 2xx evidence")
        return self


def response_observation(
    *,
    body: bytes,
    observed_at_utc: datetime,
    headers: tuple[tuple[str, str], ...],
    http_status: int,
    body_complete: bool,
    termination_reason: TerminationReason,
) -> RawResponseObservation:
    """Map exact transport-neutral response fields into ingestion input."""

    normalized = tuple((name.casefold(), value) for name, value in headers)
    if len({name for name, _ in normalized}) != len(normalized):
        raise ValueError("response metadata contains duplicate header names")
    content_type = next(
        (value for name, value in normalized if name == "content-type"),
        "application/octet-stream",
    )
    media_type = content_type.partition(";")[0].strip().casefold()
    content_encoding = next(
        (value.strip().casefold() for name, value in normalized if name == "content-encoding"),
        None,
    )
    return RawResponseObservation(
        body=bytes(body),
        observed_at_utc=observed_at_utc,
        media_type=media_type,
        content_encoding=content_encoding,
        http_status=http_status,
        body_complete=body_complete,
        termination_reason=termination_reason,
    )


def manifest_file_from_link(link: ArtifactLink) -> ManifestFile:
    """Create the exact manifest file entry for a validated artifact link."""

    digest = link.artifact_id.removeprefix("sha256:")
    return ManifestFile(
        ordinal=link.ordinal,
        link_id=link.link_id,
        artifact_id=link.artifact_id,
        relative_path=f"pubmed/sha256/{digest[:2]}/{digest}.bin",
        byte_size=link.byte_size,
        media_type=link.media_type,
        content_encoding=link.content_encoding,
        http_status=link.http_status,
        body_complete=link.body_complete,
        termination_reason=link.termination_reason,
    )


def write_immutable_record(
    store: SnapshotStore,
    relative_directory: str,
    filename: str,
    record: JournalModel,
) -> Path:
    """Publish one canonical journal file through the root writer gate."""

    approved = {
        "run-intent.json",
        "acquisition-intent.json",
        "registration-envelope.json",
        *(f"artifact-link-{ordinal:04d}.json" for ordinal in range(4)),
    }
    if filename not in approved:
        raise ValueError("filename is not an approved M1A journal filename")
    expected_types: tuple[type[JournalModel], ...]
    if filename == "run-intent.json":
        expected_types = (RunIntent,)
    elif filename == "acquisition-intent.json":
        expected_types = (AcquisitionIntent,)
    elif filename == "registration-envelope.json":
        expected_types = (
            AcquisitionRegistrationEnvelope,
            RunRegistrationEnvelope,
        )
    else:
        expected_types = (ArtifactLink,)
    if type(record) not in expected_types:
        raise ValueError("journal filename does not match the concrete record type")
    if type(record) is ArtifactLink and filename != record.filename:
        raise ValueError("artifact-link ordinal must match its filename")
    directory = _validated_journal_directory(relative_directory)
    relative = (directory / filename).as_posix()
    return store.publish_bytes(
        relative,
        record.canonical_bytes(),
        artifact_class="journal",
    ).path


def _validated_journal_directory(relative_directory: str) -> PurePosixPath:
    """Validate a journal directory without touching the filesystem."""

    directory = PurePosixPath(relative_directory)
    if (
        "\\" in relative_directory
        or directory.is_absolute()
        or not directory.parts
        or any(part in {"", ".", ".."} for part in directory.parts)
    ):
        raise SnapshotContainmentError("journal directory must be store-relative")
    return directory


def write_immutable_manifest(store: SnapshotStore, manifest: SnapshotManifest) -> Path:
    """Publish at the frozen content-addressed PubMed manifest path."""

    raw = manifest.canonical_bytes()
    digest = manifest.manifest_id.removeprefix("sha256:")
    relative = f"pubmed/manifests/sha256/{digest[:2]}/{digest}.json"
    return store.publish_bytes(relative, raw, artifact_class="manifest").path


def capture_acquisition(
    store: SnapshotStore,
    *,
    journal_relative_directory: str,
    acquisition_intent_id: AcquisitionIntentId,
    request_identity: str,
    started_at_utc: datetime,
    completed_at_utc: datetime,
    validated_record_count: int,
    execution_status: ExecutionStatus,
    coverage_status: CoverageStatus,
    result_status: ResultStatus,
    attempts_used: int,
    pages_completed: int,
    truncated: bool,
    warning_codes: tuple[WarningCode, ...],
    observations: tuple[RawResponseObservation, ...],
    code_revision: CodeRevision,
) -> CapturedAcquisition:
    """Persist ordered exact bodies, links, and one bound manifest."""

    if len(observations) > 4:
        raise ValueError("capture accepts at most four response observations")
    _validated_journal_directory(journal_relative_directory)
    links: list[ArtifactLink] = []
    for ordinal, observation in enumerate(observations):
        artifact_id = f"sha256:{sha256(observation.body).hexdigest()}"
        payload = {
            "acquisition_intent_id": acquisition_intent_id,
            "ordinal": ordinal,
            "artifact_id": artifact_id,
            "artifact_kind": "pubmed_http_response",
            "media_type": observation.media_type,
            "content_encoding": observation.content_encoding,
            "http_status": observation.http_status,
            "byte_size": len(observation.body),
            "body_complete": observation.body_complete,
            "termination_reason": observation.termination_reason,
            "observed_at_utc": observation.observed_at_utc.isoformat(
                timespec="microseconds"
            ).replace("+00:00", "Z"),
            "schema_version": "1.0",
        }
        if observation.content_encoding is None:
            del payload["content_encoding"]
        link = cast(ArtifactLink, with_computed_identity(ArtifactLink, payload))
        links.append(link)
    manifest = SnapshotManifest(
        acquisition_intent_id=acquisition_intent_id,
        request_identity=request_identity,
        started_at_utc=started_at_utc,
        completed_at_utc=completed_at_utc,
        record_count=validated_record_count,
        execution_status=execution_status,
        coverage_status=coverage_status,
        result_status=result_status,
        attempts_used=attempts_used,
        pages_completed=pages_completed,
        truncated=truncated,
        warning_codes=warning_codes,
        files=tuple(manifest_file_from_link(link) for link in links),
        code_revision=code_revision,
    )
    for link in links:
        link.canonical_bytes()
    manifest.canonical_bytes()

    link_paths: list[Path] = []
    for observation, link in zip(observations, links, strict=True):
        raw = store.store_raw_body(observation.body)
        if raw.artifact_id != link.artifact_id or raw.byte_size != link.byte_size:
            raise SnapshotIntegrityError("published raw body differs from preflight identity")
        link_paths.append(
            write_immutable_record(
                store,
                journal_relative_directory,
                link.filename,
                link,
            )
        )
    manifest_path = write_immutable_manifest(store, manifest)
    return CapturedAcquisition(manifest, manifest_path, tuple(links), tuple(link_paths))


def replay_manifest(
    raw: bytes,
    store: SnapshotStore,
    *,
    expected_manifest_id: Sha256Digest,
    expected_links: tuple[ArtifactLink, ...],
    expected_validated_record_count: int,
) -> SnapshotManifest:
    """Validate canonical manifest identity, link metadata, and raw snapshots."""

    manifest = SnapshotManifest.from_json_bytes(raw)
    if manifest.manifest_id != expected_manifest_id:
        raise SnapshotIntegrityError("manifest identity differs from expected identity")
    if manifest.record_count != expected_validated_record_count:
        raise SnapshotIntegrityError("manifest count differs from validated result count")
    expected_files = tuple(manifest_file_from_link(link) for link in expected_links)
    if manifest.files != expected_files:
        raise SnapshotIntegrityError("manifest files differ from expected artifact links")
    for item in manifest.files:
        path = store.verify(item.artifact_id)
        try:
            relative = path.relative_to(store.root).as_posix()
        except ValueError as error:
            raise SnapshotContainmentError("verified snapshot escaped its root") from error
        if relative != item.relative_path or path.stat().st_size != item.byte_size:
            raise SnapshotIntegrityError("manifest file metadata differs from snapshot")
    return manifest


def capture_dailymed_snapshot(
    store: SnapshotStore,
    *,
    run_id: RunId,
    acquisition_id: AcquisitionId,
    acquisition_intent_id: AcquisitionIntentId,
    acquisition_ordinal: int,
    query_id: QueryId,
    snapshot_id: SnapshotId,
    operation: Literal["search", "fetch"],
    request_identity: str,
    started_at_utc: datetime,
    completed_at_utc: datetime,
    execution_status: ExecutionStatus,
    coverage_status: CoverageStatus,
    result_status: ResultStatus,
    record_count: int,
    pages_completed: int,
    attempts_used: int,
    truncated: bool,
    warning_codes: tuple[WarningCode, ...],
    observations: tuple[RawResponseObservation, ...],
    stable_spl_bytes: bytes | None,
    selected_setid: CanonicalSetId | None,
    selected_spl_version: CanonicalSplVersion | None,
    code_revision: CodeRevision,
) -> CapturedDailyMedSnapshot:
    """Publish exact DailyMed responses, stable SPL bytes, and one manifest."""

    if len(observations) > 5:
        raise ValueError("DailyMed capture accepts at most five response observations")
    members: list[DailyMedManifestMember] = []
    for ordinal, observation in enumerate(observations):
        digest = sha256(observation.body).hexdigest()
        member = _dailymed_member(
            ordinal=ordinal,
            artifact_id=f"sha256:{digest}",
            artifact_kind="dailymed_http_response",
            relative_path=f"dailymed/raw/sha256/{digest[:2]}/{digest}.bin",
            byte_size=len(observation.body),
            media_type=observation.media_type,
            http_status=observation.http_status,
            body_complete=observation.body_complete,
            termination_reason=observation.termination_reason,
        )
        members.append(member)

    if stable_spl_bytes is not None:
        if selected_setid is None or selected_spl_version is None:
            raise ValueError("stable SPL capture requires the selected SETID/version")
        store.validate_dailymed_spl(
            stable_spl_bytes,
            selected_setid,
            selected_spl_version,
        )
        digest = sha256(stable_spl_bytes).hexdigest()
        status = observations[-1].http_status if observations else 200
        member = _dailymed_member(
            ordinal=len(members),
            artifact_id=f"sha256:{digest}",
            artifact_kind="dailymed_spl_xml",
            relative_path=f"dailymed/sha256/{digest}.xml",
            byte_size=len(stable_spl_bytes),
            media_type="application/xml",
            http_status=status,
            body_complete=True,
            termination_reason="complete_response",
        )
        members.append(member)

    manifest = DailyMedSnapshotManifest(
        run_id=run_id,
        acquisition_id=acquisition_id,
        acquisition_intent_id=acquisition_intent_id,
        acquisition_ordinal=acquisition_ordinal,
        query_id=query_id,
        snapshot_id=snapshot_id,
        operation=operation,
        request_identity=request_identity,
        selected_setid=selected_setid,
        selected_spl_version=selected_spl_version,
        started_at_utc=started_at_utc,
        completed_at_utc=completed_at_utc,
        execution_status=execution_status,
        coverage_status=coverage_status,
        result_status=result_status,
        record_count=record_count,
        pages_completed=pages_completed,
        attempts_used=attempts_used,
        truncated=truncated,
        warning_codes=warning_codes,
        members=tuple(members),
        code_revision=code_revision,
    )
    paths: list[Path] = []
    for observation in observations:
        paths.append(store.store_dailymed_response(observation.body).path)
    if stable_spl_bytes is not None:
        if selected_setid is None or selected_spl_version is None:
            raise RuntimeError("validated stable SPL identity unexpectedly became absent")
        paths.append(
            store.store_dailymed_spl(
                stable_spl_bytes,
                selected_setid=selected_setid,
                selected_spl_version=selected_spl_version,
            ).path
        )
    digest = manifest.manifest_id.removeprefix("sha256:")
    manifest_path = store.publish_bytes(
        f"dailymed/manifests/sha256/{digest[:2]}/{digest}.json",
        manifest.canonical_bytes(),
        artifact_class="manifest",
    ).path
    return CapturedDailyMedSnapshot(manifest, manifest_path, tuple(paths))


def replay_dailymed_snapshot(
    raw: bytes,
    store: SnapshotStore,
    *,
    expected_manifest_id: Sha256Digest,
    expected_members: tuple[DailyMedManifestMember, ...],
) -> DailyMedSnapshotManifest:
    """Revalidate canonical manifest bytes and every immutable member."""

    manifest = DailyMedSnapshotManifest.from_json_bytes(raw)
    if manifest.manifest_id != expected_manifest_id:
        raise SnapshotIntegrityError("DailyMed manifest identity differs from expected")
    if manifest.members != expected_members:
        raise SnapshotIntegrityError("DailyMed manifest members differ from expected")
    for member in manifest.members:
        path = store.verify_dailymed(
            member.artifact_id,
            stable_spl=member.artifact_kind == "dailymed_spl_xml",
            selected_setid=manifest.selected_setid,
            selected_spl_version=manifest.selected_spl_version,
        )
        if (
            path.relative_to(store.root).as_posix() != member.relative_path
            or path.stat().st_size != member.byte_size
        ):
            raise SnapshotIntegrityError("DailyMed manifest member metadata differs")
    return manifest


def capture_faers_snapshot(
    store: SnapshotStore,
    *,
    run_id: RunId,
    acquisition_id: AcquisitionId,
    acquisition_intent_id: AcquisitionIntentId,
    acquisition_ordinal: int,
    query: FaersAggregateQueryV1,
    snapshot_id: SnapshotId,
    started_at_utc: datetime,
    completed_at_utc: datetime,
    source_outcome: SourceOutcome,
    retrieved_at_utc: datetime,
    provider_as_of_utc: datetime | None,
    attempts_used: int,
    buckets: tuple[FaersAggregateBucketV1, ...],
    observations: tuple[RawResponseObservation, ...],
    code_revision: CodeRevision,
) -> CapturedFaersSnapshot:
    """Publish exact FAERS responses and their complete canonical manifest."""

    if len(observations) > 2:
        raise ValueError("FAERS capture accepts at most two response observations")
    members = tuple(
        _faers_member(ordinal, observation) for ordinal, observation in enumerate(observations)
    )
    _validate_unique_faers_member_artifacts(members, error_type=SnapshotIntegrityError)
    manifest = FaersSnapshotManifest(
        run_id=run_id,
        acquisition_id=acquisition_id,
        acquisition_intent_id=acquisition_intent_id,
        acquisition_ordinal=acquisition_ordinal,
        query=query,
        snapshot_id=snapshot_id,
        started_at_utc=started_at_utc,
        completed_at_utc=completed_at_utc,
        source_outcome=source_outcome,
        retrieved_at_utc=retrieved_at_utc,
        provider_as_of_utc=provider_as_of_utc,
        attempts_used=attempts_used,
        buckets=buckets,
        members=members,
        code_revision=code_revision,
    )
    paths: list[Path] = []
    for observation, member in zip(observations, members, strict=True):
        published = store.store_faers_response(observation.body)
        if published.artifact_id != member.artifact_id or published.byte_size != member.byte_size:
            raise SnapshotIntegrityError("published FAERS body differs from preflight identity")
        paths.append(published.path)
    digest = manifest.manifest_id.removeprefix("sha256:")
    manifest_path = store.publish_bytes(
        f"faers/manifests/sha256/{digest[:2]}/{digest}.json",
        manifest.canonical_bytes(),
        artifact_class="manifest",
    ).path
    return CapturedFaersSnapshot(manifest, manifest_path, tuple(paths))


def replay_faers_snapshot(
    raw: bytes,
    store: SnapshotStore,
    *,
    expected_manifest_id: Sha256Digest,
    expected_query: FaersAggregateQueryV1,
    expected_members: tuple[FaersManifestMember, ...],
) -> FaersSnapshotManifest:
    """Revalidate FAERS manifest identity, query ownership, and exact raw bytes."""

    if len(expected_members) > 2:
        raise SnapshotIntegrityError("FAERS replay membership exceeds the two-attempt profile")
    _validate_unique_faers_member_artifacts(
        expected_members,
        error_type=SnapshotIntegrityError,
    )
    manifest = FaersSnapshotManifest.from_json_bytes(raw)
    if len(expected_members) > manifest.attempts_used:
        raise SnapshotIntegrityError("FAERS replay members exceed manifest attempts_used")
    if manifest.manifest_id != expected_manifest_id:
        raise SnapshotIntegrityError("FAERS manifest identity differs from expected")
    if manifest.query != expected_query:
        raise SnapshotIntegrityError("FAERS manifest query differs from expected")
    if manifest.members != expected_members:
        raise SnapshotIntegrityError("FAERS manifest members differ from expected")
    for member in manifest.members:
        path = store.verify_faers(member.artifact_id)
        if (
            path.relative_to(store.root).as_posix() != member.relative_path
            or path.stat().st_size != member.byte_size
        ):
            raise SnapshotIntegrityError("FAERS manifest member metadata differs")
    return manifest


def _validate_unique_faers_member_artifacts(
    members: tuple[FaersManifestMember, ...],
    *,
    error_type: type[ValueError] | type[SnapshotIntegrityError],
) -> None:
    """Reject one retained body represented as two snapshot memberships."""

    by_artifact: dict[str, FaersManifestMember] = {}
    by_content: dict[str, FaersManifestMember] = {}
    for member in members:
        for identity_name, identity, seen in (
            ("artifact_id", member.artifact_id, by_artifact),
            ("content_hash", member.content_hash, by_content),
        ):
            first = seen.get(identity)
            if first is not None:
                raise error_type(
                    f"duplicate FAERS {identity_name} {identity} across retained attempts "
                    f"ordinal={first.ordinal} link_id={first.link_id} and "
                    f"ordinal={member.ordinal} link_id={member.link_id}"
                )
            seen[identity] = member


def _faers_member(ordinal: int, observation: RawResponseObservation) -> FaersManifestMember:
    digest = sha256(observation.body).hexdigest()
    artifact_id = f"sha256:{digest}"
    member = FaersManifestMember(
        ordinal=ordinal,
        link_id=f"artifact-link:sha256:{'0' * 64}",
        artifact_id=artifact_id,
        content_hash=artifact_id,
        relative_path=f"faers/raw/sha256/{digest[:2]}/{digest}.bin",
        byte_size=len(observation.body),
        media_type=observation.media_type,
        http_status=observation.http_status,
        observed_at_utc=observation.observed_at_utc,
        body_complete=observation.body_complete,
        termination_reason=observation.termination_reason,
    )
    return member.model_copy(update={"link_id": _faers_member_link_id(member)})


def _faers_member_link_id(member: FaersManifestMember) -> ArtifactLinkId:
    identity_payload = {
        "ordinal": member.ordinal,
        "artifact_id": member.artifact_id,
        "artifact_kind": "faers_http_response",
        "byte_size": member.byte_size,
        "media_type": member.media_type,
        "http_status": member.http_status,
        "observed_at_utc": member.observed_at_utc.isoformat(timespec="microseconds").replace(
            "+00:00", "Z"
        ),
        "body_complete": member.body_complete,
        "termination_reason": member.termination_reason,
    }
    encoded = json.dumps(identity_payload, sort_keys=True, separators=(",", ":")).encode()
    return f"artifact-link:sha256:{sha256(encoded).hexdigest()}"


def _faers_member_permits_retry(member: FaersManifestMember) -> bool:
    if not member.body_complete:
        return member.termination_reason == "read_timeout"
    return member.http_status in {408, 429} or 500 <= member.http_status <= 599


def _dailymed_member(
    *,
    ordinal: int,
    artifact_id: Sha256Digest,
    artifact_kind: Literal["dailymed_http_response", "dailymed_spl_xml"],
    relative_path: str,
    byte_size: int,
    media_type: str,
    http_status: int,
    body_complete: bool,
    termination_reason: TerminationReason,
) -> DailyMedManifestMember:
    payload = {
        "ordinal": ordinal,
        "artifact_id": artifact_id,
        "artifact_kind": artifact_kind,
        "relative_path": relative_path,
        "byte_size": byte_size,
        "media_type": media_type,
        "http_status": http_status,
        "body_complete": body_complete,
        "termination_reason": termination_reason,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return DailyMedManifestMember(
        ordinal=ordinal,
        link_id=f"artifact-link:sha256:{sha256(encoded).hexdigest()}",
        artifact_id=artifact_id,
        content_hash=artifact_id,
        artifact_kind=artifact_kind,
        relative_path=relative_path,
        byte_size=byte_size,
        media_type=media_type,
        http_status=http_status,
        body_complete=body_complete,
        termination_reason=termination_reason,
    )
