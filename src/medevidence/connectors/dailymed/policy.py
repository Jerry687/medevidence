"""Closed, bounded DailyMed request and transport policy."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from enum import StrEnum
from typing import Final, Literal
from urllib.parse import unquote_to_bytes, urljoin, urlsplit, urlunsplit
from uuid import UUID

import httpx

DAILYMED_HOST: Final = "dailymed.nlm.nih.gov"
DAILYMED_ORIGIN: Final = f"https://{DAILYMED_HOST}"
DISCOVERY_PATH: Final = "/dailymed/services/v2/spls.json"
HISTORY_PATH_TEMPLATE: Final = "/dailymed/services/v2/spls/{SETID}/history.json"
NDCS_PATH_TEMPLATE: Final = "/dailymed/services/v2/spls/{SETID}/ndcs.json"
PACKAGING_PATH_TEMPLATE: Final = "/dailymed/services/v2/spls/{SETID}/packaging.json"
CURRENT_SPL_PATH_TEMPLATE: Final = "/dailymed/services/v2/spls/{SETID}.xml"
HISTORICAL_SPL_PATH: Final = "/dailymed/getFile.cfm"

MAX_PAGES: Final = 5
MAX_CANDIDATES: Final = 100
MAX_PAYLOAD_BYTES: Final = 5_242_880
MAX_PAGE_SIZE: Final = 100
MAX_QUERY_CHARACTERS: Final = 512
RETRYABLE_STATUS_CODES: Final = frozenset({408, 429, *range(500, 600)})
REDIRECT_STATUS_CODES: Final = frozenset({301, 302, 303, 307, 308})

DISCOVERY_QUERY_KEYS: Final = frozenset(
    {
        "application_number",
        "drug_name",
        "name_type",
        "labeler",
        "ndc",
        "setid",
        "rxcui",
        "unii_code",
        "published_date",
        "published_date_comparison",
        "pagesize",
        "page",
    }
)
PAGED_QUERY_KEYS: Final = frozenset({"pagesize", "page"})
_DISCOVERY_IDENTITY_KEYS: Final = DISCOVERY_QUERY_KEYS - {"pagesize", "page"}
_SETID_PATTERN = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\Z")
_SPL_VERSION_PATTERN = re.compile(r"[1-9][0-9]*\Z")
_ASCII_DELTA_SECONDS = re.compile(r"[0-9]+\Z")
_ASCII_HEX_DIGITS: Final = frozenset("0123456789abcdefABCDEF")


class DailyMedOperation(StrEnum):
    """Closed operation vocabulary for the six frozen request paths."""

    DISCOVERY = "discovery"
    HISTORY = "history"
    NDCS = "ndcs"
    PACKAGING = "packaging"
    CURRENT_SPL = "current_spl"
    HISTORICAL_SPL = "historical_spl"


class DailyMedFailureKind(StrEnum):
    """Typed connector-local failures without raw provider objects."""

    INVALID_INPUT = "invalid_input"
    TIMEOUT = "timeout"
    RATE_LIMITED = "rate_limited"
    CLIENT_ERROR = "client_error"
    UPSTREAM_UNAVAILABLE = "upstream_unavailable"
    RETRY_EXHAUSTED = "retry_exhausted"
    TRANSPORT = "transport"
    PAYLOAD_LIMIT = "payload_limit"
    REDIRECT_REJECTED = "redirect_rejected"
    MALFORMED_RESPONSE = "malformed_response"
    IDENTITY_DRIFT = "identity_drift"
    INTEGRITY_FAILURE = "integrity_failure"
    CACHE_CONFLICT = "cache_conflict"


@dataclass(frozen=True, slots=True)
class DailyMedConnectorConfig:
    """Exact Owner-frozen DM-002 transport, pagination, and cache profile."""

    connect_timeout_seconds: float = 5.0
    read_timeout_seconds: float = 10.0
    write_timeout_seconds: float = 5.0
    pool_timeout_seconds: float = 5.0
    total_deadline_seconds: float = 30.0
    max_attempts: int = 2
    base_backoff_seconds: float = 0.25
    max_backoff_seconds: float = 4.0
    jitter_seconds: float = 0.1
    max_retry_after_seconds: float = 10.0
    max_redirects: int = 1
    max_pages: int = MAX_PAGES
    max_candidates: int = MAX_CANDIDATES
    max_payload_bytes: int = MAX_PAYLOAD_BYTES
    fixed_version_cache: Literal["immutable"] = "immutable"
    discovery_cache: Literal["none"] = "none"
    stale_fallback: Literal[False] = False

    def __post_init__(self) -> None:
        expected: tuple[tuple[str, object], ...] = (
            ("connect_timeout_seconds", 5.0),
            ("read_timeout_seconds", 10.0),
            ("write_timeout_seconds", 5.0),
            ("pool_timeout_seconds", 5.0),
            ("total_deadline_seconds", 30.0),
            ("max_attempts", 2),
            ("base_backoff_seconds", 0.25),
            ("max_backoff_seconds", 4.0),
            ("jitter_seconds", 0.1),
            ("max_retry_after_seconds", 10.0),
            ("max_redirects", 1),
            ("max_pages", 5),
            ("max_candidates", 100),
            ("max_payload_bytes", 5_242_880),
            ("fixed_version_cache", "immutable"),
            ("discovery_cache", "none"),
            ("stale_fallback", False),
        )
        for name, frozen in expected:
            value = getattr(self, name)
            if type(value) is not type(frozen) or value != frozen:
                raise ValueError(f"{name} must equal the Owner-frozen value {frozen!r}")


@dataclass(frozen=True, slots=True)
class DailyMedRequest:
    """One validated typed request rendered from a frozen path design."""

    operation: DailyMedOperation
    path: str
    query: tuple[tuple[str, str], ...]
    setid: str | None = None
    spl_version: str | None = None

    @property
    def url(self) -> str:
        """Return the canonical HTTPS URL without accepting caller URL text."""

        return str(httpx.URL(f"{DAILYMED_ORIGIN}{self.path}", params=self.query))

    @property
    def page(self) -> int | None:
        value = dict(self.query).get("page")
        return int(value) if value is not None else None

    def with_page(self, page: int) -> DailyMedRequest:
        """Return the same typed paged request with a validated page number."""

        if self.operation not in {
            DailyMedOperation.DISCOVERY,
            DailyMedOperation.HISTORY,
            DailyMedOperation.NDCS,
            DailyMedOperation.PACKAGING,
        }:
            raise ValueError("only JSON collection requests are paginated")
        _validate_page_number(page)
        query = dict(self.query)
        query["page"] = str(page)
        return build_dailymed_request(
            self.operation,
            query=query,
            setid=self.setid,
            spl_version=self.spl_version,
        )


@dataclass(frozen=True, slots=True)
class DailyMedFailure:
    """Safe typed failure returned by the connector boundary."""

    kind: DailyMedFailureKind
    message: str
    retryable: bool = False
    status_code: int | None = None
    cause_kind: DailyMedFailureKind | None = None

    def __post_init__(self) -> None:
        if not self.message.strip():
            raise ValueError("failure message must not be blank")
        if self.status_code is not None and not 100 <= self.status_code <= 599:
            raise ValueError("status_code must be an HTTP status")
        if self.kind is DailyMedFailureKind.RETRY_EXHAUSTED:
            if self.cause_kind is None or self.cause_kind is self.kind:
                raise ValueError("retry exhaustion requires a distinct cause_kind")
        elif self.cause_kind is not None:
            raise ValueError("cause_kind is reserved for retry exhaustion")


@dataclass(frozen=True, slots=True)
class RetryEvent:
    """Auditable bounded retry decision."""

    attempt_number: int
    delay_seconds: float
    failure_kind: DailyMedFailureKind
    status_code: int | None = None
    used_retry_after: bool = False

    def __post_init__(self) -> None:
        if self.attempt_number < 1:
            raise ValueError("attempt_number must be positive")
        if not math.isfinite(self.delay_seconds) or not 0 <= self.delay_seconds <= 30:
            raise ValueError("delay_seconds must be finite and within the deadline")


def validate_setid(value: str) -> str:
    """Validate the exact lowercase non-nil canonical UUID oracle."""

    if not isinstance(value, str) or _SETID_PATTERN.fullmatch(value) is None:
        raise ValueError("SETID must be an exact lowercase canonical UUID")
    parsed = UUID(value)
    if parsed.int == 0 or str(parsed) != value:
        raise ValueError("SETID must be non-nil and byte-canonical")
    return value


def validate_spl_version(value: str) -> str:
    """Validate a positive canonical ASCII SPL version string."""

    if not isinstance(value, str) or _SPL_VERSION_PATTERN.fullmatch(value) is None:
        raise ValueError("SPL version must be a positive canonical ASCII integer")
    if str(int(value)) != value:
        raise ValueError("SPL version must equal its normalized integer string")
    return value


def build_dailymed_request(
    operation: DailyMedOperation,
    *,
    query: Mapping[str, object] | None = None,
    setid: str | None = None,
    spl_version: str | None = None,
) -> DailyMedRequest:
    """Build one of the exact six requests from typed values only."""

    if not isinstance(operation, DailyMedOperation):
        raise TypeError("operation must be a DailyMedOperation")
    supplied = dict(query or {})
    if any(not isinstance(key, str) for key in supplied):
        raise TypeError("query keys must be strings")

    if operation is DailyMedOperation.DISCOVERY:
        _validate_closed_query(supplied, DISCOVERY_QUERY_KEYS)
        if not set(supplied).intersection(_DISCOVERY_IDENTITY_KEYS):
            raise ValueError("discovery requires at least one typed identity filter")
        if "setid" in supplied:
            supplied["setid"] = validate_setid(_query_text("setid", supplied["setid"]))
        path = DISCOVERY_PATH
    elif operation in {
        DailyMedOperation.HISTORY,
        DailyMedOperation.NDCS,
        DailyMedOperation.PACKAGING,
    }:
        canonical_setid = validate_setid(_required_text("setid", setid))
        _validate_closed_query(supplied, PAGED_QUERY_KEYS)
        template = {
            DailyMedOperation.HISTORY: HISTORY_PATH_TEMPLATE,
            DailyMedOperation.NDCS: NDCS_PATH_TEMPLATE,
            DailyMedOperation.PACKAGING: PACKAGING_PATH_TEMPLATE,
        }[operation]
        path = template.replace("{SETID}", canonical_setid)
        setid = canonical_setid
    elif operation is DailyMedOperation.CURRENT_SPL:
        canonical_setid = validate_setid(_required_text("setid", setid))
        if supplied:
            raise ValueError("current SPL retrieval forbids query parameters")
        if spl_version is not None:
            spl_version = validate_spl_version(spl_version)
        path = CURRENT_SPL_PATH_TEMPLATE.replace("{SETID}", canonical_setid)
        setid = canonical_setid
    else:
        canonical_setid = validate_setid(_required_text("setid", setid))
        canonical_version = validate_spl_version(_required_text("spl_version", spl_version))
        if supplied:
            raise ValueError("historical SPL query is derived and forbids caller query values")
        supplied = {"type": "zip", "setid": canonical_setid, "version": canonical_version}
        path = HISTORICAL_SPL_PATH
        setid = canonical_setid
        spl_version = canonical_version

    if operation in {
        DailyMedOperation.DISCOVERY,
        DailyMedOperation.HISTORY,
        DailyMedOperation.NDCS,
        DailyMedOperation.PACKAGING,
    }:
        if "pagesize" in supplied:
            supplied["pagesize"] = str(
                _bounded_ascii_int("pagesize", supplied["pagesize"], 1, MAX_PAGE_SIZE)
            )
        if "page" in supplied:
            supplied["page"] = str(_bounded_ascii_int("page", supplied["page"], 1, MAX_PAGES))

    pairs = tuple(sorted((key, _query_text(key, value)) for key, value in supplied.items()))
    _validate_query_character_bound(pairs)
    request = DailyMedRequest(operation, path, pairs, setid, spl_version)
    _validate_dailymed_url_parts(request.url, request)
    return request


def validate_dailymed_url(url: str, expected: DailyMedRequest) -> str:
    """Validate exact origin, path, and complete decoded query parity."""

    canonical_expected = validate_dailymed_request(expected)
    return _validate_dailymed_url_parts(url, canonical_expected)


def validate_dailymed_request(request: DailyMedRequest) -> DailyMedRequest:
    """Rebuild and verify a request against one exact frozen request design."""

    if type(request) is not DailyMedRequest:
        raise TypeError("request must be an exact DailyMedRequest")
    if not isinstance(request.query, tuple) or any(
        not isinstance(pair, tuple)
        or len(pair) != 2
        or not all(isinstance(item, str) for item in pair)
        for pair in request.query
    ):
        raise TypeError("request query must be an exact tuple of text pairs")
    query = dict(request.query)
    if len(query) != len(request.query):
        raise ValueError("request query contains duplicate keys")
    if request.operation is DailyMedOperation.DISCOVERY:
        canonical = build_dailymed_request(request.operation, query=query)
    elif request.operation in {
        DailyMedOperation.HISTORY,
        DailyMedOperation.NDCS,
        DailyMedOperation.PACKAGING,
    }:
        canonical = build_dailymed_request(request.operation, query=query, setid=request.setid)
    elif request.operation in {
        DailyMedOperation.CURRENT_SPL,
        DailyMedOperation.HISTORICAL_SPL,
    }:
        canonical = build_dailymed_request(
            request.operation,
            setid=request.setid,
            spl_version=request.spl_version,
        )
    else:
        raise ValueError("request operation is outside the frozen six designs")
    if request != canonical:
        raise ValueError("request does not exactly equal its frozen typed design")
    return canonical


def validate_connector_config(config: DailyMedConnectorConfig) -> DailyMedConnectorConfig:
    """Copy and revalidate every frozen connector configuration field."""

    if type(config) is not DailyMedConnectorConfig:
        raise TypeError("config must be an exact DailyMedConnectorConfig")
    return DailyMedConnectorConfig(
        connect_timeout_seconds=config.connect_timeout_seconds,
        read_timeout_seconds=config.read_timeout_seconds,
        write_timeout_seconds=config.write_timeout_seconds,
        pool_timeout_seconds=config.pool_timeout_seconds,
        total_deadline_seconds=config.total_deadline_seconds,
        max_attempts=config.max_attempts,
        base_backoff_seconds=config.base_backoff_seconds,
        max_backoff_seconds=config.max_backoff_seconds,
        jitter_seconds=config.jitter_seconds,
        max_retry_after_seconds=config.max_retry_after_seconds,
        max_redirects=config.max_redirects,
        max_pages=config.max_pages,
        max_candidates=config.max_candidates,
        max_payload_bytes=config.max_payload_bytes,
        fixed_version_cache=config.fixed_version_cache,
        discovery_cache=config.discovery_cache,
        stale_fallback=config.stale_fallback,
    )


def _validate_dailymed_url_parts(url: str, expected: DailyMedRequest) -> str:
    """Validate URL parts against an already reconstructed frozen request."""

    if not url or any(ord(char) < 32 or ord(char) == 127 for char in url):
        raise ValueError("URL is blank or contains control characters")
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError as error:
        raise ValueError("URL authority is malformed") from error
    if parts.scheme != "https" or parts.hostname != DAILYMED_HOST or port not in {None, 443}:
        raise ValueError("DailyMed URL must retain the exact HTTPS origin")
    if parts.username is not None or parts.password is not None or "@" in parts.netloc:
        raise ValueError("userinfo is forbidden")
    if parts.fragment or parts.path != expected.path:
        raise ValueError("DailyMed URL path or fragment violates the typed request")
    if _strict_query_pairs(parts.query) != expected.query:
        raise ValueError("DailyMed URL query must exactly equal the typed request")
    authority = DAILYMED_HOST if port is None else f"{DAILYMED_HOST}:443"
    return urlunsplit(("https", authority, expected.path, parts.query, ""))


def resolve_dailymed_redirect(current_url: str, location: str, expected: DailyMedRequest) -> str:
    """Resolve the sole allowed redirect while preserving origin/path/query."""

    canonical_current = validate_dailymed_url(current_url, expected)
    if not location or any(ord(char) < 32 or ord(char) == 127 for char in location):
        raise ValueError("redirect location is blank or contains control characters")
    resolved = urljoin(canonical_current, location)
    return validate_dailymed_url(resolved, expected)


def parse_retry_after(
    value: str | None, *, now: datetime, cap_seconds: float = 10.0
) -> float | None:
    """Parse delta-seconds or HTTP-date and cap it to the frozen bound."""

    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    if not math.isfinite(cap_seconds) or not 0 <= cap_seconds <= 10:
        raise ValueError("Retry-After cap must be within the frozen bound")
    if value is None or not (candidate := value.strip()):
        return None
    if _ASCII_DELTA_SECONDS.fullmatch(candidate):
        digits = candidate.lstrip("0") or "0"
        return cap_seconds if len(digits) > 18 else min(float(int(digits)), cap_seconds)
    try:
        retry_at = parsedate_to_datetime(candidate)
    except (TypeError, ValueError, OverflowError):
        return None
    if retry_at is None:
        return None
    if retry_at.tzinfo is None:
        retry_at = retry_at.replace(tzinfo=UTC)
    delay = max(0.0, (retry_at - now).total_seconds())
    return min(delay, cap_seconds) if math.isfinite(delay) else None


def retry_delay_seconds(attempt_number: int, *, jitter: float) -> float:
    """Return the frozen capped exponential delay with injected jitter."""

    if attempt_number not in {1, 2}:
        raise ValueError("attempt_number must be within the two-attempt budget")
    if not math.isfinite(jitter) or not 0 <= jitter <= 0.1:
        raise ValueError("jitter must be within the frozen 100 ms bound")
    return float(min(0.25 * (2 ** (attempt_number - 1)) + jitter, 4.0))


def _validate_closed_query(values: Mapping[str, object], allowed: frozenset[str]) -> None:
    extra = set(values) - allowed
    if extra:
        raise ValueError(f"query contains non-allowed keys: {sorted(extra)!r}")
    for key, value in values.items():
        _query_text(key, value)


def _query_text(name: str, value: object) -> str:
    if not isinstance(value, (str, int)) or isinstance(value, bool):
        raise TypeError(f"{name} must be a string or integer")
    text = str(value)
    if not text or any(ord(char) < 32 or ord(char) == 127 for char in text):
        raise ValueError(f"{name} must be nonblank and contain no controls")
    return text


def _required_text(name: str, value: str | None) -> str:
    if value is None:
        raise ValueError(f"{name} is required")
    return _query_text(name, value)


def _bounded_ascii_int(name: str, value: object, minimum: int, maximum: int) -> int:
    text = _query_text(name, value)
    if not text.isascii() or not text.isdigit() or str(int(text)) != text:
        raise ValueError(f"{name} must be a canonical ASCII integer")
    number = int(text)
    if not minimum <= number <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return number


def _validate_page_number(page: int) -> None:
    if isinstance(page, bool) or not isinstance(page, int) or not 1 <= page <= MAX_PAGES:
        raise ValueError(f"page must be between 1 and {MAX_PAGES}")


def _validate_query_character_bound(query: tuple[tuple[str, str], ...]) -> None:
    canonical = "&".join(f"{key}={value}" for key, value in query)
    if len(canonical) > MAX_QUERY_CHARACTERS:
        raise ValueError("canonical DailyMed query exceeds the 512-character pre-encoding bound")


def _strict_query_pairs(query: str) -> tuple[tuple[str, str], ...]:
    if not query:
        return ()
    pairs: list[tuple[str, str]] = []
    for field in query.split("&"):
        if not field:
            raise ValueError("empty query fields are forbidden")
        name, separator, value = field.partition("=")
        if not separator:
            raise ValueError("query fields require explicit values")
        pairs.append((_strict_query_component(name), _strict_query_component(value)))
    if len({name for name, _ in pairs}) != len(pairs):
        raise ValueError("duplicate query keys are forbidden")
    return tuple(sorted(pairs))


def _strict_query_component(component: str) -> str:
    cursor = 0
    while cursor < len(component):
        index = component.find("%", cursor)
        if index < 0:
            break
        escape = component[index + 1 : index + 3]
        if len(escape) != 2 or any(char not in _ASCII_HEX_DIGITS for char in escape):
            raise ValueError("query contains malformed percent encoding")
        cursor = index + 3
    try:
        decoded = unquote_to_bytes(component.replace("+", " ")).decode("utf-8", errors="strict")
    except UnicodeError as error:
        raise ValueError("query is not valid UTF-8") from error
    if any(ord(char) < 32 or ord(char) == 127 for char in decoded):
        raise ValueError("query contains decoded control characters")
    return decoded


__all__ = [
    "DAILYMED_HOST",
    "DAILYMED_ORIGIN",
    "DISCOVERY_QUERY_KEYS",
    "MAX_CANDIDATES",
    "MAX_PAGES",
    "MAX_PAYLOAD_BYTES",
    "MAX_QUERY_CHARACTERS",
    "PAGED_QUERY_KEYS",
    "REDIRECT_STATUS_CODES",
    "RETRYABLE_STATUS_CODES",
    "DailyMedConnectorConfig",
    "DailyMedFailure",
    "DailyMedFailureKind",
    "DailyMedOperation",
    "DailyMedRequest",
    "RetryEvent",
    "build_dailymed_request",
    "parse_retry_after",
    "resolve_dailymed_redirect",
    "retry_delay_seconds",
    "validate_connector_config",
    "validate_dailymed_request",
    "validate_dailymed_url",
    "validate_setid",
    "validate_spl_version",
]
