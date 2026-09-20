from __future__ import annotations

import gzip
from datetime import UTC, datetime

import httpx
import pytest

import medevidence.infrastructure.deepseek_responses_transport as transport_module
from medevidence.infrastructure.deepseek_responses_transport import (
    DEEPSEEK_RESPONSES_ENDPOINT,
    DeepSeekOneOperationObservation,
    DeepSeekRawRequest,
    DeepSeekRawTransport,
    DeepSeekTransportError,
    DeepSeekTransportErrorCode,
    DeepSeekTransportProfile,
    credential_representations,
)
from medevidence.infrastructure.deepseek_semantic_evaluator import (
    build_deepseek_v2_framing_observation,
)
from medevidence.tools.provider_attempt_framing import FramingStatus, classify_framing


class _StringSubclass(str):
    pass


class _FakeMonotonic:
    def __init__(self, now: float = 100.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def _observation_kwargs() -> dict[str, object]:
    now = datetime.now(UTC)
    return {
        "http_status": 200,
        "approved_headers": {},
        "raw_body": b"{}",
        "body_complete": True,
        "observed_body_bytes_lower_bound": 2,
        "credential_echo": False,
        "transport_error": None,
        "started_at_utc": now,
        "completed_at_utc": now,
        "response_http_version": "HTTP/2",
        "response_header_items": (("content-type", "application/json"),),
        "response_header_field_count": 1,
    }


def _profile(
    *, response_bytes: int = 128, deadline_seconds: float = 45
) -> DeepSeekTransportProfile:
    return DeepSeekTransportProfile(
        max_request_bytes=128,
        max_response_bytes=response_bytes,
        max_attempts=3,
        total_deadline_seconds=deadline_seconds,
        connect_timeout_seconds=5,
        read_timeout_seconds=30,
        write_timeout_seconds=10,
        pool_timeout_seconds=5,
        backoff_base_seconds=0.25,
        retry_after_cap_seconds=2,
    )


def _request(*, response_bytes: int = 128, deadline_seconds: float = 45) -> DeepSeekRawRequest:
    return DeepSeekRawRequest(
        api_key="bounded-test-key",
        endpoint=DEEPSEEK_RESPONSES_ENDPOINT,
        request_bytes=b'{"input":"bounded"}',
        profile=_profile(
            response_bytes=response_bytes,
            deadline_seconds=deadline_seconds,
        ),
    )


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("observed_body_bytes_lower_bound", True),
        ("response_header_field_count", True),
        ("response_http_version", _StringSubclass("HTTP/2")),
        (
            "response_header_items",
            (("content-type", "application/json"), ("content-length", True)),
        ),
    ),
    ids=(
        "lower-bound-bool",
        "header-count-bool",
        "http-version-string-subclass",
        "content-length-bool",
    ),
)
def test_observation_constructor_rejects_nonexact_primitives(field: str, value: object) -> None:
    values = _observation_kwargs()
    values[field] = value
    with pytest.raises(TypeError, match="primitives must be exact"):
        DeepSeekOneOperationObservation(**values)  # type: ignore[arg-type]


def test_exact_endpoint_host_headers_and_bytes() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        assert str(request.url) == DEEPSEEK_RESPONSES_ENDPOINT
        assert request.headers["host"] == "api.deepseek.com"
        assert request.headers["authorization"] == "Bearer bounded-test-key"
        assert request.content == b'{"input":"bounded"}'
        return httpx.Response(
            200,
            headers={"Content-Type": "application/json"},
            content=b'{"ok":true}',
        )

    reply = DeepSeekRawTransport(transport=httpx.MockTransport(handler)).execute_one(_request())
    assert calls == 1 and reply.raw_body == b'{"ok":true}'


def test_shared_transport_survives_multiple_sequential_requests() -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            headers={"Content-Type": "application/json"},
            content=b"{}",
        )

    transport = DeepSeekRawTransport(transport=httpx.MockTransport(handler))
    assert transport.execute_one(_request()).raw_body == b"{}"
    assert transport.execute_one(_request()).raw_body == b"{}"
    assert calls == 2


