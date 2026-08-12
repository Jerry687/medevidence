from __future__ import annotations

import gzip
import io
import zipfile
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

import httpx
import pytest

from medevidence.connectors.dailymed import (
    DailyMedConnector,
    DailyMedFailureKind,
    RawDailyMedResponse,
)

FIXTURES = Path(__file__).parents[2] / "fixtures" / "dailymed"
SETID = "11111111-1111-1111-1111-111111111111"
VERSION = "3"


class _RawStream(httpx.SyncByteStream):
    def __init__(self, chunks: tuple[bytes, ...]) -> None:
        self._chunks = chunks

    def __iter__(self):  # type: ignore[no-untyped-def]
        yield from self._chunks


class _FailingRawStream(httpx.SyncByteStream):
    def __iter__(self):  # type: ignore[no-untyped-def]
        yield b"abc"
        raise httpx.ReadError("synthetic partial stream")


def _fixed_utc() -> datetime:
    return datetime(2026, 1, 1, tzinfo=UTC)


def _historical_zip() -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("label.xml", (FIXTURES / "spl-valid.xml").read_bytes())
    return output.getvalue()


def test_connector_uses_only_injected_transport_and_parses_discovery() -> None:
    observed: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        observed.append(request)
        return httpx.Response(200, content=(FIXTURES / "candidates-exact.json").read_bytes())

    with DailyMedConnector(httpx.MockTransport(handler), utc_now=_fixed_utc) as connector:
        result = connector.discover(setid=SETID, pagesize=100)
    assert result.failure is None
    assert result.value is not None and len(result.value[0].candidates) == 1
    assert len(observed) == 1
    assert observed[0].url.host == "dailymed.nlm.nih.gov"
    assert observed[0].headers["accept-encoding"] == "identity"


def test_connector_retries_429_once_and_honors_bounded_retry_after() -> None:
    attempts = 0
    sleeps: list[float] = []

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(429, headers={"Retry-After": "99"})
        return httpx.Response(200, content=(FIXTURES / "setid-history.json").read_bytes())

    with DailyMedConnector(
        httpx.MockTransport(handler), utc_now=_fixed_utc, sleep=sleeps.append, jitter=lambda: 0
    ) as connector:
        result = connector.history(SETID)
    assert result.failure is None
    assert result.request_count == 2
    assert sleeps == [10.0]
    assert result.retry_events[0].used_retry_after is True


def test_connector_rejects_cross_origin_redirect_before_following() -> None:
    requests = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        return httpx.Response(302, headers={"Location": "https://example.invalid/label.xml"})

    with DailyMedConnector(httpx.MockTransport(handler), utc_now=_fixed_utc) as connector:
        result = connector.discover(setid=SETID)
    assert result.failure is not None
    assert result.failure.kind is DailyMedFailureKind.REDIRECT_REJECTED
    assert requests == 1


def test_connector_fetches_current_and_historical_exact_identity_with_immutable_cache() -> None:
    requests = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        body = (
            _historical_zip()
            if request.url.path.endswith("getFile.cfm")
            else (FIXTURES / "spl-valid.xml").read_bytes()
        )
        return httpx.Response(200, content=body)

    with DailyMedConnector(httpx.MockTransport(handler), utc_now=_fixed_utc) as connector:
        current = connector.fetch_spl(SETID, VERSION, historical=False)
        replay = connector.fetch_spl(SETID, VERSION, historical=False)
    assert current.failure is None and replay.failure is None
    assert replay.from_cache is True
    assert requests == 1

    with DailyMedConnector(httpx.MockTransport(handler), utc_now=_fixed_utc) as connector:
        historical = connector.fetch_spl(SETID, VERSION, historical=True)
    assert historical.failure is None
    assert historical.value is not None and historical.value.source_member_name == "label.xml"


def test_connector_reparses_owned_cache_and_rejects_post_construction_corruption() -> None:
    requests = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        return httpx.Response(200, content=(FIXTURES / "spl-valid.xml").read_bytes())

    with DailyMedConnector(httpx.MockTransport(handler), utc_now=_fixed_utc) as connector:
        first = connector.fetch_spl(SETID, VERSION, historical=False)
        assert first.failure is None
        connector._cache[(SETID, VERSION, False)] = (
            (FIXTURES / "spl-valid.xml")
            .read_bytes()
            .replace(SETID.encode(), b"22222222-2222-2222-2222-222222222222")
        )
        corrupted = connector.fetch_spl(SETID, VERSION, historical=False)
    assert corrupted.failure is not None
    assert corrupted.failure.kind is DailyMedFailureKind.CACHE_CONFLICT
    assert requests == 1


