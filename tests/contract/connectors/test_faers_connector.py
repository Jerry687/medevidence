from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import httpx
import pytest

from medevidence.connectors.faers import FaersConnector, FaersFailureKind
from medevidence.domain import (
    FaersAggregateQueryV1,
    FaersAggregateRequestV1,
    FaersExecutionBoundsV1,
    FaersIdentityStrategy,
    FaersInclusiveDateRangeV1,
)

FIXTURES = Path(__file__).parents[2] / "fixtures" / "faers"


class _RawStream(httpx.SyncByteStream):
    def __init__(self, chunks: tuple[bytes, ...]) -> None:
        self._chunks = chunks

    def __iter__(self):  # type: ignore[no-untyped-def]
        yield from self._chunks


class _FailingRawStream(httpx.SyncByteStream):
    def __iter__(self):  # type: ignore[no-untyped-def]
        yield b'{"results":['
        raise httpx.ReadError("synthetic stream failure")


class _ReadTimeoutRawStream(httpx.SyncByteStream):
    def __iter__(self):  # type: ignore[no-untyped-def]
        yield b'{"results":['
        raise httpx.ReadTimeout("synthetic streamed read timeout")


def _fixed_utc() -> datetime:
    return datetime(2026, 1, 1, tzinfo=UTC)


def _query() -> FaersAggregateQueryV1:
    return FaersAggregateQueryV1.create(
        FaersAggregateRequestV1(
            drug_concept_id="drug:test",
            identity_strategy=FaersIdentityStrategy.HARMONIZED_SUBSTANCE,
            identity_exact_value="TEST DRUG",
            pt_values=("DIARRHOEA", "NAUSEA", "VOMITING"),
            inclusive_date_range=FaersInclusiveDateRangeV1(
                start_date=date(2025, 1, 1), end_date=date(2025, 12, 31)
            ),
            execution_bounds=FaersExecutionBoundsV1(
                max_date_difference_days=365,
                max_inclusive_calendar_dates=366,
            ),
            statistical_unit="provider_count_occurrence",
        )
    )


def test_connector_uses_only_injected_transport_and_exact_count_request() -> None:
    observed: list[httpx.Request] = []
    body = (FIXTURES / "count-single-bucket.json").read_bytes()

    def handler(request: httpx.Request) -> httpx.Response:
        observed.append(request)
        return httpx.Response(200, content=body)

    with FaersConnector(httpx.MockTransport(handler), utc_now=_fixed_utc) as connector:
        result = connector.aggregate(_query())
    assert result.failure is None
    assert result.value is not None
    assert result.value.buckets[0].reaction_pt == "NAUSEA"
    assert result.raw_responses[0].body == body
    assert result.raw_responses[0].body_complete is True
    assert len(observed) == 1
    request = observed[0]
    assert request.method == "GET"
    assert request.url.host == "api.fda.gov"
    assert request.url.path == "/drug/event.json"
    assert request.url.params["count"] == "patient.reaction.reactionmeddrapt.exact"
    assert request.url.params["limit"] == "100"
    assert request.url.params["skip"] == "0"
    assert "drugcharacterization" not in request.url.params["search"]
    assert request.headers["accept-encoding"] == "identity"


def test_empty_complete_count_is_a_successful_bounded_page() -> None:
    body = (FIXTURES / "count-empty.json").read_bytes()
    with FaersConnector(
        httpx.MockTransport(lambda _: httpx.Response(200, content=body)), utc_now=_fixed_utc
    ) as connector:
        result = connector.query(_query())
    assert result.failure is None
    assert result.value is not None and result.value.buckets == ()
    assert result.pages_completed == 1
    assert result.truncated is False


def test_connector_retries_429_once_with_capped_retry_after() -> None:
    attempts = 0
    sleeps: list[float] = []

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(
                429,
                headers={"Retry-After": "99"},
                content=(FIXTURES / "error-429.json").read_bytes(),
            )
        return httpx.Response(200, content=(FIXTURES / "count-empty.json").read_bytes())

    with FaersConnector(
        httpx.MockTransport(handler),
        utc_now=_fixed_utc,
        sleep=sleeps.append,
        jitter=lambda: 0.0,
    ) as connector:
        result = connector.aggregate(_query())
    assert result.failure is None
    assert result.request_count == 2
    assert len(result.raw_responses) == 2
    assert sleeps == [10.0]
    assert result.retry_events[0].failure_kind is FaersFailureKind.RATE_LIMITED
    assert result.retry_events[0].used_retry_after is True