@pytest.mark.parametrize(
    "endpoint",
    (
        "http://api.deepseek.com/responses",
        "https://api.deepseek.com/v1/responses",
        "https://api.openai.com/v1/responses",
        "https://api.deepseek.com/responses?x=1",
    ),
)
def test_endpoint_substitution_rejects_before_effect(endpoint: str) -> None:
    with pytest.raises(DeepSeekTransportError, match="request_integrity"):
        DeepSeekRawRequest(
            api_key="key",
            endpoint=endpoint,
            request_bytes=b"{}",
            profile=_profile(),
        )


def test_exact_max_response_passes_and_max_plus_one_fails() -> None:
    maximum = 32
    valid = b'"' + b"x" * (maximum - 2) + b'"'
    reply = DeepSeekRawTransport(
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                200,
                headers={"Content-Type": "application/json"},
                content=valid,
            )
        )
    ).execute_one(_request(response_bytes=maximum))
    assert reply.raw_body is not None and len(reply.raw_body) == maximum
    assert reply.observed_body_bytes_lower_bound == maximum

    invalid = b'"' + b"x" * (maximum - 1) + b'"'
    captured = DeepSeekRawTransport(
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                200,
                headers={"Content-Type": "application/json"},
                content=invalid,
            )
        )
    ).execute_one(_request(response_bytes=maximum))
    assert captured.transport_error is DeepSeekTransportErrorCode.RESPONSE_TOO_LARGE
    assert captured.raw_body is None
    assert captured.observed_body_bytes_lower_bound == maximum + 1


def test_retry_is_bounded_and_redirect_is_never_followed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("time.sleep", lambda _value: None)
    calls = 0

    def retry(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            503,
            headers={"Content-Type": "application/json", "Retry-After": "0"},
            content=b"{}",
        )

    captured = DeepSeekRawTransport(transport=httpx.MockTransport(retry)).execute_one(_request())
    assert calls == 1
    assert captured.http_status == 503

    redirected = DeepSeekRawTransport(
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                307,
                headers={
                    "Content-Type": "application/json",
                    "Location": "https://evil.example/steal",
                },
                content=b"{}",
            )
        )
    ).execute_one(_request())
    assert redirected.http_status == 307


def test_provider_error_body_and_credential_never_escape() -> None:
    secret = "credential-must-not-escape"
    request = DeepSeekRawRequest(
        api_key=secret,
        endpoint=DEEPSEEK_RESPONSES_ENDPOINT,
        request_bytes=b"{}",
        profile=_profile(),
    )
    captured = DeepSeekRawTransport(
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                400,
                headers={"Content-Type": "application/json"},
                content=(f'{{"error":"{secret}"}}').encode(),
            )
        )
    ).execute_one(request)
    assert captured.credential_echo is True
    assert captured.raw_body is None
    assert secret not in repr(request)


def test_partial_body_transport_failure_is_retryable_without_raw_body() -> None:
    calls = 0

    class BrokenStream(httpx.SyncByteStream):
        def __iter__(self):  # type: ignore[no-untyped-def]
            yield b"{"
            raise httpx.ReadError("simulated post-body failure")

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            headers={"Content-Type": "application/json"},
            stream=BrokenStream(),
        )

    captured = DeepSeekRawTransport(transport=httpx.MockTransport(handler)).execute_one(_request())
    assert captured.transport_error is DeepSeekTransportErrorCode.PROVIDER_UNAVAILABLE
    assert captured.http_status == 200
    assert captured.body_complete is False
    assert captured.observed_body_bytes_lower_bound == 1
    assert captured.raw_body is None
    assert captured.credential_echo is False
    assert calls == 1


