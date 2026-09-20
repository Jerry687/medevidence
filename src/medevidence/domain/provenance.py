"""Content-addressed, source-neutral forward evidence provenance contracts."""

from __future__ import annotations

import json
from datetime import timedelta
from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import Field, StringConstraints, model_validator

from .identifiers import (
    DurableModel,
    RunId,
    Sha256Digest,
    SnapshotId,
    UtcDateTime,
    canonical_json,
    derive_identity,
    sha256_digest,
)
from .scope import SourceType


class ProvenanceParentKind(StrEnum):
    MANIFEST = "manifest"
    RAW = "raw"
    NORMALIZED = "normalized"


class ProvenanceParentRefV1(DurableModel):
    """One immutable local parent whose bytes must match its content identity."""

    kind: ProvenanceParentKind
    artifact_id: Sha256Digest
    relative_path: Annotated[str, StringConstraints(min_length=1, max_length=240)]
    byte_size: int = Field(ge=1, le=5_242_880)

    @model_validator(mode="after")
    def validate_path(self) -> Self:
        path = self.relative_path
        if (
            path.startswith("/")
            or "\\" in path
            or ":" in path
            or any(part in {"", ".", ".."} for part in path.split("/"))
            or any(ord(char) < 32 or ord(char) == 127 for char in path)
        ):
            raise ValueError("provenance parent path is not a canonical relative path")
        return self


class EvidenceProvenanceEnvelopeV1(DurableModel):
    """Exact original provenance facts bound to verified source parent artifacts."""

    schema_version: Literal["m3.evidence-provenance-envelope.v1"] = (
        "m3.evidence-provenance-envelope.v1"
    )
    envelope_id: Annotated[
        str,
        StringConstraints(pattern=r"^evidence-provenance:sha256:[0-9a-f]{64}$"),
    ]
    envelope_hash: Sha256Digest
    run_id: RunId
    evidence_id: Annotated[str, StringConstraints(pattern=r"^evidence:sha256:[0-9a-f]{64}$")]
    source: SourceType
    source_record_id: Annotated[str, StringConstraints(min_length=1, max_length=160)]
    source_version: Annotated[str, StringConstraints(min_length=1, max_length=160)]
    snapshot_id: SnapshotId
    content_hash: Sha256Digest
    source_url: Annotated[str, StringConstraints(min_length=1, max_length=2048)] | None
    lookup_key: Annotated[str, StringConstraints(min_length=1, max_length=2048)] | None
    retrieved_at: UtcDateTime
    transformation_lineage: tuple[Sha256Digest, ...] = Field(min_length=2, max_length=16)
    parent_artifacts: tuple[ProvenanceParentRefV1, ...] = Field(min_length=3, max_length=3)

    @classmethod
    def create(cls, **values: object) -> EvidenceProvenanceEnvelopeV1:
        """Derive immutable identity only from the complete validated payload."""

        body = {"schema_version": "m3.evidence-provenance-envelope.v1", **values}
        body.pop("envelope_id", None)
        body.pop("envelope_hash", None)
        return cls.model_validate(
            {
                **body,
                "envelope_id": derive_identity("evidence-provenance", body),
                "envelope_hash": sha256_digest(canonical_json(body)),
            }
        )

    @model_validator(mode="after")
    def validate_binding(self) -> Self:
        if (self.source_url is None) == (self.lookup_key is None):
            raise ValueError("source URL or lookup key must be present exactly once")
        if self.retrieved_at.utcoffset() != timedelta(0):
            raise ValueError("retrieval time must be UTC")
        if tuple(item.kind for item in self.parent_artifacts) != tuple(ProvenanceParentKind):
            raise ValueError("provenance parents must be manifest, raw, normalized")
        if len(set(self.transformation_lineage)) != len(self.transformation_lineage):
            raise ValueError("transformation artifact identities must be unique")
        if (
            self.transformation_lineage[0] != self.parent_artifacts[1].artifact_id
            or self.transformation_lineage[-1] != self.parent_artifacts[2].artifact_id
            or self.content_hash != self.parent_artifacts[2].artifact_id
        ):
            raise ValueError("transformation lineage differs from exact parents")
        body = self.model_dump(mode="python", exclude={"envelope_id", "envelope_hash"})
        if self.envelope_id != derive_identity("evidence-provenance", body):
            raise ValueError("evidence provenance envelope identity drift")
        if self.envelope_hash != sha256_digest(canonical_json(body)):
            raise ValueError("evidence provenance envelope hash drift")
        return self

    def canonical_bytes(self) -> bytes:
        raw = canonical_json(
            self.model_dump(mode="python", exclude={"envelope_id", "envelope_hash"})
        ).encode("utf-8")
        if len(raw) > 32_768:
            raise ValueError("evidence provenance envelope exceeds byte bound")
        return raw

    @classmethod
    def from_canonical_bytes(cls, raw: bytes) -> EvidenceProvenanceEnvelopeV1:
        if not raw or len(raw) > 32_768:
            raise ValueError("evidence provenance envelope has invalid byte size")
        try:
            payload = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("evidence provenance envelope is invalid JSON") from error
        if type(payload) is not dict:
            raise ValueError("evidence provenance envelope is not an object")
        parsed = cls.model_validate_json(
            canonical_json(
                {
                    **payload,
                    "envelope_id": derive_identity("evidence-provenance", payload),
                    "envelope_hash": sha256_digest(raw),
                }
            ),
            strict=False,
        )
        if parsed.canonical_bytes() != raw:
            raise ValueError("evidence provenance envelope bytes are not canonical")
        return parsed
