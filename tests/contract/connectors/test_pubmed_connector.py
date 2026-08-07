"""Offline HTTPX transport contracts for the bounded PubMed connector."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote

import httpx
import pytest

from medevidence.connectors.pubmed import (
    PUBMED_EFETCH_PATH,
    PUBMED_ESEARCH_PATH,
    PUBMED_ORIGIN,
    PubMedClientIdentity,
    PubMedConnector,
    PubMedConnectorConfig,
    PubMedFailureKind,
    PubMedResultState,
)
from medevidence.connectors.pubmed import client as pubmed_client
from medevidence.domain import (
    CoverageStatus,
    ExecutionStatus,
    PublicationStatusValue,
    ResultStatus,
    sha256_digest,
)

FIXTURES = Path(__file__).parents[2] / "fixtures" / "pubmed"
NOW = datetime(2026, 8, 5, 12, 0, tzinfo=UTC)
DUPLICATE_WARNING_MESSAGE = (
    "Duplicate PubMed identifiers were detected and handled under the operation's duplicate policy."
)


class FakeTime:
    def __init__(self) -> None:
        self.elapsed = 0.0
        self.sleep_calls: list[float] = []

    def monotonic(self) -> float:
        return self.elapsed

    def utc_now(self) -> datetime:
        return NOW + timedelta(seconds=self.elapsed)

    def sleep(self, seconds: float) -> None:
        self.sleep_calls.append(seconds)
        self.elapsed += seconds


class ChunkStream(httpx.SyncByteStream):
    def __init__(self, chunks: tuple[bytes, ...], *, fail_after_first: bool = False) -> None:
        self.chunks = chunks
        self.fail_after_first = fail_after_first
        self.closed = False

    def __iter__(self) -> Any:
        for index, chunk in enumerate(self.chunks):
            yield chunk
            if index == 0 and self.fail_after_first:
                raise httpx.ReadTimeout("synthetic stream timeout")

    def close(self) -> None:
        self.closed = True


class PreBodyFailureStream(httpx.SyncByteStream):
    def __init__(self, error: httpx.TransportError) -> None:
        self.error = error
        self.closed = False

    def __iter__(self) -> Any:
        raise self.error
        yield b""  # pragma: no cover

    def close(self) -> None:
        self.closed = True


def search_xml(*pmids: str, count: int | None = None, retstart: int = 0) -> bytes:
    total = len(pmids) if count is None else count
    identifiers = "".join(f"<Id>{pmid}</Id>" for pmid in pmids)
    return (
        "<eSearchResult>"
        f"<Count>{total}</Count>"
        f"<RetMax>{len(pmids)}</RetMax>"
        f"<RetStart>{retstart}</RetStart>"
        f"<IdList>{identifiers}</IdList>"
        "</eSearchResult>"
    ).encode()


def article_xml(
    pmid: str,
    *,
    title: str = "Synthetic title",
    language: str = "eng",
    journal: str = "Synthetic Journal",
    status: str = "MEDLINE",
) -> str:
    return (
        "<PubmedArticle>"
        f'<MedlineCitation Status="{status}">'
        f"<PMID>{pmid}</PMID>"
        "<Article>"
        f"<Journal><Title>{journal}</Title></Journal>"
        f"<ArticleTitle>{title}</ArticleTitle>"
        f"<Language>{language}</Language>"
        "</Article>"
        "</MedlineCitation>"
        "</PubmedArticle>"
    )


def fetch_xml(*articles: str) -> bytes:
    return ("<PubmedArticleSet>" + "".join(articles) + "</PubmedArticleSet>").encode()


def connector(
    handler: Callable[[httpx.Request], httpx.Response],
    *,
    config: PubMedConnectorConfig | None = None,
    fake_time: FakeTime | None = None,
    identity: PubMedClientIdentity | None = None,
) -> PubMedConnector:
    clock = fake_time or FakeTime()
    return PubMedConnector(
        httpx.MockTransport(handler),
        config,
        identity=identity,
        monotonic=clock.monotonic,
        utc_now=clock.utc_now,
        sleep=clock.sleep,
        jitter=lambda: 0.0,
    )


def assert_search_outcome(
    result: Any,
    *,
    execution: ExecutionStatus,
    coverage: CoverageStatus,
    status: ResultStatus,
) -> None:
    assert result.source_outcome is not None
    assert result.source_outcome.execution_status is execution
    assert result.source_outcome.coverage_status is coverage
    assert result.source_outcome.result_status is status


def test_one_page_success_uses_fixed_endpoint_and_bounded_parameters() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, content=search_xml("11", "22"))

    with connector(handler) as client:
        result = client.search("aspirin[Title/Abstract]")

    assert result.state is PubMedResultState.COMPLETE_SUCCESS
    assert result.pmids == ("11", "22")
    assert result.total_available == 2
    assert result.request_count == 1
    assert len(result.raw_responses) == 1
    assert_search_outcome(
        result,
        execution=ExecutionStatus.SUCCEEDED,
        coverage=CoverageStatus.COMPLETE,
        status=ResultStatus.MATCHES,
    )
    request = requests[0]
    assert request.url.scheme == "https"
    assert request.url.host == "eutils.ncbi.nlm.nih.gov"
    assert request.url.path == PUBMED_ESEARCH_PATH
    assert request.url.params["db"] == "pubmed"
    assert request.url.params["retmode"] == "xml"
    assert request.url.params["retmax"] == "20"
    assert request.url.params["tool"] == "medevidence"
    assert "email" not in request.url.params
    assert request.headers["accept-encoding"] == "identity"


def test_multi_page_success_advances_retstart_and_preserves_order() -> None:
    offsets: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        offset = int(request.url.params["retstart"])
        offsets.append(offset)
        if offset == 0:
            return httpx.Response(200, content=search_xml("11", "22", count=3))
        return httpx.Response(200, content=search_xml("33", count=3, retstart=2))

    config = PubMedConnectorConfig(page_size=2)
    with connector(handler, config=config) as client:
        result = client.search("bounded query")

    assert offsets == [0, 2]
    assert result.pmids == ("11", "22", "33")
    assert result.source_outcome is not None
    assert result.source_outcome.pages_completed == 2
    assert result.source_outcome.coverage_status is CoverageStatus.COMPLETE


def test_empty_search_is_complete_no_match_not_unavailable() -> None:
    with connector(lambda _: httpx.Response(200, content=search_xml())) as client:
        result = client.search("no matching records")

    assert result.state is PubMedResultState.EMPTY_SUCCESS
    assert result.pmids == ()
    assert_search_outcome(
        result,
        execution=ExecutionStatus.SUCCEEDED,
        coverage=CoverageStatus.COMPLETE,
        status=ResultStatus.NO_MATCH,
    )


def test_exact_page_limit_is_complete_but_one_more_result_is_truncated() -> None:
    config = PubMedConnectorConfig(page_size=2, max_pages=1)
    with connector(
        lambda _: httpx.Response(200, content=search_xml("1", "2")),
        config=config,
    ) as client:
        exact = client.search("exact page")
    with connector(
        lambda _: httpx.Response(200, content=search_xml("1", "2", count=3)),
        config=config,
    ) as client:
        truncated = client.search("one over page")

    assert exact.state is PubMedResultState.COMPLETE_SUCCESS
    assert exact.source_outcome is not None and not exact.source_outcome.truncated
    assert truncated.state is PubMedResultState.BOUNDED_TRUNCATION
    assert truncated.source_outcome is not None and truncated.source_outcome.truncated
    assert truncated.source_outcome.coverage_status is CoverageStatus.PARTIAL


def test_exact_record_limit_is_complete_but_one_more_result_is_truncated() -> None:
    config = PubMedConnectorConfig(page_size=2, max_records=2)
    with connector(
        lambda _: httpx.Response(200, content=search_xml("1", "2")),
        config=config,
    ) as client:
        exact = client.search("exact records")
    with connector(
        lambda _: httpx.Response(200, content=search_xml("1", "2", count=3)),
        config=config,
    ) as client:
        truncated = client.search("one over records")

    assert exact.state is PubMedResultState.COMPLETE_SUCCESS
    assert truncated.state is PubMedResultState.BOUNDED_TRUNCATION
    assert truncated.pmids == ("1", "2")


def test_duplicate_pmids_are_stable_and_do_not_fabricate_partial_coverage() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        offset = int(request.url.params["retstart"])
        if offset == 0:
            return httpx.Response(200, content=search_xml("1", "2", count=4))
        return httpx.Response(200, content=search_xml("2", "3", count=4, retstart=2))

    with connector(handler, config=PubMedConnectorConfig(page_size=2)) as client:
        result = client.search("duplicates")

    assert result.pmids == ("1", "2", "3")
    assert result.state is PubMedResultState.COMPLETE_SUCCESS
    assert result.source_outcome is not None
    assert result.source_outcome.coverage_status is CoverageStatus.COMPLETE
    assert "pubmed_duplicate_pmids" in result.warning_codes
    duplicate_warning = pubmed_client._domain_warning("pubmed_duplicate_pmids")
    assert duplicate_warning.message == DUPLICATE_WARNING_MESSAGE
    assert "conflicting" not in duplicate_warning.message.casefold()
    assert "discard" not in duplicate_warning.message.casefold()


@pytest.mark.parametrize(
    ("body", "kind"),
    [
        (b"<eSearchResult>", PubMedFailureKind.INVALID_XML),
        (
            b"<eSearchResult><Count>0</Count></eSearchResult>",
            PubMedFailureKind.INCOMPLETE_XML,
        ),
    ],
)
def test_invalid_and_missing_search_xml_are_typed_unavailable_failures(
    body: bytes,
    kind: PubMedFailureKind,
) -> None:
    with connector(lambda _: httpx.Response(200, content=body)) as client:
        result = client.search("malformed")

    assert result.state is PubMedResultState.FAILED
    assert result.failure is not None and result.failure.kind is kind
    assert_search_outcome(
        result,
        execution=ExecutionStatus.FAILED,
        coverage=CoverageStatus.UNAVAILABLE,
        status=ResultStatus.INDETERMINATE,
    )


@pytest.mark.parametrize(
    "body",
    [
        (
            b'<?xml version="1.0" encoding="x-unknown"?>'
            b"<eSearchResult><Count>0</Count><RetMax>0</RetMax>"
            b"<RetStart>0</RetStart><IdList /></eSearchResult>"
        ),
        (
            '<?xml version="1.0" encoding="UTF-16"?>'
            "<eSearchResult><Count>0</Count><RetMax>0</RetMax>"
            "<RetStart>0</RetStart><IdList /></eSearchResult>"
        ).encode("utf-16"),
        (
            '<?xml version="1.0" encoding="UTF-16LE"?>'
            "<eSearchResult><Count>0</Count><RetMax>0</RetMax>"
            "<RetStart>0</RetStart><IdList /></eSearchResult>"
        ).encode("utf-16-le"),
        (
            '<?xml version="1.0" encoding="UTF-16BE"?>'
            "<eSearchResult><Count>0</Count><RetMax>0</RetMax>"
            "<RetStart>0</RetStart><IdList /></eSearchResult>"
        ).encode("utf-16-be"),
    ],
)
def test_unknown_and_multibyte_xml_encodings_are_typed_invalid_xml(body: bytes) -> None:
    with connector(lambda _: httpx.Response(200, content=body)) as client:
        result = client.search("unsupported encoding")

    assert result.state is PubMedResultState.FAILED
    assert result.failure is not None
    assert result.failure.kind is PubMedFailureKind.INVALID_XML
    assert_search_outcome(
        result,
        execution=ExecutionStatus.FAILED,
        coverage=CoverageStatus.UNAVAILABLE,
        status=ResultStatus.INDETERMINATE,
    )


def test_search_provider_item_overflow_is_typed_before_results_accumulate() -> None:
    with connector(
        lambda _: httpx.Response(200, content=search_xml("1", "2")),
        config=PubMedConnectorConfig(max_records=1),
    ) as client:
        result = client.search("provider overflow")

    assert result.state is PubMedResultState.FAILED
    assert result.pmids == ()
    assert result.failure is not None
    assert result.failure.kind is PubMedFailureKind.INCOMPLETE_XML
    assert_search_outcome(
        result,
        execution=ExecutionStatus.FAILED,
        coverage=CoverageStatus.UNAVAILABLE,
        status=ResultStatus.INDETERMINATE,
    )


def test_inconsistent_count_on_later_page_preserves_verified_results() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.params["retstart"] == "0":
            return httpx.Response(200, content=search_xml("1", count=2))
        return httpx.Response(200, content=search_xml("2", count=3, retstart=1))

    with connector(handler, config=PubMedConnectorConfig(page_size=1)) as client:
        result = client.search("count drift")

    assert result.state is PubMedResultState.PARTIAL_FAILURE
    assert result.pmids == ("1",)
    assert result.failure is not None
    assert result.failure.kind is PubMedFailureKind.INCOMPLETE_XML
    assert_search_outcome(
        result,
        execution=ExecutionStatus.FAILED,
        coverage=CoverageStatus.PARTIAL,
        status=ResultStatus.MATCHES,
    )


@pytest.mark.parametrize(
    ("headers", "expected_delay"),
    [
        ({"Retry-After": "2"}, 2.0),
        ({}, 0.25),
    ],
)
def test_429_retries_with_or_without_retry_after(
    headers: dict[str, str],
    expected_delay: float,
) -> None:
    calls = 0
    fake = FakeTime()

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429, headers=headers, content=b"rate limited")
        return httpx.Response(200, content=search_xml("1"))

    with connector(handler, fake_time=fake) as client:
        result = client.search("retry")

    assert result.state is PubMedResultState.COMPLETE_SUCCESS
    assert calls == 2
    assert fake.sleep_calls == [expected_delay]
    assert result.retry_events[0].failure_kind is PubMedFailureKind.RATE_LIMITED
    assert result.retry_events[0].used_retry_after is bool(headers)


def test_retryable_5xx_then_success_and_exhaustion_are_distinct() -> None:
    recovery_calls = 0

    def recovery(_: httpx.Request) -> httpx.Response:
        nonlocal recovery_calls
        recovery_calls += 1
        if recovery_calls == 1:
            return httpx.Response(503, content=b"temporary")
        return httpx.Response(200, content=search_xml("1"))

    with connector(recovery) as client:
        recovered = client.search("recover")
    assert recovered.state is PubMedResultState.COMPLETE_SUCCESS
    assert recovery_calls == 2
    assert recovered.retry_events[0].failure_kind is PubMedFailureKind.RETRYABLE_SERVER_ERROR

    exhausted_calls = 0

    def exhausted(_: httpx.Request) -> httpx.Response:
        nonlocal exhausted_calls
        exhausted_calls += 1
        return httpx.Response(503, content=b"still unavailable")

    config = PubMedConnectorConfig(max_attempts=3)
    with connector(exhausted, config=config) as client:
        failed = client.search("exhaust")

    assert exhausted_calls == 3
    assert failed.failure is not None
    assert failed.failure.kind is PubMedFailureKind.RETRY_EXHAUSTED
    assert failed.failure.cause_kind is PubMedFailureKind.RETRYABLE_SERVER_ERROR
    assert failed.source_outcome is not None
    assert failed.source_outcome.coverage_status is CoverageStatus.UNAVAILABLE


def test_non_retryable_4xx_is_attempted_once() -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(400, content=b"bad request")

    with connector(handler) as client:
        result = client.search("bad request")

    assert calls == 1
    assert result.failure is not None
    assert result.failure.kind is PubMedFailureKind.CLIENT_ERROR
    assert result.retry_events == ()


@pytest.mark.parametrize(
    ("error_factory", "kind"),
    [
        (
            lambda request: httpx.ConnectError("offline failure", request=request),
            PubMedFailureKind.TRANSPORT,
        ),
        (
            lambda request: httpx.ReadTimeout("offline timeout", request=request),
            PubMedFailureKind.TIMEOUT,
        ),
    ],
)
def test_connection_and_timeout_failures_are_typed_without_retry(
    error_factory: Callable[[httpx.Request], httpx.TransportError],
    kind: PubMedFailureKind,
) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise error_factory(request)

    with connector(handler) as client:
        result = client.search("transport")

    assert calls == 1
    assert result.failure is not None and result.failure.kind is kind
    assert result.retry_events == ()


def test_later_page_exhausted_failure_retains_earlier_results() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.params["retstart"] == "0":
            return httpx.Response(200, content=search_xml("1", count=2))
        return httpx.Response(503, content=b"unavailable")

    config = PubMedConnectorConfig(page_size=1, max_attempts=2)
    with connector(handler, config=config) as client:
        result = client.search("partial")

    assert result.pmids == ("1",)
    assert result.state is PubMedResultState.PARTIAL_FAILURE
    assert result.request_count == 3
    assert result.failure is not None
    assert result.failure.kind is PubMedFailureKind.RETRY_EXHAUSTED
    assert_search_outcome(
        result,
        execution=ExecutionStatus.FAILED,
        coverage=CoverageStatus.PARTIAL,
        status=ResultStatus.MATCHES,
    )


def test_allowed_redirect_is_manual_and_query_preserving() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(307, headers={"Location": str(request.url)})
        return httpx.Response(200, content=search_xml("1"))

    with connector(handler) as client:
        result = client.search("redirect")

    assert result.state is PubMedResultState.COMPLETE_SUCCESS
    assert len(requests) == 2
    expected_params = {
        "db": ["pubmed"],
        "term": ["redirect"],
        "retmode": ["xml"],
        "retstart": ["0"],
        "retmax": ["20"],
        "tool": ["medevidence"],
    }
    assert parse_qs(requests[0].url.query.decode(), keep_blank_values=True) == expected_params
    assert parse_qs(requests[1].url.query.decode(), keep_blank_values=True) == expected_params
    assert tuple(raw.status_code for raw in result.raw_responses) == (307, 200)


@pytest.mark.parametrize(
    "location",
    [
        f"https://evil.example{PUBMED_ESEARCH_PATH}",
        f"http://eutils.ncbi.nlm.nih.gov{PUBMED_ESEARCH_PATH}",
        f"https://eutils.ncbi.nlm.nih.gov.evil.example{PUBMED_ESEARCH_PATH}",
        f"{PUBMED_ORIGIN}{PUBMED_EFETCH_PATH}",
    ],
)
def test_disallowed_redirects_and_lookalikes_fail_closed(location: str) -> None:
    with connector(lambda _: httpx.Response(302, headers={"Location": location})) as client:
        result = client.search("redirect rejection")

    assert result.failure is not None
    assert result.failure.kind is PubMedFailureKind.REDIRECT_REJECTED
    assert result.request_count == 1


def test_redirect_query_tampering_and_loop_bound_are_rejected() -> None:
    def tamper(request: httpx.Request) -> httpx.Response:
        query = parse_qs(request.url.query.decode())
        query["term"] = ["different"]
        location = str(
            httpx.URL(
                f"{PUBMED_ORIGIN}{PUBMED_ESEARCH_PATH}",
                params={key: values[0] for key, values in query.items()},
            )
        )
        return httpx.Response(302, headers={"Location": location})

    with connector(tamper) as client:
        tampered = client.search("original")
    assert tampered.failure is not None
    assert tampered.failure.kind is PubMedFailureKind.REDIRECT_REJECTED

    calls = 0

    def loop(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(307, headers={"Location": str(request.url)})

    with connector(loop, config=PubMedConnectorConfig(max_redirects=1)) as client:
        looped = client.search("loop")
    assert looped.failure is not None
    assert looped.failure.kind is PubMedFailureKind.REDIRECT_REJECTED
    assert calls == 2


def test_redirect_invalid_utf8_query_is_not_followed() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        original_url = str(request.url)
        assert "term=%EF%BF%BD" in original_url
        location = original_url.replace("term=%EF%BF%BD", "term=%FF")
        return httpx.Response(307, headers={"Location": location})

    with connector(handler) as client:
        result = client.search("\ufffd")

    assert len(requests) == 1
    assert result.request_count == 1
    assert result.failure is not None
    assert result.failure.kind is PubMedFailureKind.REDIRECT_REJECTED


def test_mixed_case_email_redirect_is_rejected_and_redacted_from_raw_metadata() -> None:
    email = "researcher@example.test"
    encoded_email = quote(email, safe="")
    outbound_requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        outbound_requests.append(request)
        redirected_params = [
            ("Email" if name.casefold() == "email" else name, value)
            for name, value in request.url.params.multi_items()
        ]
        location = str(
            httpx.URL(
                f"{PUBMED_ORIGIN}{PUBMED_ESEARCH_PATH}",
                params=redirected_params,
            )
        )
        return httpx.Response(302, headers={"Location": location})

    with connector(
        handler,
        identity=PubMedClientIdentity(email=email),
    ) as client:
        result = client.search("mixed-case email")

    assert len(outbound_requests) == 1
    assert outbound_requests[0].url.params["email"] == email
    assert result.failure is not None
    assert result.failure.kind is PubMedFailureKind.REDIRECT_REJECTED
    assert len(result.raw_responses) == 1
    raw = result.raw_responses[0]
    retained_metadata = (
        raw.request_url,
        raw.final_url,
        *(value for _, value in raw.headers),
    )
    assert all("email=" not in value.casefold() for value in retained_metadata)
    assert all(email.casefold() not in value.casefold() for value in retained_metadata)
    assert all(encoded_email.casefold() not in value.casefold() for value in retained_metadata)


def test_payload_limit_allows_exact_bytes_and_fails_one_byte_below() -> None:
    body = search_xml("1")
    exact_config = PubMedConnectorConfig(max_payload_bytes=len(body))
    with connector(
        lambda _: httpx.Response(200, content=body),
        config=exact_config,
    ) as client:
        exact = client.search("exact payload")
    assert exact.state is PubMedResultState.COMPLETE_SUCCESS

    over_config = PubMedConnectorConfig(max_payload_bytes=len(body) - 1)
    with connector(
        lambda _: httpx.Response(200, content=body),
        config=over_config,
    ) as client:
        over = client.search("over payload")
    assert over.failure is not None
    assert over.failure.kind is PubMedFailureKind.PAYLOAD_LIMIT
    assert over.source_outcome is not None
    assert over.source_outcome.coverage_status is CoverageStatus.UNAVAILABLE
    assert len(over.raw_responses) == 1
    assert over.raw_responses[0].body == body[:-1]
    assert not over.raw_responses[0].body_complete
    assert over.raw_responses[0].termination_reason == "payload_limit"


def test_cumulative_payload_limit_applies_across_pages() -> None:
    first = search_xml("1", count=2)
    second = search_xml("2", count=2, retstart=1)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=first if request.url.params["retstart"] == "0" else second,
        )

    config = PubMedConnectorConfig(
        page_size=1,
        max_payload_bytes=len(first) + len(second) - 1,
    )
    with connector(handler, config=config) as client:
        result = client.search("cumulative payload")

    assert result.pmids == ("1",)
    assert result.failure is not None
    assert result.failure.kind is PubMedFailureKind.PAYLOAD_LIMIT
    assert result.state is PubMedResultState.PARTIAL_FAILURE
    assert result.source_outcome is not None
    assert result.source_outcome.coverage_status is CoverageStatus.PARTIAL
    assert len(result.raw_responses) == 2
    assert not result.raw_responses[-1].body_complete
    assert result.raw_responses[-1].termination_reason == "payload_limit"


def test_streaming_response_is_read_once_and_closed_on_success_and_timeout() -> None:
    success_stream = ChunkStream((search_xml("1")[:20], search_xml("1")[20:]))

    with connector(lambda _: httpx.Response(200, stream=success_stream)) as client:
        success = client.search("stream success")
    assert success.state is PubMedResultState.COMPLETE_SUCCESS
    assert success_stream.closed

    retained_prefix = b"x" * 65_536
    timeout_stream = ChunkStream((retained_prefix, b"ignored"), fail_after_first=True)
    with connector(lambda _: httpx.Response(200, stream=timeout_stream)) as client:
        timed_out = client.search("stream timeout")
    assert timed_out.failure is not None
    assert timed_out.failure.kind is PubMedFailureKind.TIMEOUT
    assert len(timed_out.raw_responses) == 1
    assert timed_out.raw_responses[0].body == retained_prefix
    assert not timed_out.raw_responses[0].body_complete
    assert timeout_stream.closed


@pytest.mark.parametrize(
    ("error", "expected_kind"),
    [
        (httpx.ReadTimeout("synthetic pre-body timeout"), PubMedFailureKind.TIMEOUT),
        (httpx.ReadError("synthetic pre-body transport"), PubMedFailureKind.TRANSPORT),
    ],
)
def test_pre_body_stream_failure_does_not_fabricate_empty_raw_response(
    error: httpx.TransportError,
    expected_kind: PubMedFailureKind,
) -> None:
    stream = PreBodyFailureStream(error)
    with connector(lambda _: httpx.Response(200, stream=stream)) as client:
        result = client.search("pre-body failure")

    assert result.failure is not None
    assert result.failure.kind is expected_kind
    assert result.raw_responses == ()
    assert stream.closed


def test_total_deadline_is_enforced_after_response_arrival() -> None:
    fake = FakeTime()

    def handler(_: httpx.Request) -> httpx.Response:
        fake.elapsed = 1.0
        return httpx.Response(200, content=search_xml("1"))

    with connector(
        handler,
        config=PubMedConnectorConfig(total_deadline_seconds=1),
        fake_time=fake,
    ) as client:
        result = client.search("deadline")

    assert result.failure is not None
    assert result.failure.kind is PubMedFailureKind.TIMEOUT


def test_total_deadline_is_enforced_after_search_response_parsing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeTime()
    original_parser = pubmed_client.parse_search_page

    def slow_parser(payload: bytes, expected_retstart: int, *, max_items: int):
        page = original_parser(
            payload,
            expected_retstart=expected_retstart,
            max_items=max_items,
        )
        fake.elapsed = 1.0
        return page

    monkeypatch.setattr(pubmed_client, "parse_search_page", slow_parser)
    with connector(
        lambda _: httpx.Response(200, content=search_xml("1")),
        config=PubMedConnectorConfig(total_deadline_seconds=1),
        fake_time=fake,
    ) as client:
        result = client.search("deadline after parsing")

    assert result.failure is not None
    assert result.failure.kind is PubMedFailureKind.TIMEOUT
    assert result.source_outcome is not None
    assert result.source_outcome.coverage_status is CoverageStatus.UNAVAILABLE


def test_retry_after_is_capped_and_retry_delay_cannot_cross_deadline() -> None:
    fake = FakeTime()
    calls = 0

    def recover(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429, headers={"Retry-After": "999"})
        return httpx.Response(200, content=search_xml("1"))

    config = PubMedConnectorConfig(max_retry_after_seconds=1.0)
    with connector(recover, config=config, fake_time=fake) as client:
        recovered = client.search("capped")
    assert recovered.state is PubMedResultState.COMPLETE_SUCCESS
    assert fake.sleep_calls == [1.0]

    no_sleep = FakeTime()
    with connector(
        lambda _: httpx.Response(429, headers={"Retry-After": "2"}),
        config=PubMedConnectorConfig(total_deadline_seconds=1),
        fake_time=no_sleep,
    ) as client:
        exhausted = client.search("deadline before retry")
    assert exhausted.failure is not None
    assert exhausted.failure.kind is PubMedFailureKind.RETRY_EXHAUSTED
    assert no_sleep.sleep_calls == []
    assert exhausted.request_count == 1


def test_spoofed_final_response_url_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def spoofed_send(*_: object, **__: object) -> httpx.Response:
        spoofed_request = httpx.Request(
            "GET",
            f"https://eutils.ncbi.nlm.nih.gov.evil.example{PUBMED_ESEARCH_PATH}",
        )
        return httpx.Response(
            200,
            request=spoofed_request,
            content=search_xml("1"),
        )

    client = connector(
        lambda _: (_ for _ in ()).throw(AssertionError("mock transport should be bypassed"))
    )
    monkeypatch.setattr(client._client, "send", spoofed_send)
    with client:
        result = client.search("final URL")

    assert result.failure is not None
    assert result.failure.kind is PubMedFailureKind.REDIRECT_REJECTED


def test_invalid_input_never_calls_transport_or_fabricates_outcome() -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise AssertionError("transport must not be called")

    with connector(handler) as client:
        blank = client.search(" ")
        invalid_pmids = client.fetch(("0",))

    assert calls == 0
    assert blank.failure is not None
    assert blank.failure.kind is PubMedFailureKind.INVALID_INPUT
    assert blank.source_outcome is None
    assert invalid_pmids.failure is not None
    assert invalid_pmids.failure.kind is PubMedFailureKind.INVALID_INPUT
    assert invalid_pmids.source_outcome is None


@pytest.mark.parametrize(
    ("query", "query_id"),
    [
        pytest.param("q" * 1_000_000, None, id="oversized-query"),
        pytest.param("\ud800", None, id="lone-surrogate-query"),
        pytest.param(
            "bounded query",
            "q" * 1_000_000,
            id="oversized-query-id",
        ),
        pytest.param("bounded query", 42, id="nontext-query-id"),
    ],
)
def test_invalid_search_input_is_typed_bounded_and_never_calls_transport(
    query: str,
    query_id: object,
) -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise AssertionError("invalid search input must not reach transport")

    with connector(handler) as client:
        result = client.search(query, query_id=query_id)  # type: ignore[arg-type]

    assert calls == 0
    assert result.failure is not None
    assert result.failure.kind is PubMedFailureKind.INVALID_INPUT
    assert result.source_outcome is None
    assert result.query == ""
    assert result.query_id is None
    assert result.pmids == ()
    assert result.raw_responses == ()
    assert result.request_count == 0


@pytest.mark.parametrize(
    ("pmids", "query_id"),
    [
        pytest.param(("9" * 1_000_000,), None, id="oversized-pmid"),
        pytest.param(
            ("1",),
            "q" * 1_000_000,
            id="oversized-query-id",
        ),
        pytest.param(("1",), 42, id="nontext-query-id"),
    ],
)
def test_invalid_fetch_or_query_id_is_typed_bounded_and_never_calls_transport(
    pmids: tuple[str, ...],
    query_id: object,
) -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise AssertionError("invalid fetch input must not reach transport")

    with connector(handler) as client:
        result = client.fetch(pmids, query_id=query_id)  # type: ignore[arg-type]

    assert calls == 0
    assert result.failure is not None
    assert result.failure.kind is PubMedFailureKind.INVALID_INPUT
    assert result.source_outcome is None
    assert result.query_id is None
    assert result.requested_pmids == ()
    assert result.not_retrieved_pmids == ()
    assert result.publications == ()
    assert result.malformed_records == ()
    assert result.record_issues == ()
    assert result.raw_responses == ()
    assert result.request_count == 0


@pytest.mark.parametrize(
    "pmids",
    [
        ("9" * 129,),
        ("1", "2"),
    ],
)
def test_fetch_rejects_unbounded_input_before_transport_and_does_not_echo_it(
    pmids: tuple[str, ...],
) -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise AssertionError("transport must not be called for invalid bounded input")

    with connector(handler, config=PubMedConnectorConfig(max_records=1)) as client:
        result = client.fetch(pmids)

    assert calls == 0
    assert result.failure is not None
    assert result.failure.kind is PubMedFailureKind.INVALID_INPUT
    assert result.source_outcome is None
    assert result.requested_pmids == ()
    assert result.not_retrieved_pmids == ()
    assert result.publications == ()
    assert result.malformed_records == ()
    assert result.record_issues == ()


def test_fetch_success_maps_exact_record_provenance_and_status() -> None:
    body = (FIXTURES / "valid_fetch.xml").read_bytes()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == PUBMED_EFETCH_PATH
        assert request.url.params["id"] == "111"
        return httpx.Response(200, content=body)

    with connector(handler) as client:
        result = client.fetch(("111",), query_id="query:fetch-111")

    assert result.state is PubMedResultState.COMPLETE_SUCCESS
    assert result.not_retrieved_pmids == ()
    assert len(result.publications) == 1
    record = result.publications[0]
    assert record.pmid == "111"
    assert record.title == "Safety of example drug in adults"
    assert record.publication_status.status is PublicationStatusValue.RETRACTED
    assert record.provenance.query_id == "query:fetch-111"
    assert record.provenance.source_record_id == "111"
    assert record.provenance.content_hash == sha256_digest(body)
    assert record.provenance.source_outcome == result.source_outcome
    assert result.source_outcome is not None
    assert result.source_outcome.coverage_status is CoverageStatus.COMPLETE


def test_duplicate_caller_input_warning_does_not_claim_provider_records_were_discarded() -> None:
    with connector(lambda _: httpx.Response(200, content=fetch_xml(article_xml("111")))) as client:
        result = client.fetch(("111", "111"))

    assert result.state is PubMedResultState.COMPLETE_SUCCESS
    assert result.requested_pmids == ("111",)
    assert tuple(record.pmid for record in result.publications) == ("111",)
    assert "pubmed_duplicate_pmids" in result.warning_codes
    assert result.source_outcome is not None
    assert "pubmed_duplicate_pmids" in result.source_outcome.warning_codes
    duplicate_warning = next(
        warning
        for warning in result.publications[0].provenance.warnings
        if warning.code == "pubmed_duplicate_pmids"
    )
    assert duplicate_warning.message == DUPLICATE_WARNING_MESSAGE
    assert "conflicting" not in duplicate_warning.message.casefold()
    assert "discard" not in duplicate_warning.message.casefold()


def test_fetch_provenance_uses_each_batch_post_response_retrieval_time() -> None:
    fake = FakeTime()
    first_batch_attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal first_batch_attempts
        pmid = request.url.params["id"]
        if pmid == "111":
            first_batch_attempts += 1
            if first_batch_attempts == 1:
                fake.elapsed = 1.0
                return httpx.Response(503, content=b"temporary")
            fake.elapsed = 2.0
            return httpx.Response(200, content=fetch_xml(article_xml("111")))
        assert pmid == "222"
        fake.elapsed = 3.0
        return httpx.Response(200, content=fetch_xml(article_xml("222")))

    with connector(
        handler,
        config=PubMedConnectorConfig(page_size=1, max_attempts=2),
        fake_time=fake,
    ) as client:
        result = client.fetch(("111", "222"))

    assert first_batch_attempts == 2
    expected_times = {
        "111": NOW + timedelta(seconds=2),
        "222": NOW + timedelta(seconds=3),
    }
    assert tuple(record.pmid for record in result.publications) == ("111", "222")
    for record in result.publications:
        assert record.provenance.retrieved_at == expected_times[record.pmid]
        assert record.publication_status.retrieved_as_of == expected_times[record.pmid]
        assert record.provenance.retrieved_at != NOW


def test_identity_email_is_sent_but_not_retained_in_raw_response_urls() -> None:
    outbound_requests: list[httpx.Request] = []
    email = "researcher@example.test"

    def handler(request: httpx.Request) -> httpx.Response:
        outbound_requests.append(request)
        if len(outbound_requests) == 1:
            return httpx.Response(307, headers={"Location": str(request.url)})
        return httpx.Response(200, content=search_xml("1"))

    with connector(
        handler,
        identity=PubMedClientIdentity(email=email),
    ) as client:
        result = client.search("email redaction")

    assert len(outbound_requests) == 2
    assert all(request.url.params["email"] == email for request in outbound_requests)
    assert len(result.raw_responses) == 2
    for raw_response in result.raw_responses:
        retained_metadata = (
            raw_response.request_url,
            raw_response.final_url,
            *(value for _, value in raw_response.headers),
        )
        assert all("email=" not in value for value in retained_metadata)
        assert all(email not in value for value in retained_metadata)


def test_fetch_malformed_sibling_is_partial_and_valid_record_is_retained() -> None:
    body = fetch_xml(
        article_xml("111"),
        article_xml("222", title=" "),
    )
    with connector(lambda _: httpx.Response(200, content=body)) as client:
        result = client.fetch(("111", "222"))

    assert result.state is PubMedResultState.PARTIAL_SUCCESS
    assert tuple(record.pmid for record in result.publications) == ("111",)
    assert result.not_retrieved_pmids == ("222",)
    assert len(result.malformed_records) == 1
    assert result.source_outcome is not None
    assert result.source_outcome.coverage_status is CoverageStatus.PARTIAL
    assert result.source_outcome.result_status is ResultStatus.MATCHES


def test_fetch_all_malformed_is_partial_indeterminate_not_no_match() -> None:
    body = fetch_xml(article_xml("111", title=" "))
    with connector(lambda _: httpx.Response(200, content=body)) as client:
        result = client.fetch(("111",))

    assert result.state is PubMedResultState.PARTIAL_SUCCESS
    assert result.publications == ()
    assert result.source_outcome is not None
    assert result.source_outcome.coverage_status is CoverageStatus.PARTIAL
    assert result.source_outcome.result_status is ResultStatus.INDETERMINATE


@pytest.mark.parametrize(
    "malformed_article",
    [
        article_xml("111").replace(
            "</Article>",
            "<Abstract><AbstractText>First</AbstractText></Abstract>"
            "<Abstract><AbstractText>Second</AbstractText></Abstract></Article>",
        ),
        article_xml("111").replace(
            "</Article>",
            "<PublicationTypeList><PublicationType>Journal Article</PublicationType>"
            "</PublicationTypeList>"
            "<PublicationTypeList><PublicationType>Retracted Publication</PublicationType>"
            "</PublicationTypeList></Article>",
        ),
        article_xml("111").replace(
            "</MedlineCitation>",
            '<CommentsCorrectionsList><CommentsCorrections RefType="RetractionIn">'
            "<PMID>999</PMID></CommentsCorrections></CommentsCorrectionsList>"
            '<CommentsCorrectionsList><CommentsCorrections RefType="RetractionIn">'
            "<PMID>888</PMID></CommentsCorrections></CommentsCorrectionsList>"
            "</MedlineCitation>",
        ),
        article_xml("111").replace(
            "</MedlineCitation>",
            '<CommentsCorrectionsList><CommentsCorrections RefType="RetractionIn">'
            "<PMID>999</PMID><PMID>888</PMID>"
            "</CommentsCorrections></CommentsCorrectionsList></MedlineCitation>",
        ),
    ],
)
def test_duplicate_status_metadata_is_partial_malformed_not_hidden_current(
    malformed_article: str,
) -> None:
    with connector(lambda _: httpx.Response(200, content=fetch_xml(malformed_article))) as client:
        result = client.fetch(("111",))

    assert result.state is PubMedResultState.PARTIAL_SUCCESS
    assert result.publications == ()
    assert result.not_retrieved_pmids == ("111",)
    assert len(result.malformed_records) == 1
    assert result.malformed_records[0].pmid_hint == "111"
    assert result.source_outcome is not None
    assert result.source_outcome.coverage_status is CoverageStatus.PARTIAL
    assert result.source_outcome.result_status is ResultStatus.INDETERMINATE


def test_duplicate_current_and_retracted_whole_records_are_not_retained() -> None:
    retracted = (
        article_xml("111", title="Retracted version")
        .replace(
            "</Article>",
            "<PublicationTypeList><PublicationType>Retracted Publication</PublicationType>"
            "</PublicationTypeList></Article>",
        )
        .replace(
            "</MedlineCitation>",
            '<CommentsCorrectionsList><CommentsCorrections RefType="RetractionIn">'
            "<PMID>999</PMID></CommentsCorrections></CommentsCorrectionsList>"
            "</MedlineCitation>",
        )
    )
    body = fetch_xml(
        article_xml("111", title="Current version"),
        retracted,
    )

    with connector(lambda _: httpx.Response(200, content=body)) as client:
        result = client.fetch(("111", "222"))

    assert result.state is PubMedResultState.PARTIAL_SUCCESS
    assert result.publications == ()
    assert result.not_retrieved_pmids == ("111", "222")
    assert result.malformed_records == ()
    assert "pubmed_duplicate_pmids" in result.warning_codes
    assert "pubmed_missing_records" in result.warning_codes
    assert result.source_outcome is not None
    assert result.source_outcome.coverage_status is CoverageStatus.PARTIAL
    assert result.source_outcome.result_status is ResultStatus.INDETERMINATE


@pytest.mark.parametrize(
    "first_is_retracted",
    [
        pytest.param(False, id="current-then-retracted"),
        pytest.param(True, id="retracted-then-current"),
    ],
)
def test_repeated_provider_pmid_across_fetch_batches_is_evicted_operation_wide(
    first_is_retracted: bool,
) -> None:
    current = article_xml("111", title="Current version")
    retracted = (
        article_xml("111", title="Retracted version")
        .replace(
            "</Article>",
            "<PublicationTypeList><PublicationType>Retracted Publication</PublicationType>"
            "</PublicationTypeList></Article>",
        )
        .replace(
            "</MedlineCitation>",
            '<CommentsCorrectionsList><CommentsCorrections RefType="RetractionIn">'
            "<PMID>999</PMID></CommentsCorrections></CommentsCorrectionsList>"
            "</MedlineCitation>",
        )
    )
    first, second = (retracted, current) if first_is_retracted else (current, retracted)
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_pmid = request.url.params["id"]
        calls.append(requested_pmid)
        article = first if requested_pmid == "111" else second
        return httpx.Response(200, content=fetch_xml(article))

    with connector(
        handler,
        config=PubMedConnectorConfig(page_size=1),
    ) as client:
        result = client.fetch(("111", "222"))

    assert calls == ["111", "222"]
    assert result.request_count == 2
    assert len(result.raw_responses) == 2
    assert result.state is PubMedResultState.PARTIAL_SUCCESS
    assert result.failure is None
    assert result.publications == ()
    assert result.not_retrieved_pmids == ("111", "222")
    assert result.malformed_records == ()
    assert result.record_issues == ()
    assert "pubmed_duplicate_pmids" in result.warning_codes
    assert "pubmed_missing_records" in result.warning_codes
    assert "pubmed_unexpected_records" in result.warning_codes
    assert result.source_outcome is not None
    assert result.source_outcome.coverage_status is CoverageStatus.PARTIAL
    assert result.source_outcome.result_status is ResultStatus.INDETERMINATE


def test_fetch_provider_item_overflow_is_typed_before_diagnostics_accumulate() -> None:
    body = fetch_xml(article_xml("111"), article_xml("222"))
    with connector(
        lambda _: httpx.Response(200, content=body),
        config=PubMedConnectorConfig(max_records=1),
    ) as client:
        result = client.fetch(("111",))

    assert result.state is PubMedResultState.FAILED
    assert result.publications == ()
    assert result.malformed_records == ()
    assert result.record_issues == ()
    assert result.failure is not None
    assert result.failure.kind is PubMedFailureKind.INCOMPLETE_XML
    assert result.source_outcome is not None
    assert result.source_outcome.coverage_status is CoverageStatus.UNAVAILABLE
    assert result.source_outcome.result_status is ResultStatus.INDETERMINATE


def test_multi_batch_fetch_fails_on_first_per_batch_diagnostic_overflow() -> None:
    calls: list[str] = []
    over_budget_batch = fetch_xml("<PubmedArticle />", "<PubmedArticle />")

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.params["id"])
        return httpx.Response(200, content=over_budget_batch)

    with connector(
        handler,
        config=PubMedConnectorConfig(max_records=2, page_size=1),
    ) as client:
        result = client.fetch(("111", "222"))

    assert calls == ["111"]
    assert result.request_count == 1
    assert len(result.raw_responses) == 1
    assert result.state is PubMedResultState.FAILED
    assert result.failure is not None
    assert result.failure.kind is PubMedFailureKind.INCOMPLETE_XML
    assert result.requested_pmids == ("111", "222")
    assert result.not_retrieved_pmids == ("111", "222")
    assert result.publications == ()
    assert result.malformed_records == ()
    assert result.record_issues == ()
    accumulated_items = (
        len(result.publications) + len(result.malformed_records) + len(result.record_issues)
    )
    assert accumulated_items <= 2
    assert result.source_outcome is not None
    assert result.source_outcome.execution_status is ExecutionStatus.FAILED
    assert result.source_outcome.coverage_status is CoverageStatus.UNAVAILABLE
    assert result.source_outcome.result_status is ResultStatus.INDETERMINATE


def test_oversized_invalid_pmid_hint_is_not_echoed_in_fetch_diagnostics() -> None:
    oversized_pmid = "9" * 100_000
    body = fetch_xml(article_xml(oversized_pmid))
    with connector(lambda _: httpx.Response(200, content=body)) as client:
        result = client.fetch(("111",))

    assert result.state is PubMedResultState.PARTIAL_SUCCESS
    assert result.publications == ()
    assert result.not_retrieved_pmids == ("111",)
    assert len(result.malformed_records) == 1
    assert result.malformed_records[0].pmid_hint is None
    assert result.source_outcome is not None
    assert result.source_outcome.coverage_status is CoverageStatus.PARTIAL
    assert result.source_outcome.result_status is ResultStatus.INDETERMINATE


@pytest.mark.parametrize(
    ("first_batch", "expected_warning"),
    [
        (fetch_xml(article_xml("111", title=" ")), "pubmed_malformed_records"),
        (
            fetch_xml(
                article_xml("111").replace(
                    "</Journal>",
                    "<JournalIssue><PubDate><Year>0000</Year></PubDate></JournalIssue></Journal>",
                )
            ),
            "pubmed_record_mapping_warning",
        ),
    ],
)
def test_failed_fetch_after_first_batch_defect_is_partial_and_indeterminate(
    first_batch: bytes,
    expected_warning: str,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.params["id"] == "111":
            return httpx.Response(200, content=first_batch)
        return httpx.Response(503, content=b"unavailable")

    with connector(
        handler,
        config=PubMedConnectorConfig(page_size=1, max_attempts=1),
    ) as client:
        result = client.fetch(("111", "222"))

    assert result.state is PubMedResultState.PARTIAL_FAILURE
    assert result.publications == ()
    assert result.failure is not None
    assert result.failure.kind is PubMedFailureKind.RETRY_EXHAUSTED
    assert expected_warning in result.warning_codes
    assert result.source_outcome is not None
    assert result.source_outcome.execution_status is ExecutionStatus.FAILED
    assert result.source_outcome.coverage_status is CoverageStatus.PARTIAL
    assert result.source_outcome.result_status is ResultStatus.INDETERMINATE


@pytest.mark.parametrize(
    "publication_type",
    ["Retracted Publication", "Retraction of Publication"],
)
def test_retraction_publication_type_without_resolved_notice_is_unknown_not_current(
    publication_type: str,
) -> None:
    body = fetch_xml(
        article_xml("111").replace(
            "</Article>",
            f"<PublicationTypeList><PublicationType>{publication_type}</PublicationType>"
            "</PublicationTypeList></Article>",
        )
    )

    with connector(lambda _: httpx.Response(200, content=body)) as client:
        result = client.fetch(("111",))

    assert len(result.publications) == 1
    status = result.publications[0].publication_status
    assert status.status is PublicationStatusValue.UNKNOWN_OR_UNVERIFIED
    assert status.status is not PublicationStatusValue.CURRENT_OR_NO_KNOWN_NOTICE
    assert "publication_status_relationship_unresolved" in status.warning_codes


def test_fetch_page_bound_retains_first_batch_and_exposes_unretrieved_ids() -> None:
    config = PubMedConnectorConfig(page_size=1, max_pages=1)
    with connector(
        lambda request: httpx.Response(
            200,
            content=fetch_xml(article_xml(request.url.params["id"])),
        ),
        config=config,
    ) as client:
        result = client.fetch(("111", "222"))

    assert result.state is PubMedResultState.BOUNDED_TRUNCATION
    assert tuple(record.pmid for record in result.publications) == ("111",)
    assert result.not_retrieved_pmids == ("222",)
    assert result.source_outcome is not None and result.source_outcome.truncated


def test_later_fetch_failure_retains_publication_with_failed_partial_provenance() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        pmid = request.url.params["id"]
        if pmid == "111":
            return httpx.Response(200, content=fetch_xml(article_xml("111")))
        return httpx.Response(503, content=b"unavailable")

    config = PubMedConnectorConfig(page_size=1, max_attempts=1)
    with connector(handler, config=config) as client:
        result = client.fetch(("111", "222"), query_id="query:partial-fetch")

    assert result.state is PubMedResultState.PARTIAL_FAILURE
    assert tuple(record.pmid for record in result.publications) == ("111",)
    assert result.not_retrieved_pmids == ("222",)
    assert result.failure is not None
    assert result.failure.kind is PubMedFailureKind.RETRY_EXHAUSTED
    assert result.source_outcome is not None
    assert result.source_outcome.execution_status is ExecutionStatus.FAILED
    assert result.source_outcome.coverage_status is CoverageStatus.PARTIAL
    provenance = result.publications[0].provenance
    assert provenance.failure is not None
    assert provenance.failure.failure_id == result.source_outcome.failure_id


def test_fetch_invalid_xml_is_typed_unavailable() -> None:
    with connector(lambda _: httpx.Response(200, content=b"<PubmedArticleSet>")) as client:
        result = client.fetch(("111",))

    assert result.state is PubMedResultState.FAILED
    assert result.failure is not None
    assert result.failure.kind is PubMedFailureKind.INVALID_XML
    assert result.source_outcome is not None
    assert result.source_outcome.coverage_status is CoverageStatus.UNAVAILABLE


def test_mock_injection_has_no_implicit_real_transport_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden_transport(*_: object, **__: object) -> httpx.HTTPTransport:
        raise AssertionError("real HTTP transport must not be constructed")

    monkeypatch.setattr(httpx, "HTTPTransport", forbidden_transport)
    with connector(lambda _: httpx.Response(200, content=search_xml("1"))) as client:
        result = client.search("offline only")

    assert result.state is PubMedResultState.COMPLETE_SUCCESS
    with pytest.raises(TypeError):
        PubMedConnector()  # type: ignore[call-arg]


def test_closed_connector_does_not_reopen_or_call_transport() -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, content=search_xml("1"))

    client = connector(handler)
    client.close()
    result = client.search("closed")

    assert calls == 0
    assert result.failure is not None
    assert result.failure.kind is PubMedFailureKind.INTERNAL_CONTRACT
    assert result.source_outcome is None


def test_m1a_constrained_profile_and_raw_handoff_are_exact() -> None:
    config = PubMedConnectorConfig.m1a_constrained_v1()
    with connector(
        lambda request: httpx.Response(
            200,
            content=search_xml("1"),
            headers={"content-type": "application/xml; charset=utf-8"},
            request=request,
        ),
        config=config,
    ) as client:
        result = client.search("synthetic", query_id="query:constrained")

    assert (
        config.page_size,
        config.max_pages,
        config.max_attempts,
        config.max_redirects,
        config.max_records,
        config.max_payload_bytes,
        config.total_deadline_seconds,
    ) == (100, 1, 2, 1, 100, 5_242_880, 30)
    assert len(result.raw_responses) == 1
    raw = result.raw_responses[0]
    assert raw.body == search_xml("1")
    assert raw.observed_at_utc == NOW
    assert ("content-type", "application/xml; charset=utf-8") in raw.headers