@pytest.mark.parametrize(
    ("error_type", "first_chunk"),
    (
        (httpx.ReadTimeout, b""),
        (httpx.ReadError, b""),
        (httpx.ReadTimeout, b"partial"),
        (httpx.ReadError, b"partial"),
    ),
)
def test_stream_transport_error_before_deadline_is_unavailable_and_incomplete(
    error_type: type[httpx.TransportError], first_chunk: bytes
) -> None:
    class BrokenStream(httpx.SyncByteStream):
        def __iter__(self):  # type: ignore[no-untyped-def]
            if first_chunk:
                yield first_chunk
            raise error_type("bounded stream failure")

    observation = DeepSeekRawTransport(
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                200,
                headers={"Content-Type": "application/json"},
                stream=BrokenStream(),
                extensions={"http_version": b"HTTP/2"},
            )
        )
    ).execute_one(_request())

    assert observation.http_status == 200
    assert observation.transport_error is DeepSeekTransportErrorCode.PROVIDER_UNAVAILABLE
    assert observation.body_complete is False
    assert observation.observed_body_bytes_lower_bound == len(first_chunk)
    assert observation.raw_body is None
    assert observation.credential_echo is False
    framing = build_deepseek_v2_framing_observation(
        observation,
        disposition="transport_unavailable",
        raw_body_hash=None,
        raw_relative_path=None,
    )
    decision = classify_framing(framing)
    assert decision.status is FramingStatus.REJECTED
    assert decision.rejection_code == "response_body_incomplete"


@pytest.mark.parametrize(
    "representation",
    credential_representations("bounded-test-key"),
)
def test_every_frozen_credential_representation_drops_body(
    representation: bytes,
) -> None:
    observation = DeepSeekRawTransport(
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                200,
                headers={"Content-Type": "application/json"},
                content=b"prefix-" + representation + b"-suffix",
            )
        )
    ).execute_one(_request())
    assert observation.credential_echo is True
    assert observation.raw_body is None


def test_credential_detection_crosses_stream_chunk_boundary() -> None:
    marker = b"bounded-test-key"

    class SplitStream(httpx.SyncByteStream):
        def __iter__(self):  # type: ignore[no-untyped-def]
            yield b"prefix-" + marker[:5]
            yield marker[5:] + b"-suffix"

    observation = DeepSeekRawTransport(
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                200,
                headers={"Content-Type": "application/json"},
                stream=SplitStream(),
            )
        )
    ).execute_one(_request())
    assert observation.credential_echo is True
    assert observation.raw_body is None


def test_small_chunks_complete_with_exact_observed_length() -> None:
    class SmallStream(httpx.SyncByteStream):
        def __iter__(self):  # type: ignore[no-untyped-def]
            yield b"{"
            yield b"}"

    observation = DeepSeekRawTransport(
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                200,
                headers={"Content-Type": "application/json"},
                stream=SmallStream(),
            )
        )
    ).execute_one(_request())

    assert observation.raw_body == b"{}"
    assert observation.body_complete is True
    assert observation.observed_body_bytes_lower_bound == 2


def test_small_chunks_before_timeout_retain_observed_lower_bound() -> None:
    class BrokenStream(httpx.SyncByteStream):
        def __iter__(self):  # type: ignore[no-untyped-def]
            yield b"{"
            yield b"partial"
            raise httpx.ReadTimeout("bounded stream failure")

    observation = DeepSeekRawTransport(
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                200,
                headers={"Content-Type": "application/json"},
                stream=BrokenStream(),
            )
        )
    ).execute_one(_request())

    assert observation.transport_error is DeepSeekTransportErrorCode.PROVIDER_UNAVAILABLE
    assert observation.observed_body_bytes_lower_bound == len(b"{partial")
    assert observation.body_complete is False
    assert observation.raw_body is None


def test_small_chunks_crossing_deadline_stop_subsequent_consumption() -> None:
    clock = _FakeMonotonic()
    consumed: list[bytes] = []

    class DelayedStream(httpx.SyncByteStream):
        def __iter__(self):  # type: ignore[no-untyped-def]
            consumed.append(b"{")
            yield b"{"
            clock.now = 110.0
            consumed.append(b"x")
            yield b"x"
            consumed.append(b"unread")
            yield b"unread"

    observation = DeepSeekRawTransport(
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                200,
                headers={"Content-Type": "application/json"},
                stream=DelayedStream(),
            )
        )
    ).execute_one(
        _request(deadline_seconds=10),
        monotonic_clock=clock,
    )

    assert observation.transport_error is DeepSeekTransportErrorCode.DEADLINE_EXCEEDED
    assert observation.observed_body_bytes_lower_bound == 1
    assert observation.body_complete is False
    assert observation.raw_body is None
    assert consumed == [b"{", b"x"]


