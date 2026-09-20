"""Single declarative authority for Attempt004 response framing."""

# ruff: noqa: E501  # Generated SQL predicates remain inspectable literals.

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Final, TypedDict, cast, final

APPROVED_HEADER_NAMES: Final = (
    "content-encoding",
    "content-length",
    "content-type",
    "transfer-encoding",
    "x-request-id",
)
APPROVED_JSON_MEDIA_TYPES: Final = (
    "application/json",
    "application/json; charset=utf-8",
)
POSTGRES_BIGINT_MAX: Final = 9_223_372_036_854_775_807
MAX_RAW_RESPONSE_BYTES: Final = 131_072
MAX_OBSERVED_BODY_BYTES_LOWER_BOUND: Final = MAX_RAW_RESPONSE_BYTES + 1
_MAX_HEADER_FIELDS = 128
_MAX_APPROVED_OCCURRENCES = 8
_MAX_HEADER_VALUE_BYTES = 8_192
_MAX_APPROVED_HEADER_BYTES = 32_768
_SHA256 = re.compile(r"sha256:[0-9a-f]{64}")
_HEADER_NAME = re.compile(r"[!#$%&'*+.^_`|~0-9A-Za-z-]{1,128}")
_WINDOWS_RESERVED_PATH_BASE_NAMES: Final = (
    "AUX",
    "CLOCK$",
    "COM1",
    "COM2",
    "COM3",
    "COM4",
    "COM5",
    "COM6",
    "COM7",
    "COM8",
    "COM9",
    "CON",
    "LPT1",
    "LPT2",
    "LPT3",
    "LPT4",
    "LPT5",
    "LPT6",
    "LPT7",
    "LPT8",
    "LPT9",
    "NUL",
    "PRN",
)


class _NoncanonicalString(str):
    """Generated witness for values equal to, but not exactly, built-in ``str``."""


class _NoncanonicalList(list[object]):
    """Generated external witness equal to, but not exactly, built-in ``list``."""


def _exact_str_tuple(value: object) -> bool:
    return type(value) is tuple and all(type(item) is str for item in value)


def _exact_optional_str(value: object) -> bool:
    return value is None or type(value) is str


def _exact_optional_int(value: object) -> bool:
    return value is None or type(value) is int


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=True, allow_nan=False, sort_keys=True, separators=(",", ":")
    ).encode("ascii")


def _identity(kind: str, value: object) -> str:
    return f"{kind}:sha256:{hashlib.sha256(_canonical_bytes(value)).hexdigest()}"


APPROVED_HEADER_NAMES_IDENTITY: Final = _identity(
    "m3-approved-header-names", list(APPROVED_HEADER_NAMES)
)


def canonical_approved_header_names_bytes() -> bytes:
    """Return the exact fixed header-authority bytes hashed by both runtimes."""

    return _canonical_bytes(list(APPROVED_HEADER_NAMES))


