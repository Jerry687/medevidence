"""Closed FAERS count-query serialization and transport policy."""

from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from enum import StrEnum
from typing import Final, Literal
from urllib.parse import quote, urlsplit

from medevidence.domain import GI_PT_SET_M1B_V1, FaersAggregateQueryV1

FAERS_SCHEME: Final = "https"
FAERS_HOST: Final = "api.fda.gov"
FAERS_PORT: Final = 443
FAERS_ORIGIN: Final = f"{FAERS_SCHEME}://{FAERS_HOST}"
FAERS_PATH: Final = "/drug/event.json"
FAERS_COUNT_FIELD: Final = "patient.reaction.reactionmeddrapt.exact"
FAERS_EXECUTION_PROFILE_ID: Final = "FAERS_M1B_CONSTRAINED_V1"
MAX_QUERY_CHARACTERS: Final = 512
MAX_PAGES: Final = 5
PAGE_SIZE: Final = 100
MAX_RECORDS: Final = 100
MAX_BUCKETS: Final = 100
MAX_PAYLOAD_BYTES: Final = 5_242_880
RETRYABLE_STATUS_CODES: Final = frozenset({408, 429, *range(500, 600)})
REDIRECT_STATUS_CODES: Final = frozenset(range(300, 400))
_ASCII_DELTA_SECONDS = re.compile(r"[0-9]+\Z")
_UPPER_PERCENT_ESCAPE = re.compile(r"%[0-9A-F]{2}")


class FaersFailureKind(StrEnum):
    """Typed connector failures without provider-native objects or payload text."""

    INVALID_INPUT = "invalid_input"
    TIMEOUT = "timeout"
    RATE_LIMITED = "rate_limited"
    AUTHENTICATION_OR_AUTHORIZATION = "authentication_or_authorization"
    CLIENT_ERROR = "client_error"
    UPSTREAM_UNAVAILABLE = "upstream_unavailable"
    RETRY_EXHAUSTED = "retry_exhausted"
    TRANSPORT = "transport"
    PAYLOAD_LIMIT = "payload_limit"
    REDIRECT_REJECTED = "redirect_rejected"
    MALFORMED_RESPONSE = "malformed_response"
    INTEGRITY_FAILURE = "integrity_failure"


@dataclass(frozen=True, slots=True)
class FaersConnectorConfig:
    """Exact Owner-frozen FAERS_M1B_CONSTRAINED_V1 transport profile."""

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
    max_redirects: Literal[0] = 0
    max_pages: int = MAX_PAGES
    page_size: int = PAGE_SIZE
    max_records: int = MAX_RECORDS
    max_buckets: int = MAX_BUCKETS
    max_response_bytes: int = MAX_PAYLOAD_BYTES
    max_cumulative_bytes: int = MAX_PAYLOAD_BYTES
    result_cache: Literal["none"] = "none"
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
            ("max_redirects", 0),
            ("max_pages", 5),
            ("page_size", 100),
            ("max_records", 100),
            ("max_buckets", 100),
            ("max_response_bytes", 5_242_880),
            ("max_cumulative_bytes", 5_242_880),
            ("result_cache", "none"),
            ("stale_fallback", False),
        )
        for name, frozen in expected:
            value = getattr(self, name)
            if type(value) is not type(frozen) or value != frozen:
                raise ValueError(f"{name} must equal the Owner-frozen value {frozen!r}")


