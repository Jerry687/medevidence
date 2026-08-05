"""Strict identifiers and deterministic serialization for domain contracts."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import date, datetime, timedelta
from enum import Enum
from typing import Annotated, Any, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    StringConstraints,
)

type SchemaVersion = Literal["1.0"]


class DurableModel(BaseModel):
    """Base policy for immutable durable domain contracts."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        validate_default=True,
    )


def _require_nonblank(value: str) -> str:
    if not value.strip():
        raise ValueError("value must contain at least one non-whitespace character")
    return value


def _require_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("timestamp must be timezone-aware UTC")
    return value


def _jsonable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return _jsonable(value.model_dump(mode="python"))
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat(timespec="microseconds").replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_jsonable(item) for item in value]
    return value


def canonical_json(value: Any) -> str:
    """Serialize supported domain content to deterministic canonical JSON."""

    return json.dumps(
        _jsonable(value),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def sha256_digest(value: str | bytes) -> str:
    """Return the lowercase namespaced SHA-256 digest for exact bytes."""

    encoded = value.encode("utf-8") if isinstance(value, str) else value
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def derive_identity(namespace: str, value: Any) -> str:
    """Derive a namespaced identity from canonical serialized content."""

    digest = sha256_digest(canonical_json(value)).removeprefix("sha256:")
    return f"{namespace}:sha256:{digest}"


type NonBlankText = Annotated[
    str,
    StringConstraints(min_length=1, max_length=512),
    AfterValidator(_require_nonblank),
]
type ShortText = Annotated[
    str,
    StringConstraints(min_length=1, max_length=128),
    AfterValidator(_require_nonblank),
]
type LongText = Annotated[
    str,
    StringConstraints(min_length=1, max_length=4096),
    AfterValidator(_require_nonblank),
]
type ExactText = Annotated[
    str,
    StringConstraints(min_length=1),
    AfterValidator(_require_nonblank),
]
type UtcDateTime = Annotated[datetime, AfterValidator(_require_utc)]

type Pmid = Annotated[str, StringConstraints(pattern=r"^[1-9][0-9]*$")]
type Pmcid = Annotated[str, StringConstraints(pattern=r"^PMC[1-9][0-9]*$")]
type Doi = Annotated[
    str,
    StringConstraints(
        min_length=7,
        max_length=255,
        pattern=r"^10\.[0-9]{4,9}/\S+$",
    ),
]
type Sha256Digest = Annotated[
    str,
    StringConstraints(pattern=r"^sha256:[0-9a-f]{64}$"),
]

_STABLE_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$"
type DrugConceptId = Annotated[str, StringConstraints(pattern=_STABLE_ID_PATTERN)]
type AdverseEventConceptId = Annotated[str, StringConstraints(pattern=_STABLE_ID_PATTERN)]
type QueryId = Annotated[str, StringConstraints(pattern=_STABLE_ID_PATTERN)]
type FailureId = Annotated[str, StringConstraints(pattern=_STABLE_ID_PATTERN)]
type SnapshotId = Annotated[str, StringConstraints(pattern=_STABLE_ID_PATTERN)]
type ArtifactId = Annotated[str, StringConstraints(pattern=_STABLE_ID_PATTERN)]
type SourceRecordId = Annotated[str, StringConstraints(pattern=_STABLE_ID_PATTERN)]
type PublicationNoticeId = Annotated[str, StringConstraints(pattern=_STABLE_ID_PATTERN)]
type ConnectorVersion = Annotated[
    str,
    StringConstraints(
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._+-]*$",
    ),
]
type SourceLookupKey = NonBlankText
type WarningCode = Annotated[
    str,
    StringConstraints(pattern=r"^[a-z][a-z0-9_]{0,127}$"),
]

type ScopeId = Annotated[str, StringConstraints(pattern=r"^scope:sha256:[0-9a-f]{64}$")]
type PublicationStatusIdentity = Annotated[
    str,
    StringConstraints(pattern=r"^publication-status:sha256:[0-9a-f]{64}$"),
]
type PublicationVersionId = Annotated[
    str,
    StringConstraints(pattern=r"^pubmed:[1-9][0-9]*:sha256:[0-9a-f]{64}$"),
]
type CitationId = Annotated[str, StringConstraints(pattern=r"^citation:sha256:[0-9a-f]{64}$")]
type ClaimId = Annotated[str, StringConstraints(pattern=r"^claim:sha256:[0-9a-f]{64}$")]
type ReportId = Annotated[str, StringConstraints(pattern=r"^report:sha256:[0-9a-f]{64}$")]
