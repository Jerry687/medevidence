"""Strict identifiers and deterministic serialization for domain contracts."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
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


_CANONICAL_SETID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)
_CANONICAL_SPL_VERSION_PATTERN = re.compile(r"^[1-9][0-9]*$")


def _require_canonical_setid(value: str) -> str:
    """Accept only the Owner-frozen lowercase, non-nil UUID representation."""

    if len(value) != 36 or _CANONICAL_SETID_PATTERN.fullmatch(value) is None:
        raise ValueError("SETID must be the exact lowercase canonical UUID form")
    try:
        parsed = uuid.UUID(value)
    except ValueError as error:
        raise ValueError("SETID must parse as a UUID") from error
    if str(parsed) != value:
        raise ValueError("SETID must equal its canonical UUID normalization")
    if parsed.int == 0:
        raise ValueError("nil SETID is forbidden")
    return value


def _require_canonical_spl_version(value: str) -> str:
    """Accept only a positive canonical ASCII integer string."""

    if _CANONICAL_SPL_VERSION_PATTERN.fullmatch(value) is None:
        raise ValueError("SPL version must be a positive canonical integer")
    if str(int(value)) != value:
        raise ValueError("SPL version must equal its canonical integer normalization")
    return value


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


def _reject_non_m1a_json_value(value: Any, *, path: str = "$") -> None:
    """Reject values outside the frozen M1A canonical JSON profile."""

    if value is None:
        raise ValueError(f"{path}: null is not permitted by M1A_CANONICAL_JSON_V1")
    if isinstance(value, float):
        raise ValueError(f"{path}: floats are not permitted by M1A_CANONICAL_JSON_V1")
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError(f"{path}: JSON object keys must be strings")
            _reject_non_m1a_json_value(item, path=f"{path}.{key}")
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for index, item in enumerate(value):
            _reject_non_m1a_json_value(item, path=f"{path}[{index}]")


def m1a_canonical_json_bytes(value: Any) -> bytes:
    """Serialize with the distinct, terminal-LF M1A canonical JSON profile."""

    jsonable = _jsonable(
        value.model_dump(mode="python", exclude_none=True)
        if isinstance(value, BaseModel)
        else value
    )
    _reject_non_m1a_json_value(jsonable)
    text = json.dumps(
        jsonable,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return text.encode("utf-8") + b"\n"


def derive_m1a_journal_identity(
    *,
    namespace: str,
    prefix: str,
    self_field: str,
    value: BaseModel | Mapping[str, Any],
) -> str:
    """Derive a frozen M1A journal ID without changing generic identities."""

    payload = (
        value.model_dump(mode="python", exclude_none=True)
        if isinstance(value, BaseModel)
        else dict(value)
    )
    if self_field not in payload:
        raise ValueError(f"missing logical identity field: {self_field}")
    del payload[self_field]
    canonical = m1a_canonical_json_bytes(payload)
    preimage = namespace.encode("ascii") + b"\x00" + canonical
    return f"{prefix}{hashlib.sha256(preimage).hexdigest()}"


def parse_m1a_json_bytes(raw: bytes) -> Any:
    """Parse UTF-8 JSON while rejecting BOM, duplicates, floats, and null."""

    if raw.startswith(b"\xef\xbb\xbf"):
        raise ValueError("UTF-8 BOM is forbidden")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError("M1A JSON must be valid UTF-8") from error

    def reject_constant(value: str) -> None:
        raise ValueError(f"non-finite number is forbidden: {value}")

    def reject_float(value: str) -> None:
        raise ValueError(f"float is forbidden: {value}")

    def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, item in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON object key: {key}")
            result[key] = item
        return result

    try:
        parsed = json.loads(
            text,
            object_pairs_hook=unique_object,
            parse_constant=reject_constant,
            parse_float=reject_float,
        )
    except json.JSONDecodeError as error:
        raise ValueError("invalid M1A JSON") from error
    _reject_non_m1a_json_value(parsed)
    return parsed


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
type CanonicalSetId = Annotated[str, AfterValidator(_require_canonical_setid)]
type CanonicalSplVersion = Annotated[str, AfterValidator(_require_canonical_spl_version)]

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
type RunIntentId = Annotated[
    str,
    StringConstraints(pattern=r"^run-intent:sha256:[0-9a-f]{64}$"),
]
type AcquisitionIntentId = Annotated[
    str,
    StringConstraints(pattern=r"^acquisition-intent:sha256:[0-9a-f]{64}$"),
]
type ArtifactLinkId = Annotated[
    str,
    StringConstraints(pattern=r"^artifact-link:sha256:[0-9a-f]{64}$"),
]
type AcquisitionRegistrationEnvelopeId = Annotated[
    str,
    StringConstraints(pattern=r"^registration-envelope:acquisition:sha256:[0-9a-f]{64}$"),
]
type RunRegistrationEnvelopeId = Annotated[
    str,
    StringConstraints(pattern=r"^registration-envelope:run:sha256:[0-9a-f]{64}$"),
]
type RunId = Annotated[
    str,
    StringConstraints(
        pattern=(
            r"^run:[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-"
            r"[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
        )
    ),
]
type AttemptId = Annotated[
    str,
    StringConstraints(
        pattern=(
            r"^attempt:[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-"
            r"[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
        )
    ),
]
type RequestId = Annotated[
    str,
    StringConstraints(
        pattern=(
            r"^request:[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-"
            r"[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
        )
    ),
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
type AcquisitionId = Annotated[str, StringConstraints(pattern=_STABLE_ID_PATTERN)]
type CandidateId = Annotated[str, StringConstraints(pattern=_STABLE_ID_PATTERN)]
type CandidateSetId = Annotated[str, StringConstraints(pattern=_STABLE_ID_PATTERN)]
type DecisionId = Annotated[str, StringConstraints(pattern=_STABLE_ID_PATTERN)]
type LabelVersionId = Annotated[str, StringConstraints(pattern=_STABLE_ID_PATTERN)]
type SectionId = Annotated[str, StringConstraints(pattern=_STABLE_ID_PATTERN)]
type SourceOutcomeId = Annotated[str, StringConstraints(pattern=_STABLE_ID_PATTERN)]
type RetainedSplResponseId = Annotated[str, StringConstraints(pattern=_STABLE_ID_PATTERN)]
type LabelSelectionWarningId = Annotated[str, StringConstraints(pattern=_STABLE_ID_PATTERN)]

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