@pytest.mark.parametrize("status", [408, 500, 503])
def test_connector_retries_only_frozen_http_classes(status: int) -> None:
    attempts = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(status, content=b"{}")

    with FaersConnector(
        httpx.MockTransport(handler),
        utc_now=_fixed_utc,
        sleep=lambda _: None,
        jitter=lambda: 0.0,
    ) as connector:
        result = connector.aggregate(_query())
    assert result.failure is not None
    assert result.failure.kind is FaersFailureKind.RETRY_EXHAUSTED
    assert attempts == 2


def test_connector_retries_connect_and_read_timeouts_but_not_other_transport_errors() -> None:
    for exception, expected_attempts in (
        (httpx.ConnectTimeout("synthetic timeout"), 2),
        (httpx.ReadTimeout("synthetic timeout"), 2),
        (httpx.ConnectError("synthetic failure"), 1),
    ):
        attempts = 0

        def handler(_: httpx.Request, error: httpx.TransportError = exception) -> httpx.Response:
            nonlocal attempts
            attempts += 1
            raise error

        with FaersConnector(
            httpx.MockTransport(handler),
            utc_now=_fixed_utc,
            sleep=lambda _: None,
            jitter=lambda: 0.0,
        ) as connector:
            result = connector.aggregate(_query())
        assert result.failure is not None
        assert attempts == expected_attempts


def test_connector_rejects_redirect_without_following() -> None:
    requests = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        return httpx.Response(302, headers={"Location": "https://api.fda.gov/drug/event.json"})

    with FaersConnector(httpx.MockTransport(handler), utc_now=_fixed_utc) as connector:
        result = connector.aggregate(_query())
    assert result.failure is not None
    assert result.failure.kind is FaersFailureKind.REDIRECT_REJECTED
    assert requests == 1


@pytest.mark.parametrize("status", [400, 404, 422])
def test_connector_does_not_retry_permanent_client_errors(status: int) -> None:
    requests = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        return httpx.Response(status, content=b"{}")

    with FaersConnector(httpx.MockTransport(handler), utc_now=_fixed_utc) as connector:
        result = connector.aggregate(_query())
    assert result.failure is not None
    assert result.failure.kind is FaersFailureKind.CLIENT_ERROR
    assert requests == 1


@pytest.mark.parametrize("status", [401, 403])
def test_connector_maps_authentication_and_authorization_without_retry(status: int) -> None:
    requests = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        return httpx.Response(status, content=b"{}")

    with FaersConnector(httpx.MockTransport(handler), utc_now=_fixed_utc) as connector:
        result = connector.aggregate(_query())
    assert result.failure is not None
    assert result.failure.kind is FaersFailureKind.AUTHENTICATION_OR_AUTHORIZATION
    assert result.failure.status_code == status
    assert requests == 1


def test_malformed_or_raw_provider_envelope_never_establishes_a_count_page() -> None:
    for fixture in ("malformed.json", "raw-single-latest.json", "raw-truncated-page.json"):
        body = (FIXTURES / fixture).read_bytes()
        with FaersConnector(
            httpx.MockTransport(lambda _, body=body: httpx.Response(200, content=body)),
            utc_now=_fixed_utc,
        ) as connector:
            result = connector.aggregate(_query())
        assert result.value is None
        assert result.failure is not None
        assert result.failure.kind is FaersFailureKind.MALFORMED_RESPONSE
        assert result.raw_responses[0].body == body


def test_exact_payload_boundary_is_retained_and_plus_one_truncates() -> None:
    prefix = b'{"results":[]}'
    exact = prefix + (b" " * (5_242_880 - len(prefix)))
    with FaersConnector(
        httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                headers={"Content-Length": "5242880"},
                stream=_RawStream((exact[:3_000_000], exact[3_000_000:])),
            )
        ),
        utc_now=_fixed_utc,
    ) as connector:
        boundary = connector.aggregate(_query())
    assert boundary.failure is None
    assert boundary.value is not None
    assert boundary.truncated is True
    assert boundary.raw_responses[0].body == exact

    too_large = exact + b" "
    with FaersConnector(
        httpx.MockTransport(lambda _: httpx.Response(200, stream=_RawStream((too_large,)))),
        utc_now=_fixed_utc,
    ) as connector:
        plus_one = connector.aggregate(_query())
    assert plus_one.failure is not None
    assert plus_one.failure.kind is FaersFailureKind.PAYLOAD_LIMIT
    assert plus_one.truncated is True
    assert plus_one.raw_responses[0].body == exact
    assert plus_one.raw_responses[0].body_complete is False