class FramingStatus(StrEnum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    UNAVAILABLE = "unavailable_not_classified"


class HeaderSurfaceState(StrEnum):
    VALID = "valid"
    INVALID = "invalid"


class HttpVersionState(StrEnum):
    MISSING = "missing"
    HTTP_1_1 = "http_1_1"
    HTTP_2 = "http_2"
    UNSUPPORTED = "unsupported"


class ContentLengthState(StrEnum):
    ABSENT = "absent"
    VALID = "valid"
    DUPLICATE = "duplicate"
    INVALID = "invalid"


class TransferEncodingState(StrEnum):
    ABSENT = "absent"
    CHUNKED = "chunked"
    MULTIPLE = "multiple"
    INVALID = "invalid"


class ContentEncodingState(StrEnum):
    ABSENT = "absent"
    IDENTITY = "identity"
    UNSUPPORTED = "unsupported"


class ContentTypeState(StrEnum):
    APPROVED = "approved_json"
    ABSENT = "absent"
    DUPLICATE = "duplicate"
    INVALID = "invalid"


class RawEvidenceState(StrEnum):
    BOUND = "bound"
    MISSING = "missing"


@final
@dataclass(frozen=True, slots=True)
class HeaderOccurrence:
    name: str
    value: str


@final
@dataclass(frozen=True, slots=True)
class NormalizedHeaderFacts:
    approved_header_names: tuple[str, ...]
    approved_header_names_identity: str
    occurrences: tuple[HeaderOccurrence, ...]
    observed_names: tuple[str, ...]
    raw_header_field_count: int
    surface_state: HeaderSurfaceState
    facts_identity: str


def _header_payload(
    occurrences: tuple[HeaderOccurrence, ...],
    raw_header_field_count: int,
    surface_state: HeaderSurfaceState,
) -> dict[str, object]:
    by_name = {
        name: [item.value for item in occurrences if item.name == name]
        for name in APPROVED_HEADER_NAMES
    }
    return {
        "approved_header_names_identity": APPROVED_HEADER_NAMES_IDENTITY,
        "occurrences": by_name,
        "raw_header_field_count": raw_header_field_count,
        "surface_state": surface_state.value,
    }


def _make_header_facts(
    occurrences: tuple[HeaderOccurrence, ...],
    raw_header_field_count: int,
    surface_state: HeaderSurfaceState,
) -> NormalizedHeaderFacts:
    observed_names = tuple(sorted({item.name for item in occurrences}))
    return NormalizedHeaderFacts(
        APPROVED_HEADER_NAMES,
        APPROVED_HEADER_NAMES_IDENTITY,
        occurrences,
        observed_names,
        raw_header_field_count,
        surface_state,
        _identity(
            "m3-normalized-header-facts",
            _header_payload(occurrences, raw_header_field_count, surface_state),
        ),
    )


def normalize_approved_headers(
    raw_header_items: tuple[tuple[str, str], ...],
    *,
    raw_header_field_count: int,
) -> NormalizedHeaderFacts:
    """Normalize only the exact approved surface, retaining bounded multiplicity."""

    if (
        type(raw_header_field_count) is not int
        or not 0 <= raw_header_field_count <= POSTGRES_BIGINT_MAX
        or type(raw_header_items) is not tuple
        or raw_header_field_count < len(raw_header_items)
    ):
        raise ValueError("raw header field count is invalid")
    if len(raw_header_items) > _MAX_HEADER_FIELDS or raw_header_field_count > _MAX_HEADER_FIELDS:
        return _make_header_facts((), raw_header_field_count, HeaderSurfaceState.INVALID)
    approved: list[tuple[int, HeaderOccurrence]] = []
    counts: dict[str, int] = {}
    total_bytes = 0
    order = {name: index for index, name in enumerate(APPROVED_HEADER_NAMES)}
    for ordinal, pair in enumerate(raw_header_items):
        if type(pair) is not tuple or len(pair) != 2:
            return _make_header_facts((), raw_header_field_count, HeaderSurfaceState.INVALID)
        name, value = pair
        if type(name) is not str or _HEADER_NAME.fullmatch(name) is None:
            return _make_header_facts((), raw_header_field_count, HeaderSurfaceState.INVALID)
        normalized_name = name.lower()
        if normalized_name not in order:
            continue
        if type(value) is not str:
            return _make_header_facts((), raw_header_field_count, HeaderSurfaceState.INVALID)
        try:
            encoded = value.encode("ascii")
        except UnicodeEncodeError:
            return _make_header_facts((), raw_header_field_count, HeaderSurfaceState.INVALID)
        if len(encoded) > _MAX_HEADER_VALUE_BYTES or any(
            byte < 32 or byte == 127 for byte in encoded
        ):
            return _make_header_facts((), raw_header_field_count, HeaderSurfaceState.INVALID)
        counts[normalized_name] = counts.get(normalized_name, 0) + 1
        total_bytes += len(encoded)
        if (
            counts[normalized_name] > _MAX_APPROVED_OCCURRENCES
            or total_bytes > _MAX_APPROVED_HEADER_BYTES
        ):
            return _make_header_facts((), raw_header_field_count, HeaderSurfaceState.INVALID)
        approved.append((ordinal, HeaderOccurrence(normalized_name, value)))
    approved.sort(key=lambda item: (order[item[1].name], item[0]))
    return _make_header_facts(
        tuple(item for _, item in approved),
        raw_header_field_count,
        HeaderSurfaceState.VALID,
    )


def reconstruct_normalized_headers(
    *,
    approved_header_names: tuple[str, ...],
    approved_header_names_identity: str,
    occurrences: tuple[tuple[str, str], ...],
    observed_names: tuple[str, ...],
    raw_header_field_count: int,
    surface_state: str,
    facts_identity: str,
) -> NormalizedHeaderFacts:
    """Fail closed unless persisted header facts are the exact canonical projection."""

    if (
        not _exact_str_tuple(approved_header_names)
        or approved_header_names != APPROVED_HEADER_NAMES
        or type(approved_header_names_identity) is not str
        or approved_header_names_identity != APPROVED_HEADER_NAMES_IDENTITY
        or type(occurrences) is not tuple
        or any(
            type(pair) is not tuple
            or len(pair) != 2
            or type(pair[0]) is not str
            or type(pair[1]) is not str
            for pair in occurrences
        )
        or not _exact_str_tuple(observed_names)
        or type(raw_header_field_count) is not int
        or not 0 <= raw_header_field_count <= POSTGRES_BIGINT_MAX
        or type(surface_state) is not str
        or type(facts_identity) is not str
    ):
        raise ValueError("approved header authority drift")
    try:
        persisted_state = HeaderSurfaceState(surface_state)
    except ValueError:
        raise ValueError("normalized header surface state drift") from None
    rebuilt = (
        _make_header_facts((), raw_header_field_count, HeaderSurfaceState.INVALID)
        if persisted_state is HeaderSurfaceState.INVALID and not occurrences
        else normalize_approved_headers(occurrences, raw_header_field_count=raw_header_field_count)
    )
    if (
        rebuilt.surface_state is not persisted_state
        or rebuilt.observed_names != observed_names
        or rebuilt.facts_identity != facts_identity
        or any(name not in APPROVED_HEADER_NAMES for name in observed_names)
    ):
        raise ValueError("normalized header facts drift")
    return rebuilt


@final
@dataclass(frozen=True, slots=True)
class FramingObservation:
    disposition: str
    http_status: int
    http_version_state: HttpVersionState
    observed_http_version: str | None
    headers: NormalizedHeaderFacts
    raw_header_field_count: int
    content_length_state: ContentLengthState
    content_length_value: int | None
    transfer_encoding_state: TransferEncodingState
    content_encoding_state: ContentEncodingState
    content_type_state: ContentTypeState
    body_complete: bool
    actual_body_byte_count: int | None
    observed_body_bytes_lower_bound: int
    raw_evidence_state: RawEvidenceState
    raw_body_hash: str | None
    raw_relative_path: str | None
    raw_artifact_identity: str | None
    input_identity: str


@final
@dataclass(frozen=True, slots=True)
class UnavailableObservation:
    disposition: str
    http_status: int | None
    input_identity: str


type Observation = FramingObservation | UnavailableObservation


def _values(headers: NormalizedHeaderFacts, name: str) -> tuple[str, ...]:
    return tuple(item.value for item in headers.occurrences if item.name == name)


def canonical_normalized_header_facts_bytes(value: NormalizedHeaderFacts) -> bytes:
    """Return the exact credential-safe bytes bound by the normalized-facts identity."""

    if type(value) is not NormalizedHeaderFacts or not _valid_headers(value):
        raise ValueError("normalized header facts drift")
    return _canonical_bytes(
        _header_payload(value.occurrences, value.raw_header_field_count, value.surface_state)
    )


def _content_length(values: tuple[str, ...]) -> tuple[ContentLengthState, int | None]:
    if not values:
        return ContentLengthState.ABSENT, None
    if len(values) != 1:
        return ContentLengthState.DUPLICATE, None
    value = values[0]
    maximum = str(POSTGRES_BIGINT_MAX)
    if (
        re.fullmatch(r"0|[1-9][0-9]*", value) is None
        or len(value) > len(maximum)
        or (len(value) == len(maximum) and value > maximum)
    ):
        return ContentLengthState.INVALID, None
    return ContentLengthState.VALID, int(value)


def _transfer_encoding(values: tuple[str, ...]) -> TransferEncodingState:
    if not values:
        return TransferEncodingState.ABSENT
    if len(values) != 1:
        return TransferEncodingState.MULTIPLE
    value = values[0]
    return (
        TransferEncodingState.CHUNKED
        if value.strip().lower() == "chunked" and "," not in value
        else TransferEncodingState.INVALID
    )


def _content_encoding(values: tuple[str, ...]) -> ContentEncodingState:
    if not values:
        return ContentEncodingState.ABSENT
    if len(values) == 1 and values[0].strip().lower() == "identity" and "," not in values[0]:
        return ContentEncodingState.IDENTITY
    return ContentEncodingState.UNSUPPORTED


def raw_body_persistence_permitted(headers: NormalizedHeaderFacts) -> bool:
    """Return the sole header-derived authority for persisting raw response bytes."""

    if type(headers) is not NormalizedHeaderFacts or not _valid_headers(headers):
        raise ValueError("normalized header facts drift")
    return headers.surface_state is HeaderSurfaceState.VALID and _content_encoding(
        _values(headers, "content-encoding")
    ) in {ContentEncodingState.ABSENT, ContentEncodingState.IDENTITY}


def _content_type(values: tuple[str, ...]) -> ContentTypeState:
    if not values:
        return ContentTypeState.ABSENT
    if len(values) != 1:
        return ContentTypeState.DUPLICATE
    return (
        ContentTypeState.APPROVED
        if values[0] in APPROVED_JSON_MEDIA_TYPES
        else ContentTypeState.INVALID
    )


def provider_raw_relative_path_is_canonical(value: object) -> bool:
    """Return whether a persisted provider-body path is canonical and relative."""

    if not (
        type(value) is str
        and 1 <= len(value) <= 1_024
        and value.isascii()
        and all(32 <= ord(character) <= 126 for character in value)
        and value[0] != "/"
        and "\\" not in value
        and ":" not in value
        and all(part not in {"", ".", ".."} for part in value.split("/"))
    ):
        return False
    return all(
        component[-1] not in {".", " "}
        and component.split(".", 1)[0].rstrip(" .").upper() not in _WINDOWS_RESERVED_PATH_BASE_NAMES
        for component in value.split("/")
    )


def _observation_payload(value: FramingObservation) -> dict[str, object]:
    return {
        "actual_body_byte_count": value.actual_body_byte_count,
        "body_complete": value.body_complete,
        "content_encoding_state": value.content_encoding_state.value,
        "content_length_state": value.content_length_state.value,
        "content_length_value": value.content_length_value,
        "content_type_state": value.content_type_state.value,
        "disposition": value.disposition,
        "header_facts_identity": value.headers.facts_identity,
        "http_status": value.http_status,
        "http_version_state": value.http_version_state.value,
        "observed_http_version": value.observed_http_version,
        "observed_body_bytes_lower_bound": value.observed_body_bytes_lower_bound,
        "raw_artifact_identity": value.raw_artifact_identity,
        "raw_evidence_state": value.raw_evidence_state.value,
        "raw_header_field_count": value.raw_header_field_count,
        "transfer_encoding_state": value.transfer_encoding_state.value,
    }


def build_framing_observation(
    *,
    disposition: str,
    http_status: int,
    http_version: str | None,
    headers: NormalizedHeaderFacts,
    raw_header_field_count: int,
    body_complete: bool,
    actual_body_byte_count: int | None,
    raw_body_hash: str | None,
    raw_relative_path: str | None,
    observed_body_bytes_lower_bound: int | None = None,
) -> FramingObservation:
    """Build the only classifier input from normalized facts and persisted raw binding."""

    if (
        type(disposition) is not str
        or not disposition
        or len(disposition) > 64
        or not disposition.isascii()
        or any(not 33 <= ord(character) <= 126 for character in disposition)
        or disposition in {"credential_echo", "evidence_persistence_failure"}
        or type(http_status) is not int
        or not 100 <= http_status <= 599
        or type(headers) is not NormalizedHeaderFacts
        or not _valid_headers(headers)
        or type(raw_header_field_count) is not int
        or raw_header_field_count != headers.raw_header_field_count
        or type(body_complete) is not bool
        or not _exact_optional_int(actual_body_byte_count)
        or not _exact_optional_int(observed_body_bytes_lower_bound)
        or not _exact_optional_str(http_version)
        or not _exact_optional_str(raw_body_hash)
        or not _exact_optional_str(raw_relative_path)
    ):
        raise ValueError("framing observation facts are invalid")
    if http_version is None:
        version_state = HttpVersionState.MISSING
    elif http_version == "HTTP/1.1":
        version_state = HttpVersionState.HTTP_1_1
    elif http_version == "HTTP/2":
        version_state = HttpVersionState.HTTP_2
    elif (
        type(http_version) is str
        and 1 <= len(http_version) <= 16
        and http_version.isascii()
        and all(33 <= ord(character) <= 126 for character in http_version)
    ):
        version_state = HttpVersionState.UNSUPPORTED
    else:
        raise ValueError("observed HTTP version is invalid")
    if body_complete:
        if (
            type(actual_body_byte_count) is not int
            or not 0 <= actual_body_byte_count <= MAX_RAW_RESPONSE_BYTES
        ):
            raise ValueError("complete body byte count is invalid")
        if observed_body_bytes_lower_bound is None:
            observed_body_bytes_lower_bound = actual_body_byte_count
        if (
            type(observed_body_bytes_lower_bound) is not int
            or observed_body_bytes_lower_bound != actual_body_byte_count
        ):
            raise ValueError("complete body lower bound differs from exact byte count")
    elif (
        actual_body_byte_count is not None
        or type(observed_body_bytes_lower_bound) is not int
        or not 0 <= observed_body_bytes_lower_bound <= MAX_OBSERVED_BODY_BYTES_LOWER_BOUND
    ):
        raise ValueError("incomplete body requires one bounded observed-byte lower bound")
    raw_missing = raw_body_hash is None and raw_relative_path is None
    raw_bound = (
        type(raw_body_hash) is str
        and _SHA256.fullmatch(raw_body_hash) is not None
        and type(raw_relative_path) is str
        and provider_raw_relative_path_is_canonical(raw_relative_path)
        and body_complete
        and actual_body_byte_count is not None
    )
    if not raw_missing and not raw_bound:
        raise ValueError("raw evidence binding is invalid")
    raw_identity = (
        _identity(
            "m3-provider-raw-artifact",
            {
                "body_byte_count": actual_body_byte_count,
                "body_hash": raw_body_hash,
                "relative_path": raw_relative_path,
            },
        )
        if raw_bound
        else None
    )
    cl_state, cl_value = _content_length(_values(headers, "content-length"))
    provisional = FramingObservation(
        disposition,
        http_status,
        version_state,
        http_version,
        headers,
        raw_header_field_count,
        cl_state,
        cl_value,
        _transfer_encoding(_values(headers, "transfer-encoding")),
        _content_encoding(_values(headers, "content-encoding")),
        _content_type(_values(headers, "content-type")),
        body_complete,
        actual_body_byte_count,
        observed_body_bytes_lower_bound,
        RawEvidenceState.BOUND if raw_bound else RawEvidenceState.MISSING,
        raw_body_hash,
        raw_relative_path,
        raw_identity,
        "",
    )
    return replace(
        provisional,
        input_identity=_identity("m3-framing-input", _observation_payload(provisional)),
    )


def build_unavailable_observation(*, disposition: str, http_status: int) -> UnavailableObservation:
    """Build a fact-free terminal for credential or persistence failure."""

    if (
        type(disposition) is not str
        or disposition not in {"credential_echo", "evidence_persistence_failure"}
        or type(http_status) is not int
        or not 100 <= http_status <= 599
    ):
        raise ValueError("unavailable framing path is invalid")
    payload = {"disposition": disposition, "http_status": http_status, "framing_facts": None}
    return UnavailableObservation(disposition, http_status, _identity("m3-framing-input", payload))


def _valid_headers(value: NormalizedHeaderFacts) -> bool:
    if (
        type(value) is not NormalizedHeaderFacts
        or not _exact_str_tuple(value.approved_header_names)
        or value.approved_header_names != APPROVED_HEADER_NAMES
        or type(value.approved_header_names_identity) is not str
        or value.approved_header_names_identity != APPROVED_HEADER_NAMES_IDENTITY
        or type(value.occurrences) is not tuple
        or any(
            type(item) is not HeaderOccurrence
            or type(item.name) is not str
            or type(item.value) is not str
            for item in value.occurrences
        )
        or not _exact_str_tuple(value.observed_names)
        or tuple(sorted(set(value.observed_names))) != value.observed_names
        or any(name not in APPROVED_HEADER_NAMES for name in value.observed_names)
        or tuple(sorted({item.name for item in value.occurrences})) != value.observed_names
        or type(value.raw_header_field_count) is not int
        or not 0 <= value.raw_header_field_count <= POSTGRES_BIGINT_MAX
        or value.raw_header_field_count < len(value.occurrences)
        or type(value.surface_state) is not HeaderSurfaceState
        or type(value.facts_identity) is not str
        or value.facts_identity
        != _identity(
            "m3-normalized-header-facts",
            _header_payload(
                value.occurrences,
                value.raw_header_field_count,
                value.surface_state,
            ),
        )
    ):
        return False
    if value.surface_state is HeaderSurfaceState.INVALID:
        return not value.occurrences and not value.observed_names
    if value.raw_header_field_count > _MAX_HEADER_FIELDS:
        return False
    rebuilt = normalize_approved_headers(
        tuple((item.name, item.value) for item in value.occurrences),
        raw_header_field_count=value.raw_header_field_count,
    )
    return rebuilt == value


def canonical_raw_artifact_bytes(value: FramingObservation) -> bytes | None:
    """Return exact raw-binding bytes, or ``None`` for an intentionally rawless input."""

    _validate_observation(value)
    if value.raw_evidence_state is RawEvidenceState.MISSING:
        return None
    return _canonical_bytes(
        {
            "body_byte_count": value.actual_body_byte_count,
            "body_hash": value.raw_body_hash,
            "relative_path": value.raw_relative_path,
        }
    )


def canonical_framing_input_bytes(value: Observation) -> bytes:
    """Return exact bytes used by Python and PostgreSQL input-identity authority."""

    _validate_observation(value)
    if type(value) is UnavailableObservation:
        return _canonical_bytes(
            {
                "disposition": value.disposition,
                "framing_facts": None,
                "http_status": value.http_status,
            }
        )
    return _canonical_bytes(_observation_payload(value))


class Op(StrEnum):
    EQ = "eq"
    IN = "in"
    TRUE = "true"
    FALSE = "false"
    PRESENT = "present"
    ABSENT = "absent"
    FIELD_NE = "field_ne"
    FIELD_EQ = "field_eq"


@dataclass(frozen=True, slots=True)
class Atom:
    field: str
    op: Op
    value: str | int | tuple[str, ...] | None = None


@dataclass(frozen=True, slots=True)
class AllOf:
    parts: tuple[Expression, ...]


@dataclass(frozen=True, slots=True)
class AnyOf:
    parts: tuple[Expression, ...]


type Expression = Atom | AllOf | AnyOf


def _all(*parts: Expression) -> AllOf:
    return AllOf(parts)


def _any(*parts: Expression) -> AnyOf:
    return AnyOf(parts)


def _eq(field: str, value: str | int | None) -> Atom:
    return Atom(field, Op.EQ, value)


def _in(field: str, *values: str) -> Atom:
    return Atom(field, Op.IN, values)


@dataclass(frozen=True, slots=True)
class ExampleSpec:
    http_version: str | None
    header_items: tuple[tuple[str, str], ...]
    body_complete: bool
    actual_body_byte_count: int | None
    persist_raw: bool
    unavailable_disposition: str | None = None
    raw_header_field_count: int | None = None


@dataclass(frozen=True, slots=True)
class FramingRule:
    key: str
    condition: Expression
    status: FramingStatus
    accepted_class: str | None
    rejection_code: str | None
    example: ExampleSpec


_JSON = (("content-type", "application/json"),)


def _example(
    version: str | None,
    *headers: tuple[str, str],
    complete: bool = True,
    count: int | None = 2,
    raw: bool = True,
) -> ExampleSpec:
    items = (*_JSON, *headers)
    return ExampleSpec(version, items, complete, count, raw, None, len(items))


def _reject(code: str, condition: Expression, example: ExampleSpec) -> FramingRule:
    return FramingRule(code, condition, FramingStatus.REJECTED, None, code, example)


def _accept(
    key: str, accepted_class: str, condition: Expression, example: ExampleSpec
) -> FramingRule:
    return FramingRule(key, condition, FramingStatus.ACCEPTED, accepted_class, None, example)


def _unavailable(disposition: str) -> FramingRule:
    return FramingRule(
        f"{disposition}_unavailable",
        _eq("disposition", disposition),
        FramingStatus.UNAVAILABLE,
        None,
        None,
        ExampleSpec(None, (), False, None, False, disposition),
    )


FRAMING_RULES: Final = (
    _unavailable("credential_echo"),
    _unavailable("evidence_persistence_failure"),
    _reject(
        "missing_http_version",
        _eq("http_version_state", "missing"),
        _example(None),
    ),
    _reject(
        "unsupported_http_version", _eq("http_version_state", "unsupported"), _example("HTTP/3")
    ),
    _reject(
        "invalid_approved_header_surface",
        _eq("header_surface_state", "invalid"),
        ExampleSpec(
            "HTTP/2",
            (("content-type", "application/json"),),
            True,
            2,
            True,
            None,
            _MAX_HEADER_FIELDS + 1,
        ),
    ),
    _reject(
        "te_and_cl",
        _all(
            _in("content_length_state", "valid", "duplicate", "invalid"),
            _in("transfer_encoding_state", "chunked", "multiple", "invalid"),
        ),
        _example("HTTP/1.1", ("content-length", "2"), ("transfer-encoding", "chunked")),
    ),
    _reject(
        "duplicate_content_length",
        _eq("content_length_state", "duplicate"),
        _example("HTTP/1.1", ("content-length", "2"), ("content-length", "2")),
    ),
    _reject(
        "invalid_content_length",
        _eq("content_length_state", "invalid"),
        _example("HTTP/1.1", ("content-length", "02")),
    ),
    _reject(
        "multiple_transfer_encoding",
        _eq("transfer_encoding_state", "multiple"),
        _example("HTTP/1.1", ("transfer-encoding", "chunked"), ("transfer-encoding", "chunked")),
    ),
    _reject(
        "invalid_transfer_encoding",
        _eq("transfer_encoding_state", "invalid"),
        _example("HTTP/1.1", ("transfer-encoding", "gzip")),
    ),
    _reject(
        "http_2_transfer_encoding",
        _all(_eq("http_version_state", "http_2"), _eq("transfer_encoding_state", "chunked")),
        _example("HTTP/2", ("transfer-encoding", "chunked")),
    ),
    _reject(
        "compression_not_identity",
        _eq("content_encoding_state", "unsupported"),
        _example("HTTP/2", ("content-encoding", "gzip")),
    ),
    _reject(
        "http_1_1_missing_framing",
        _all(
            _eq("http_version_state", "http_1_1"),
            _eq("content_length_state", "absent"),
            _eq("transfer_encoding_state", "absent"),
        ),
        _example("HTTP/1.1"),
    ),
    _reject(
        "response_body_incomplete",
        _eq("body_complete", False),
        _example("HTTP/2", complete=False, count=None, raw=False),
    ),
    _reject(
        "content_length_mismatch",
        _all(
            _eq("content_length_state", "valid"),
            Atom("content_length_value", Op.FIELD_NE, "actual_body_byte_count"),
        ),
        _example("HTTP/1.1", ("content-length", "3")),
    ),
    _reject(
        "invalid_content_type",
        _in("content_type_state", "absent", "duplicate", "invalid"),
        ExampleSpec("HTTP/2", (("content-type", "text/html"),), True, 2, True),
    ),
    _reject(
        "raw_evidence_missing", _eq("raw_evidence_state", "missing"), _example("HTTP/2", raw=False)
    ),
    _accept(
        "accept_http_1_1_chunked",
        "http_1_1_chunked",
        _all(
            _eq("http_version_state", "http_1_1"),
            _eq("content_length_state", "absent"),
            _eq("transfer_encoding_state", "chunked"),
        ),
        _example("HTTP/1.1", ("transfer-encoding", "chunked")),
    ),
    _accept(
        "accept_http_1_1_content_length",
        "http_1_1_content_length",
        _all(
            _eq("http_version_state", "http_1_1"),
            _eq("content_length_state", "valid"),
            Atom("content_length_value", Op.FIELD_EQ, "actual_body_byte_count"),
        ),
        _example("HTTP/1.1", ("content-length", "2")),
    ),
    _accept(
        "accept_http_2_data",
        "http_2_data",
        _all(
            _eq("http_version_state", "http_2"),
            _eq("transfer_encoding_state", "absent"),
            _any(
                _eq("content_length_state", "absent"),
                _all(
                    _eq("content_length_state", "valid"),
                    Atom("content_length_value", Op.FIELD_EQ, "actual_body_byte_count"),
                ),
            ),
        ),
        _example("HTTP/2"),
    ),
)


@final
@dataclass(frozen=True, slots=True)
class FramingDecision:
    status: FramingStatus
    accepted_class: str | None
    rejection_code: str | None
    rule_key: str
    input_identity: str


def _facts(value: Observation) -> dict[str, object]:
    if type(value) is UnavailableObservation:
        return {
            "disposition": value.disposition,
            "http_status": value.http_status,
            "observation_available": False,
        }
    assert type(value) is FramingObservation
    return {
        **_observation_payload(value),
        "header_surface_state": value.headers.surface_state.value,
        "observation_available": True,
    }


def _evaluate(expression: Expression, facts: Mapping[str, object]) -> bool:
    if type(expression) is AllOf:
        return all(_evaluate(part, facts) for part in expression.parts)
    if type(expression) is AnyOf:
        return any(_evaluate(part, facts) for part in expression.parts)
    assert type(expression) is Atom
    actual = facts.get(expression.field)
    if expression.op is Op.EQ:
        return actual == expression.value and type(actual) is type(expression.value)
    if expression.op is Op.IN:
        assert type(expression.value) is tuple
        return actual in expression.value
    if expression.op is Op.TRUE:
        return actual is True
    if expression.op is Op.FALSE:
        return actual is False
    if expression.op is Op.PRESENT:
        return actual is not None
    if expression.op is Op.ABSENT:
        return actual is None
    other = facts.get(str(expression.value))
    if expression.op is Op.FIELD_NE:
        return actual is not None and other is not None and actual != other
    if expression.op is Op.FIELD_EQ:
        return actual is not None and other is not None and actual == other
    raise AssertionError("unknown declarative operation")


def _validate_observation(value: Observation) -> None:
    if type(value) is UnavailableObservation:
        if (
            type(value.disposition) is not str
            or type(value.http_status) is not int
            or type(value.input_identity) is not str
        ):
            raise ValueError("unavailable response status drift")
        expected = build_unavailable_observation(
            disposition=value.disposition, http_status=value.http_status
        )
        if value != expected:
            raise ValueError("unavailable input identity drift")
        return
    if (
        type(value) is not FramingObservation
        or type(value.disposition) is not str
        or type(value.http_status) is not int
        or type(value.http_version_state) is not HttpVersionState
        or not _exact_optional_str(value.observed_http_version)
        or type(value.headers) is not NormalizedHeaderFacts
        or not _valid_headers(value.headers)
        or type(value.raw_header_field_count) is not int
        or type(value.content_length_state) is not ContentLengthState
        or not _exact_optional_int(value.content_length_value)
        or type(value.transfer_encoding_state) is not TransferEncodingState
        or type(value.content_encoding_state) is not ContentEncodingState
        or type(value.content_type_state) is not ContentTypeState
        or type(value.body_complete) is not bool
        or not _exact_optional_int(value.actual_body_byte_count)
        or type(value.observed_body_bytes_lower_bound) is not int
        or type(value.raw_evidence_state) is not RawEvidenceState
        or not _exact_optional_str(value.raw_body_hash)
        or not _exact_optional_str(value.raw_relative_path)
        or not _exact_optional_str(value.raw_artifact_identity)
        or type(value.input_identity) is not str
    ):
        raise ValueError("framing observation type or header binding drift")
    if value.input_identity != _identity("m3-framing-input", _observation_payload(value)):
        raise ValueError("framing input identity drift")
    rebuilt = build_framing_observation(
        disposition=value.disposition,
        http_status=value.http_status,
        http_version=value.observed_http_version,
        headers=value.headers,
        raw_header_field_count=value.raw_header_field_count,
        body_complete=value.body_complete,
        actual_body_byte_count=value.actual_body_byte_count,
        observed_body_bytes_lower_bound=value.observed_body_bytes_lower_bound,
        raw_body_hash=value.raw_body_hash,
        raw_relative_path=value.raw_relative_path,
    )
    if value != rebuilt:
        raise ValueError("framing observation is noncanonical")


def classify_framing(value: Observation) -> FramingDecision:
    """Recompute the decision by first match; no supplied decision has authority."""

    _validate_observation(value)
    facts = _facts(value)
    for rule in FRAMING_RULES:
        if _evaluate(rule.condition, facts):
            return FramingDecision(
                rule.status,
                rule.accepted_class,
                rule.rejection_code,
                rule.key,
                value.input_identity,
            )
    return FramingDecision(
        FramingStatus.REJECTED,
        None,
        "invalid_unclassified",
        "invalid_unclassified",
        value.input_identity,
    )


def matching_rule_keys(value: Observation) -> tuple[str, ...]:
    """Return all active declarative rows in authority order for regression proof."""

    _validate_observation(value)
    facts = _facts(value)
    return tuple(rule.key for rule in FRAMING_RULES if _evaluate(rule.condition, facts))


def projection_matches(
    value: Observation,
    *,
    framing_status: str,
    accepted_framing_class: str | None,
    framing_rejection_code: str | None,
    framing_input_identity: str,
) -> bool:
    """Compare an untrusted stored/projected decision with fresh recomputation."""

    if (
        type(framing_status) is not str
        or not _exact_optional_str(accepted_framing_class)
        or not _exact_optional_str(framing_rejection_code)
        or type(framing_input_identity) is not str
    ):
        return False
    decision = classify_framing(value)
    return (
        (value.disposition != "success" or decision.status is FramingStatus.ACCEPTED)
        and framing_status == decision.status.value
        and accepted_framing_class == decision.accepted_class
        and framing_rejection_code == decision.rejection_code
        and framing_input_identity == decision.input_identity
    )


def canonical_observation_projection(value: Observation) -> dict[str, object]:
    """Project only freshly reconstructed facts for persistence or external evidence."""

    _validate_observation(value)
    decision = classify_framing(value)
    projection: dict[str, object]
    if type(value) is UnavailableObservation:
        projection = {
            "accepted_framing_class": None,
            "approved_header_names": APPROVED_HEADER_NAMES,
            "approved_header_names_identity": APPROVED_HEADER_NAMES_IDENTITY,
            "disposition": value.disposition,
            "framing_input_identity": value.input_identity,
            "framing_contract_identity": FRAMING_CONTRACT_IDENTITY,
            "framing_rejection_code": None,
            "framing_status": decision.status.value,
            "http_status": value.http_status,
            "normalized_content_encoding_values": None,
            "normalized_content_length_values": None,
            "normalized_content_type_values": None,
            "normalized_header_facts_identity": None,
            "normalized_header_names": (),
            "normalized_transfer_encoding_values": None,
            "normalized_x_request_id_values": None,
        }
        return {**projection, **legacy_v2_raw_projection(value)}
    projection = {
        **_observation_payload(value),
        "accepted_framing_class": decision.accepted_class,
        "approved_header_names": value.headers.approved_header_names,
        "approved_header_names_identity": value.headers.approved_header_names_identity,
        "framing_input_identity": value.input_identity,
        "framing_contract_identity": FRAMING_CONTRACT_IDENTITY,
        "framing_rejection_code": decision.rejection_code,
        "framing_status": decision.status.value,
        "header_surface_state": value.headers.surface_state.value,
        "normalized_content_encoding_values": _values(value.headers, "content-encoding"),
        "normalized_content_length_values": _values(value.headers, "content-length"),
        "normalized_content_type_values": _values(value.headers, "content-type"),
        "normalized_header_facts_identity": value.headers.facts_identity,
        "normalized_header_names": value.headers.observed_names,
        "normalized_transfer_encoding_values": _values(value.headers, "transfer-encoding"),
        "normalized_x_request_id_values": _values(value.headers, "x-request-id"),
    }
    return {**projection, **legacy_v2_raw_projection(value)}


LEGACY_RAW_FIELD_BINDINGS: Final = (
    ("body_byte_count", "actual_body_byte_count"),
    ("body_hash", "raw_body_hash"),
    ("body_relative_path", "raw_relative_path"),
)


def legacy_v2_raw_projection(
    value: Observation, legacy_values: Mapping[str, object] | None = None
) -> dict[str, object]:
    """Project and optionally validate the exact legacy raw-field mirror of V2 authority."""

    _validate_observation(value)
    projection: dict[str, object]
    if type(value) is UnavailableObservation:
        projection = {legacy: None for legacy, _ in LEGACY_RAW_FIELD_BINDINGS}
        projection["observed_body_bytes_lower_bound"] = None
    else:
        projection = {legacy: getattr(value, v2) for legacy, v2 in LEGACY_RAW_FIELD_BINDINGS}
        projection["observed_body_bytes_lower_bound"] = value.observed_body_bytes_lower_bound
    if legacy_values is not None and (
        type(legacy_values) is not dict
        or any(type(name) is not str for name in legacy_values)
        or frozenset(legacy_values) != frozenset(projection)
        or any(
            type(legacy_values[name]) is not type(expected) or legacy_values[name] != expected
            for name, expected in projection.items()
        )
    ):
        raise ValueError("legacy raw projection differs from canonical V2 authority")
    return projection


@final
@dataclass(frozen=True, slots=True)
class PersistedMutation:
    field: str
    value: object
    operation: str = "set"


class MutationKind(StrEnum):
    """Closed reason why one generated witness differs from canonical state."""

    INVALID = "invalid"
    NULL = "null"
    MISSING = "missing"
    TYPE = "type"
    CARDINALITY = "cardinality"
    MALFORMED = "malformed"
    CROSS_CONDITION = "cross_condition"


class ConsumerMutationValueKind(StrEnum):
    """Exact representation used to mutate one named consumer authority."""

    DECLARED = "declared"
    EXTERNAL_JSON_LIST = "external_json_list"
    BOOL_FOR_INT = "bool_for_int"
    LIST_FOR_TUPLE = "list_for_tuple"
    NONEXACT_STRING_SUBCLASS = "nonexact_string_subclass"
    NONEXACT_LIST_SUBCLASS = "nonexact_list_subclass"
    REMOVE = "remove"


class PersistedAuthorityValueKind(StrEnum):
    """Exact canonical built-in shape of one persisted V2 authority."""

    BOOL = "bool"
    INT = "int"
    STR = "str"
    STR_TUPLE = "str_tuple"


class PersistedAuthorityStorage(StrEnum):
    """Whether an authority is shared with V1 or introduced by V2."""

    COMMON = "common"
    V2_ONLY = "v2_only"


@final
@dataclass(frozen=True, slots=True)
class PersistedAuthorityCrossCondition:
    """One exact relational contradiction built only from canonical field values."""

    companion_field: str
    target_alternative: object
    companion_alternative: object


@final
@dataclass(frozen=True, slots=True)
class PersistedAuthorityFieldSpec:
    """Sole declarative inventory row for one persisted V2 authority field."""

    field: str
    value_kind: PersistedAuthorityValueKind
    storage: PersistedAuthorityStorage
    positive_rule_key: str
    mutation_kinds: tuple[MutationKind, ...]
    cross_condition: PersistedAuthorityCrossCondition | None


def _cross_condition(
    companion_field: str,
    target_alternative: object,
    companion_alternative: object,
) -> PersistedAuthorityCrossCondition:
    return PersistedAuthorityCrossCondition(
        companion_field,
        target_alternative,
        companion_alternative,
    )


def _authority_field(
    field: str,
    value_kind: PersistedAuthorityValueKind,
    *,
    storage: PersistedAuthorityStorage = PersistedAuthorityStorage.COMMON,
    positive_rule_key: str = "accept_http_2_data",
    cross_condition: PersistedAuthorityCrossCondition | None = None,
) -> PersistedAuthorityFieldSpec:
    mutation_kinds = (
        *((MutationKind.INVALID,) if value_kind is not PersistedAuthorityValueKind.BOOL else ()),
        MutationKind.NULL,
        MutationKind.MISSING,
        MutationKind.TYPE,
        *(
            (MutationKind.CARDINALITY, MutationKind.MALFORMED)
            if value_kind is PersistedAuthorityValueKind.STR_TUPLE
            else (
                (MutationKind.MALFORMED,) if value_kind is PersistedAuthorityValueKind.STR else ()
            )
        ),
        *((MutationKind.CROSS_CONDITION,) if cross_condition is not None else ()),
    )
    return PersistedAuthorityFieldSpec(
        field,
        value_kind,
        storage,
        positive_rule_key,
        mutation_kinds,
        cross_condition,
    )


# This is the sole persisted-field authority. Projection, persistence field sets,
# and generated positive/mutation coverage are all derived from these rows.
PERSISTED_AUTHORITY_FIELD_REGISTRY: Final = (
    _authority_field(
        "disposition",
        PersistedAuthorityValueKind.STR,
        cross_condition=_cross_condition("error_code", "response_invalid", "deadline_exceeded"),
    ),
    _authority_field(
        "error_code",
        PersistedAuthorityValueKind.STR,
        positive_rule_key="missing_http_version",
        cross_condition=_cross_condition(
            "disposition", "deadline_exceeded", "authentication_failed"
        ),
    ),
    _authority_field(
        "credential_echo",
        PersistedAuthorityValueKind.BOOL,
        cross_condition=_cross_condition("disposition", True, "response_invalid"),
    ),
    _authority_field(
        "http_status",
        PersistedAuthorityValueKind.INT,
        cross_condition=_cross_condition(
            "framing_input_identity",
            201,
            "m3-framing-input:sha256:" + "f" * 64,
        ),
    ),
    _authority_field(
        "body_complete",
        PersistedAuthorityValueKind.BOOL,
        cross_condition=_cross_condition("actual_body_byte_count", False, 3),
    ),
    _authority_field(
        "body_byte_count",
        PersistedAuthorityValueKind.INT,
        cross_condition=_cross_condition("actual_body_byte_count", 3, 4),
    ),
    _authority_field(
        "body_hash",
        PersistedAuthorityValueKind.STR,
        cross_condition=_cross_condition(
            "raw_body_hash", "sha256:" + "e" * 64, "sha256:" + "f" * 64
        ),
    ),
    _authority_field(
        "body_relative_path",
        PersistedAuthorityValueKind.STR,
        cross_condition=_cross_condition(
            "raw_relative_path", "raw/legacy-alternate.json", "raw/v2-alternate.json"
        ),
    ),
    _authority_field(
        "observed_body_bytes_lower_bound",
        PersistedAuthorityValueKind.INT,
        cross_condition=_cross_condition("actual_body_byte_count", 3, 4),
    ),
    _authority_field("approved_header_names", PersistedAuthorityValueKind.STR_TUPLE),
    _authority_field(
        "approved_header_names_identity",
        PersistedAuthorityValueKind.STR,
        storage=PersistedAuthorityStorage.V2_ONLY,
    ),
    _authority_field(
        "normalized_header_names",
        PersistedAuthorityValueKind.STR_TUPLE,
        storage=PersistedAuthorityStorage.V2_ONLY,
        cross_condition=_cross_condition(
            "normalized_header_facts_identity",
            ("content-type", "x-request-id"),
            "m3-normalized-header-facts:sha256:" + "f" * 64,
        ),
    ),
    _authority_field(
        "normalized_content_encoding_values",
        PersistedAuthorityValueKind.STR_TUPLE,
        storage=PersistedAuthorityStorage.V2_ONLY,
        cross_condition=_cross_condition(
            "normalized_header_facts_identity",
            ("identity",),
            "m3-normalized-header-facts:sha256:" + "e" * 64,
        ),
    ),
    _authority_field(
        "normalized_content_length_values",
        PersistedAuthorityValueKind.STR_TUPLE,
        storage=PersistedAuthorityStorage.V2_ONLY,
        cross_condition=_cross_condition(
            "normalized_header_facts_identity",
            ("2",),
            "m3-normalized-header-facts:sha256:" + "d" * 64,
        ),
    ),
    _authority_field(
        "normalized_content_type_values",
        PersistedAuthorityValueKind.STR_TUPLE,
        storage=PersistedAuthorityStorage.V2_ONLY,
        cross_condition=_cross_condition(
            "normalized_header_facts_identity",
            ("application/json; charset=utf-8",),
            "m3-normalized-header-facts:sha256:" + "c" * 64,
        ),
    ),
    _authority_field(
        "normalized_transfer_encoding_values",
        PersistedAuthorityValueKind.STR_TUPLE,
        storage=PersistedAuthorityStorage.V2_ONLY,
        cross_condition=_cross_condition(
            "normalized_header_facts_identity",
            ("chunked",),
            "m3-normalized-header-facts:sha256:" + "b" * 64,
        ),
    ),
    _authority_field(
        "normalized_x_request_id_values",
        PersistedAuthorityValueKind.STR_TUPLE,
        storage=PersistedAuthorityStorage.V2_ONLY,
        cross_condition=_cross_condition(
            "normalized_header_facts_identity",
            ("request-alternate",),
            "m3-normalized-header-facts:sha256:" + "a" * 64,
        ),
    ),
    _authority_field(
        "normalized_header_facts_identity",
        PersistedAuthorityValueKind.STR,
        storage=PersistedAuthorityStorage.V2_ONLY,
        cross_condition=_cross_condition(
            "normalized_header_names",
            "m3-normalized-header-facts:sha256:" + "9" * 64,
            ("content-type", "x-request-id"),
        ),
    ),
    _authority_field(
        "raw_header_field_count",
        PersistedAuthorityValueKind.INT,
        storage=PersistedAuthorityStorage.V2_ONLY,
        cross_condition=_cross_condition(
            "normalized_header_facts_identity",
            2,
            "m3-normalized-header-facts:sha256:" + "8" * 64,
        ),
    ),
    _authority_field(
        "framing_contract_identity",
        PersistedAuthorityValueKind.STR,
        storage=PersistedAuthorityStorage.V2_ONLY,
    ),
    _authority_field(
        "framing_input_identity",
        PersistedAuthorityValueKind.STR,
        storage=PersistedAuthorityStorage.V2_ONLY,
        cross_condition=_cross_condition("http_status", "m3-framing-input:sha256:" + "7" * 64, 201),
    ),
    _authority_field(
        "http_version_state",
        PersistedAuthorityValueKind.STR,
        storage=PersistedAuthorityStorage.V2_ONLY,
        cross_condition=_cross_condition("observed_http_version", "http_1_1", "HTTP/3"),
    ),
    _authority_field(
        "observed_http_version",
        PersistedAuthorityValueKind.STR,
        storage=PersistedAuthorityStorage.V2_ONLY,
        cross_condition=_cross_condition("http_version_state", "HTTP/1.1", "unsupported"),
    ),
    _authority_field(
        "header_surface_state",
        PersistedAuthorityValueKind.STR,
        storage=PersistedAuthorityStorage.V2_ONLY,
        cross_condition=_cross_condition(
            "normalized_header_facts_identity",
            "invalid",
            "m3-normalized-header-facts:sha256:" + "6" * 64,
        ),
    ),
    _authority_field(
        "content_length_state",
        PersistedAuthorityValueKind.STR,
        storage=PersistedAuthorityStorage.V2_ONLY,
        cross_condition=_cross_condition("content_length_value", "duplicate", 3),
    ),
    _authority_field(
        "content_length_value",
        PersistedAuthorityValueKind.INT,
        storage=PersistedAuthorityStorage.V2_ONLY,
        positive_rule_key="accept_http_1_1_content_length",
        cross_condition=_cross_condition("content_length_state", 3, "duplicate"),
    ),
    _authority_field(
        "transfer_encoding_state",
        PersistedAuthorityValueKind.STR,
        storage=PersistedAuthorityStorage.V2_ONLY,
        cross_condition=_cross_condition(
            "normalized_transfer_encoding_values", "chunked", ("gzip",)
        ),
    ),
    _authority_field(
        "content_encoding_state",
        PersistedAuthorityValueKind.STR,
        storage=PersistedAuthorityStorage.V2_ONLY,
        cross_condition=_cross_condition(
            "normalized_content_encoding_values", "identity", ("gzip",)
        ),
    ),
    _authority_field(
        "content_type_state",
        PersistedAuthorityValueKind.STR,
        storage=PersistedAuthorityStorage.V2_ONLY,
        cross_condition=_cross_condition(
            "normalized_content_type_values",
            "invalid",
            ("application/json; charset=utf-8",),
        ),
    ),
    _authority_field(
        "actual_body_byte_count",
        PersistedAuthorityValueKind.INT,
        storage=PersistedAuthorityStorage.V2_ONLY,
        cross_condition=_cross_condition("observed_body_bytes_lower_bound", 3, 4),
    ),
    _authority_field(
        "raw_evidence_state",
        PersistedAuthorityValueKind.STR,
        storage=PersistedAuthorityStorage.V2_ONLY,
        cross_condition=_cross_condition(
            "raw_artifact_identity",
            "missing",
            "m3-provider-raw-artifact:sha256:" + "5" * 64,
        ),
    ),
    _authority_field(
        "raw_body_hash",
        PersistedAuthorityValueKind.STR,
        storage=PersistedAuthorityStorage.V2_ONLY,
        cross_condition=_cross_condition(
            "raw_artifact_identity",
            "sha256:" + "4" * 64,
            "m3-provider-raw-artifact:sha256:" + "3" * 64,
        ),
    ),
    _authority_field(
        "raw_relative_path",
        PersistedAuthorityValueKind.STR,
        storage=PersistedAuthorityStorage.V2_ONLY,
        cross_condition=_cross_condition(
            "raw_artifact_identity",
            "raw/alternate.json",
            "m3-provider-raw-artifact:sha256:" + "2" * 64,
        ),
    ),
    _authority_field(
        "raw_artifact_identity",
        PersistedAuthorityValueKind.STR,
        storage=PersistedAuthorityStorage.V2_ONLY,
        cross_condition=_cross_condition(
            "raw_body_hash",
            "m3-provider-raw-artifact:sha256:" + "1" * 64,
            "sha256:" + "2" * 64,
        ),
    ),
    _authority_field(
        "framing_status",
        PersistedAuthorityValueKind.STR,
        storage=PersistedAuthorityStorage.V2_ONLY,
        cross_condition=_cross_condition("accepted_framing_class", "rejected", "http_1_1_chunked"),
    ),
    _authority_field(
        "accepted_framing_class",
        PersistedAuthorityValueKind.STR,
        storage=PersistedAuthorityStorage.V2_ONLY,
        cross_condition=_cross_condition("framing_status", "http_1_1_chunked", "rejected"),
    ),
    _authority_field(
        "framing_rejection_code",
        PersistedAuthorityValueKind.STR,
        storage=PersistedAuthorityStorage.V2_ONLY,
        positive_rule_key="missing_http_version",
        cross_condition=_cross_condition("framing_status", "invalid_content_type", "accepted"),
    ),
)

PERSISTED_AUTHORITY_FIELDS: Final = tuple(spec.field for spec in PERSISTED_AUTHORITY_FIELD_REGISTRY)
V2_ONLY_LEDGER_COLUMNS: Final = tuple(
    spec.field
    for spec in PERSISTED_AUTHORITY_FIELD_REGISTRY
    if spec.storage is PersistedAuthorityStorage.V2_ONLY
)
V2_PERSISTED_COLUMNS: Final = (
    "schema_version",
    "event_kind",
    *PERSISTED_AUTHORITY_FIELDS,
)


def persisted_authority_field_specs() -> tuple[PersistedAuthorityFieldSpec, ...]:
    """Return the immutable registry that owns V2 persisted authority coverage."""

    return PERSISTED_AUTHORITY_FIELD_REGISTRY


@final
@dataclass(frozen=True, slots=True)
class MutationConsumerTarget:
    """Direct boundary paths for the exact authority fields mutated by one consumer."""

    consumer: str
    authority_fields: tuple[str, ...]
    direct_target_paths: tuple[str, ...]
    mutation_operations: tuple[str, ...]
    mutation_value_kinds: tuple[ConsumerMutationValueKind, ...]


@final
@dataclass(frozen=True, slots=True)
class ConsumerMutationWitness:
    """Actual named-field mutation applied at one consumer boundary."""

    case_id: str
    consumer: str
    target_authority_field: str
    field: str
    direct_target_path: str
    operation: str
    value_kind: ConsumerMutationValueKind
    canonical_value: object
    mutated_value: object


def apply_persisted_mutations(
    values: Mapping[str, object], mutations: tuple[PersistedMutation, ...]
) -> dict[str, object]:
    """Apply one generated adversarial mutation set without changing its authority."""

    if (
        type(values) is not dict
        or any(type(name) is not str for name in values)
        or type(mutations) is not tuple
    ):
        raise TypeError("generated mutation input is invalid")
    names = tuple(
        item.field
        for item in mutations
        if type(item) is PersistedMutation
        and type(item.field) is str
        and item.operation in {"set", "remove"}
    )
    if len(names) != len(mutations) or len(set(names)) != len(names):
        raise ValueError("generated mutations must have unique exact fields")
    result = dict(values)
    for item in mutations:
        if item.operation == "remove":
            if item.field not in result:
                raise ValueError("generated missing-field mutation target is absent")
            del result[item.field]
        else:
            if item.field not in result:
                raise ValueError("generated set mutation target is absent")
            result[item.field] = item.value
    return result


@final
@dataclass(frozen=True, slots=True)
class NoncanonicalVariant:
    case_id: str
    mutations: tuple[PersistedMutation, ...]
    expected_admitted: bool = False
    consumers: tuple[str, ...] = ("python", "repository", "postgres")
    target_authority_field: str = ""
    mutation_kind: MutationKind = MutationKind.INVALID
    expected_first_match_rule: str = ""
    expected_status: FramingStatus = FramingStatus.REJECTED
    expected_class: str | None = None
    expected_code: str | None = None
    valid_witness_value: object = None
    valid_witness_values: tuple[object, ...] = ()
    cross_condition_fields: tuple[str, ...] = ()
    consumer_targets: tuple[MutationConsumerTarget, ...] = ()


_PERSISTED_RUNTIME_CONSUMERS: Final = ("repository", "postgres")
_BOOL_FOR_INT_PROJECTION_FIELDS: Final = tuple(
    spec.field
    for spec in PERSISTED_AUTHORITY_FIELD_REGISTRY
    if spec.value_kind is PersistedAuthorityValueKind.INT
)
_STR_SUBCLASS_PROJECTION_FIELDS: Final = tuple(
    spec.field
    for spec in PERSISTED_AUTHORITY_FIELD_REGISTRY
    if spec.value_kind is PersistedAuthorityValueKind.STR
)

_FINALIZER_DIRECT_TARGET_PATHS: Final = {
    "accepted_framing_class": "projected_decision.accepted_class",
    "body_complete": "observation.body_complete",
    "credential_echo": "observation.credential_echo",
    "framing_input_identity": "projected_decision.input_identity",
    "framing_rejection_code": "projected_decision.rejection_code",
    "framing_status": "projected_decision.status",
    "http_status": "observation.http_status",
    "observed_body_bytes_lower_bound": "observation.observed_body_bytes_lower_bound",
    "observed_http_version": "observation.response_http_version",
    "raw_body_hash": "raw_body_hash",
    "raw_header_field_count": "observation.response_header_field_count",
    "raw_relative_path": "raw_relative_path",
}

_PYTHON_CLASSIFIER_DIRECT_TARGET_PATHS: Final = {
    "actual_body_byte_count": "FramingObservation.actual_body_byte_count",
    "approved_header_names": "NormalizedHeaderFacts.approved_header_names",
    "approved_header_names_identity": "NormalizedHeaderFacts.approved_header_names_identity",
    "body_complete": "FramingObservation.body_complete",
    "content_encoding_state": "FramingObservation.content_encoding_state",
    "content_length_state": "FramingObservation.content_length_state",
    "content_length_value": "FramingObservation.content_length_value",
    "content_type_state": "FramingObservation.content_type_state",
    "disposition": "FramingObservation.disposition",
    "framing_input_identity": "FramingObservation.input_identity",
    "header_surface_state": "NormalizedHeaderFacts.surface_state",
    "http_status": "FramingObservation.http_status",
    "http_version_state": "FramingObservation.http_version_state",
    "normalized_header_facts_identity": "NormalizedHeaderFacts.facts_identity",
    "normalized_header_names": "NormalizedHeaderFacts.observed_names",
    "observed_body_bytes_lower_bound": "FramingObservation.observed_body_bytes_lower_bound",
    "observed_http_version": "FramingObservation.observed_http_version",
    "raw_artifact_identity": "FramingObservation.raw_artifact_identity",
    "raw_body_hash": "FramingObservation.raw_body_hash",
    "raw_evidence_state": "FramingObservation.raw_evidence_state",
    "raw_header_field_count": "FramingObservation.raw_header_field_count",
    "raw_relative_path": "FramingObservation.raw_relative_path",
    "transfer_encoding_state": "FramingObservation.transfer_encoding_state",
}

_PYTHON_CLASSIFIER_ENUM_FIELDS: Final = {
    "content_encoding_state": ContentEncodingState,
    "content_length_state": ContentLengthState,
    "content_type_state": ContentTypeState,
    "header_surface_state": HeaderSurfaceState,
    "http_version_state": HttpVersionState,
    "raw_evidence_state": RawEvidenceState,
    "transfer_encoding_state": TransferEncodingState,
}


def _consumer_target_path(consumer: str, field: str) -> str | None:
    if consumer == "python":
        return _PYTHON_CLASSIFIER_DIRECT_TARGET_PATHS.get(field)
    if consumer == "repository":
        return f"ProviderAttemptEvent.{field}"
    if consumer == "postgres":
        return f"m3_provider_attempt_events.{field}"
    if consumer == "external" and field in _EXTERNAL_PROVIDER_EVENT_MUTATION_FIELDS:
        return f"provider-attempt-projection.events[*].{field}"
    if consumer == "finalizer":
        return _FINALIZER_DIRECT_TARGET_PATHS.get(field)
    return None


def _mutation_kind(
    mutations: tuple[PersistedMutation, ...], *, valid_witness_value: object
) -> MutationKind:
    if len(mutations) > 1:
        return MutationKind.CROSS_CONDITION
    mutation = mutations[0]
    if mutation.operation == "remove":
        return MutationKind.MISSING
    if mutation.value is None:
        return MutationKind.NULL
    return (
        MutationKind.TYPE
        if type(mutation.value) is not type(valid_witness_value)
        else MutationKind.INVALID
    )


def _consumer_canonical_value(consumer: str, field: str, value: object) -> object:
    if consumer == "python" and field in _PYTHON_CLASSIFIER_ENUM_FIELDS:
        if type(value) is not str:
            raise AssertionError("python classifier enum witness is not canonical")
        return _PYTHON_CLASSIFIER_ENUM_FIELDS[field](value)
    if consumer == "external" and type(value) is tuple:
        return list(value)
    if consumer == "finalizer":
        if field == "framing_status":
            if type(value) is not str:
                raise AssertionError("finalizer framing status witness is not canonical")
            return FramingStatus(value)
        if field in {"normalized_header_names", "normalized_content_type_values"}:
            if type(value) is not tuple or not value:
                raise AssertionError("finalizer header witness is not canonical")
            return value[0]
    return value


def _consumer_value_kind(
    consumer: str,
    mutation: PersistedMutation,
    canonical_value: object,
    mutation_kind: MutationKind,
) -> ConsumerMutationValueKind:
    if mutation.operation == "remove":
        return ConsumerMutationValueKind.REMOVE
    if mutation_kind is MutationKind.TYPE:
        if type(canonical_value) is int:
            return ConsumerMutationValueKind.BOOL_FOR_INT
        if isinstance(canonical_value, str):
            return ConsumerMutationValueKind.NONEXACT_STRING_SUBCLASS
        if type(canonical_value) is tuple:
            return ConsumerMutationValueKind.LIST_FOR_TUPLE
        if type(canonical_value) is list:
            return ConsumerMutationValueKind.NONEXACT_LIST_SUBCLASS
    if consumer == "external" and type(canonical_value) is list and type(mutation.value) is tuple:
        return ConsumerMutationValueKind.EXTERNAL_JSON_LIST
    return ConsumerMutationValueKind.DECLARED


def _consumer_mutated_value(
    consumer: str,
    mutation: PersistedMutation,
    value_kind: ConsumerMutationValueKind,
    canonical_value: object,
) -> object:
    if value_kind is ConsumerMutationValueKind.BOOL_FOR_INT:
        return True
    if value_kind is ConsumerMutationValueKind.NONEXACT_STRING_SUBCLASS:
        if not isinstance(canonical_value, str):
            raise AssertionError("string-subclass mutation lacks string witness")
        return _NoncanonicalString(canonical_value)
    if value_kind is ConsumerMutationValueKind.LIST_FOR_TUPLE:
        if type(canonical_value) is not tuple:
            raise AssertionError("list-for-tuple mutation lacks tuple witness")
        return list(canonical_value)
    if value_kind is ConsumerMutationValueKind.NONEXACT_LIST_SUBCLASS:
        if type(canonical_value) is not list:
            raise AssertionError("external list-subclass mutation lacks list witness")
        return _NoncanonicalList(canonical_value)
    if value_kind is ConsumerMutationValueKind.EXTERNAL_JSON_LIST:
        if type(mutation.value) is not tuple:
            raise AssertionError("external JSON-list mutation lacks tuple witness")
        return list(mutation.value)
    return mutation.value


def _enrich_noncanonical_variant(
    rule: FramingRule,
    variant: NoncanonicalVariant,
    *,
    canonical: Mapping[str, object],
) -> NoncanonicalVariant:
    fields = tuple(item.field for item in variant.mutations)
    if any(field not in canonical for field in fields):
        raise AssertionError("generated mutation lacks an exact valid witness field")
    target_field = fields[0]
    valid_witness_values = tuple(canonical[field] for field in fields)
    valid_witness_value = valid_witness_values[0]
    inferred_kind = _mutation_kind(variant.mutations, valid_witness_value=valid_witness_value)
    kind = variant.mutation_kind if variant.case_id.startswith("primitive:") else inferred_kind
    cross_fields = fields if kind is MutationKind.CROSS_CONDITION else ()
    consumers = tuple(consumer for consumer in variant.consumers if consumer != "python")
    if all(field in _PYTHON_CLASSIFIER_DIRECT_TARGET_PATHS for field in fields) and all(
        mutation.operation != "remove" for mutation in variant.mutations
    ):
        consumers = ("python", *consumers)
    if all(field in _EXTERNAL_PROVIDER_EVENT_MUTATION_FIELDS for field in fields):
        consumers = (*consumers, "external")
    targets: list[MutationConsumerTarget] = []
    for consumer in consumers:
        paths = tuple(_consumer_target_path(consumer, field) for field in fields)
        if any(path is None for path in paths):
            raise AssertionError(
                f"generated consumer {consumer!r} cannot directly mutate {fields!r}"
            )
        canonical_values = tuple(
            _consumer_canonical_value(consumer, field, canonical[field]) for field in fields
        )
        value_kinds = tuple(
            _consumer_value_kind(consumer, mutation, canonical_value, kind)
            for mutation, canonical_value in zip(variant.mutations, canonical_values, strict=True)
        )
        targets.append(
            MutationConsumerTarget(
                consumer,
                fields,
                tuple(path for path in paths if path is not None),
                tuple(mutation.operation for mutation in variant.mutations),
                value_kinds,
            )
        )
    enriched = replace(
        variant,
        consumers=consumers,
        target_authority_field=target_field,
        mutation_kind=kind,
        expected_first_match_rule=rule.key,
        expected_status=rule.status,
        expected_class=rule.accepted_class,
        expected_code=rule.rejection_code,
        valid_witness_value=valid_witness_value,
        valid_witness_values=valid_witness_values,
        cross_condition_fields=cross_fields,
        consumer_targets=tuple(targets),
    )
    validate_generated_mutation_case(enriched)
    return enriched


def validate_generated_mutation_case(case: NoncanonicalVariant) -> None:
    """Reject mutation metadata that overstates its target or consumer reachability."""

    if (
        type(case) is not NoncanonicalVariant
        or type(case.case_id) is not str
        or not case.case_id
        or type(case.mutations) is not tuple
        or not case.mutations
        or type(case.expected_admitted) is not bool
        or case.expected_admitted
        or type(case.consumers) is not tuple
        or not case.consumers
        or any(type(consumer) is not str for consumer in case.consumers)
        or len(case.consumers) != len(set(case.consumers))
        or type(case.target_authority_field) is not str
        or not case.target_authority_field
        or type(case.mutation_kind) is not MutationKind
        or type(case.expected_first_match_rule) is not str
        or not case.expected_first_match_rule
        or type(case.expected_status) is not FramingStatus
        or not _exact_optional_str(case.expected_class)
        or not _exact_optional_str(case.expected_code)
        or type(case.valid_witness_values) is not tuple
        or type(case.cross_condition_fields) is not tuple
        or type(case.consumer_targets) is not tuple
    ):
        raise ValueError("generated mutation metadata is noncanonical")
    fields = tuple(mutation.field for mutation in case.mutations)
    if any(
        type(mutation) is not PersistedMutation
        or type(mutation.field) is not str
        or mutation.operation not in {"set", "remove"}
        for mutation in case.mutations
    ) or len(fields) != len(set(fields)):
        raise ValueError("generated mutation set is noncanonical")
    if (
        len(case.valid_witness_values) != len(fields)
        or case.valid_witness_value is not case.valid_witness_values[0]
    ):
        raise ValueError("generated valid witness inventory drift")
    if case.mutation_kind is MutationKind.CROSS_CONDITION and case.case_id.startswith("primitive:"):
        try:
            cross_spec = _persisted_authority_spec(case.target_authority_field)
        except AssertionError as error:
            raise ValueError("cross-condition target authority is unknown") from error
        declared_cross = cross_spec.cross_condition
        if (
            declared_cross is None
            or len(fields) != 2
            or fields != (case.target_authority_field, declared_cross.companion_field)
            or case.cross_condition_fields != fields
            or any(mutation.operation != "set" for mutation in case.mutations)
            or type(case.mutations[0].value) is not type(declared_cross.target_alternative)
            or case.mutations[0].value != declared_cross.target_alternative
            or type(case.mutations[1].value) is not type(declared_cross.companion_alternative)
            or case.mutations[1].value != declared_cross.companion_alternative
            or not persisted_authority_value_is_canonical(
                case.target_authority_field, case.mutations[0].value
            )
            or not persisted_authority_value_is_canonical(fields[1], case.mutations[1].value)
        ):
            raise ValueError("cross-condition mutation fields differ from declared authority")
    elif case.mutation_kind is not MutationKind.CROSS_CONDITION:
        inferred_kind = _mutation_kind(case.mutations, valid_witness_value=case.valid_witness_value)
        applicable_kinds: tuple[MutationKind, ...] = ()
        if case.case_id.startswith("primitive:"):
            try:
                applicable_kinds = _persisted_authority_spec(
                    case.target_authority_field
                ).mutation_kinds
            except AssertionError as error:
                raise ValueError("mutation field differs from declared target authority") from error
        if (
            fields != (case.target_authority_field,)
            or case.cross_condition_fields
            or (
                case.case_id.startswith("primitive:") and case.mutation_kind not in applicable_kinds
            )
            or (
                case.mutation_kind not in {MutationKind.CARDINALITY, MutationKind.MALFORMED}
                and case.mutation_kind is not inferred_kind
            )
            or (
                case.mutation_kind in {MutationKind.CARDINALITY, MutationKind.MALFORMED}
                and inferred_kind is not MutationKind.INVALID
            )
        ):
            raise ValueError("mutation field differs from declared target authority")
    elif len(fields) < 2 or case.cross_condition_fields != fields:
        raise ValueError("cross-condition mutation fields differ from declared authority")
    if tuple(target.consumer for target in case.consumer_targets) != case.consumers:
        raise ValueError("mutation consumer inventory drift")
    canonical_by_field = dict(zip(fields, case.valid_witness_values, strict=True))
    mutated_by_field = apply_persisted_mutations(canonical_by_field, case.mutations)
    for mutation in case.mutations:
        if mutation.operation == "remove":
            if mutation.field in mutated_by_field:
                raise ValueError("generated structural removal did not remove its exact target")
            continue
        before = canonical_by_field[mutation.field]
        after = mutated_by_field[mutation.field]
        if type(before) is type(after) and before == after:
            raise ValueError("generated mutation is a canonical named-field no-op")
    for target in case.consumer_targets:
        expected_paths = tuple(_consumer_target_path(target.consumer, field) for field in fields)
        expected_canonical_values = tuple(
            _consumer_canonical_value(target.consumer, field, value)
            for field, value in zip(fields, case.valid_witness_values, strict=True)
        )
        expected_value_kinds = tuple(
            _consumer_value_kind(target.consumer, mutation, canonical_value, case.mutation_kind)
            for mutation, canonical_value in zip(
                case.mutations, expected_canonical_values, strict=True
            )
        )
        if (
            type(target) is not MutationConsumerTarget
            or target.authority_fields != fields
            or any(path is None for path in expected_paths)
            or target.direct_target_paths != expected_paths
            or target.mutation_operations
            != tuple(mutation.operation for mutation in case.mutations)
            or target.mutation_value_kinds != expected_value_kinds
        ):
            raise ValueError("mutation consumer path differs from direct authority")
        for witness in _consumer_mutation_witnesses(case, target):
            if witness.operation == "remove":
                continue
            if (
                type(witness.mutated_value) is type(witness.canonical_value)
                and witness.mutated_value == witness.canonical_value
            ):
                raise ValueError("generated consumer mutation is a canonical no-op")


def _consumer_mutation_witnesses(
    case: NoncanonicalVariant,
    target: MutationConsumerTarget,
    canonical_values: tuple[object, ...] | None = None,
) -> tuple[ConsumerMutationWitness, ...]:
    if canonical_values is None:
        canonical_values = tuple(
            _consumer_canonical_value(target.consumer, field, value)
            for field, value in zip(
                target.authority_fields,
                case.valid_witness_values,
                strict=True,
            )
        )
    return tuple(
        ConsumerMutationWitness(
            case.case_id,
            target.consumer,
            case.target_authority_field,
            mutation.field,
            path,
            mutation.operation,
            value_kind,
            canonical_value,
            _runtime_consumer_mutated_value(
                case,
                target.consumer,
                mutation,
                value_kind,
                canonical_value,
            ),
        )
        for mutation, path, value_kind, canonical_value in zip(
            case.mutations,
            target.direct_target_paths,
            target.mutation_value_kinds,
            canonical_values,
            strict=True,
        )
    )


def _same_consumer_canonical_shape(actual: object, declared: object) -> bool:
    if type(actual) is not type(declared):
        return False
    if type(declared) is list:
        actual_items: tuple[object, ...] = tuple(cast(list[object], actual))
        declared_items: tuple[object, ...] = tuple(cast(list[object], declared))
        if not declared_items:
            return not actual_items
        expected_types = {type(item) for item in declared_items}
        return len(expected_types) == 1 and all(
            type(item) in expected_types for item in actual_items
        )
    if type(declared) is tuple:
        actual_items = cast(tuple[object, ...], actual)
        declared_items = cast(tuple[object, ...], declared)
        if not declared_items:
            return not actual_items
        expected_types = {type(item) for item in declared_items}
        return len(expected_types) == 1 and all(
            type(item) in expected_types for item in actual_items
        )
    return True


def _alternate_invalid_value(field: str, canonical_value: object) -> object:
    if type(canonical_value) is bool:
        return not canonical_value
    if type(canonical_value) is int:
        return canonical_value + 1 if canonical_value < POSTGRES_BIGINT_MAX else -1
    if isinstance(canonical_value, str):
        first = f"invalid:{field}"
        return first if first != canonical_value else f"invalid-alt:{field}"
    if type(canonical_value) is tuple:
        first_tuple = (f"invalid:{field}",)
        return first_tuple if first_tuple != canonical_value else (f"invalid-alt:{field}",)
    if type(canonical_value) is list:
        first_list = [f"invalid:{field}"]
        return first_list if first_list != canonical_value else [f"invalid-alt:{field}"]
    raise ValueError("runtime canonical mutation type is unsupported")


def _runtime_consumer_mutated_value(
    case: NoncanonicalVariant,
    consumer: str,
    mutation: PersistedMutation,
    value_kind: ConsumerMutationValueKind,
    canonical_value: object,
) -> object:
    declared = _consumer_mutated_value(consumer, mutation, value_kind, canonical_value)
    if case.mutation_kind is MutationKind.CROSS_CONDITION:
        return declared
    if mutation.operation == "remove" or case.mutation_kind is MutationKind.NULL:
        return declared
    if case.mutation_kind is MutationKind.TYPE:
        return declared
    if type(declared) is type(canonical_value) and declared == canonical_value:
        return _alternate_invalid_value(mutation.field, canonical_value)
    return declared


def generated_consumer_mutation_witness(
    case: NoncanonicalVariant,
    consumer: str,
    canonical_values: Mapping[str, object] | None = None,
) -> tuple[ConsumerMutationWitness, ...]:
    """Return exact direct mutations in one consumer's native representation."""

    validate_generated_mutation_case(case)
    if type(consumer) is not str:
        raise ValueError("generated mutation consumer is noncanonical")
    target = next(
        (item for item in case.consumer_targets if item.consumer == consumer),
        None,
    )
    if target is None:
        raise ValueError("generated mutation does not reach requested consumer")
    actual_values: tuple[object, ...] | None = None
    if canonical_values is not None:
        if type(canonical_values) is not dict or any(
            type(field) is not str for field in canonical_values
        ):
            raise ValueError("consumer canonical mapping is noncanonical")
        if any(field not in canonical_values for field in target.authority_fields):
            raise ValueError("consumer canonical target field is missing")
        actual_values = tuple(canonical_values[field] for field in target.authority_fields)
        declared_values = tuple(
            _consumer_canonical_value(consumer, field, value)
            for field, value in zip(
                target.authority_fields,
                case.valid_witness_values,
                strict=True,
            )
        )
        if any(
            not _same_consumer_canonical_shape(actual, declared)
            for actual, declared in zip(actual_values, declared_values, strict=True)
        ):
            raise ValueError("consumer canonical target type differs from declared witness")
    witnesses = _consumer_mutation_witnesses(case, target, actual_values)
    for witness in witnesses:
        if witness.operation == "remove":
            continue
        if (
            type(witness.mutated_value) is type(witness.canonical_value)
            and witness.mutated_value == witness.canonical_value
        ):
            raise ValueError("generated consumer mutation is a canonical no-op")
    return witnesses


_GOVERNED_PRIMITIVE_FIELDS: Final = PERSISTED_AUTHORITY_FIELDS
_EXTERNAL_PROVIDER_EVENT_MUTATION_FIELDS: Final = frozenset(PERSISTED_AUTHORITY_FIELDS)


def governed_primitive_fields() -> tuple[str, ...]:
    """Return the exact projection primitives covered by the generated matrix."""

    return _GOVERNED_PRIMITIVE_FIELDS


def _persisted_authority_spec(field: str) -> PersistedAuthorityFieldSpec:
    match = next(
        (spec for spec in PERSISTED_AUTHORITY_FIELD_REGISTRY if spec.field == field),
        None,
    )
    if match is None:
        raise AssertionError(f"unknown governed primitive field: {field}")
    return match


_TYPED_IDENTITY = re.compile(r"[a-z0-9-]+:sha256:[0-9a-f]{64}")


def persisted_authority_value_is_canonical(field: str, value: object) -> bool:
    """Validate one field in isolation, without applying any relational binding."""

    try:
        spec = _persisted_authority_spec(field)
    except AssertionError:
        return False
    expected_type = {
        PersistedAuthorityValueKind.BOOL: bool,
        PersistedAuthorityValueKind.INT: int,
        PersistedAuthorityValueKind.STR: str,
        PersistedAuthorityValueKind.STR_TUPLE: tuple,
    }[spec.value_kind]
    if type(value) is not expected_type:
        return False
    if type(value) is bool:
        return True
    if type(value) is int:
        upper_bound = {
            "http_status": 599,
            "body_byte_count": MAX_RAW_RESPONSE_BYTES,
            "actual_body_byte_count": MAX_RAW_RESPONSE_BYTES,
            "observed_body_bytes_lower_bound": MAX_OBSERVED_BODY_BYTES_LOWER_BOUND,
        }.get(field, POSTGRES_BIGINT_MAX)
        lower_bound = 100 if field == "http_status" else 0
        return lower_bound <= value <= upper_bound
    if type(value) is tuple:
        if not _exact_str_tuple(value):
            return False
        if field == "approved_header_names":
            return value == APPROVED_HEADER_NAMES
        if field == "normalized_header_names":
            return (
                len(value) == len(set(value))
                and tuple(sorted(value)) == value
                and all(name in APPROVED_HEADER_NAMES for name in value)
            )
        return (
            len(value) <= _MAX_APPROVED_OCCURRENCES
            and sum(len(item.encode("ascii", errors="ignore")) for item in value)
            <= _MAX_APPROVED_HEADER_BYTES
            and all(
                item.isascii()
                and len(item.encode("ascii")) <= _MAX_HEADER_VALUE_BYTES
                and all(32 <= ord(character) <= 126 for character in item)
                for item in value
            )
        )
    assert type(value) is str
    if field == "disposition":
        return value in {
            "started",
            "interrupted_unknown_after_start",
            *V2_TERMINAL_DISPOSITIONS,
        }
    if field == "error_code":
        return value in {
            "interrupted_unknown_after_start",
            *(item for item in V2_TERMINAL_DISPOSITIONS if item != "success"),
        }
    if field in {"body_hash", "raw_body_hash"}:
        return _SHA256.fullmatch(value) is not None
    if field in {"body_relative_path", "raw_relative_path"}:
        return provider_raw_relative_path_is_canonical(value)
    if field == "approved_header_names_identity":
        return value == APPROVED_HEADER_NAMES_IDENTITY
    if field == "framing_contract_identity":
        return value == FRAMING_CONTRACT_IDENTITY
    identity_prefixes = {
        "normalized_header_facts_identity": "m3-normalized-header-facts",
        "framing_input_identity": "m3-framing-input",
        "raw_artifact_identity": "m3-provider-raw-artifact",
    }
    if field in identity_prefixes:
        return _TYPED_IDENTITY.fullmatch(value) is not None and value.startswith(
            identity_prefixes[field] + ":sha256:"
        )
    enum_types = {
        "http_version_state": HttpVersionState,
        "header_surface_state": HeaderSurfaceState,
        "content_length_state": ContentLengthState,
        "transfer_encoding_state": TransferEncodingState,
        "content_encoding_state": ContentEncodingState,
        "content_type_state": ContentTypeState,
        "raw_evidence_state": RawEvidenceState,
        "framing_status": FramingStatus,
    }
    enum_type = enum_types.get(field)
    if enum_type is not None:
        return value in {item.value for item in enum_type}
    if field == "observed_http_version":
        return (
            1 <= len(value) <= 16
            and value.isascii()
            and all(33 <= ord(character) <= 126 for character in value)
        )
    if field == "accepted_framing_class":
        return value in {
            rule.accepted_class for rule in FRAMING_RULES if rule.accepted_class is not None
        }
    if field == "framing_rejection_code":
        return value in {
            rule.rejection_code for rule in FRAMING_RULES if rule.rejection_code is not None
        }
    return False


def _invalid_primitive_value(field: str, valid_value: object) -> object:
    if type(valid_value) is bool:
        raise AssertionError(f"boolean authority has no exact invalid primitive: {field}")
    if type(valid_value) is int:
        return 99 if field == "http_status" else -1
    if type(valid_value) is str:
        return f"invalid:{field}"
    if type(valid_value) is tuple:
        return (f"invalid:{field}",)
    raise AssertionError(f"unaccounted governed primitive type: {field}")


def _type_drift_primitive_value(field: str, valid_value: object) -> object:
    if type(valid_value) is bool:
        return 0 if valid_value else 1
    if type(valid_value) is int:
        return True
    if type(valid_value) is str:
        return _NoncanonicalString(valid_value)
    if type(valid_value) is tuple:
        return list(valid_value)
    raise AssertionError(f"unaccounted governed primitive type: {field}")


def _cardinality_primitive_value(field: str, valid_value: object) -> object:
    if type(valid_value) is not tuple:
        raise AssertionError(f"non-container authority has cardinality mutation: {field}")
    return (*valid_value, valid_value[-1]) if valid_value else (f"cardinality:{field}",)


def _malformed_primitive_value(field: str, valid_value: object) -> object:
    if type(valid_value) is str:
        if field in {"body_hash", "raw_body_hash"}:
            return "sha256:not-a-digest"
        if field in {"body_relative_path", "raw_relative_path"}:
            return "../outside"
        return ""
    if type(valid_value) is tuple:
        return (f" malformed:{field} ",)
    raise AssertionError(f"authority has no malformed canonical mutation: {field}")


def _primitive_case_id(kind: MutationKind, field: str) -> str:
    if kind is MutationKind.TYPE:
        if field in {"body_complete", "credential_echo"}:
            return f"primitive:int_for_bool:{field}"
        if field in _BOOL_FOR_INT_PROJECTION_FIELDS:
            return f"primitive:bool_for_int:{field}"
        aliases = {
            "approved_header_names": "approved_header_name",
            "normalized_header_names": "normalized_header_name",
            "normalized_content_type_values": "header_occurrence_value",
        }
        return f"primitive:str_subclass:{aliases.get(field, field)}"
    return f"primitive:{kind.value}:{field}"


def _primitive_consumers_for(fields: tuple[str, ...], kind: MutationKind) -> tuple[str, ...]:
    consumers: tuple[str, ...] = (
        ()
        if kind is MutationKind.MISSING
        else (("repository",) if kind is MutationKind.TYPE else _PERSISTED_RUNTIME_CONSUMERS)
    )
    if kind is not MutationKind.MISSING and all(
        field in _PYTHON_CLASSIFIER_DIRECT_TARGET_PATHS for field in fields
    ):
        consumers = ("python", *consumers)
    if kind is not MutationKind.MISSING and all(
        field in _FINALIZER_DIRECT_TARGET_PATHS for field in fields
    ):
        consumers = (*consumers, "finalizer")
    return consumers


def _primitive_variants(
    canonical: Mapping[str, object], fields: tuple[str, ...]
) -> tuple[NoncanonicalVariant, ...]:
    variants: list[NoncanonicalVariant] = []
    for field in fields:
        spec = _persisted_authority_spec(field)
        valid_value = canonical[field]
        expected_type = {
            PersistedAuthorityValueKind.BOOL: bool,
            PersistedAuthorityValueKind.INT: int,
            PersistedAuthorityValueKind.STR: str,
            PersistedAuthorityValueKind.STR_TUPLE: tuple,
        }[spec.value_kind]
        if type(valid_value) is not expected_type:
            raise AssertionError(f"canonical positive witness type drift: {field}")
        by_kind: dict[MutationKind, PersistedMutation] = {
            MutationKind.NULL: PersistedMutation(field, None),
            MutationKind.MISSING: PersistedMutation(field, None, "remove"),
            MutationKind.TYPE: PersistedMutation(
                field, _type_drift_primitive_value(field, valid_value)
            ),
        }
        if MutationKind.INVALID in spec.mutation_kinds:
            by_kind[MutationKind.INVALID] = PersistedMutation(
                field, _invalid_primitive_value(field, valid_value)
            )
        if MutationKind.CARDINALITY in spec.mutation_kinds:
            by_kind[MutationKind.CARDINALITY] = PersistedMutation(
                field, _cardinality_primitive_value(field, valid_value)
            )
        if MutationKind.MALFORMED in spec.mutation_kinds:
            by_kind[MutationKind.MALFORMED] = PersistedMutation(
                field, _malformed_primitive_value(field, valid_value)
            )
        variants.extend(
            NoncanonicalVariant(
                _primitive_case_id(kind, field),
                (by_kind[kind],),
                False,
                _primitive_consumers_for((field,), kind),
                mutation_kind=kind,
            )
            for kind in spec.mutation_kinds
            if kind is not MutationKind.CROSS_CONDITION
        )
        if spec.cross_condition is not None:
            cross = spec.cross_condition
            companion = cross.companion_field
            if companion == field or companion not in canonical:
                raise AssertionError(f"cross-condition companion drift: {field}")
            if not persisted_authority_value_is_canonical(field, cross.target_alternative):
                raise AssertionError(f"cross-condition target is not locally canonical: {field}")
            if not persisted_authority_value_is_canonical(companion, cross.companion_alternative):
                raise AssertionError(f"cross-condition companion is not locally canonical: {field}")
            cross_fields = (field, companion)
            variants.append(
                NoncanonicalVariant(
                    _primitive_case_id(MutationKind.CROSS_CONDITION, field),
                    (
                        PersistedMutation(field, cross.target_alternative),
                        PersistedMutation(companion, cross.companion_alternative),
                    ),
                    False,
                    _primitive_consumers_for(cross_fields, MutationKind.CROSS_CONDITION),
                    mutation_kind=MutationKind.CROSS_CONDITION,
                )
            )
    return tuple(variants)


@final
@dataclass(frozen=True, slots=True)
class PrecedenceVariant:
    case_id: str
    observation: Observation
    active_rule_keys: tuple[str, ...]
    expected_status: FramingStatus
    expected_class: str | None
    expected_code: str | None
    expected_admitted: bool = True


@dataclass(frozen=True, slots=True)
class FactFreeEventRule:
    event_kind: str
    disposition: str


@dataclass(frozen=True, slots=True)
class V2EventMetadataRule:
    event_kind: str
    disposition: str
    credential_echo: bool
    error_code: str | None


class CanonicalV2EventMetadata(TypedDict):
    """Exact credential/error projection derived from one V2 topology row."""

    credential_echo: bool
    error_code: str | None


V2_EVENT_METADATA_REQUIRED_FIELDS: Final = (
    "event_kind",
    "disposition",
    "credential_echo",
    "error_code",
)
V2_EVENT_METADATA_PROJECTION_FIELDS: Final = ("credential_echo", "error_code")
V2_TERMINAL_DISPOSITIONS: Final = (
    "success",
    "retryable_status",
    "transport_unavailable",
    "deadline_exceeded",
    "response_invalid",
    "response_too_large",
    "credential_echo",
    "authentication_failed",
    "provider_rejected",
    "candidate_invalid",
    "evidence_persistence_failure",
    "validation_internal_failure",
)
V2_EVENT_METADATA_RULES: Final = (
    V2EventMetadataRule("START", "started", False, None),
    V2EventMetadataRule(
        "RECOVERY",
        "interrupted_unknown_after_start",
        False,
        "interrupted_unknown_after_start",
    ),
    *(
        V2EventMetadataRule(
            "TERMINAL",
            disposition,
            disposition == "credential_echo",
            None if disposition == "success" else disposition,
        )
        for disposition in V2_TERMINAL_DISPOSITIONS
    ),
)


def canonical_v2_event_metadata(*, event_kind: str, disposition: str) -> CanonicalV2EventMetadata:
    """Return the sole credential/error metadata projection for one V2 event."""

    if type(event_kind) is not str or type(disposition) is not str:
        raise ValueError("V2 event metadata topology is invalid")
    match = next(
        (
            rule
            for rule in V2_EVENT_METADATA_RULES
            if rule.event_kind == event_kind and rule.disposition == disposition
        ),
        None,
    )
    if match is None:
        raise ValueError("V2 event metadata topology is invalid")
    if type(match.credential_echo) is not bool or not (
        match.error_code is None or type(match.error_code) is str
    ):
        raise AssertionError("V2 event metadata row has noncanonical primitive types")
    return {
        "credential_echo": match.credential_echo,
        "error_code": match.error_code,
    }


def v2_event_metadata_matches(values: Mapping[str, object]) -> bool:
    """Validate credential/error metadata from the shared declarative rows."""

    if type(values) is not dict:
        return False
    keys = tuple(values.keys())
    if (
        len(keys) != len(V2_EVENT_METADATA_REQUIRED_FIELDS)
        or any(type(key) is not str for key in keys)
        or frozenset(keys) != frozenset(V2_EVENT_METADATA_REQUIRED_FIELDS)
    ):
        return False
    event_kind = values["event_kind"]
    disposition = values["disposition"]
    credential_echo = values["credential_echo"]
    error_code = values["error_code"]
    if (
        type(event_kind) is not str
        or type(disposition) is not str
        or type(credential_echo) is not bool
        or not (error_code is None or type(error_code) is str)
    ):
        return False
    try:
        expected = canonical_v2_event_metadata(event_kind=event_kind, disposition=disposition)
    except ValueError:
        return False
    return credential_echo is expected["credential_echo"] and error_code == expected["error_code"]


FACT_FREE_V2_EVENT_RULES: Final = (
    FactFreeEventRule("START", "started"),
    FactFreeEventRule("RECOVERY", "interrupted_unknown_after_start"),
    FactFreeEventRule("TERMINAL", "transport_unavailable"),
    FactFreeEventRule("TERMINAL", "deadline_exceeded"),
    FactFreeEventRule("TERMINAL", "response_invalid"),
    FactFreeEventRule("TERMINAL", "response_too_large"),
    FactFreeEventRule("TERMINAL", "authentication_failed"),
    FactFreeEventRule("TERMINAL", "provider_rejected"),
)
FACT_FREE_LEGACY_EXPECTED: Final = (
    ("http_status", None),
    ("body_complete", None),
    ("body_byte_count", None),
    ("body_hash", None),
    ("body_relative_path", None),
    ("observed_body_bytes_lower_bound", None),
    ("approved_header_names", ()),
)


@final
@dataclass(frozen=True, slots=True)
class FactFreeEventCase:
    case_id: str
    schema_version: str
    event_kind: str
    disposition: str
    expected_match: bool
    mutations: tuple[PersistedMutation, ...] = ()


def canonical_fact_free_v2_event_projection(
    *, event_kind: str, disposition: str
) -> dict[str, object]:
    """Return the sole legacy-plus-V2 shape for an event with no response facts."""

    if (
        type(event_kind) is not str
        or type(disposition) is not str
        or FactFreeEventRule(event_kind, disposition) not in FACT_FREE_V2_EVENT_RULES
    ):
        raise ValueError("fact-free V2 event topology is invalid")
    candidate = {
        "schema_version": "M3_PROVIDER_ATTEMPT_EVENT_V2",
        "event_kind": event_kind,
        "disposition": disposition,
        **canonical_v2_event_metadata(event_kind=event_kind, disposition=disposition),
        **dict(FACT_FREE_LEGACY_EXPECTED),
        **dict.fromkeys(V2_ONLY_LEDGER_COLUMNS),
    }
    return {
        "schema_version": candidate["schema_version"],
        "event_kind": candidate["event_kind"],
        **{field: candidate[field] for field in PERSISTED_AUTHORITY_FIELDS},
    }


def fact_free_v2_event_matches(values: Mapping[str, object]) -> bool:
    """Validate the exact fact-free event projection without trusting event callers."""

    if type(values) is not dict:
        return False
    event_kind = values.get("event_kind")
    disposition = values.get("disposition")
    if type(event_kind) is not str or type(disposition) is not str:
        return False
    try:
        expected = canonical_fact_free_v2_event_projection(
            event_kind=event_kind,
            disposition=disposition,
        )
    except ValueError:
        return False
    keys = tuple(values.keys())
    if (
        len(keys) != len(expected)
        or any(type(key) is not str for key in keys)
        or frozenset(keys) != frozenset(expected)
        or not v2_event_metadata_matches(
            {name: values[name] for name in V2_EVENT_METADATA_REQUIRED_FIELDS}
        )
    ):
        return False
    return all(
        type(values[name]) is type(expected_value) and values[name] == expected_value
        for name, expected_value in expected.items()
    )


def fact_free_event_case_projection(case: FactFreeEventCase) -> dict[str, object]:
    """Materialize a generated fact-free positive or adversarial projection."""

    if (
        type(case) is not FactFreeEventCase
        or type(case.case_id) is not str
        or type(case.schema_version) is not str
        or type(case.event_kind) is not str
        or type(case.disposition) is not str
        or type(case.expected_match) is not bool
        or type(case.mutations) is not tuple
    ):
        raise ValueError("fact-free event case has noncanonical primitive types")
    if case.schema_version == "M3_PROVIDER_ATTEMPT_EVENT_V1":
        projection = canonical_fact_free_v2_event_projection(
            event_kind=case.event_kind, disposition=case.disposition
        )
        projection["schema_version"] = case.schema_version
    else:
        projection = canonical_fact_free_v2_event_projection(
            event_kind=case.event_kind, disposition=case.disposition
        )
    return apply_persisted_mutations(projection, case.mutations)


@final
@dataclass(frozen=True, slots=True)
class GeneratedContractCase:
    rule_key: str
    observation: Observation
    expected_status: FramingStatus
    expected_class: str | None
    expected_code: str | None
    expected_admitted: bool = True
    precedence_variants: tuple[PrecedenceVariant, ...] = ()
    noncanonical_variants: tuple[NoncanonicalVariant, ...] = ()
    fact_free_event_cases: tuple[FactFreeEventCase, ...] = ()


def generated_mutation_witness(value: Observation) -> dict[str, object]:
    """Return exact canonical values available to generated boundary mutations."""

    candidate = {
        **dict.fromkeys(PERSISTED_AUTHORITY_FIELDS),
        **canonical_observation_projection(value),
        **canonical_v2_event_metadata(event_kind="TERMINAL", disposition=value.disposition),
    }
    if type(value) is FramingObservation:
        candidate["raw_body_hash"] = value.raw_body_hash
        candidate["raw_relative_path"] = value.raw_relative_path
    else:
        candidate["raw_body_hash"] = None
        candidate["raw_relative_path"] = None
    return {field: candidate[field] for field in PERSISTED_AUTHORITY_FIELDS}


def _observation_for_example(spec: ExampleSpec, status: FramingStatus) -> Observation:
    if spec.unavailable_disposition is not None:
        return build_unavailable_observation(
            disposition=spec.unavailable_disposition, http_status=200
        )
    raw_header_field_count = (
        spec.raw_header_field_count
        if spec.raw_header_field_count is not None
        else len(spec.header_items)
    )
    headers = normalize_approved_headers(
        spec.header_items, raw_header_field_count=raw_header_field_count
    )
    return build_framing_observation(
        disposition="success" if status is FramingStatus.ACCEPTED else "response_invalid",
        http_status=200,
        http_version=spec.http_version,
        headers=headers,
        raw_header_field_count=raw_header_field_count,
        body_complete=spec.body_complete,
        actual_body_byte_count=spec.actual_body_byte_count,
        observed_body_bytes_lower_bound=(spec.actual_body_byte_count if spec.body_complete else 0),
        raw_body_hash=("sha256:" + "0" * 64) if spec.persist_raw else None,
        raw_relative_path="raw/case.json" if spec.persist_raw else None,
    )


def _merge_examples(first: ExampleSpec, second: ExampleSpec) -> ExampleSpec:
    content_types = [
        item
        for item in (*first.header_items, *second.header_items)
        if item[0].lower() == "content-type"
    ]
    selected_type = next(
        (item for item in content_types if item[1] != "application/json"),
        ("content-type", "application/json"),
    )
    other_headers = tuple(
        item
        for item in (*first.header_items, *second.header_items)
        if item[0].lower() != "content-type"
    )
    complete = first.body_complete and second.body_complete
    raw = complete and first.persist_raw and second.persist_raw
    count = first.actual_body_byte_count if complete else None
    items = (selected_type, *other_headers)
    raw_header_field_count = max(
        len(items),
        first.raw_header_field_count or len(first.header_items),
        second.raw_header_field_count or len(second.header_items),
    )
    return ExampleSpec(
        first.http_version,
        items,
        complete,
        count,
        raw,
        None,
        raw_header_field_count,
    )


def _precedence_variants(rule_index: int) -> tuple[PrecedenceVariant, ...]:
    first = FRAMING_RULES[rule_index]
    if first.status is not FramingStatus.REJECTED:
        return ()
    variants: list[PrecedenceVariant] = []
    for second in FRAMING_RULES[rule_index + 1 :]:
        if second.status is not FramingStatus.REJECTED:
            continue
        try:
            observation = _observation_for_example(
                _merge_examples(first.example, second.example), FramingStatus.REJECTED
            )
        except ValueError:
            continue
        facts = _facts(observation)
        if not (
            _evaluate(first.condition, facts)
            and _evaluate(second.condition, facts)
            and classify_framing(observation).rule_key == first.key
        ):
            continue
        decision = classify_framing(observation)
        variants.append(
            PrecedenceVariant(
                f"precedence:{first.key}+{second.key}",
                observation,
                (first.key, second.key),
                decision.status,
                decision.accepted_class,
                decision.rejection_code,
            )
        )
    return tuple(variants)


def _noncanonical_variants(rule: FramingRule) -> tuple[NoncanonicalVariant, ...]:
    observation = _observation_for_example(rule.example, rule.status)
    canonical = generated_mutation_witness(observation)
    variants: list[NoncanonicalVariant] = []
    if rule.key == "credential_echo_unavailable":
        variants.extend(
            (
                NoncanonicalVariant(
                    "event_metadata:credential_echo_false",
                    (PersistedMutation("credential_echo", False),),
                    False,
                    ("repository", "postgres"),
                ),
                NoncanonicalVariant(
                    "event_metadata:credential_echo_integer_one",
                    (PersistedMutation("credential_echo", 1),),
                    False,
                    ("python", "repository"),
                ),
            )
        )
    if rule.key == "evidence_persistence_failure_unavailable":
        variants.extend(
            (
                NoncanonicalVariant(
                    "event_metadata:nonsuccess_error_null",
                    (PersistedMutation("error_code", None),),
                    False,
                    ("repository", "postgres"),
                ),
                NoncanonicalVariant(
                    "event_metadata:nonsuccess_error_foreign",
                    (PersistedMutation("error_code", "response_invalid"),),
                    False,
                    ("repository", "postgres"),
                ),
            )
        )
    if rule.status is FramingStatus.ACCEPTED:
        variants.extend(
            (
                NoncanonicalVariant(
                    f"{rule.key}:accepted_incomplete_rawless",
                    tuple(
                        PersistedMutation(name, value)
                        for name, value in (
                            ("body_complete", False),
                            ("actual_body_byte_count", None),
                            ("raw_evidence_state", "missing"),
                            ("raw_body_hash", None),
                            ("raw_relative_path", None),
                            ("raw_artifact_identity", None),
                        )
                    ),
                ),
                NoncanonicalVariant(
                    f"{rule.key}:missing_raw_artifact",
                    (PersistedMutation("raw_artifact_identity", None),),
                ),
            )
        )
    if rule.rejection_code == "content_length_mismatch":
        variants.append(
            NoncanonicalVariant(
                "content_length_mismatch:null_actual_incomplete",
                (
                    PersistedMutation("body_complete", False),
                    PersistedMutation("actual_body_byte_count", None),
                    PersistedMutation("raw_evidence_state", "missing"),
                    PersistedMutation("raw_body_hash", None),
                    PersistedMutation("raw_relative_path", None),
                    PersistedMutation("raw_artifact_identity", None),
                ),
            )
        )
    if rule.rejection_code == "invalid_content_type":
        variants.append(
            NoncanonicalVariant(
                "media_drift:foreign_accepted_decision",
                (
                    PersistedMutation("framing_status", "accepted"),
                    PersistedMutation("accepted_framing_class", "http_2_data"),
                    PersistedMutation("framing_rejection_code", None),
                ),
                False,
                ("python", "repository", "postgres", "finalizer"),
            )
        )
    if rule.key == "accept_http_2_data":
        foreign_legacy_values = {
            "body_byte_count": 3,
            "body_hash": "sha256:" + "f" * 64,
            "body_relative_path": "raw/foreign.json",
            "observed_body_bytes_lower_bound": 3,
        }
        variants.extend(
            (
                NoncanonicalVariant(
                    "approved_header_authority_drift",
                    (
                        PersistedMutation(
                            "approved_header_names_identity",
                            "m3-approved-header-names:sha256:" + "f" * 64,
                        ),
                    ),
                ),
                NoncanonicalVariant(
                    "unapproved_header_used_in_framing",
                    (PersistedMutation("normalized_header_names", ("content-type", "x-foreign")),),
                ),
                NoncanonicalVariant(
                    "framing_input_identity_drift",
                    (
                        PersistedMutation(
                            "framing_input_identity", "m3-framing-input:sha256:" + "f" * 64
                        ),
                    ),
                    False,
                    ("python", "repository", "postgres", "finalizer"),
                ),
                NoncanonicalVariant(
                    "decision_drift",
                    (PersistedMutation("accepted_framing_class", "http_1_1_chunked"),),
                    False,
                    ("python", "repository", "postgres", "finalizer"),
                ),
                NoncanonicalVariant(
                    "raw_header_field_count_drift",
                    (PersistedMutation("raw_header_field_count", 2),),
                    False,
                    ("python", "repository", "postgres", "finalizer"),
                ),
                NoncanonicalVariant(
                    "event_metadata:non_echo_credential_true",
                    (PersistedMutation("credential_echo", True),),
                    False,
                    ("repository", "postgres"),
                ),
                NoncanonicalVariant(
                    "event_metadata:credential_echo_integer_zero",
                    (PersistedMutation("credential_echo", 0),),
                    False,
                    ("python", "repository"),
                ),
                NoncanonicalVariant(
                    "event_metadata:success_error_nonnull",
                    (PersistedMutation("error_code", "success"),),
                    False,
                    ("repository", "postgres"),
                ),
                *(
                    NoncanonicalVariant(
                        f"legacy_raw_projection:{field}_drift",
                        (PersistedMutation(field, foreign_value),),
                        False,
                        ("repository", "postgres"),
                    )
                    for field, foreign_value in foreign_legacy_values.items()
                ),
                NoncanonicalVariant(
                    "legacy_raw_projection:internally_consistent_foreign_tuple",
                    tuple(
                        PersistedMutation(field, foreign_value)
                        for field, foreign_value in foreign_legacy_values.items()
                    ),
                    False,
                    ("repository", "postgres"),
                ),
            )
        )
    registry_fields = tuple(
        spec.field
        for spec in PERSISTED_AUTHORITY_FIELD_REGISTRY
        if spec.positive_rule_key == rule.key
    )
    variants.extend(_primitive_variants(canonical, registry_fields))
    return tuple(
        _enrich_noncanonical_variant(rule, variant, canonical=canonical) for variant in variants
    )


def _fact_free_event_cases() -> tuple[FactFreeEventCase, ...]:
    positive = tuple(
        FactFreeEventCase(
            f"fact_free_v2:{rule.event_kind.lower()}:{rule.disposition}",
            "M3_PROVIDER_ATTEMPT_EVENT_V2",
            rule.event_kind,
            rule.disposition,
            True,
        )
        for rule in FACT_FREE_V2_EVENT_RULES
    )
    return (
        *positive,
        FactFreeEventCase(
            "fact_free_v2:http_status_smuggling",
            "M3_PROVIDER_ATTEMPT_EVENT_V2",
            "TERMINAL",
            "transport_unavailable",
            False,
            (PersistedMutation("http_status", 503),),
        ),
        FactFreeEventCase(
            "fact_free_v2:v2_fact_smuggling",
            "M3_PROVIDER_ATTEMPT_EVENT_V2",
            "START",
            "started",
            False,
            (PersistedMutation("framing_status", "rejected"),),
        ),
        FactFreeEventCase(
            "fact_free_v1:v2_absent",
            "M3_PROVIDER_ATTEMPT_EVENT_V1",
            "START",
            "started",
            True,
        ),
    )


def generated_contract_cases() -> tuple[GeneratedContractCase, ...]:
    """Generate positive, precedence, mutation, unavailable, and V1 witnesses."""

    cases = []
    for index, rule in enumerate(FRAMING_RULES):
        observation = _observation_for_example(rule.example, rule.status)
        cases.append(
            GeneratedContractCase(
                rule.key,
                observation,
                rule.status,
                rule.accepted_class,
                rule.rejection_code,
                True,
                _precedence_variants(index),
                _noncanonical_variants(rule),
                _fact_free_event_cases() if index == 0 else (),
            )
        )
    return tuple(cases)


def framing_contract_identity() -> str:
    """Return the canonical identity of constants, ordered expressions, and outcomes."""

    def expression_payload(expression: Expression) -> object:
        if type(expression) is Atom:
            return ["atom", expression.field, expression.op.value, expression.value]
        if type(expression) is AllOf:
            return ["all", [expression_payload(part) for part in expression.parts]]
        assert type(expression) is AnyOf
        return ["any", [expression_payload(part) for part in expression.parts]]

    payload = {
        "approved_header_names": list(APPROVED_HEADER_NAMES),
        "approved_header_names_identity": APPROVED_HEADER_NAMES_IDENTITY,
        "approved_json_media_types": list(APPROVED_JSON_MEDIA_TYPES),
        "bounds": {
            "approved_header_bytes": _MAX_APPROVED_HEADER_BYTES,
            "approved_occurrences_per_name": _MAX_APPROVED_OCCURRENCES,
            "header_fields": _MAX_HEADER_FIELDS,
            "header_value_bytes": _MAX_HEADER_VALUE_BYTES,
            "observed_body_bytes_lower_bound": MAX_OBSERVED_BODY_BYTES_LOWER_BOUND,
            "postgres_bigint_max": POSTGRES_BIGINT_MAX,
            "raw_response_bytes": MAX_RAW_RESPONSE_BYTES,
        },
        "raw_body_persistence": {
            "content_encoding_states": ["absent", "identity"],
            "header_surface_state": "valid",
        },
        "fact_free_v2_event_rows": [
            [rule.event_kind, rule.disposition] for rule in FACT_FREE_V2_EVENT_RULES
        ],
        "fact_free_v2_legacy_expected": list(FACT_FREE_LEGACY_EXPECTED),
        "v2_event_metadata_rows": [
            [
                rule.event_kind,
                rule.disposition,
                rule.credential_echo,
                rule.error_code,
            ]
            for rule in V2_EVENT_METADATA_RULES
        ],
        "v2_event_metadata_mapping": {
            "comparison": "exact-dict-keys-and-builtin-values-before-equality-v2",
            "projection_fields": list(V2_EVENT_METADATA_PROJECTION_FIELDS),
            "required_fields": [
                ["event_kind", "str"],
                ["disposition", "str"],
                ["credential_echo", "bool"],
                ["error_code", "str-or-none"],
            ],
        },
        "identity_serializations": {
            "canonical_json": "ascii-sorted-keys-compact-v1",
            "framing_input_fields": [
                "actual_body_byte_count",
                "body_complete",
                "content_encoding_state",
                "content_length_state",
                "content_length_value",
                "content_type_state",
                "disposition",
                "header_facts_identity",
                "http_status",
                "http_version_state",
                "observed_body_bytes_lower_bound",
                "observed_http_version",
                "raw_artifact_identity",
                "raw_evidence_state",
                "raw_header_field_count",
                "transfer_encoding_state",
            ],
            "normalized_header_occurrences": "exact-approved-arrays-plus-raw-count-v2",
            "raw_artifact_fields": ["body_byte_count", "body_hash", "relative_path"],
            "unavailable_input_fields": ["disposition", "framing_facts", "http_status"],
        },
        "canonical_primitive_types": {
            "bool_fields": ["body_complete", "credential_echo", "expected_match"],
            "container_shapes": [
                "exact-dict-for-public-mapping-projections",
                "exact-header-occurrence-dataclass",
                "exact-tuple-for-header-authority-occurrences-and-names",
                "exact-tuple-for-generated-mutations",
            ],
            "int_fields": list(_BOOL_FOR_INT_PROJECTION_FIELDS),
            "optional": "exact-none-or-exact-declared-builtin",
            "str_fields": [
                *_STR_SUBCLASS_PROJECTION_FIELDS,
                "approved_header_name",
                "framing_rejection_code",
                "header_occurrence_name",
                "header_occurrence_value",
                "normalized_header_name",
                "raw_body_hash",
                "raw_relative_path",
                "schema_version",
            ],
        },
        "legacy_raw_field_bindings": list(LEGACY_RAW_FIELD_BINDINGS),
        "normalization": "strict-ascii-approved-header-surface-exact-builtins-v2",
        "persisted_authority_field_registry": [
            [
                spec.field,
                spec.value_kind.value,
                spec.storage.value,
                spec.positive_rule_key,
                [kind.value for kind in spec.mutation_kinds],
                (
                    None
                    if spec.cross_condition is None
                    else [
                        spec.cross_condition.companion_field,
                        spec.cross_condition.target_alternative,
                        spec.cross_condition.companion_alternative,
                    ]
                ),
            ]
            for spec in PERSISTED_AUTHORITY_FIELD_REGISTRY
        ],
        "postgres_identity": "postgresql-18-core-sha256-convert-to-utf8-v1",
        "provider_raw_relative_path": (
            "ascii-printable-1-1024-forward-slash-components-no-empty-dot-dotdot-colon-"
            "trailing-dot-space-or-windows-device-alias-v2"
        ),
        "windows_reserved_path_base_names": list(_WINDOWS_RESERVED_PATH_BASE_NAMES),
        "regression_matrix": "persisted-authority-generated-mutations-v8",
        "rules": [
            [
                rule.key,
                expression_payload(rule.condition),
                rule.status.value,
                rule.accepted_class,
                rule.rejection_code,
                [
                    rule.example.http_version,
                    list(rule.example.header_items),
                    rule.example.body_complete,
                    rule.example.actual_body_byte_count,
                    rule.example.persist_raw,
                    rule.example.unavailable_disposition,
                    rule.example.raw_header_field_count,
                ],
            ]
            for rule in FRAMING_RULES
        ],
        "version": "M3_PROVIDER_FRAMING_AUTHORITY_V2",
    }
    return _identity("m3-provider-framing-contract", payload)


FRAMING_CONTRACT_IDENTITY: Final = framing_contract_identity()


def _sql_literal(value: object) -> str:
    if value is None:
        return "NULL"
    if type(value) is bool:
        return "TRUE" if value else "FALSE"
    if type(value) is int:
        return str(value)
    if type(value) is str:
        return "'" + value.replace("'", "''") + "'"
    raise TypeError("unsupported SQL literal")


def _sql(expression: Expression) -> str:
    if type(expression) is AllOf:
        return "(" + " AND ".join(_sql(part) for part in expression.parts) + ") IS TRUE"
    if type(expression) is AnyOf:
        return "(" + " OR ".join(_sql(part) for part in expression.parts) + ") IS TRUE"
    assert type(expression) is Atom
    field = expression.field
    if expression.op is Op.EQ:
        return f"{field} IS NOT DISTINCT FROM {_sql_literal(expression.value)}"
    if expression.op is Op.IN:
        assert type(expression.value) is tuple
        values = ",".join(_sql_literal(item) for item in expression.value)
        return f"({field} IN ({values})) IS TRUE"
    if expression.op is Op.TRUE:
        return f"{field} IS TRUE"
    if expression.op is Op.FALSE:
        return f"{field} IS FALSE"
    if expression.op is Op.PRESENT:
        return f"{field} IS NOT NULL"
    if expression.op is Op.ABSENT:
        return f"{field} IS NULL"
    other = str(expression.value)
    if expression.op is Op.FIELD_NE:
        return f"({field} IS NOT NULL AND {other} IS NOT NULL AND {field} IS DISTINCT FROM {other}) IS TRUE"
    if expression.op is Op.FIELD_EQ:
        return f"({field} IS NOT NULL AND {other} IS NOT NULL AND {field} IS NOT DISTINCT FROM {other}) IS TRUE"
    raise AssertionError("unknown declarative operation")


def _sql_json(column: str) -> str:
    return f"COALESCE(to_json({column})::text,'null')"


def _sql_identity(kind: str, serialization_sql: str) -> str:
    prefix = _sql_literal(f"{kind}:sha256:")
    return f"({prefix}||encode(sha256(convert_to(({serialization_sql}),'UTF8')),'hex'))"


@final
@dataclass(frozen=True, slots=True)
class PostgresFramingContract:
    approved_header_names_identity_sql: str
    normalized_header_facts_serialization_sql: str
    normalized_header_facts_identity_sql: str
    raw_artifact_serialization_sql: str
    raw_artifact_identity_sql: str
    framing_input_serialization_sql: str
    framing_input_identity_sql: str
    v2_facts_absent_predicate: str
    fact_free_v2_event_predicate: str
    v2_event_metadata_predicate: str
    legacy_raw_projection_predicate: str
    expected_status_case: str
    expected_class_case: str
    expected_rejection_case: str
    canonical_fact_shape: str
    canonical_decision_check: str


def render_provider_raw_relative_path_predicate(column: str) -> str:
    """Render the SQL twin of the canonical provider raw relative-path grammar."""

    if column not in {"body_relative_path", "raw_relative_path"}:
        raise ValueError("provider raw path column is invalid")
    reserved = "|".join(value.replace("$", r"\$") for value in _WINDOWS_RESERVED_PATH_BASE_NAMES)
    return (
        f"char_length({column}) BETWEEN 1 AND 1024 IS TRUE AND "
        f"left({column},1)<>'/' IS TRUE AND position(chr(92) IN {column})=0 IS TRUE AND "
        f"position(':' IN {column})=0 IS TRUE AND {column} ~ '^[ -~]+$' AND "
        f"{column} !~ '(^/|/$|//|(^|/)\\.{{1,2}}(/|$))' AND "
        f"{column} !~ '(^|/)[^/]*[. ](/|$)' AND "
        f"{column} !~* '(^|/)({reserved})([ .]*\\.[^/]*)?(/|$)'"
    )


def render_v1_immutability_predicate() -> str:
    """Keep V2 facts absent and legacy body paths canonical for V1 rows."""

    return (
        "(schema_version IS DISTINCT FROM 'M3_PROVIDER_ATTEMPT_EVENT_V1' OR "
        f"({render_v2_facts_absent_predicate()} AND "
        "(body_relative_path IS NULL OR "
        f"({render_provider_raw_relative_path_predicate('body_relative_path')})))) IS TRUE"
    )


def render_v2_facts_absent_predicate() -> str:
    """Require the complete V2 fact/identity/decision surface to be absent."""

    return "(" + " AND ".join(f"{name} IS NULL" for name in V2_ONLY_LEDGER_COLUMNS) + ") IS TRUE"


def render_fact_free_v2_event_predicate() -> str:
    """Render the same exact no-response topology enforced by the Python helper."""

    rows = " OR ".join(
        f"(event_kind IS NOT DISTINCT FROM {_sql_literal(rule.event_kind)} AND "
        f"disposition IS NOT DISTINCT FROM {_sql_literal(rule.disposition)})"
        for rule in FACT_FREE_V2_EVENT_RULES
    )
    legacy = []
    for name, value in FACT_FREE_LEGACY_EXPECTED:
        if value is None:
            legacy.append(f"{name} IS NULL")
        elif value == ():
            legacy.append(f"{name} IS NOT DISTINCT FROM ARRAY[]::varchar[]")
        else:
            raise AssertionError("unsupported fact-free legacy value")
    return (
        "(schema_version IS NOT DISTINCT FROM 'M3_PROVIDER_ATTEMPT_EVENT_V2' AND "
        f"({rows}) IS TRUE AND {render_v2_event_metadata_predicate()} AND "
        f"{' AND '.join(legacy)} AND "
        f"{render_v2_facts_absent_predicate()}) IS TRUE"
    )


def render_v2_event_metadata_predicate() -> str:
    """Render exact null-total credential/error metadata from shared rows."""

    rows = []
    for rule in V2_EVENT_METADATA_RULES:
        credential = (
            "credential_echo IS TRUE" if rule.credential_echo else "credential_echo IS FALSE"
        )
        error = (
            "error_code IS NULL"
            if rule.error_code is None
            else f"error_code IS NOT DISTINCT FROM {_sql_literal(rule.error_code)}"
        )
        rows.append(
            f"(event_kind IS NOT DISTINCT FROM {_sql_literal(rule.event_kind)} AND "
            f"disposition IS NOT DISTINCT FROM {_sql_literal(rule.disposition)} AND "
            f"{credential} AND {error})"
        )
    return "(" + " OR ".join(rows) + ") IS TRUE"


def render_postgres_contract() -> PostgresFramingContract:
    """Render ordered, NULL-total CASE authority and canonical shape predicates."""

    def case(attribute: str, fallback: str) -> str:
        lines = ["CASE"]
        for rule in FRAMING_RULES:
            outcome = getattr(rule, attribute)
            lines.append(
                f" WHEN {_sql(rule.condition)} THEN {_sql_literal(outcome.value if isinstance(outcome, StrEnum) else outcome)}"
            )
        lines.append(f" ELSE {_sql_literal(fallback)} END")
        return "".join(lines)

    status_case = case("status", FramingStatus.REJECTED.value)
    class_case = case("accepted_class", "")
    rejection_case = case("rejection_code", "invalid_unclassified")
    exact_headers = (
        "ARRAY[" + ",".join(_sql_literal(name) for name in APPROVED_HEADER_NAMES) + "]::varchar[]"
    )
    approved_serialization = _sql_literal(_canonical_bytes(list(APPROVED_HEADER_NAMES)).decode())
    approved_identity_sql = _sql_identity("m3-approved-header-names", approved_serialization)
    value_columns = {
        "content-encoding": "normalized_content_encoding_values",
        "content-length": "normalized_content_length_values",
        "content-type": "normalized_content_type_values",
        "transfer-encoding": "normalized_transfer_encoding_values",
        "x-request-id": "normalized_x_request_id_values",
    }
    occurrence_parts = []
    for index, name in enumerate(APPROVED_HEADER_NAMES):
        prefix = ("," if index else "") + json.dumps(name) + ":"
        occurrence_parts.extend(
            [_sql_literal(prefix), f"array_to_json({value_columns[name]})::text"]
        )
    header_serialization_sql = (
        "("
        + "||".join(
            [
                _sql_literal('{"approved_header_names_identity":'),
                "to_json(approved_header_names_identity)::text",
                _sql_literal(',"occurrences":{'),
                *occurrence_parts,
                _sql_literal('},"raw_header_field_count":'),
                _sql_json("raw_header_field_count"),
                _sql_literal(',"surface_state":'),
                "to_json(header_surface_state)::text",
                _sql_literal("}"),
            ]
        )
        + ")"
    )
    header_identity_sql = _sql_identity("m3-normalized-header-facts", header_serialization_sql)
    raw_serialization_sql = (
        "("
        + "||".join(
            [
                _sql_literal('{"body_byte_count":'),
                _sql_json("actual_body_byte_count"),
                _sql_literal(',"body_hash":'),
                _sql_json("raw_body_hash"),
                _sql_literal(',"relative_path":'),
                _sql_json("raw_relative_path"),
                _sql_literal("}"),
            ]
        )
        + ")"
    )
    raw_identity_sql = _sql_identity("m3-provider-raw-artifact", raw_serialization_sql)
    available_input_serialization = (
        "("
        + "||".join(
            [
                _sql_literal('{"actual_body_byte_count":'),
                _sql_json("actual_body_byte_count"),
                _sql_literal(',"body_complete":'),
                _sql_json("body_complete"),
                _sql_literal(',"content_encoding_state":'),
                _sql_json("content_encoding_state"),
                _sql_literal(',"content_length_state":'),
                _sql_json("content_length_state"),
                _sql_literal(',"content_length_value":'),
                _sql_json("content_length_value"),
                _sql_literal(',"content_type_state":'),
                _sql_json("content_type_state"),
                _sql_literal(',"disposition":'),
                _sql_json("disposition"),
                _sql_literal(',"header_facts_identity":'),
                _sql_json("normalized_header_facts_identity"),
                _sql_literal(',"http_status":'),
                _sql_json("http_status"),
                _sql_literal(',"http_version_state":'),
                _sql_json("http_version_state"),
                _sql_literal(',"observed_body_bytes_lower_bound":'),
                _sql_json("observed_body_bytes_lower_bound"),
                _sql_literal(',"observed_http_version":'),
                _sql_json("observed_http_version"),
                _sql_literal(',"raw_artifact_identity":'),
                _sql_json("raw_artifact_identity"),
                _sql_literal(',"raw_evidence_state":'),
                _sql_json("raw_evidence_state"),
                _sql_literal(',"raw_header_field_count":'),
                _sql_json("raw_header_field_count"),
                _sql_literal(',"transfer_encoding_state":'),
                _sql_json("transfer_encoding_state"),
                _sql_literal("}"),
            ]
        )
        + ")"
    )
    unavailable_input_serialization = (
        "("
        + "||".join(
            [
                _sql_literal('{"disposition":'),
                _sql_json("disposition"),
                _sql_literal(',"framing_facts":null,"http_status":'),
                _sql_json("http_status"),
                _sql_literal("}"),
            ]
        )
        + ")"
    )
    input_serialization_sql = (
        "(CASE WHEN disposition IN ('credential_echo','evidence_persistence_failure') IS TRUE "
        f"THEN {unavailable_input_serialization} ELSE {available_input_serialization} END)"
    )
    input_identity_sql = _sql_identity("m3-framing-input", input_serialization_sql)
    legacy_raw_equalities = " AND ".join(
        f"{legacy} IS NOT DISTINCT FROM {v2}" for legacy, v2 in LEGACY_RAW_FIELD_BINDINGS
    )
    legacy_raw_projection_predicate = (
        "((framing_status IS NOT DISTINCT FROM 'unavailable_not_classified' AND "
        f"{legacy_raw_equalities} AND observed_body_bytes_lower_bound IS NULL) OR "
        "(framing_status IN ('accepted','rejected') IS TRUE AND "
        f"{legacy_raw_equalities} AND "
        "((body_complete IS TRUE AND observed_body_bytes_lower_bound IS NOT DISTINCT FROM actual_body_byte_count) OR "
        f"(body_complete IS FALSE AND observed_body_bytes_lower_bound BETWEEN 0 AND {MAX_OBSERVED_BODY_BYTES_LOWER_BOUND} IS TRUE)) IS TRUE)) IS TRUE"
    )
    array_shape_parts = []
    derived_names_parts = ["ARRAY[]::varchar[]"]
    for name in APPROVED_HEADER_NAMES:
        column = value_columns[name]
        indexed = " AND ".join(
            f"({column}[{index}] IS NULL OR (octet_length({column}[{index}])<={_MAX_HEADER_VALUE_BYTES} AND {column}[{index}] ~ '^[ -~]*$')) IS TRUE"
            for index in range(1, _MAX_APPROVED_OCCURRENCES + 1)
        )
        array_shape_parts.append(
            f"({column} IS NOT NULL AND cardinality({column}) BETWEEN 0 AND {_MAX_APPROVED_OCCURRENCES} IS TRUE AND "
            f"array_position({column},NULL) IS NULL AND COALESCE(array_lower({column},1),1)=1 IS TRUE AND {indexed})"
        )
        derived_names_parts.append(
            f"CASE WHEN cardinality({column})>0 IS TRUE THEN ARRAY[{_sql_literal(name)}]::varchar[] ELSE ARRAY[]::varchar[] END"
        )
    total_value_bytes = "+".join(
        f"COALESCE(octet_length({column}[{index}]),0)"
        for column in value_columns.values()
        for index in range(1, _MAX_APPROVED_OCCURRENCES + 1)
    )
    arrays_shape = (
        "("
        + " AND ".join(array_shape_parts)
        + f" AND ({total_value_bytes})<={_MAX_APPROVED_HEADER_BYTES} IS TRUE) IS TRUE"
    )
    derived_names = "(" + "||".join(derived_names_parts) + ")"
    cl_column = value_columns["content-length"]
    cl_text = f"{cl_column}[1]"
    cl_valid = (
        f"(cardinality({cl_column})=1 AND {cl_text} ~ '^(0|[1-9][0-9]*)$' AND "
        f"(char_length({cl_text})<19 OR (char_length({cl_text})=19 AND "
        f'{cl_text} COLLATE "C"<={_sql_literal(str(POSTGRES_BIGINT_MAX))} COLLATE "C"))) IS TRUE'
    )
    te_column = value_columns["transfer-encoding"]
    ce_column = value_columns["content-encoding"]
    ct_column = value_columns["content-type"]
    approved_occurrence_count = "+".join(
        f"cardinality({column})" for column in value_columns.values()
    )
    header_state_binding = (
        f"(raw_header_field_count BETWEEN 0 AND {POSTGRES_BIGINT_MAX} IS TRUE AND "
        f"raw_header_field_count>=({approved_occurrence_count}) IS TRUE AND "
        "((header_surface_state IS NOT DISTINCT FROM 'invalid' AND "
        + " AND ".join(f"cardinality({column})=0 IS TRUE" for column in value_columns.values())
        + " AND normalized_header_names IS NOT DISTINCT FROM ARRAY[]::varchar[] AND "
        "content_length_state IS NOT DISTINCT FROM 'absent' AND "
        "transfer_encoding_state IS NOT DISTINCT FROM 'absent' AND "
        "content_encoding_state IS NOT DISTINCT FROM 'absent' AND "
        "content_type_state IS NOT DISTINCT FROM 'absent') OR "
        f"(header_surface_state IS NOT DISTINCT FROM 'valid' AND raw_header_field_count<={_MAX_HEADER_FIELDS} IS TRUE AND {arrays_shape} AND "
        f"normalized_header_names IS NOT DISTINCT FROM {derived_names} AND "
        f"content_length_state IS NOT DISTINCT FROM (CASE WHEN cardinality({cl_column})=0 THEN 'absent' WHEN cardinality({cl_column})<>1 THEN 'duplicate' WHEN {cl_valid} THEN 'valid' ELSE 'invalid' END) AND "
        f"content_length_value IS NOT DISTINCT FROM (CASE WHEN {cl_valid} THEN {cl_text}::bigint ELSE NULL END) AND "
        f"transfer_encoding_state IS NOT DISTINCT FROM (CASE WHEN cardinality({te_column})=0 THEN 'absent' WHEN cardinality({te_column})<>1 THEN 'multiple' WHEN btrim(lower({te_column}[1]))='chunked' AND position(',' IN {te_column}[1])=0 THEN 'chunked' ELSE 'invalid' END) AND "
        f"content_encoding_state IS NOT DISTINCT FROM (CASE WHEN cardinality({ce_column})=0 THEN 'absent' WHEN cardinality({ce_column})=1 AND btrim(lower({ce_column}[1]))='identity' AND position(',' IN {ce_column}[1])=0 THEN 'identity' ELSE 'unsupported' END) AND "
        f"content_type_state IS NOT DISTINCT FROM (CASE WHEN cardinality({ct_column})=0 THEN 'absent' WHEN cardinality({ct_column})<>1 THEN 'duplicate' WHEN {ct_column}[1] IN ('application/json','application/json; charset=utf-8') IS TRUE THEN 'approved_json' ELSE 'invalid' END))) IS TRUE) IS TRUE"
    )
    framing_present = (
        "http_version_state IS NOT NULL AND header_surface_state IS NOT NULL AND "
        "content_length_state IS NOT NULL AND transfer_encoding_state IS NOT NULL AND "
        "content_encoding_state IS NOT NULL AND content_type_state IS NOT NULL AND "
        "raw_header_field_count IS NOT NULL AND body_complete IS NOT NULL AND raw_evidence_state IS NOT NULL"
    )
    raw_relative_path_predicate = render_provider_raw_relative_path_predicate("raw_relative_path")
    unavailable = (
        "disposition IN ('credential_echo','evidence_persistence_failure') IS TRUE AND "
        "http_status BETWEEN 100 AND 599 IS TRUE AND "
        f"approved_header_names IS NOT DISTINCT FROM {exact_headers} AND "
        f"approved_header_names_identity IS NOT DISTINCT FROM {approved_identity_sql} AND "
        f"framing_contract_identity IS NOT DISTINCT FROM {_sql_literal(FRAMING_CONTRACT_IDENTITY)} AND "
        "normalized_header_names IS NOT DISTINCT FROM ARRAY[]::varchar[] AND "
        + " AND ".join(f"{column} IS NULL" for column in value_columns.values())
        + " AND "
        "http_version_state IS NULL AND observed_http_version IS NULL AND "
        "header_surface_state IS NULL AND content_length_state IS NULL AND "
        "content_length_value IS NULL AND transfer_encoding_state IS NULL AND "
        "content_encoding_state IS NULL AND content_type_state IS NULL AND "
        "body_complete IS NULL AND actual_body_byte_count IS NULL AND "
        "raw_evidence_state IS NULL AND raw_body_hash IS NULL AND raw_relative_path IS NULL AND "
        "raw_artifact_identity IS NULL AND normalized_header_facts_identity IS NULL AND raw_header_field_count IS NULL AND "
        f"framing_input_identity IS NOT DISTINCT FROM {input_identity_sql}"
    )
    classified = (
        "disposition NOT IN ('credential_echo','evidence_persistence_failure') IS TRUE AND "
        "char_length(disposition) BETWEEN 1 AND 64 IS TRUE AND disposition ~ '^[!-~]+$' AND "
        f"{framing_present} AND http_status BETWEEN 100 AND 599 IS TRUE AND "
        f"approved_header_names IS NOT DISTINCT FROM {exact_headers} AND "
        f"approved_header_names_identity IS NOT DISTINCT FROM {approved_identity_sql} AND "
        f"framing_contract_identity IS NOT DISTINCT FROM {_sql_literal(FRAMING_CONTRACT_IDENTITY)} AND "
        f"normalized_header_facts_identity IS NOT DISTINCT FROM {header_identity_sql} AND "
        f"framing_input_identity IS NOT DISTINCT FROM {input_identity_sql} AND "
        "header_surface_state IN ('valid','invalid') IS TRUE AND "
        "content_length_state IN ('absent','valid','duplicate','invalid') IS TRUE AND "
        "transfer_encoding_state IN ('absent','chunked','multiple','invalid') IS TRUE AND "
        "content_encoding_state IN ('absent','identity','unsupported') IS TRUE AND "
        "content_type_state IN ('approved_json','absent','duplicate','invalid') IS TRUE AND "
        f"{header_state_binding} AND "
        "((http_version_state IS NOT DISTINCT FROM 'missing' AND observed_http_version IS NULL) OR "
        "(http_version_state IS NOT DISTINCT FROM 'http_1_1' AND observed_http_version IS NOT DISTINCT FROM 'HTTP/1.1') OR "
        "(http_version_state IS NOT DISTINCT FROM 'http_2' AND observed_http_version IS NOT DISTINCT FROM 'HTTP/2') OR "
        "(http_version_state IS NOT DISTINCT FROM 'unsupported' AND char_length(observed_http_version) BETWEEN 1 AND 16 IS TRUE AND "
        "observed_http_version NOT IN ('HTTP/1.1','HTTP/2') IS TRUE AND observed_http_version ~ '^[!-~]+$')) IS TRUE AND "
        f"((content_length_state IS NOT DISTINCT FROM 'valid' AND content_length_value BETWEEN 0 AND {POSTGRES_BIGINT_MAX} IS TRUE) OR "
        "(content_length_state IN ('absent','duplicate','invalid') IS TRUE AND content_length_value IS NULL)) IS TRUE AND "
        f"((body_complete IS TRUE AND actual_body_byte_count BETWEEN 0 AND {MAX_RAW_RESPONSE_BYTES} IS TRUE) OR "
        "(body_complete IS FALSE AND actual_body_byte_count IS NULL)) IS TRUE AND "
        "((raw_evidence_state IS NOT DISTINCT FROM 'bound' AND body_complete IS TRUE AND raw_body_hash IS NOT NULL AND "
        "(raw_body_hash ~ '^sha256:[0-9a-f]{64}$') IS TRUE AND raw_relative_path IS NOT NULL AND "
        f"{raw_relative_path_predicate} AND "
        f"raw_artifact_identity IS NOT DISTINCT FROM {raw_identity_sql}) OR "
        "(raw_evidence_state IS NOT DISTINCT FROM 'missing' AND raw_body_hash IS NULL AND raw_relative_path IS NULL AND raw_artifact_identity IS NULL)) IS TRUE"
    )
    fact_shape = f"(({unavailable}) OR ({classified})) IS TRUE"
    decision = (
        f"({fact_shape} AND {legacy_raw_projection_predicate} AND "
        f"{render_v2_event_metadata_predicate()} AND "
        f"framing_status IS NOT DISTINCT FROM ({status_case}) AND "
        f"accepted_framing_class IS NOT DISTINCT FROM NULLIF(({class_case}),'') AND "
        f"framing_rejection_code IS NOT DISTINCT FROM ({rejection_case}) AND "
        f"(disposition IS DISTINCT FROM 'success' OR ({status_case}) IS NOT DISTINCT FROM 'accepted')) IS TRUE"
    )
    return PostgresFramingContract(
        approved_identity_sql,
        header_serialization_sql,
        header_identity_sql,
        raw_serialization_sql,
        raw_identity_sql,
        input_serialization_sql,
        input_identity_sql,
        render_v2_facts_absent_predicate(),
        render_fact_free_v2_event_predicate(),
        render_v2_event_metadata_predicate(),
        legacy_raw_projection_predicate,
        status_case,
        class_case,
        rejection_case,
        fact_shape,
        decision,
    )
