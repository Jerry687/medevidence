"""Immutable DailyMed V2 discovery, packaging, and selected-SPL capture."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import Field, StringConstraints, model_validator

from medevidence.domain import (
    CoverageStatus,
    SourceOutcome,
    SourceType,
    canonical_json,
    derive_identity,
    sha256_digest,
)
from medevidence.domain.identifiers import DurableModel

from .snapshots import RAW_RESPONSE_BYTE_CAPACITY, SnapshotIntegrityError, SnapshotStore

DAILYMED_V2_MANIFEST_CAP = 1_048_576
DAILYMED_V2_RAW_MEMBER_CAP = 20
DAILYMED_V2_JOURNAL_CAP = 2_097_152
type DailyMedV2Operation = Literal["discovery", "packaging", "selected_spl"]
type Sha256 = Annotated[str, StringConstraints(pattern=r"^sha256:[0-9a-f]{64}$")]


def _is_utc(value: datetime) -> bool:
    offset = value.utcoffset() if value.tzinfo is not None else None
    return offset is not None and offset.total_seconds() == 0


@dataclass(frozen=True, slots=True)
class DailyMedV2Observation:
    """Exact bounded connector observation without a connector-layer type."""

    body: bytes
    status_code: int
    observed_at_utc: datetime
    request_url: str
    final_url: str
    media_type: str
    page_number: int
    attempt_count: int
    body_complete: bool
    termination_reason: str

    def __post_init__(self) -> None:
        if (
            type(self.body) is not bytes
            or len(self.body) > RAW_RESPONSE_BYTE_CAPACITY
            or type(self.status_code) is not int
            or not 100 <= self.status_code <= 599
            or type(self.observed_at_utc) is not datetime
            or not _is_utc(self.observed_at_utc)
            or type(self.page_number) is not int
            or not 1 <= self.page_number <= 5
            or type(self.attempt_count) is not int
            or not 1 <= self.attempt_count <= 2
            or type(self.body_complete) is not bool
            or self.body_complete != (self.termination_reason == "complete_response")
            or self.termination_reason
            not in {"complete_response", "payload_limit", "stream_error", "deadline_exceeded"}
        ):
            raise ValueError("DailyMed V2 response observation is invalid")
        for url in (self.request_url, self.final_url):
            if (
                type(url) is not str
                or not url.startswith("https://dailymed.nlm.nih.gov/")
                or len(url) > 2048
            ):
                raise ValueError("DailyMed V2 response URL is outside the exact origin")
        if (
            type(self.media_type) is not str
            or not 1 <= len(self.media_type) <= 128
            or any(ord(char) < 32 or ord(char) == 127 for char in self.media_type)
        ):
            raise ValueError("DailyMed V2 response media type is invalid")


class DailyMedV2Member(DurableModel):
    ordinal: int = Field(ge=0, lt=21)
    kind: Literal["dailymed_http_response", "dailymed_spl_xml"]
    link_id: str
    artifact_id: Sha256
    content_hash: Sha256
    relative_path: str
    byte_size: int = Field(ge=0, le=RAW_RESPONSE_BYTE_CAPACITY)
    media_type: str
    http_status: int = Field(ge=100, le=599)
    observed_at_utc: datetime
    body_complete: bool
    termination_reason: Literal[
        "complete_response", "payload_limit", "stream_error", "deadline_exceeded"
    ]
    page_number: int | None = Field(default=None, ge=1, le=5)
    attempt_count: int | None = Field(default=None, ge=1, le=2)
    request_url: str | None = None
    final_url: str | None = None

    @model_validator(mode="after")
    def exact_member(self) -> Self:
        digest = self.artifact_id.removeprefix("sha256:")
        expected = (
            f"dailymed/raw/sha256/{digest[:2]}/{digest}.bin"
            if self.kind == "dailymed_http_response"
            else f"dailymed/sha256/{digest}.xml"
        )
        if (
            self.content_hash != self.artifact_id
            or self.relative_path != expected
            or self.body_complete != (self.termination_reason == "complete_response")
            or not _is_utc(self.observed_at_utc)
        ):
            raise ValueError("DailyMed V2 member content or time differs")
        if self.kind == "dailymed_spl_xml":
            if (
                self.byte_size == 0
                or not self.body_complete
                or any(
                    value is not None
                    for value in (
                        self.page_number,
                        self.attempt_count,
                        self.request_url,
                        self.final_url,
                    )
                )
            ):
                raise ValueError("stable SPL member has response-only fields")
        elif any(
            value is None
            for value in (self.page_number, self.attempt_count, self.request_url, self.final_url)
        ):
            raise ValueError("DailyMed raw response lacks page, attempt or URL")
        payload = self.model_dump(mode="python", exclude={"link_id"})
        if self.link_id != derive_identity("dailymed-v2-member", payload):
            raise ValueError("DailyMed V2 member link identity differs")
        return self


class DailyMedV2Manifest(DurableModel):
    manifest_schema_version: Literal["m3.dailymed-v2-snapshot.v1"] = "m3.dailymed-v2-snapshot.v1"
    operation: DailyMedV2Operation
    run_id: str
    acquisition_id: str
    acquisition_intent_id: str
    acquisition_ordinal: int = Field(ge=0, le=7)
    attempt_id: str
    query_id: str
    snapshot_id: str
    request_identity: Sha256
    started_at_utc: datetime
    completed_at_utc: datetime
    source_outcome: SourceOutcome
    requests_sent: int = Field(ge=0, le=20)
    pages_completed: int = Field(ge=0, le=5)
    selected_setid: str | None = None
    selected_spl_version: str | None = None
    members: tuple[DailyMedV2Member, ...] = Field(max_length=21)
    code_revision: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{40}$")]

    @model_validator(mode="after")
    def exact_manifest(self) -> Self:
        if (
            self.source_outcome.source is not SourceType.DAILYMED
            or self.source_outcome.query_id != self.query_id
            or self.source_outcome.pages_completed != self.pages_completed
            or not _is_utc(self.started_at_utc)
            or not _is_utc(self.completed_at_utc)
            or self.completed_at_utc < self.started_at_utc
        ):
            raise ValueError("DailyMed V2 manifest outcome or time differs")
        if tuple(item.ordinal for item in self.members) != tuple(range(len(self.members))):
            raise ValueError("DailyMed V2 member ordinals are not contiguous")
        raw = tuple(item for item in self.members if item.kind == "dailymed_http_response")
        stable = tuple(item for item in self.members if item.kind == "dailymed_spl_xml")
        expected_stable_count = (
            1
            if self.operation == "selected_spl"
            and self.source_outcome.coverage_status is CoverageStatus.COMPLETE
            else 0
        )
        if (
            len(raw) > (4 if self.operation == "selected_spl" else DAILYMED_V2_RAW_MEMBER_CAP)
            or len(stable) != expected_stable_count
            or self.requests_sent < len(raw)
            or sum(item.byte_size for item in raw) > RAW_RESPONSE_BYTE_CAPACITY
            or len({item.link_id for item in self.members}) != len(self.members)
        ):
            raise ValueError("DailyMed V2 raw membership or byte count differs")
        if self.operation == "selected_spl":
            if (self.selected_setid is None) != (self.selected_spl_version is None):
                raise ValueError("DailyMed V2 selected identity is incomplete")
        elif self.selected_setid is not None or self.selected_spl_version is not None:
            raise ValueError("non-fetch DailyMed V2 manifest cannot contain selected identity")
        if self.source_outcome.coverage_status is CoverageStatus.COMPLETE and (
            not raw
            or not raw[-1].body_complete
            or not 200 <= raw[-1].http_status <= 299
            or raw[-1].byte_size == 0
            or self.source_outcome.truncated
        ):
            raise ValueError("complete DailyMed V2 capture requires complete 2xx raw")
        if self.source_outcome.coverage_status is CoverageStatus.UNAVAILABLE and (
            raw or self.pages_completed
        ):
            raise ValueError("unavailable DailyMed V2 capture cannot retain raw responses")
        return self

    def canonical_bytes(self) -> bytes:
        data = (canonical_json(self) + "\n").encode("utf-8")
        if len(data) > DAILYMED_V2_MANIFEST_CAP:
            raise ValueError("DailyMed V2 manifest exceeds its byte bound")
        return data

    @property
    def manifest_id(self) -> str:
        return sha256_digest(self.canonical_bytes())

    @classmethod
    def from_canonical_bytes(cls, raw: bytes) -> Self:
        if type(raw) is not bytes or not raw or len(raw) > DAILYMED_V2_MANIFEST_CAP:
            raise ValueError("DailyMed V2 manifest size is invalid")
        document = json.loads(raw.decode("utf-8", errors="strict"))
        if type(document) is not dict:
            raise ValueError("DailyMed V2 manifest JSON root is invalid")
        value = cls.model_validate_json(raw, strict=False)
        value = cls.model_validate(value.model_dump(mode="python"), strict=True)
        if value.canonical_bytes() != raw:
            raise ValueError("DailyMed V2 manifest is noncanonical")
        return value


@dataclass(frozen=True, slots=True)
class CapturedDailyMedV2:
    manifest: DailyMedV2Manifest
    manifest_path: Path


def _member_from_observation(ordinal: int, observation: DailyMedV2Observation) -> DailyMedV2Member:
    digest = hashlib.sha256(observation.body).hexdigest()
    payload = {
        "ordinal": ordinal,
        "kind": "dailymed_http_response",
        "artifact_id": f"sha256:{digest}",
        "content_hash": f"sha256:{digest}",
        "relative_path": f"dailymed/raw/sha256/{digest[:2]}/{digest}.bin",
        "byte_size": len(observation.body),
        "media_type": observation.media_type,
        "http_status": observation.status_code,
        "observed_at_utc": observation.observed_at_utc,
        "body_complete": observation.body_complete,
        "termination_reason": observation.termination_reason,
        "page_number": observation.page_number,
        "attempt_count": observation.attempt_count,
        "request_url": observation.request_url,
        "final_url": observation.final_url,
    }
    return DailyMedV2Member.model_validate(
        {
            **payload,
            "link_id": derive_identity("dailymed-v2-member", payload),
        }
    )


def capture_dailymed_v2(
    store: SnapshotStore,
    *,
    operation: DailyMedV2Operation,
    run_id: str,
    acquisition_id: str,
    acquisition_intent_id: str,
    acquisition_ordinal: int,
    attempt_id: str,
    query_id: str,
    snapshot_id: str,
    request_identity: str,
    started_at_utc: datetime,
    completed_at_utc: datetime,
    source_outcome: SourceOutcome,
    requests_sent: int,
    pages_completed: int,
    observations: tuple[DailyMedV2Observation, ...],
    stable_spl_bytes: bytes | None,
    selected_setid: str | None,
    selected_spl_version: str | None,
    code_revision: str,
) -> CapturedDailyMedV2:
    """Publish every response byte before its exact versioned manifest."""

    if type(store) is not SnapshotStore or type(observations) is not tuple:
        raise TypeError("DailyMed V2 capture requires exact inputs")
    members = [_member_from_observation(index, item) for index, item in enumerate(observations)]
    if stable_spl_bytes is not None:
        if selected_setid is None or selected_spl_version is None:
            raise ValueError("selected SPL requires exact SETID/version")
        store.validate_dailymed_spl(stable_spl_bytes, selected_setid, selected_spl_version)
        digest = hashlib.sha256(stable_spl_bytes).hexdigest()
        payload = {
            "ordinal": len(members),
            "kind": "dailymed_spl_xml",
            "artifact_id": f"sha256:{digest}",
            "content_hash": f"sha256:{digest}",
            "relative_path": f"dailymed/sha256/{digest}.xml",
            "byte_size": len(stable_spl_bytes),
            "media_type": "application/xml",
            "http_status": 200,
            "observed_at_utc": completed_at_utc,
            "body_complete": True,
            "termination_reason": "complete_response",
            "page_number": None,
            "attempt_count": None,
            "request_url": None,
            "final_url": None,
        }
        members.append(
            DailyMedV2Member.model_validate(
                {
                    **payload,
                    "link_id": derive_identity("dailymed-v2-member", payload),
                }
            )
        )
    manifest = DailyMedV2Manifest(
        operation=operation,
        run_id=run_id,
        acquisition_id=acquisition_id,
        acquisition_intent_id=acquisition_intent_id,
        acquisition_ordinal=acquisition_ordinal,
        attempt_id=attempt_id,
        query_id=query_id,
        snapshot_id=snapshot_id,
        request_identity=request_identity,
        started_at_utc=started_at_utc,
        completed_at_utc=completed_at_utc,
        source_outcome=source_outcome,
        requests_sent=requests_sent,
        pages_completed=pages_completed,
        selected_setid=selected_setid,
        selected_spl_version=selected_spl_version,
        members=tuple(members),
        code_revision=code_revision,
    )
    if not store.has_writer_lock:
        raise SnapshotIntegrityError("DailyMed V2 capture requires the root writer lock")
    for item in observations:
        store.store_dailymed_response(item.body)
    if stable_spl_bytes is not None:
        assert selected_setid is not None
        assert selected_spl_version is not None
        store.store_dailymed_spl(
            stable_spl_bytes,
            selected_setid=selected_setid,
            selected_spl_version=selected_spl_version,
        )
    digest = manifest.manifest_id.removeprefix("sha256:")
    relative = f"dailymed/v2/manifests/sha256/{digest[:2]}/{digest}.json"
    published = store.publish_bytes(relative, manifest.canonical_bytes(), artifact_class="manifest")
    return CapturedDailyMedV2(manifest, published.path)


def replay_dailymed_v2(
    store: SnapshotStore,
    *,
    manifest_id: str,
    expected_operation: DailyMedV2Operation,
    expected_run_id: str,
    expected_acquisition_id: str,
    expected_intent_id: str,
    expected_query_id: str,
    expected_request_identity: str,
) -> DailyMedV2Manifest:
    """Reparse exact manifest and all bounded original raw response bytes."""

    digest = manifest_id.removeprefix("sha256:")
    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        raise SnapshotIntegrityError("DailyMed V2 manifest identity is invalid")
    target = store.root / "dailymed" / "v2" / "manifests" / "sha256" / digest[:2] / f"{digest}.json"
    raw = _read_exact(store, target, DAILYMED_V2_MANIFEST_CAP)
    if sha256_digest(raw) != manifest_id:
        raise SnapshotIntegrityError("DailyMed V2 manifest bytes differ")
    manifest = DailyMedV2Manifest.from_canonical_bytes(raw)
    if (
        manifest.operation != expected_operation
        or manifest.run_id != expected_run_id
        or manifest.acquisition_id != expected_acquisition_id
        or manifest.acquisition_intent_id != expected_intent_id
        or manifest.query_id != expected_query_id
        or manifest.request_identity != expected_request_identity
    ):
        raise SnapshotIntegrityError("DailyMed V2 manifest context differs")
    for member in manifest.members:
        parent = store.root.joinpath(*member.relative_path.split("/"))
        body = _read_exact(store, parent, RAW_RESPONSE_BYTE_CAPACITY)
        if len(body) != member.byte_size or sha256_digest(body) != member.content_hash:
            raise SnapshotIntegrityError("DailyMed V2 source member bytes differ")
        if member.kind == "dailymed_spl_xml":
            assert manifest.selected_setid is not None
            assert manifest.selected_spl_version is not None
            store.validate_dailymed_spl(
                body, manifest.selected_setid, manifest.selected_spl_version
            )
    return manifest


def _read_exact(store: SnapshotStore, target: Path, cap: int) -> bytes:
    store._require_safe_path(target, allow_missing_leaf=False)
    if not target.is_file() or not 0 <= target.stat().st_size <= cap:
        raise SnapshotIntegrityError("DailyMed V2 source file is missing or oversized")
    size = target.stat().st_size
    with target.open("rb") as handle:
        raw = handle.read(cap + 1)
    store._require_safe_path(target, allow_missing_leaf=False)
    if len(raw) != size or len(raw) > cap:
        raise SnapshotIntegrityError("DailyMed V2 source file changed during read")
    return raw