def test_connector_marks_discovery_and_history_truncated_at_page_ceiling() -> None:
    def response(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params["page"])
        if request.url.path.endswith("history.json"):
            row = {"setid": SETID, "spl_version": str(page), "marketing_state": "active"}
        else:
            row = {"setid": SETID, "spl_version": str(page), "ingredients": ["synthetic"]}
        body = {"data": [row], "metadata": {"page": page, "pagesize": 1, "total": 100}}
        return httpx.Response(200, json=body)

    with DailyMedConnector(httpx.MockTransport(response), utc_now=_fixed_utc) as connector:
        discovery = connector.discover(setid=SETID, pagesize=1)
        history = connector.history(SETID, pagesize=1)
    assert discovery.failure is None and discovery.truncated is True
    assert history.failure is None and history.truncated is True
    assert discovery.pages_completed == history.pages_completed == 5


def test_connector_marks_discovery_and_history_truncated_at_record_ceiling() -> None:
    def response(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("history.json"):
            rows = [
                {"setid": SETID, "spl_version": str(index + 1), "marketing_state": "active"}
                for index in range(100)
            ]
        else:
            rows = [
                {
                    "setid": f"{index + 1:08x}-1111-1111-1111-111111111111",
                    "spl_version": "3",
                    "ingredients": ["synthetic"],
                }
                for index in range(100)
            ]
        return httpx.Response(
            200,
            json={"data": rows, "metadata": {"page": 1, "pagesize": 100, "total": 101}},
        )

    with DailyMedConnector(httpx.MockTransport(response), utc_now=_fixed_utc) as connector:
        discovery = connector.discover(setid=SETID, pagesize=100)
        history = connector.history(SETID, pagesize=100)
    assert discovery.failure is None and discovery.truncated is True
    assert history.failure is None and history.truncated is True
    assert discovery.pages_completed == history.pages_completed == 1


def test_connector_has_no_real_transport_fallback_on_mock_failure() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("synthetic offline failure")

    with DailyMedConnector(
        httpx.MockTransport(handler), utc_now=_fixed_utc, sleep=lambda _: None, jitter=lambda: 0
    ) as connector:
        result = connector.discover(setid=SETID)
    assert result.failure is not None
    assert result.failure.kind is DailyMedFailureKind.RETRY_EXHAUSTED
    assert result.failure.cause_kind is DailyMedFailureKind.TRANSPORT
    assert result.request_count == 2


@pytest.mark.parametrize(
    "content_encoding",
    [
        "gzip",
        "deflate",
        "br",
        "gzip, identity",
        "identity, gzip",
        "identity,,",
        "",
        " ",
        ",",
        "Identity x",
    ],
)
def test_connector_rejects_nonidentity_or_malformed_content_encoding(
    content_encoding: str,
) -> None:
    body = gzip.compress((FIXTURES / "spl-valid.xml").read_bytes())

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"Content-Encoding": content_encoding},
            stream=_RawStream((body,)),
        )

    with DailyMedConnector(httpx.MockTransport(handler), utc_now=_fixed_utc) as connector:
        result = connector.fetch_spl(SETID, VERSION, historical=False)
    assert result.failure is not None
    assert result.failure.kind is DailyMedFailureKind.INTEGRITY_FAILURE
    assert result.raw_responses == ()


def test_connector_canonicalizes_identity_content_encoding_and_retains_exact_raw_bytes() -> None:
    body = (FIXTURES / "candidates-exact.json").read_bytes()

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"Content-Encoding": " \tIDENTITY\t "},
            stream=_RawStream((body[:17], body[17:])),
        )

    with DailyMedConnector(httpx.MockTransport(handler), utc_now=_fixed_utc) as connector:
        result = connector.discover(setid=SETID, pagesize=100)
    assert result.failure is None
    assert result.raw_responses[0].body == body
    assert sha256(result.raw_responses[0].body).digest() == sha256(body).digest()
    assert result.raw_responses[0].headers == (("content-encoding", "identity"),)