def test_small_cross_chunk_credential_echo_precedes_incomplete_stream_error() -> None:
    marker = b"bounded-test-key"

    class BrokenStream(httpx.SyncByteStream):
        def __iter__(self):  # type: ignore[no-untyped-def]
            yield b"prefix-" + marker[:5]
            yield marker[5:]
            raise httpx.ReadError("bounded stream failure")

    observation = DeepSeekRawTransport(
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                200,
                headers={"Content-Type": "application/json"},
                stream=BrokenStream(),
            )
        )
    ).execute_one(_request())

    assert observation.credential_echo is True
    assert observation.raw_body is None
    assert observation.body_complete is False
    assert observation.observed_body_bytes_lower_bound == len(b"prefix-") + len(marker)


def test_reserved_percent_credential_crosses_chunk_boundary() -> None:
    key = "a/b?c=d&e"
    marker = b"a%2Fb%3Fc%3Dd%26e"

    class SplitPercentStream(httpx.SyncByteStream):
        def __iter__(self):  # type: ignore[no-untyped-def]
            yield b"prefix-" + marker[:7]
            yield marker[7:] + b"-suffix"

    request = DeepSeekRawRequest(
        api_key=key,
        endpoint=DEEPSEEK_RESPONSES_ENDPOINT,
        request_bytes=b"{}",
        profile=_profile(),
    )
    observation = DeepSeekRawTransport(
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                200,
                headers={"Content-Type": "application/json"},
                stream=SplitPercentStream(),
            )
        )
    ).execute_one(request)
    assert observation.credential_echo is True
    assert observation.raw_body is None


def test_allowed_header_credential_echo_drops_header_values_and_body() -> None:
    observation = DeepSeekRawTransport(
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                200,
                headers={
                    "Content-Type": "application/json",
                    "X-Request-ID": "bounded-test-key",
                },
                content=b"{}",
            )
        )
    ).execute_one(_request())
    assert observation.credential_echo is True
    assert observation.approved_headers == {}
    assert observation.raw_body is None


def test_retry_after_credential_echo_is_detected_before_use() -> None:
    request = DeepSeekRawRequest(
        api_key="99",
        endpoint=DEEPSEEK_RESPONSES_ENDPOINT,
        request_bytes=b"{}",
        profile=_profile(),
    )
    observation = DeepSeekRawTransport(
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                503,
                headers={
                    "Content-Type": "application/json",
                    "Retry-After": "99",
                },
                content=b"{}",
            )
        )
    ).execute_one(request)
    assert observation.credential_echo is True
    assert observation.retry_after is None
    assert observation.raw_body is None


def test_finite_representation_set_includes_json_and_percent_forms() -> None:
    values = credential_representations('a/b?c=d&e"\\')
    assert b'a/b?c=d&e\\"\\\\' in values
    assert b"a%2Fb%3Fc%3Dd%26e%22%5C" in values
    assert b"a%2fb%3fc%3dd%26e%22%5c" in values
    assert b"%61%2F%62%3F%63%3D%64%26%65%22%5C" in values
    assert b"%61%2f%62%3f%63%3d%64%26%65%22%5c" in values


def test_streaming_deadline_returns_bounded_terminal_observation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def deadline(*_args: object) -> None:
        raise DeepSeekTransportError(DeepSeekTransportErrorCode.DEADLINE_EXCEEDED)

    monkeypatch.setattr(transport_module, "_deadline", deadline)
    observation = DeepSeekRawTransport(
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                200,
                headers={"Content-Type": "application/json"},
                stream=httpx.ByteStream(b"{}"),
            )
        )
    ).execute_one(_request())
    assert observation.transport_error is DeepSeekTransportErrorCode.DEADLINE_EXCEEDED
    assert observation.raw_body is None


def test_attempt_timeout_uses_only_remaining_absolute_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = _FakeMonotonic()
    monkeypatch.setattr(transport_module.time, "monotonic", clock)
    deadline_at = clock.now + 10.0

    initial = transport_module._attempt_timeout(deadline_at, _profile(deadline_seconds=10))
    assert (initial.connect, initial.read, initial.write, initial.pool) == (5.0, 10.0, 10.0, 5.0)

    clock.now = deadline_at - 1.0
    final = transport_module._attempt_timeout(deadline_at, _profile(deadline_seconds=10))
    assert (final.connect, final.read, final.write, final.pool) == (1.0, 1.0, 1.0, 1.0)


