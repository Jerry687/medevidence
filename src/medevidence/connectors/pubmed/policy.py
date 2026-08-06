"""Bounded, network-free transport policy for the PubMed connector."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from enum import StrEnum
from typing import Final, Literal
from urllib.parse import unquote_to_bytes, urljoin, urlsplit, urlunsplit

PUBMED_HOST: Final = "eutils.ncbi.nlm.nih.gov"
PUBMED_ORIGIN: Final = f"https://{PUBMED_HOST}"
PUBMED_ESEARCH_PATH: Final = "/entrez/eutils/esearch.fcgi"
PUBMED_EFETCH_PATH: Final = "/entrez/eutils/efetch.fcgi"
PUBMED_ENDPOINT_PATHS: Final = frozenset({PUBMED_ESEARCH_PATH, PUBMED_EFETCH_PATH})
RETRYABLE_STATUS_CODES: Final = frozenset({429, 500, 502, 503, 504})

MAX_QUERY_CHARACTERS: Final = 512
MAX_PAGE_SIZE: Final = 100
MAX_PAGES: Final = 5
MAX_RECORDS: Final = 100
MAX_PAYLOAD_BYTES: Final = 5_242_880
MAX_TOTAL_DEADLINE_SECONDS: Final = 60.0
MAX_ATTEMPTS: Final = 5
MAX_REDIRECTS: Final = 5

_ASCII_DELTA_SECONDS = re.compile(r"[0-9]+\Z")
_ASCII_HEX_DIGITS: Final = frozenset("0123456789abcdefABCDEF")


class PubMedResultState(StrEnum):
    """Connector-local terminal result classification."""

    COMPLETE_SUCCESS = "complete_success"
    EMPTY_SUCCESS = "empty_success"
    BOUNDED_TRUNCATION = "bounded_truncation"
    PARTIAL_SUCCESS = "partial_success"
    PARTIAL_FAILURE = "partial_failure"
    FAILED = "failed"


class PubMedFailureKind(StrEnum):
    """Connector-local failure classification without provider SDK objects."""

    INVALID_INPUT = "invalid_input"
    RATE_LIMITED = "rate_limited"
    CLIENT_ERROR = "client_error"
    RETRYABLE_SERVER_ERROR = "retryable_server_error"
    RETRY_EXHAUSTED = "retry_exhausted"
    SERVER_ERROR = "server_error"
    TIMEOUT = "timeout"
    TRANSPORT = "transport"
    INVALID_XML = "invalid_xml"
    INCOMPLETE_XML = "incomplete_xml"
    PAYLOAD_LIMIT = "payload_limit"
    REDIRECT_REJECTED = "redirect_rejected"
    INTERNAL_CONTRACT = "internal_contract"


@dataclass(frozen=True, slots=True)
class PubMedConnectorConfig:
    """Finite execution limits for one bounded PubMed operation."""

    max_query_characters: int = MAX_QUERY_CHARACTERS
    page_size: int = 20
    max_pages: int = MAX_PAGES
    max_records: int = MAX_RECORDS
    max_payload_bytes: int = MAX_PAYLOAD_BYTES
    connect_timeout_seconds: float = 5.0
    read_timeout_seconds: float = 10.0
    write_timeout_seconds: float = 5.0
    pool_timeout_seconds: float = 5.0
    total_deadline_seconds: int = 30
    max_attempts: int = 3
    base_backoff_seconds: float = 0.25
    jitter_seconds: float = 0.1
    max_backoff_seconds: float = 4.0
    max_retry_after_seconds: float = 10.0
    max_redirects: int = 2
    cache_policy: Literal["none"] = "none"

    def __post_init__(self) -> None:
        _require_bounded_int(
            "max_query_characters",
            self.max_query_characters,
            minimum=1,
            maximum=MAX_QUERY_CHARACTERS,
        )
        _require_bounded_int(
            "page_size",
            self.page_size,
            minimum=1,
            maximum=MAX_PAGE_SIZE,
        )
        _require_bounded_int("max_pages", self.max_pages, minimum=1, maximum=MAX_PAGES)
        _require_bounded_int("max_records", self.max_records, minimum=1, maximum=MAX_RECORDS)
        _require_bounded_int(
            "max_payload_bytes",
            self.max_payload_bytes,
            minimum=1,
            maximum=MAX_PAYLOAD_BYTES,
        )
        _require_bounded_float(
            "connect_timeout_seconds",
            self.connect_timeout_seconds,
            minimum_exclusive=0.0,
            maximum=MAX_TOTAL_DEADLINE_SECONDS,
        )
        _require_bounded_float(
            "read_timeout_seconds",
            self.read_timeout_seconds,
            minimum_exclusive=0.0,
            maximum=MAX_TOTAL_DEADLINE_SECONDS,
        )
        _require_bounded_float(
            "write_timeout_seconds",
            self.write_timeout_seconds,
            minimum_exclusive=0.0,
            maximum=MAX_TOTAL_DEADLINE_SECONDS,
        )
        _require_bounded_float(
            "pool_timeout_seconds",
            self.pool_timeout_seconds,
            minimum_exclusive=0.0,
            maximum=MAX_TOTAL_DEADLINE_SECONDS,
        )
        _require_bounded_int(
            "total_deadline_seconds",
            self.total_deadline_seconds,
            minimum=1,
            maximum=int(MAX_TOTAL_DEADLINE_SECONDS),
        )
        _require_bounded_int(
            "max_attempts",
            self.max_attempts,
            minimum=1,
            maximum=MAX_ATTEMPTS,
        )
        _require_bounded_float(
            "base_backoff_seconds",
            self.base_backoff_seconds,
            minimum_inclusive=0.0,
            maximum=MAX_TOTAL_DEADLINE_SECONDS,
        )
        _require_bounded_float(
            "jitter_seconds",
            self.jitter_seconds,
            minimum_inclusive=0.0,
            maximum=MAX_TOTAL_DEADLINE_SECONDS,
        )
        _require_bounded_float(
            "max_backoff_seconds",
            self.max_backoff_seconds,
            minimum_inclusive=0.0,
            maximum=MAX_TOTAL_DEADLINE_SECONDS,
        )
        _require_bounded_float(
            "max_retry_after_seconds",
            self.max_retry_after_seconds,
            minimum_inclusive=0.0,
            maximum=MAX_TOTAL_DEADLINE_SECONDS,
        )
        _require_bounded_int(
            "max_redirects",
            self.max_redirects,
            minimum=0,
            maximum=MAX_REDIRECTS,
        )
        if self.base_backoff_seconds > self.max_backoff_seconds:
            raise ValueError("base_backoff_seconds must not exceed max_backoff_seconds")
        if self.jitter_seconds > self.max_backoff_seconds:
            raise ValueError("jitter_seconds must not exceed max_backoff_seconds")
        if self.cache_policy != "none":
            raise ValueError("M1A PubMed cache_policy must be 'none'")

    @property
    def max_cumulative_payload_bytes(self) -> int:
        """Expose the payload limit using its policy-level meaning."""

        return self.max_payload_bytes


@dataclass(frozen=True, slots=True)
class PubMedFailure:
    """Typed connector failure safe to carry across the adapter boundary."""

    kind: PubMedFailureKind
    message: str
    retryable: bool
    status_code: int | None = None
    cause_kind: PubMedFailureKind | None = None

    def __post_init__(self) -> None:
        if not self.message.strip():
            raise ValueError("failure message must not be blank")
        if self.status_code is not None and not 100 <= self.status_code <= 599:
            raise ValueError("status_code must be an HTTP status")
        if self.kind is PubMedFailureKind.RETRY_EXHAUSTED:
            if self.cause_kind is None:
                raise ValueError("retry exhaustion requires cause_kind")
            if self.cause_kind is PubMedFailureKind.RETRY_EXHAUSTED:
                raise ValueError("retry exhaustion cannot cause itself")
        elif self.cause_kind is not None:
            raise ValueError("cause_kind is reserved for retry exhaustion")


@dataclass(frozen=True, slots=True)
class RawPubMedResponse:
    """Validated raw response material retained for later snapshotting."""

    request_url: str
    final_url: str
    status_code: int
    body: bytes
    headers: tuple[tuple[str, str], ...] = ()
    page_number: int = 1
    attempt_count: int = 1

    def __post_init__(self) -> None:
        if not self.request_url or not self.final_url:
            raise ValueError("request and final URLs must not be blank")
        if not 100 <= self.status_code <= 599:
            raise ValueError("status_code must be an HTTP status")
        if self.page_number < 1:
            raise ValueError("page_number must be positive")
        if self.attempt_count < 1:
            raise ValueError("attempt_count must be positive")


@dataclass(frozen=True, slots=True)
class RetryEvent:
    """Auditable record of a single bounded retry decision."""

    attempt_number: int
    delay_seconds: float
    failure_kind: PubMedFailureKind
    status_code: int | None = None
    used_retry_after: bool = False

    def __post_init__(self) -> None:
        if self.attempt_number < 1:
            raise ValueError("attempt_number must be positive")
        _require_bounded_float(
            "delay_seconds",
            self.delay_seconds,
            minimum_inclusive=0.0,
            maximum=MAX_TOTAL_DEADLINE_SECONDS,
        )
        if self.status_code is not None and not 100 <= self.status_code <= 599:
            raise ValueError("status_code must be an HTTP status")


def validate_pubmed_url(url: str, expected_path: str) -> str:
    """Validate and canonicalize one exact PubMed E-utilities endpoint URL."""

    if expected_path not in PUBMED_ENDPOINT_PATHS:
        raise ValueError("expected_path is not an approved PubMed endpoint")
    if not url or any(ord(character) < 32 or ord(character) == 127 for character in url):
        raise ValueError("URL is blank or contains control characters")

    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError as error:
        raise ValueError("URL authority is malformed") from error

    if parts.scheme.casefold() != "https":
        raise ValueError("PubMed endpoint requires HTTPS")
    if parts.username is not None or parts.password is not None or "@" in parts.netloc:
        raise ValueError("userinfo is forbidden in PubMed URLs")
    if parts.hostname is None or parts.hostname.casefold() != PUBMED_HOST:
        raise ValueError("PubMed hostname is not the exact approved host")
    if port not in {None, 443}:
        raise ValueError("PubMed URL uses a non-HTTPS port")
    if parts.path != expected_path:
        raise ValueError("PubMed URL path is not the expected exact endpoint")
    if parts.fragment:
        raise ValueError("fragments are forbidden in PubMed URLs")

    authority = PUBMED_HOST if port is None else f"{PUBMED_HOST}:443"
    return urlunsplit(("https", authority, expected_path, parts.query, ""))


def resolve_pubmed_redirect(current_url: str, location: str, expected_path: str) -> str:
    """Resolve one redirect while preserving the exact origin and endpoint path."""

    canonical_current = validate_pubmed_url(current_url, expected_path)
    if not location or any(ord(character) < 32 or ord(character) == 127 for character in location):
        raise ValueError("redirect location is blank or contains control characters")
    resolved = urljoin(canonical_current, location)
    canonical_resolved = validate_pubmed_url(resolved, expected_path)
    if sorted(_strict_query_pairs(urlsplit(canonical_current).query)) != sorted(
        _strict_query_pairs(urlsplit(canonical_resolved).query)
    ):
        raise ValueError("redirect must preserve the complete PubMed query")
    return canonical_resolved


def _strict_query_pairs(query: str) -> tuple[tuple[str, str], ...]:
    """Parse form-style query pairs without replacement decoding or normalization."""

    pairs: list[tuple[str, str]] = []
    for field in query.split("&"):
        if not field:
            continue
        name, separator, value = field.partition("=")
        pairs.append(
            (
                _strict_query_component(name),
                _strict_query_component(value if separator else ""),
            )
        )
    return tuple(pairs)


def _strict_query_component(component: str) -> str:
    """Validate percent escapes, decode bytes, and require exact UTF-8 text."""

    cursor = 0
    while cursor < len(component):
        percent_index = component.find("%", cursor)
        if percent_index < 0:
            break
        escape = component[percent_index + 1 : percent_index + 3]
        if len(escape) != 2 or any(character not in _ASCII_HEX_DIGITS for character in escape):
            raise ValueError("redirect query contains a malformed percent escape")
        cursor = percent_index + 3

    try:
        decoded_bytes = unquote_to_bytes(component.replace("+", " "))
        return decoded_bytes.decode("utf-8", errors="strict")
    except UnicodeError as error:
        raise ValueError("redirect query is not valid UTF-8") from error


def parse_retry_after(
    value: str | None,
    *,
    now: datetime,
    cap_seconds: float,
) -> float | None:
    """Parse an HTTP Retry-After value and cap it to a finite policy delay."""

    _require_bounded_float(
        "cap_seconds",
        cap_seconds,
        minimum_inclusive=0.0,
        maximum=MAX_TOTAL_DEADLINE_SECONDS,
    )
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    if value is None:
        return None
    candidate = value.strip()
    if not candidate:
        return None
    if _ASCII_DELTA_SECONDS.fullmatch(candidate):
        significant_digits = candidate.lstrip("0") or "0"
        if len(significant_digits) > 18:
            return cap_seconds
        return min(float(int(significant_digits)), cap_seconds)

    try:
        retry_at = parsedate_to_datetime(candidate)
    except (TypeError, ValueError, OverflowError):
        return None
    if retry_at is None:
        return None
    if retry_at.tzinfo is None:
        retry_at = retry_at.replace(tzinfo=UTC)
    delta_seconds = max(0.0, (retry_at - now).total_seconds())
    if not math.isfinite(delta_seconds):
        return None
    return min(delta_seconds, cap_seconds)


def retry_delay_seconds(
    attempt_number: int,
    *,
    config: PubMedConnectorConfig,
    jitter: float,
) -> float:
    """Return a deterministic capped exponential delay using injected jitter."""

    _require_bounded_int(
        "attempt_number",
        attempt_number,
        minimum=1,
        maximum=config.max_attempts,
    )
    _require_bounded_float(
        "jitter",
        jitter,
        minimum_inclusive=0.0,
        maximum=config.jitter_seconds,
    )
    exponential = config.base_backoff_seconds * (2 ** (attempt_number - 1))
    return float(min(exponential + jitter, config.max_backoff_seconds))


def _require_bounded_int(name: str, value: int, *, minimum: int, maximum: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer")
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")


def _require_bounded_float(
    name: str,
    value: float,
    *,
    maximum: float,
    minimum_inclusive: float | None = None,
    minimum_exclusive: float | None = None,
) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be numeric")
    numeric = float(value)
    if not math.isfinite(numeric):
        raise ValueError(f"{name} must be finite")
    if minimum_inclusive is not None and numeric < minimum_inclusive:
        raise ValueError(f"{name} must be at least {minimum_inclusive}")
    if minimum_exclusive is not None and numeric <= minimum_exclusive:
        raise ValueError(f"{name} must be greater than {minimum_exclusive}")
    if numeric > maximum:
        raise ValueError(f"{name} must not exceed {maximum}")