@dataclass(frozen=True, slots=True)
class FaersRequest:
    """One validated provider-count request derived from a closed domain query."""

    query: FaersAggregateQueryV1
    provider_expression: str
    page_number: int = 1
    limit: Literal[100] = PAGE_SIZE
    skip: int = 0

    def __post_init__(self) -> None:
        if self.page_number < 1 or self.page_number > MAX_PAGES:
            raise ValueError("page_number must be within the frozen five-page ceiling")
        if self.limit != PAGE_SIZE:
            raise ValueError("FAERS count request limit must equal 100")
        if self.skip != (self.page_number - 1) * PAGE_SIZE:
            raise ValueError("FAERS count request skip must derive from the page number")

    @property
    def encoded_query(self) -> str:
        """Return the sole canonical, once-encoded query string."""

        search = _percent_encode(self.provider_expression)
        count = _percent_encode(FAERS_COUNT_FIELD)
        return f"search={search}&count={count}&limit={self.limit}&skip={self.skip}"

    @property
    def url(self) -> str:
        """Return the exact frozen HTTPS URL."""

        return f"{FAERS_ORIGIN}{FAERS_PATH}?{self.encoded_query}"

    def with_page(self, page_number: int) -> FaersRequest:
        """Return the same typed query at a derived bounded page offset."""

        return build_faers_request(self.query, page_number=page_number)


@dataclass(frozen=True, slots=True)
class FaersFailure:
    """Safe typed failure returned by the FAERS connector boundary."""

    kind: FaersFailureKind
    message: str
    retryable: bool = False
    status_code: int | None = None
    cause_kind: FaersFailureKind | None = None

    def __post_init__(self) -> None:
        if not self.message.strip():
            raise ValueError("failure message must not be blank")
        if self.status_code is not None and not 100 <= self.status_code <= 599:
            raise ValueError("status_code must be an HTTP status")
        if self.kind is FaersFailureKind.RETRY_EXHAUSTED:
            if self.cause_kind is None or self.cause_kind is self.kind:
                raise ValueError("retry exhaustion requires a distinct cause_kind")
        elif self.cause_kind is not None:
            raise ValueError("cause_kind is reserved for retry exhaustion")


@dataclass(frozen=True, slots=True)
class FaersRetryEvent:
    """Auditable bounded retry decision."""

    attempt_number: int
    delay_seconds: float
    failure_kind: FaersFailureKind
    status_code: int | None = None
    used_retry_after: bool = False

    def __post_init__(self) -> None:
        if self.attempt_number < 1:
            raise ValueError("attempt_number must be positive")
        if not math.isfinite(self.delay_seconds) or not 0 <= self.delay_seconds <= 30:
            raise ValueError("delay_seconds must be finite and within the deadline")


def serialize_faers_query(query: FaersAggregateQueryV1) -> str:
    """Serialize the exact three-clause FAERS AST before URL encoding."""

    validated = _validated_query(query)
    identity = _escape_provider_string(validated.identity_value)
    identity_clause = f'{validated.identity_field}:"{identity}"'
    pt_clauses = tuple(f'{validated.group_field}:"{term}"' for term in GI_PT_SET_M1B_V1)
    reaction_clause = f"({'+OR+'.join(pt_clauses)})"
    start = validated.inclusive_date_range.start_date.strftime("%Y%m%d")
    end = validated.inclusive_date_range.end_date.strftime("%Y%m%d")
    date_clause = f"receivedate:[{start}+TO+{end}]"
    expression = "+AND+".join((identity_clause, reaction_clause, date_clause))
    if len(expression) > MAX_QUERY_CHARACTERS:
        raise ValueError("FAERS provider expression exceeds 512 characters before encoding")
    return expression


def build_faers_request(query: FaersAggregateQueryV1, *, page_number: int = 1) -> FaersRequest:
    """Build the sole count-mode request from a validated domain query."""

    if isinstance(page_number, bool) or not isinstance(page_number, int):
        raise TypeError("page_number must be an integer")
    validated = _validated_query(query)
    request = FaersRequest(
        query=validated,
        provider_expression=serialize_faers_query(validated),
        page_number=page_number,
        skip=(page_number - 1) * PAGE_SIZE,
    )
    return request


def validate_faers_request(request: FaersRequest) -> FaersRequest:
    """Rebuild every request field and reject post-construction drift."""

    if type(request) is not FaersRequest:
        raise TypeError("request must be an exact FaersRequest")
    canonical = build_faers_request(request.query, page_number=request.page_number)
    if request != canonical:
        raise ValueError("request does not equal its frozen derived design")
    return canonical


