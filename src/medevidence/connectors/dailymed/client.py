"""Synchronous, transport-injected, bounded DailyMed connector."""

from __future__ import annotations

import random
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Literal, TypeVar

import httpx

from .parsing import (
    DailyMedCandidatePage,
    DailyMedHistoryPage,
    DailyMedParseError,
    ParsedSplDocument,
    parse_candidate_page,
    parse_historical_zip,
    parse_history_page,
    parse_spl_document,
)
from .policy import (
    REDIRECT_STATUS_CODES,
    RETRYABLE_STATUS_CODES,
    DailyMedConnectorConfig,
    DailyMedFailure,
    DailyMedFailureKind,
    DailyMedOperation,
    DailyMedRequest,
    RetryEvent,
    build_dailymed_request,
    parse_retry_after,
    resolve_dailymed_redirect,
    retry_delay_seconds,
    validate_connector_config,
    validate_dailymed_request,
    validate_dailymed_url,
)

T = TypeVar("T")
_SAFE_RESPONSE_HEADERS = frozenset(
    {
        "content-encoding",
        "content-length",
        "content-type",
        "location",
        "retry-after",
        "x-ratelimit-remaining",
    }
)
_RETAINED_RESPONSE_HEADERS = _SAFE_RESPONSE_HEADERS - {"location"}


def _canonical_content_length(value: str) -> int:
    if not value or not value.isascii() or not value.isdecimal():
        raise ValueError("Content-Length must be a canonical ASCII decimal")
    length = int(value)
    if str(length) != value:
        raise ValueError("Content-Length must not contain signs, whitespace, or leading zeros")
    if length > 5_242_880:
        raise ValueError("Content-Length exceeds the frozen raw-body bound")
    return length


def _validated_response_headers(
    headers: httpx.Headers,
) -> tuple[tuple[tuple[str, str], ...], int | None]:
    raw_content_lengths = [
        value for name, value in headers.raw if name.lower() == b"content-length"
    ]
    if len(raw_content_lengths) > 1:
        raise ValueError("Content-Length must have exactly one raw occurrence when present")
    raw_transfer_encodings = [
        value for name, value in headers.raw if name.lower() == b"transfer-encoding"
    ]
    if raw_content_lengths and raw_transfer_encodings:
        raise ValueError("Content-Length and Transfer-Encoding cannot coexist")
    declared_length: int | None = None
    canonical_length: str | None = None
    if raw_content_lengths:
        try:
            canonical_length = raw_content_lengths[0].decode("ascii", errors="strict")
        except UnicodeError as error:
            raise ValueError("Content-Length must be ASCII") from error
        declared_length = _canonical_content_length(canonical_length)

    encoding_values = headers.get_list("content-encoding")
    canonical_encoding: str | None = None
    if encoding_values:
        if len(encoding_values) != 1:
            raise ValueError("multiple Content-Encoding fields are forbidden")
        raw_encoding = encoding_values[0]
        canonical_encoding = raw_encoding.strip(" \t").casefold()
        if canonical_encoding != "identity" or "," in raw_encoding:
            raise ValueError("Content-Encoding must canonically equal identity")

    retained: dict[str, str] = {}
    for name, value in headers.multi_items():
        folded = name.casefold()
        if folded not in _RETAINED_RESPONSE_HEADERS or folded in {
            "content-encoding",
            "content-length",
        }:
            continue
        if folded in retained:
            raise ValueError("duplicate retained response headers are forbidden")
        retained[folded] = value
    if canonical_encoding is not None:
        retained["content-encoding"] = canonical_encoding
    if canonical_length is not None:
        retained["content-length"] = canonical_length
    return tuple(sorted(retained.items())), declared_length