def test_connector_rejects_multiple_content_encoding_header_fields() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers=[("Content-Encoding", "identity"), ("Content-Encoding", "identity")],
            stream=_RawStream(((FIXTURES / "spl-valid.xml").read_bytes(),)),
        )

    with DailyMedConnector(httpx.MockTransport(handler), utc_now=_fixed_utc) as connector:
        result = connector.fetch_spl(SETID, VERSION, historical=False)
    assert result.failure is not None
    assert result.failure.kind is DailyMedFailureKind.INTEGRITY_FAILURE


def test_historical_zip_receives_exact_raw_transport_bytes_not_decoded_ambiguity() -> None:
    exact_zip = _historical_zip()
    encoded_zip = gzip.compress(exact_zip)

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"Content-Encoding": "gzip"},
            stream=_RawStream((encoded_zip,)),
        )

    with DailyMedConnector(httpx.MockTransport(handler), utc_now=_fixed_utc) as connector:
        result = connector.fetch_spl(SETID, VERSION, historical=True)
    assert result.failure is not None
    assert result.failure.kind is DailyMedFailureKind.INTEGRITY_FAILURE
    assert result.raw_responses == ()


@pytest.mark.parametrize(("size", "complete"), [(5_242_880, True), (5_242_881, False)])
def test_connector_bounds_exact_raw_transport_bytes(size: int, complete: bool) -> None:
    body = b"x" * size

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=_RawStream((body[:3_000_000], body[3_000_000:])))

    with DailyMedConnector(httpx.MockTransport(handler), utc_now=_fixed_utc) as connector:
        result = connector.discover(setid=SETID)
    if complete:
        assert result.failure is not None
        assert result.failure.kind is DailyMedFailureKind.MALFORMED_RESPONSE
        assert result.raw_responses[0].body == body
        assert result.raw_responses[0].body_complete is True
    else:
        assert result.failure is not None
        assert result.failure.kind is DailyMedFailureKind.PAYLOAD_LIMIT
        assert result.raw_responses[0].body == body[:5_242_880]
        assert result.raw_responses[0].body_complete is False
        assert result.raw_responses[0].termination_reason == "payload_limit"


@pytest.mark.parametrize(
    "content_length",
    ["", " ", "+1", "-1", "01", "1.0", "1,2", "5242881", "9" * 1000],
)
def test_connector_rejects_noncanonical_or_overbound_content_length(
    content_length: str,
) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"Content-Length": content_length},
            stream=_RawStream((b"x",)),
        )

    with DailyMedConnector(httpx.MockTransport(handler), utc_now=_fixed_utc) as connector:
        result = connector.discover(setid=SETID)
    assert result.failure is not None
    assert result.failure.kind is DailyMedFailureKind.INTEGRITY_FAILURE
    assert result.raw_responses == ()


def test_connector_rejects_duplicate_content_length_and_cl_te_framing() -> None:
    header_sets = (
        [("Content-Length", "1"), ("Content-Length", "1")],
        [("Content-Length", "1"), ("Transfer-Encoding", "chunked")],
    )
    for headers in header_sets:
        with DailyMedConnector(
            httpx.MockTransport(
                lambda _request, headers=headers: httpx.Response(
                    200, headers=headers, stream=_RawStream((b"x",))
                )
            ),
            utc_now=_fixed_utc,
        ) as connector:
            result = connector.discover(setid=SETID)
        assert result.failure is not None
        assert result.failure.kind is DailyMedFailureKind.INTEGRITY_FAILURE
        assert result.raw_responses == ()


def test_retained_response_rejects_non_ascii_content_length_instance_drift() -> None:
    with pytest.raises(ValueError, match="ASCII"):
        RawDailyMedResponse(
            request_url="https://dailymed.nlm.nih.gov/request",
            final_url="https://dailymed.nlm.nih.gov/request",
            status_code=200,
            body=b"x",
            observed_at_utc=_fixed_utc(),
            headers=(("content-length", "\u0661"),),
        )


