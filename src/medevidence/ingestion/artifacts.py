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
    AcquisitionIntentId,
    ArtifactLinkId,
    DurableModel,
    Sha256Digest,
    UtcDateTime,
    WarningCode,
    m1a_canonical_json_bytes,
    parse_m1a_json_bytes,
)
from medevidence.domain.sources import CoverageStatus, ExecutionStatus, ResultStatus

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