@dataclass(frozen=True, slots=True)
class RawDailyMedResponse:
    """Validated response bytes retained for immutable snapshotting."""

    request_url: str
    final_url: str
    status_code: int
    body: bytes
    observed_at_utc: datetime
    body_complete: bool = True
    termination_reason: Literal[
        "complete_response", "payload_limit", "stream_error", "deadline_exceeded"
    ] = "complete_response"
    headers: tuple[tuple[str, str], ...] = ()
    page_number: int = 1
    attempt_count: int = 1

    def __post_init__(self) -> None:
        if not isinstance(self.body, bytes):
            raise TypeError("retained DailyMed body must be exact bytes")
        if self.observed_at_utc.tzinfo is None or self.observed_at_utc.utcoffset() != timedelta(0):
            raise ValueError("observed_at_utc must be timezone-aware UTC")
        if self.body_complete != (self.termination_reason == "complete_response"):
            raise ValueError("body_complete must exactly match complete_response termination")
        if self.page_number < 1 or self.attempt_count < 1:
            raise ValueError("page and attempt counts must be positive")
        if not isinstance(self.headers, tuple) or self.headers != tuple(sorted(self.headers)):
            raise ValueError("retained DailyMed headers must be a canonical sorted tuple")
        names: set[str] = set()
        for pair in self.headers:
            if not isinstance(pair, tuple) or len(pair) != 2:
                raise TypeError("retained DailyMed header entries must be exact pairs")
            name, value = pair
            if (
                not isinstance(name, str)
                or not isinstance(value, str)
                or name not in _RETAINED_RESPONSE_HEADERS
                or name != name.casefold()
                or name in names
            ):
                raise ValueError("retained DailyMed headers violate the closed evidence profile")
            if any(ord(character) < 32 or ord(character) == 127 for character in value):
                raise ValueError("retained DailyMed header values contain control characters")
            if name == "content-encoding" and value != "identity":
                raise ValueError("retained Content-Encoding must be canonical identity")
            names.add(name)
        header_map = dict(self.headers)
        if "content-length" in header_map:
            declared_length = _canonical_content_length(header_map["content-length"])
            if self.body_complete and len(self.body) != declared_length:
                raise ValueError("complete body length differs from Content-Length")


@dataclass(frozen=True, slots=True)
class DailyMedConnectorResult[T]:
    """Bounded operation result with raw responses and retry evidence."""

    value: T | None
    failure: DailyMedFailure | None
    raw_responses: tuple[RawDailyMedResponse, ...]
    retry_events: tuple[RetryEvent, ...]
    request_count: int
    pages_completed: int
    truncated: bool = False
    from_cache: bool = False

    def __post_init__(self) -> None:
        if (self.value is None) == (self.failure is None):
            raise ValueError("connector result requires exactly one value or failure")


@dataclass(slots=True)
class _Context:
    started_at: float
    raw_responses: list[RawDailyMedResponse] = field(default_factory=list)
    retry_events: list[RetryEvent] = field(default_factory=list)
    cumulative_bytes: int = 0
    request_count: int = 0
    pages_completed: int = 0


@dataclass(frozen=True, slots=True)
class _Response:
    request_url: str
    final_url: str
    status_code: int
    body: bytes
    headers: tuple[tuple[str, str], ...]

    def header(self, name: str) -> str | None:
        folded = name.casefold()
        return next((value for key, value in self.headers if key == folded), None)