@pytest.mark.parametrize("consumed", [False, True])
def test_complete_raw_body_must_equal_content_length(consumed: bool) -> None:
    body = (FIXTURES / "candidates-exact.json").read_bytes()

    def handler(_: httpx.Request) -> httpx.Response:
        if consumed:
            return httpx.Response(200, headers={"Content-Length": str(len(body) + 1)}, content=body)
        return httpx.Response(
            200,
            headers={"Content-Length": str(len(body) + 1)},
            stream=_RawStream((body,)),
        )

    with DailyMedConnector(httpx.MockTransport(handler), utc_now=_fixed_utc) as connector:
        result = connector.discover(setid=SETID, pagesize=100)
    assert result.failure is not None
    assert result.failure.kind is DailyMedFailureKind.INTEGRITY_FAILURE
    assert result.raw_responses == ()


def test_exact_bound_content_length_and_absent_content_length_are_valid() -> None:
    maximum = b"x" * 5_242_880

    def maximum_handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"Content-Length": "5242880"},
            stream=_RawStream((maximum,)),
        )

    with DailyMedConnector(httpx.MockTransport(maximum_handler), utc_now=_fixed_utc) as connector:
        maximum_result = connector.discover(setid=SETID)
    assert maximum_result.failure is not None
    assert maximum_result.failure.kind is DailyMedFailureKind.MALFORMED_RESPONSE
    assert maximum_result.raw_responses[0].body == maximum
    assert ("content-length", "5242880") in maximum_result.raw_responses[0].headers

    body = (FIXTURES / "candidates-exact.json").read_bytes()
    with DailyMedConnector(
        httpx.MockTransport(lambda _: httpx.Response(200, stream=_RawStream((body,)))),
        utc_now=_fixed_utc,
    ) as connector:
        absent_result = connector.discover(setid=SETID, pagesize=100)
    assert absent_result.failure is None
    assert dict(absent_result.raw_responses[0].headers).get("content-length") is None


def test_partial_stream_preserves_truthful_termination_despite_declared_length() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"Content-Length": "100"},
            stream=_FailingRawStream(),
        )

    with DailyMedConnector(httpx.MockTransport(handler), utc_now=_fixed_utc) as connector:
        result = connector.discover(setid=SETID)
    assert result.failure is not None
    assert result.failure.kind is DailyMedFailureKind.RETRY_EXHAUSTED
    assert result.failure.cause_kind is DailyMedFailureKind.TRANSPORT
    assert len(result.raw_responses) == 2
    assert all(raw.body == b"abc" for raw in result.raw_responses)
    assert all(raw.body_complete is False for raw in result.raw_responses)
    assert all(raw.termination_reason == "stream_error" for raw in result.raw_responses)


def test_redirect_and_retry_responses_enforce_content_length_preflight() -> None:
    for status, headers in (
        (
            302,
            {
                "Location": "https://dailymed.nlm.nih.gov/dailymed/services/v2/spls.json",
                "Content-Length": "01",
            },
        ),
        (429, {"Content-Length": "5242881"}),
    ):
        with DailyMedConnector(
            httpx.MockTransport(
                lambda _request, status=status, headers=headers: httpx.Response(
                    status, headers=headers, stream=_RawStream((b"",))
                )
            ),
            utc_now=_fixed_utc,
        ) as connector:
            result = connector.discover(setid=SETID)
        assert result.failure is not None
        assert result.failure.kind is DailyMedFailureKind.INTEGRITY_FAILURE
        assert result.request_count == 1


def test_redirect_body_is_raw_bounded_and_length_verified_before_following() -> None:
    requests = 0
    final_body = (FIXTURES / "candidates-exact.json").read_bytes()

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        if requests == 1:
            return httpx.Response(
                302,
                headers={"Location": str(request.url), "Content-Length": "1"},
                stream=_RawStream((b"x",)),
            )
        return httpx.Response(200, content=final_body)

    with DailyMedConnector(httpx.MockTransport(handler), utc_now=_fixed_utc) as connector:
        result = connector.discover(setid=SETID, pagesize=100)
    assert result.failure is None
    assert result.request_count == 2
    assert len(result.raw_responses) == 2
    assert result.raw_responses[0].body == b"x"
    assert result.raw_responses[0].headers == (("content-length", "1"),)