def test_supplied_coordinator_deadline_and_clock_are_authoritative_end_to_end(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = _FakeMonotonic()
    timeout_facts: list[dict[str, float]] = []

    def forbidden_wall_clock() -> float:
        raise AssertionError("explicit coordinator clock must be used")

    def handler(request: httpx.Request) -> httpx.Response:
        timeout_facts.append(request.extensions["timeout"])
        return httpx.Response(
            200,
            headers={"Content-Type": "application/json"},
            content=b"{}",
        )

    monkeypatch.setattr(transport_module.time, "monotonic", forbidden_wall_clock)
    observation = DeepSeekRawTransport(transport=httpx.MockTransport(handler)).execute_one(
        _request(deadline_seconds=45),
        absolute_deadline_monotonic=105.0,
        monotonic_clock=clock,
    )

    assert observation.raw_body == b"{}"
    assert len(timeout_facts) == 1
    assert timeout_facts[0] == {"connect": 5.0, "read": 5.0, "write": 5.0, "pool": 5.0}


def test_expired_supplied_deadline_never_invokes_http_transport() -> None:
    clock = _FakeMonotonic(now=145.0)
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise AssertionError("expired coordinator deadline must prevent HTTP")

    observation = DeepSeekRawTransport(transport=httpx.MockTransport(handler)).execute_one(
        _request(deadline_seconds=45),
        absolute_deadline_monotonic=145.0,
        monotonic_clock=clock,
    )

    assert calls == 0
    assert observation.http_status is None
    assert observation.transport_error is DeepSeekTransportErrorCode.DEADLINE_EXCEEDED


def test_pre_response_timeout_after_absolute_deadline_is_deadline_exceeded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = _FakeMonotonic()
    monkeypatch.setattr(transport_module.time, "monotonic", clock)

    def handler(request: httpx.Request) -> httpx.Response:
        clock.now = 110.001
        raise httpx.ReadTimeout("after absolute deadline", request=request)

    observation = DeepSeekRawTransport(transport=httpx.MockTransport(handler)).execute_one(
        _request(deadline_seconds=10)
    )

    assert observation.transport_error is DeepSeekTransportErrorCode.DEADLINE_EXCEEDED
    assert observation.http_status is None
    assert observation.raw_body is None


def test_pre_response_timeout_just_before_deadline_retains_transport_class(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = _FakeMonotonic()
    monkeypatch.setattr(transport_module.time, "monotonic", clock)

    def handler(request: httpx.Request) -> httpx.Response:
        clock.now = 109.999
        raise httpx.ReadTimeout("before absolute deadline", request=request)

    observation = DeepSeekRawTransport(transport=httpx.MockTransport(handler)).execute_one(
        _request(deadline_seconds=10)
    )

    assert observation.transport_error is DeepSeekTransportErrorCode.PROVIDER_UNAVAILABLE
    assert observation.raw_body is None


@pytest.mark.parametrize(
    ("second_read_time", "expected"),
    (
        (109.999, DeepSeekTransportErrorCode.PROVIDER_UNAVAILABLE),
        (110.0, DeepSeekTransportErrorCode.DEADLINE_EXCEEDED),
        (110.001, DeepSeekTransportErrorCode.DEADLINE_EXCEEDED),
    ),
    ids=("before", "exact", "after"),
)
def test_mid_stream_timeout_respects_absolute_deadline_boundary(
    monkeypatch: pytest.MonkeyPatch,
    second_read_time: float,
    expected: DeepSeekTransportErrorCode,
) -> None:
    clock = _FakeMonotonic()
    monkeypatch.setattr(transport_module.time, "monotonic", clock)
    first_chunk = b"{" * transport_module._CHUNK_BYTES

    class TwoReadStream(httpx.SyncByteStream):
        def __iter__(self):  # type: ignore[no-untyped-def]
            yield first_chunk
            clock.now = second_read_time
            raise httpx.ReadTimeout("second read crossed deadline")

    observation = DeepSeekRawTransport(
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                200,
                headers={"Content-Type": "application/json"},
                stream=TwoReadStream(),
            )
        )
    ).execute_one(
        _request(
            response_bytes=transport_module._CHUNK_BYTES * 2,
            deadline_seconds=10,
        )
    )

    assert observation.transport_error is expected
    assert observation.observed_body_bytes_lower_bound == len(first_chunk)
    assert observation.body_complete is False
    assert observation.raw_body is None