class DailyMedConnector:
    """DailyMed adapter whose ordinary constructor requires an injected transport."""

    def __init__(
        self,
        transport: httpx.BaseTransport,
        config: DailyMedConnectorConfig | None = None,
        *,
        monotonic: Callable[[], float] = time.monotonic,
        utc_now: Callable[[], datetime] | None = None,
        sleep: Callable[[float], None] = time.sleep,
        jitter: Callable[[], float] | None = None,
    ) -> None:
        if not isinstance(transport, httpx.BaseTransport):
            raise TypeError("transport must implement httpx.BaseTransport")
        self._config = validate_connector_config(config or DailyMedConnectorConfig())
        self._monotonic = monotonic
        self._utc_now = utc_now or (lambda: datetime.now(UTC))
        self._sleep = sleep
        self._jitter = jitter or (lambda: random.uniform(0, self._config.jitter_seconds))
        self._cache: dict[tuple[str, str, bool], bytes] = {}
        self._client = httpx.Client(
            transport=transport,
            follow_redirects=False,
            trust_env=False,
            headers={
                "Accept-Encoding": "identity",
                "User-Agent": "medevidence/m1b-dm-002",
            },
        )
        self._closed = False

    @property
    def config(self) -> DailyMedConnectorConfig:
        return validate_connector_config(self._config)

    def close(self) -> None:
        if not self._closed:
            self._client.close()
            self._closed = True

    def __enter__(self) -> DailyMedConnector:
        if self._closed:
            raise RuntimeError("connector is closed")
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def discover(
        self, **query: object
    ) -> DailyMedConnectorResult[tuple[DailyMedCandidatePage, ...]]:
        """Retrieve at most five pages and 100 parsed candidates without caching."""

        try:
            request = build_dailymed_request(DailyMedOperation.DISCOVERY, query=query)
        except (TypeError, ValueError) as error:
            return self._input_failure(error)
        context = _Context(self._monotonic())
        pages: list[DailyMedCandidatePage] = []
        candidate_count = 0
        for page_number in range(1, self._config.max_pages + 1):
            current = request.with_page(page_number)
            response, failure = self._send_with_retries(context, current, page_number)
            if failure is not None:
                return self._failed(context, failure)
            assert response is not None
            try:
                requested_pagesize = dict(current.query).get("pagesize")
                page = parse_candidate_page(
                    response.body,
                    expected_page=page_number,
                    expected_pagesize=(
                        int(requested_pagesize) if requested_pagesize is not None else None
                    ),
                )
            except DailyMedParseError as error:
                return self._failed(context, self._parse_failure(error))
            context.pages_completed += 1
            pages.append(page)
            candidate_count += len(page.candidates)
            if candidate_count > self._config.max_candidates:
                return self._failed(
                    context,
                    DailyMedFailure(
                        DailyMedFailureKind.PAYLOAD_LIMIT,
                        "DailyMed discovery exceeded the 100-candidate bound.",
                    ),
                )
            if page.next_page is None:
                return self._success(context, tuple(pages))
            if candidate_count == self._config.max_candidates:
                return self._success(context, tuple(pages), truncated=True)
            next_page_count = min(page.pagesize, page.total - candidate_count)
            if candidate_count + next_page_count > self._config.max_candidates:
                return self._success(context, tuple(pages), truncated=True)
        return DailyMedConnectorResult(
            value=tuple(pages),
            failure=None,
            raw_responses=tuple(context.raw_responses),
            retry_events=tuple(context.retry_events),
            request_count=context.request_count,
            pages_completed=context.pages_completed,
            truncated=pages[-1].next_page is not None,
        )

    def history(
        self, setid: str, *, pagesize: int = 100
    ) -> DailyMedConnectorResult[tuple[DailyMedHistoryPage, ...]]:
        """Retrieve bounded exact-SETID history with identity parity."""

        try:
            request = build_dailymed_request(
                DailyMedOperation.HISTORY,
                setid=setid,
                query={"pagesize": pagesize, "page": 1},
            )
        except (TypeError, ValueError) as error:
            return self._input_failure(error)
        context = _Context(self._monotonic())
        pages: list[DailyMedHistoryPage] = []
        record_count = 0
        for page_number in range(1, self._config.max_pages + 1):
            current = request.with_page(page_number)
            response, failure = self._send_with_retries(context, current, page_number)
            if failure is not None:
                return self._failed(context, failure)
            assert response is not None
            try:
                page = parse_history_page(
                    response.body,
                    expected_setid=setid,
                    expected_page=page_number,
                    expected_pagesize=int(dict(current.query)["pagesize"]),
                )
            except DailyMedParseError as error:
                return self._failed(context, self._parse_failure(error))
            pages.append(page)
            context.pages_completed += 1
            record_count += len(page.records)
            if record_count > self._config.max_candidates:
                return self._failed(
                    context,
                    DailyMedFailure(
                        DailyMedFailureKind.PAYLOAD_LIMIT,
                        "DailyMed history exceeded the 100-record bound.",
                    ),
                )
            if page.next_page is None:
                return self._success(context, tuple(pages))
            if record_count == self._config.max_candidates:
                return self._success(context, tuple(pages), truncated=True)
            next_page_count = min(page.pagesize, page.total - record_count)
            if record_count + next_page_count > self._config.max_candidates:
                return self._success(context, tuple(pages), truncated=True)
        return DailyMedConnectorResult(
            value=tuple(pages),
            failure=None,
            raw_responses=tuple(context.raw_responses),
            retry_events=tuple(context.retry_events),
            request_count=context.request_count,
            pages_completed=context.pages_completed,
            truncated=pages[-1].next_page is not None,
        )

    def fetch_spl(
        self,
        setid: str,
        spl_version: str,
        *,
        historical: bool,
    ) -> DailyMedConnectorResult[ParsedSplDocument]:
        """Fetch and validate an exact current XML or historical ZIP label version."""

        try:
            request = build_dailymed_request(
                DailyMedOperation.HISTORICAL_SPL if historical else DailyMedOperation.CURRENT_SPL,
                setid=setid,
                spl_version=spl_version,
            )
        except (TypeError, ValueError) as error:
            return self._input_failure(error)
        if request.setid is None or request.spl_version is None:
            raise RuntimeError("typed SPL request omitted its validated fixed-version identity")
        cache_key = (request.setid, request.spl_version, historical)
        cached_payload = self._cache.get(cache_key)
        if cached_payload is not None:
            try:
                cached = self._parse_spl_payload(cached_payload, request, historical)
            except DailyMedParseError:
                return DailyMedConnectorResult(
                    value=None,
                    failure=DailyMedFailure(
                        DailyMedFailureKind.CACHE_CONFLICT,
                        "Immutable DailyMed fixed-version cache failed identity verification.",
                    ),
                    raw_responses=(),
                    retry_events=(),
                    request_count=0,
                    pages_completed=0,
                )
            return DailyMedConnectorResult(
                value=cached,
                failure=None,
                raw_responses=(),
                retry_events=(),
                request_count=0,
                pages_completed=0,
                from_cache=True,
            )
        context = _Context(self._monotonic())
        response, failure = self._send_with_retries(context, request, 1)
        if failure is not None:
            return self._failed(context, failure)
        assert response is not None
        try:
            parsed = self._parse_spl_payload(response.body, request, historical)
        except DailyMedParseError as error:
            return self._failed(context, self._parse_failure(error))
        context.pages_completed = 1
        existing = self._cache.setdefault(cache_key, bytes(response.body))
        if existing != response.body:
            return self._failed(
                context,
                DailyMedFailure(
                    DailyMedFailureKind.CACHE_CONFLICT,
                    "Immutable DailyMed fixed-version cache entry conflicts with parsed bytes.",
                ),
            )
        return self._success(context, parsed)

    @staticmethod
    def _parse_spl_payload(
        payload: bytes, request: DailyMedRequest, historical: bool
    ) -> ParsedSplDocument:
        if request.setid is None or request.spl_version is None:
            raise RuntimeError("validated SPL request omitted fixed-version identity")
        return (
            parse_historical_zip(
                payload,
                expected_setid=request.setid,
                expected_spl_version=request.spl_version,
            )
            if historical
            else parse_spl_document(
                payload,
                expected_setid=request.setid,
                expected_spl_version=request.spl_version,
            )
        )

    def _send_with_retries(
        self, context: _Context, request: DailyMedRequest, page: int
    ) -> tuple[_Response | None, DailyMedFailure | None]:
        try:
            request = validate_dailymed_request(request)
        except (TypeError, ValueError):
            return None, DailyMedFailure(
                DailyMedFailureKind.INVALID_INPUT,
                "DailyMed request violated the frozen typed design.",
            )
        for attempt in range(1, self._config.max_attempts + 1):
            response, failure = self._send_once(context, request, page, attempt)
            cause: DailyMedFailureKind
            if failure is not None:
                if failure.kind not in {DailyMedFailureKind.TIMEOUT, DailyMedFailureKind.TRANSPORT}:
                    return None, failure
                cause = failure.kind
            else:
                assert response is not None
                if response.status_code not in RETRYABLE_STATUS_CODES:
                    return response, None
                cause = (
                    DailyMedFailureKind.RATE_LIMITED
                    if response.status_code == 429
                    else DailyMedFailureKind.UPSTREAM_UNAVAILABLE
                )
            status = response.status_code if response is not None else None
            if attempt == self._config.max_attempts:
                return None, DailyMedFailure(
                    DailyMedFailureKind.RETRY_EXHAUSTED,
                    "DailyMed retry attempt budget was exhausted.",
                    status_code=status,
                    cause_kind=cause,
                )
            try:
                retry_after = (
                    parse_retry_after(
                        response.header("retry-after"),
                        now=self._require_utc(),
                        cap_seconds=self._config.max_retry_after_seconds,
                    )
                    if response is not None
                    else None
                )
                delay = (
                    retry_after
                    if retry_after is not None
                    else retry_delay_seconds(attempt, jitter=self._jitter())
                )
            except (TypeError, ValueError):
                return None, DailyMedFailure(
                    DailyMedFailureKind.INTEGRITY_FAILURE,
                    "Injected retry timing violated the frozen policy.",
                )
            if delay > self._remaining(context):
                return None, DailyMedFailure(
                    DailyMedFailureKind.RETRY_EXHAUSTED,
                    "Retry delay would exceed the DailyMed total deadline.",
                    status_code=status,
                    cause_kind=cause,
                )
            context.retry_events.append(
                RetryEvent(attempt, delay, cause, status, retry_after is not None)
            )
            self._sleep(delay)
        raise RuntimeError("bounded retry loop terminated without a result")

    def _send_once(
        self, context: _Context, typed: DailyMedRequest, page: int, attempt: int
    ) -> tuple[_Response | None, DailyMedFailure | None]:
        remaining = self._remaining(context)
        if remaining <= 0:
            return None, DailyMedFailure(DailyMedFailureKind.TIMEOUT, "DailyMed deadline expired.")
        current_url = typed.url
        redirects = 0
        while True:
            timeout = httpx.Timeout(
                connect=min(self._config.connect_timeout_seconds, remaining),
                read=min(self._config.read_timeout_seconds, remaining),
                write=min(self._config.write_timeout_seconds, remaining),
                pool=min(self._config.pool_timeout_seconds, remaining),
            )
            try:
                canonical_url = validate_dailymed_url(current_url, typed)
                request = self._client.build_request("GET", canonical_url, timeout=timeout)
                validate_dailymed_url(str(request.url), typed)
            except ValueError:
                return None, DailyMedFailure(
                    DailyMedFailureKind.REDIRECT_REJECTED,
                    "DailyMed URL violated the frozen request policy.",
                )
            context.request_count += 1
            try:
                response = self._client.send(request, stream=True, follow_redirects=False)
                try:
                    try:
                        headers, declared_length = _validated_response_headers(response.headers)
                    except ValueError:
                        return None, DailyMedFailure(
                            DailyMedFailureKind.INTEGRITY_FAILURE,
                            "DailyMed response framing violated the exact-byte policy.",
                        )
                    body, complete, termination = self._read_body(response, context)
                    if complete and declared_length is not None and len(body) != declared_length:
                        return None, DailyMedFailure(
                            DailyMedFailureKind.INTEGRITY_FAILURE,
                            "DailyMed complete raw body differs from Content-Length.",
                        )
                    raw = RawDailyMedResponse(
                        request_url=str(request.url),
                        final_url=str(response.url),
                        status_code=response.status_code,
                        body=body,
                        observed_at_utc=self._require_utc(),
                        body_complete=complete,
                        termination_reason=termination,
                        headers=headers,
                        page_number=page,
                        attempt_count=attempt,
                    )
                    context.raw_responses.append(raw)
                    if not complete:
                        kind = (
                            DailyMedFailureKind.PAYLOAD_LIMIT
                            if termination == "payload_limit"
                            else DailyMedFailureKind.TIMEOUT
                            if termination == "deadline_exceeded"
                            else DailyMedFailureKind.TRANSPORT
                        )
                        return None, DailyMedFailure(
                            kind, "DailyMed response was not completely retained."
                        )
                    if response.status_code in REDIRECT_STATUS_CODES:
                        location = response.headers.get("location")
                        if redirects >= self._config.max_redirects:
                            return None, DailyMedFailure(
                                DailyMedFailureKind.REDIRECT_REJECTED,
                                "DailyMed redirect budget was exceeded.",
                            )
                        try:
                            current_url = resolve_dailymed_redirect(
                                current_url, location or "", typed
                            )
                        except ValueError:
                            return None, DailyMedFailure(
                                DailyMedFailureKind.REDIRECT_REJECTED,
                                "DailyMed redirect changed origin, path, or query.",
                            )
                        redirects += 1
                        remaining = self._remaining(context)
                        continue
                    result = _Response(
                        str(request.url), str(response.url), response.status_code, body, headers
                    )
                finally:
                    response.close()
            except httpx.TimeoutException:
                return None, DailyMedFailure(
                    DailyMedFailureKind.TIMEOUT, "DailyMed transport timed out.", retryable=True
                )
            except httpx.TransportError:
                return None, DailyMedFailure(
                    DailyMedFailureKind.TRANSPORT, "DailyMed transport failed.", retryable=True
                )
            if result.status_code == 200:
                return result, None
            if result.status_code in RETRYABLE_STATUS_CODES:
                return result, None
            if 400 <= result.status_code < 500:
                return None, DailyMedFailure(
                    DailyMedFailureKind.CLIENT_ERROR,
                    "DailyMed returned a permanent client error.",
                    status_code=result.status_code,
                )
            return None, DailyMedFailure(
                DailyMedFailureKind.UPSTREAM_UNAVAILABLE,
                "DailyMed returned an unsupported upstream response.",
                status_code=result.status_code,
            )

    def _read_body(
        self, response: httpx.Response, context: _Context
    ) -> tuple[
        bytes,
        bool,
        Literal["complete_response", "payload_limit", "stream_error", "deadline_exceeded"],
    ]:
        chunks: list[bytes] = []
        try:
            raw_chunks = (response.content,) if response.is_stream_consumed else response.iter_raw()
            for chunk in raw_chunks:
                if self._remaining(context) <= 0:
                    return b"".join(chunks), False, "deadline_exceeded"
                if context.cumulative_bytes + len(chunk) > self._config.max_payload_bytes:
                    retained = self._config.max_payload_bytes - context.cumulative_bytes
                    if retained > 0:
                        chunks.append(chunk[:retained])
                        context.cumulative_bytes += retained
                    return b"".join(chunks), False, "payload_limit"
                chunks.append(chunk)
                context.cumulative_bytes += len(chunk)
        except httpx.TransportError:
            return b"".join(chunks), False, "stream_error"
        return b"".join(chunks), True, "complete_response"

    def _remaining(self, context: _Context) -> float:
        return self._config.total_deadline_seconds - (self._monotonic() - context.started_at)

    def _require_utc(self) -> datetime:
        value = self._utc_now()
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("injected clock must return timezone-aware UTC")
        return value

    @staticmethod
    def _parse_failure(error: DailyMedParseError) -> DailyMedFailure:
        kind = (
            DailyMedFailureKind.IDENTITY_DRIFT
            if "identity" in str(error).casefold() or "setid" in str(error).casefold()
            else DailyMedFailureKind.MALFORMED_RESPONSE
        )
        return DailyMedFailure(kind, "DailyMed response failed the frozen parser policy.")

    def _input_failure(self, error: Exception) -> DailyMedConnectorResult[T]:
        del error
        return DailyMedConnectorResult(
            value=None,
            failure=DailyMedFailure(
                DailyMedFailureKind.INVALID_INPUT, "DailyMed input is invalid."
            ),
            raw_responses=(),
            retry_events=(),
            request_count=0,
            pages_completed=0,
        )

    @staticmethod
    def _success(
        context: _Context, value: T, *, truncated: bool = False
    ) -> DailyMedConnectorResult[T]:
        return DailyMedConnectorResult(
            value=value,
            failure=None,
            raw_responses=tuple(context.raw_responses),
            retry_events=tuple(context.retry_events),
            request_count=context.request_count,
            pages_completed=context.pages_completed,
            truncated=truncated,
        )

    @staticmethod
    def _failed(context: _Context, failure: DailyMedFailure) -> DailyMedConnectorResult[T]:
        return DailyMedConnectorResult(
            value=None,
            failure=failure,
            raw_responses=tuple(context.raw_responses),
            retry_events=tuple(context.retry_events),
            request_count=context.request_count,
            pages_completed=context.pages_completed,
        )


__all__ = ["DailyMedConnector", "DailyMedConnectorResult", "RawDailyMedResponse"]