@pytest.mark.parametrize(
    "headers",
    [
        [("Content-Length", "2"), ("Content-Length", "2")],
        [("Content-Length", "2"), ("Transfer-Encoding", "chunked")],
        [("Content-Length", "02")],
        [("Content-Length", "+2")],
        [("Content-Length", "5242881")],
        [("Content-Encoding", "gzip")],
    ],
)
def test_connector_rejects_ambiguous_or_nonidentity_response_framing(
    headers: list[tuple[str, str]],
) -> None:
    with FaersConnector(
        httpx.MockTransport(
            lambda _: httpx.Response(200, headers=headers, stream=_RawStream((b"{}",)))
        ),
        utc_now=_fixed_utc,
    ) as connector:
        result = connector.aggregate(_query())
    assert result.failure is not None
    assert result.failure.kind is FaersFailureKind.INTEGRITY_FAILURE
    assert result.raw_responses == ()


def test_connector_rejects_complete_content_length_mismatch() -> None:
    body = (FIXTURES / "count-empty.json").read_bytes()
    with FaersConnector(
        httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                headers={"Content-Length": str(len(body) + 1)},
                stream=_RawStream((body,)),
            )
        ),
        utc_now=_fixed_utc,
    ) as connector:
        result = connector.aggregate(_query())
    assert result.failure is not None
    assert result.failure.kind is FaersFailureKind.INTEGRITY_FAILURE
    assert result.raw_responses == ()


def test_partial_stream_retains_exact_bytes_and_truthful_termination() -> None:
    with FaersConnector(
        httpx.MockTransport(lambda _: httpx.Response(200, stream=_FailingRawStream())),
        utc_now=_fixed_utc,
    ) as connector:
        result = connector.aggregate(_query())
    assert result.failure is not None
    assert result.failure.kind is FaersFailureKind.TRANSPORT
    assert result.raw_responses[0].body == b'{"results":['
    assert result.raw_responses[0].body_complete is False
    assert result.raw_responses[0].termination_reason == "stream_error"


def test_streamed_read_timeout_retains_partial_bytes_and_retries_once() -> None:
    requests = 0
    sleeps: list[float] = []

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        return httpx.Response(200, stream=_ReadTimeoutRawStream())

    with FaersConnector(
        httpx.MockTransport(handler),
        utc_now=_fixed_utc,
        sleep=sleeps.append,
        jitter=lambda: 0.0,
    ) as connector:
        result = connector.aggregate(_query())
    assert result.failure is not None
    assert result.failure.kind is FaersFailureKind.RETRY_EXHAUSTED
    assert result.failure.cause_kind is FaersFailureKind.TIMEOUT
    assert result.request_count == requests == 2
    assert sleeps == [0.25]
    assert len(result.retry_events) == 1
    assert result.retry_events[0].failure_kind is FaersFailureKind.TIMEOUT
    assert len(result.raw_responses) == 2
    assert all(raw.body == b'{"results":[' for raw in result.raw_responses)
    assert all(raw.body_complete is False for raw in result.raw_responses)
    assert all(raw.termination_reason == "read_timeout" for raw in result.raw_responses)


def test_no_transport_is_implicitly_constructed() -> None:
    with pytest.raises(TypeError):
        FaersConnector(None)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "clock",
    [
        lambda: datetime(2026, 1, 1),
        lambda: "2026-01-01T00:00:00Z",
        lambda: None,
    ],
)
def test_invalid_injected_clock_is_typed_integrity_failure_without_evidence(
    clock: object,
) -> None:
    requests = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        return httpx.Response(200, content=(FIXTURES / "count-empty.json").read_bytes())

    with FaersConnector(
        httpx.MockTransport(handler),
        utc_now=clock,  # type: ignore[arg-type]
    ) as connector:
        result = connector.aggregate(_query())
    assert result.failure is not None
    assert result.failure.kind is FaersFailureKind.INTEGRITY_FAILURE
    assert result.raw_responses == ()
    assert result.request_count == requests == 0