def test_v2_capture_preserves_approved_header_multiplicity_and_http_version() -> None:
    observation = DeepSeekRawTransport(
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                200,
                headers=[
                    ("Content-Type", "application/json"),
                    ("X-Request-ID", "first"),
                    ("X-Request-ID", "second"),
                    ("Server", "not-part-of-approved-surface"),
                ],
                content=b"{}",
                extensions={"http_version": b"HTTP/2"},
            )
        )
    ).execute_one(_request())

    assert observation.response_http_version == "HTTP/2"
    assert observation.response_header_field_count == 5
    assert observation.response_header_items == (
        ("content-type", "application/json"),
        ("x-request-id", "first"),
        ("x-request-id", "second"),
        ("content-length", "2"),
    )
    assert "server" not in observation.approved_headers


def test_streaming_gzip_credential_content_is_never_returned_for_persistence() -> None:
    compressed = gzip.compress(b'{"echo":"bounded-test-key"}')

    class SplitCompressedStream(httpx.SyncByteStream):
        def __iter__(self):  # type: ignore[no-untyped-def]
            midpoint = len(compressed) // 2
            yield compressed[:midpoint]
            yield compressed[midpoint:]

    observation = DeepSeekRawTransport(
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                200,
                headers={
                    "Content-Encoding": "gzip",
                    "Content-Type": "application/json",
                },
                stream=SplitCompressedStream(),
                extensions={"http_version": b"HTTP/2"},
            )
        )
    ).execute_one(_request())

    assert observation.raw_body is None
    assert observation.body_complete is False
    assert observation.credential_echo is False
    assert observation.transport_error is None
    assert observation.observed_body_bytes_lower_bound == len(compressed)
    assert ("content-encoding", "gzip") in observation.response_header_items
    assert not hasattr(observation, "response_hash")


@pytest.mark.parametrize("content_encoding", ("br", "x-unknown"))
def test_unknown_compression_never_returns_raw_body(content_encoding: str) -> None:
    payload = b"opaque-provider-wire-bytes"
    observation = DeepSeekRawTransport(
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                200,
                headers={
                    "Content-Encoding": content_encoding,
                    "Content-Type": "application/json",
                },
                stream=httpx.ByteStream(payload),
                extensions={"http_version": b"HTTP/2"},
            )
        )
    ).execute_one(_request())

    assert observation.raw_body is None
    assert observation.body_complete is False
    assert observation.observed_body_bytes_lower_bound == len(payload)
    assert ("content-encoding", content_encoding) in observation.response_header_items


def test_invalid_normalized_header_surface_never_returns_raw_body() -> None:
    payload = b"{}"
    invalid_value = "x" * 9_000
    observation = DeepSeekRawTransport(
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                200,
                headers={
                    "Content-Type": "application/json",
                    "X-Request-ID": invalid_value,
                },
                stream=httpx.ByteStream(payload),
                extensions={"http_version": b"HTTP/2"},
            )
        )
    ).execute_one(_request())

    assert observation.raw_body is None
    assert observation.body_complete is False
    assert observation.observed_body_bytes_lower_bound == len(payload)


def test_credential_echo_clears_v2_header_and_version_surface() -> None:
    observation = DeepSeekRawTransport(
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                200,
                headers={"Server": "bounded-test-key"},
                content=b"{}",
                extensions={"http_version": b"HTTP/2"},
            )
        )
    ).execute_one(_request())

    assert observation.credential_echo is True
    assert observation.response_http_version is None
    assert observation.response_header_items == ()
    assert observation.response_header_field_count == 0
    assert observation.raw_body is None