def validate_connector_config(config: FaersConnectorConfig) -> FaersConnectorConfig:
    """Copy and revalidate every frozen connector setting."""

    if type(config) is not FaersConnectorConfig:
        raise TypeError("config must be an exact FaersConnectorConfig")
    return FaersConnectorConfig(
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
        page_size=config.page_size,
        max_records=config.max_records,
        max_buckets=config.max_buckets,
        max_response_bytes=config.max_response_bytes,
        max_cumulative_bytes=config.max_cumulative_bytes,
        result_cache=config.result_cache,
        stale_fallback=config.stale_fallback,
    )


def validate_faers_url(url: str, expected: FaersRequest) -> str:
    """Require exact origin, path, query order, and uppercase percent encoding."""

    canonical = validate_faers_request(expected)
    if not isinstance(url, str) or url != canonical.url:
        raise ValueError("FAERS URL must exactly equal the derived typed request")
    parts = urlsplit(url)
    if (
        parts.scheme != FAERS_SCHEME
        or parts.hostname != FAERS_HOST
        or parts.port not in {None, FAERS_PORT}
        or parts.path != FAERS_PATH
        or parts.fragment
        or parts.username is not None
        or parts.password is not None
    ):
        raise ValueError("FAERS URL violated the frozen HTTPS boundary")
    if "+" in parts.query:
        raise ValueError("spaces and provider plus tokens must be percent encoded")
    escapes = re.findall(r"%..", parts.query)
    if any(_UPPER_PERCENT_ESCAPE.fullmatch(item) is None for item in escapes):
        raise ValueError("percent escapes must use canonical uppercase hexadecimal")
    return url


def parse_retry_after(
    value: str | None, *, now: datetime, cap_seconds: float = 10.0
) -> float | None:
    """Parse Retry-After delta seconds or HTTP date within the frozen cap."""

    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    if not math.isfinite(cap_seconds) or not 0 <= cap_seconds <= 10:
        raise ValueError("Retry-After cap must be within ten seconds")
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
    """Return frozen exponential backoff plus injected bounded jitter."""

    if attempt_number not in {1, 2}:
        raise ValueError("attempt_number must be within the two-attempt budget")
    if not math.isfinite(jitter) or not 0 <= jitter <= 0.1:
        raise ValueError("jitter must be within the frozen 100 ms bound")
    return float(min(0.25 * (2 ** (attempt_number - 1)) + jitter, 4.0))


def _validated_query(query: FaersAggregateQueryV1) -> FaersAggregateQueryV1:
    if type(query) is not FaersAggregateQueryV1:
        raise TypeError("query must be an exact FaersAggregateQueryV1")
    return FaersAggregateQueryV1.model_validate(query.model_dump(mode="python"))


def _escape_provider_string(value: str) -> str:
    if unicodedata.normalize("NFC", value) != value:
        raise ValueError("identity value must already be canonical Unicode NFC")
    if "%" in value:
        raise ValueError("pre-encoded percent input is forbidden")
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise ValueError("identity value contains forbidden controls")
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _percent_encode(value: str) -> str:
    encoded = quote(value, safe="", encoding="utf-8", errors="strict")
    if "+" in encoded or any(
        _UPPER_PERCENT_ESCAPE.fullmatch(item) is None for item in re.findall(r"%..", encoded)
    ):
        raise RuntimeError("standard-library percent encoder violated the frozen contract")
    return encoded


__all__ = [
    "FAERS_COUNT_FIELD",
    "FAERS_EXECUTION_PROFILE_ID",
    "FAERS_HOST",
    "FAERS_PATH",
    "MAX_BUCKETS",
    "MAX_PAGES",
    "MAX_PAYLOAD_BYTES",
    "MAX_QUERY_CHARACTERS",
    "PAGE_SIZE",
    "FaersConnectorConfig",
    "FaersFailure",
    "FaersFailureKind",
    "FaersRequest",
    "FaersRetryEvent",
    "build_faers_request",
    "parse_retry_after",
    "retry_delay_seconds",
    "serialize_faers_query",
    "validate_connector_config",
    "validate_faers_request",
    "validate_faers_url",
]