@pytest.mark.parametrize(
    "foreign_url",
    [
        "https://example.invalid/drug/event.json",
        "https://api.fda.gov/foreign.json",
        "https://api.fda.gov/drug/event.json?search=foreign",
    ],
)
def test_connector_rejects_foreign_or_mismatched_final_url_before_evidence(
    foreign_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = (FIXTURES / "count-empty.json").read_bytes()

    with FaersConnector(
        httpx.MockTransport(lambda _: httpx.Response(500)), utc_now=_fixed_utc
    ) as connector:
        monkeypatch.setattr(
            connector._client,
            "send",
            lambda *_args, **_kwargs: httpx.Response(
                200,
                request=httpx.Request("GET", foreign_url),
                content=body,
            ),
        )
        result = connector.aggregate(_query())
    assert result.failure is not None
    assert result.failure.kind is FaersFailureKind.REDIRECT_REJECTED
    assert result.raw_responses == ()


@pytest.mark.parametrize(
    "payload",
    [
        b'{"results":[],"results":[]}',
        b'{"results":[{"term":"NAUSEA","count":' + (b"9" * 10_000) + b"}]}",
        b'{"results":[{"term":"NAUSEA","count":9223372036854775808}]}',
    ],
)
def test_connector_translates_json_numeric_and_duplicate_failures(payload: bytes) -> None:
    with FaersConnector(
        httpx.MockTransport(lambda _: httpx.Response(200, content=payload)),
        utc_now=_fixed_utc,
    ) as connector:
        result = connector.aggregate(_query())
    assert result.value is None
    assert result.failure is not None
    assert result.failure.kind is FaersFailureKind.MALFORMED_RESPONSE


class _MonotonicSequence:
    def __init__(self, values: list[object]) -> None:
        self._values = iter(values)

    def __call__(self) -> object:
        value = next(self._values)
        if isinstance(value, BaseException):
            raise value
        return value


@pytest.mark.parametrize(
    "value",
    [
        "0",
        None,
        True,
        float("nan"),
        float("inf"),
        float("-inf"),
        RuntimeError("synthetic monotonic failure"),
    ],
)
def test_invalid_initial_monotonic_sample_is_integrity_failure_without_io(value: object) -> None:
    requests = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        return httpx.Response(200, content=(FIXTURES / "count-empty.json").read_bytes())

    with FaersConnector(
        httpx.MockTransport(handler),
        utc_now=_fixed_utc,
        monotonic=_MonotonicSequence([value]),  # type: ignore[arg-type]
    ) as connector:
        result = connector.aggregate(_query())
    assert result.failure is not None
    assert result.failure.kind is FaersFailureKind.INTEGRITY_FAILURE
    assert result.request_count == requests == 0
    assert result.raw_responses == ()


@pytest.mark.parametrize(
    "later_value",
    ["1", None, True, float("nan"), float("inf"), RuntimeError("synthetic later failure")],
)
def test_invalid_later_monotonic_sample_retains_only_completed_prefix(
    later_value: object,
) -> None:
    body = (FIXTURES / "count-empty.json").read_bytes()

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=_RawStream((body[:10], body[10:])))

    clock = _MonotonicSequence([0.0, 0.0, 0.0, later_value])
    with FaersConnector(
        httpx.MockTransport(handler),
        utc_now=_fixed_utc,
        monotonic=clock,  # type: ignore[arg-type]
    ) as connector:
        result = connector.aggregate(_query())
    assert result.failure is not None
    assert result.failure.kind is FaersFailureKind.INTEGRITY_FAILURE
    assert result.request_count == 1
    assert len(result.raw_responses) == 1
    assert result.raw_responses[0].body == body[:10]
    assert result.raw_responses[0].body_complete is False
    assert result.raw_responses[0].termination_reason == "clock_integrity_failure"


def test_monotonic_rewind_cannot_extend_deadline_and_retains_prefix_truthfully() -> None:
    body = (FIXTURES / "count-empty.json").read_bytes()
    clock = _MonotonicSequence([10.0, 10.0, 10.0, 9.0])
    with FaersConnector(
        httpx.MockTransport(
            lambda _: httpx.Response(200, stream=_RawStream((body[:10], body[10:])))
        ),
        utc_now=_fixed_utc,
        monotonic=clock,  # type: ignore[arg-type]
    ) as connector:
        result = connector.aggregate(_query())
    assert result.failure is not None
    assert result.failure.kind is FaersFailureKind.INTEGRITY_FAILURE
    assert result.raw_responses[0].body == body[:10]
    assert result.raw_responses[0].termination_reason == "clock_integrity_failure"


def test_monotonic_deadline_is_exactly_bounded_at_thirty_seconds() -> None:
    requests = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        return httpx.Response(200, content=(FIXTURES / "count-empty.json").read_bytes())

    with FaersConnector(
        httpx.MockTransport(handler),
        utc_now=_fixed_utc,
        monotonic=_MonotonicSequence([5.0, 35.0, 35.0]),  # type: ignore[arg-type]
    ) as connector:
        result = connector.aggregate(_query())
    assert result.failure is not None
    assert result.failure.kind is FaersFailureKind.RETRY_EXHAUSTED
    assert result.failure.cause_kind is FaersFailureKind.TIMEOUT
    assert result.request_count == requests == 0
    assert result.raw_responses == ()
