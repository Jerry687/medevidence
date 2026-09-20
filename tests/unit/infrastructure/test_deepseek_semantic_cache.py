from __future__ import annotations

import gzip
import hashlib
import json
from dataclasses import fields, replace
from typing import cast

import httpx
import pytest
from tests.contract.infrastructure.test_deepseek_semantic_evaluator import (
    API_KEY,
    _response_semantic_v2,
)
from tests.unit.tools.test_report_validation import _v2_request

import medevidence.tools.report_validation_v2 as validation_v2
from medevidence.domain import canonical_json
from medevidence.infrastructure.deepseek_semantic_cache import (
    DurableDeepSeekSemanticEvaluationPortV2,
    SemanticCachePortError,
    SemanticCachePortErrorCode,
    semantic_evaluation_operation_id,
)
from medevidence.infrastructure.deepseek_semantic_evaluator import (
    DeepSeekResponsesSemanticEvaluatorV2,
)
from medevidence.persistence.semantic_cache import (
    SemanticCacheEvent,
    SemanticCacheLease,
    make_semantic_cache_event,
    validate_semantic_cache_event,
)
from medevidence.tools.report_validation import (
    CitationRelationship,
    PlannedStage2SemanticInputV2,
    SemanticSupport,
    ValidationMode,
    canonical_stage1_receipt_payload_v2,
    canonical_validate_report,
)
from medevidence.tools.semantic_evaluation import SemanticEvaluationRequest


class Journal:
    def __init__(self, fail_kind: str | None = None) -> None:
        self.events: list[SemanticCacheEvent] = []
        self.fail_kind = fail_kind

    def acquire_operation_lease(self, operation_id: str) -> SemanticCacheLease:
        return cast(SemanticCacheLease, object())

    def release_operation_lease(self, lease: SemanticCacheLease) -> None:
        del lease

    def append(self, event: SemanticCacheEvent) -> SemanticCacheEvent:
        if event.event_kind == self.fail_kind:
            raise RuntimeError(f"{self.fail_kind} persistence failed")
        validate_semantic_cache_event(event)
        if any(
            item.operation_id == event.operation_id
            and item.attempt_ordinal == event.attempt_ordinal
            and item.event_slot == event.event_slot
            for item in self.events
        ):
            raise RuntimeError("duplicate slot")
        self.events.append(event)
        return event

    def list_events(self, operation_id: str) -> tuple[SemanticCacheEvent, ...]:
        return tuple(
            validate_semantic_cache_event(item)
            for item in self.events
            if item.operation_id == operation_id
        )


class Stage1Store:
    def __init__(self, payload: dict[str, object] | None) -> None:
        self.payload = payload

    def load_stage1_receipt(self, receipt_id: str):  # type: ignore[no-untyped-def]
        if self.payload is None or self.payload["receipt_id"] != receipt_id:
            return None
        return self.payload


def _request_and_receipt() -> tuple[SemanticEvaluationRequest, dict[str, object]]:
    report, _provider, projections = _v2_request(
        (CitationRelationship.SUPPORTS,), (SemanticSupport.SUPPORTED,)
    )
    report = replace(
        report,
        registry=replace(
            report.registry,
            semantic_expectations=tuple(
                PlannedStage2SemanticInputV2(
                    item.citation_id, item.input_digest, item.method, item.version
                )
                for item in projections
            ),
        ),
    )
    preflight = canonical_validate_report(report, mode=ValidationMode.PREPARE_STAGE1)
    receipt = preflight.stage1_receipt
    assert receipt is not None
    claim = report.registry.claims[0]
    citation = report.registry.citations[0]
    evidence = report.registry.evidence[0]
    current = validation_v2.SemanticEvaluationInput(report.run_id, claim, citation, evidence)
    request = validation_v2._planned_semantic_request_v2(report, receipt, claim, current)
    return request, canonical_stage1_receipt_payload_v2(receipt)


def _two_requests_and_receipt() -> tuple[
    tuple[SemanticEvaluationRequest, SemanticEvaluationRequest], dict[str, object]
]:
    report, _provider, projections = _v2_request(
        (CitationRelationship.SUPPORTS, CitationRelationship.CONTEXT_ONLY),
        (SemanticSupport.SUPPORTED, SemanticSupport.SUPPORTED),
    )
    report = replace(
        report,
        registry=replace(
            report.registry,
            semantic_expectations=tuple(
                PlannedStage2SemanticInputV2(
                    item.citation_id, item.input_digest, item.method, item.version
                )
                for item in projections
            ),
        ),
    )
    receipt = canonical_validate_report(report, mode=ValidationMode.PREPARE_STAGE1).stage1_receipt
    assert receipt is not None
    claim = report.registry.claims[0]
    evidence = {item.evidence_id: item for item in report.registry.evidence}
    requests = tuple(
        validation_v2._planned_semantic_request_v2(
            report,
            receipt,
            claim,
            validation_v2.SemanticEvaluationInput(
                report.run_id, claim, citation, evidence[citation.evidence_id]
            ),
        )
        for citation in report.registry.citations
    )
    assert len(requests) == 2
    return cast(tuple[SemanticEvaluationRequest, SemanticEvaluationRequest], requests), (
        canonical_stage1_receipt_payload_v2(receipt)
    )


def _port(
    handler, journal: Journal, receipt: dict[str, object] | None, *, sleeps=None
) -> DurableDeepSeekSemanticEvaluationPortV2:  # type: ignore[no-untyped-def]
    evaluator = DeepSeekResponsesSemanticEvaluatorV2(
        api_key=API_KEY, transport=httpx.MockTransport(handler)
    )
    return DurableDeepSeekSemanticEvaluationPortV2(
        evaluator=evaluator,
        journal=journal,
        stage1_receipts=Stage1Store(receipt),
        sleeper=(lambda seconds: sleeps.append(seconds)) if sleeps is not None else lambda _: None,
    )


def _success() -> httpx.Response:
    return httpx.Response(
        200,
        headers={"Content-Type": "application/json"},
        content=canonical_json(_response_semantic_v2()).encode("utf-8"),
        extensions={"http_version": b"HTTP/2"},
    )


def _rebuild(event: SemanticCacheEvent, **changes: object) -> SemanticCacheEvent:
    values = {
        field.name: getattr(event, field.name)
        for field in fields(event)
        if field.name != "event_id"
    }
    values.update(changes)
    return make_semantic_cache_event(**values)


def test_stage1_must_load_and_bind_before_start_or_provider() -> None:
    request, receipt = _request_and_receipt()
    journal = Journal()
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return _success()

    with pytest.raises(SemanticCachePortError, match="stage1_unavailable"):
        _port(handler, journal, None).evaluate_v2(request)
    changed = dict(receipt)
    changed["report_content_hash"] = "sha256:" + "f" * 64
    with pytest.raises(SemanticCachePortError, match="stage1_binding_drift"):
        _port(handler, journal, changed).evaluate_v2(request)
    assert calls == 0 and journal.events == []


def test_operation_identity_is_stable_and_separates_citations() -> None:
    request, _receipt = _request_and_receipt()
    requests, _ = _two_requests_and_receipt()
    assert semantic_evaluation_operation_id(request) == semantic_evaluation_operation_id(request)
    assert semantic_evaluation_operation_id(requests[0]) != semantic_evaluation_operation_id(
        requests[1]
    )


def test_success_persists_start_raw_result_terminal_and_cache_hit_uses_no_network() -> None:
    request, receipt = _request_and_receipt()
    journal = Journal()
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        assert [item.event_kind for item in journal.events] == ["START"]
        return _success()

    port = _port(handler, journal, receipt)
    first = port.evaluate_v2(request)
    second = port.evaluate_v2(request)
    assert first == second
    assert calls == 1
    assert [item.event_kind for item in journal.events] == ["START", "RAW", "RESULT", "TERMINAL"]
    assert journal.events[-1].disposition == "success"


def test_retryable_terminal_gets_new_attempt_under_one_port_call() -> None:
    request, receipt = _request_and_receipt()
    journal = Journal()
    responses = iter(
        (
            httpx.Response(
                503,
                headers={"Content-Type": "application/json", "Retry-After": "0"},
                content=b'{"error":"temporary"}',
                extensions={"http_version": b"HTTP/2"},
            ),
            _success(),
        )
    )
    sleeps: list[float] = []
    result = _port(lambda _: next(responses), journal, receipt, sleeps=sleeps).evaluate_v2(request)
    assert result.result is SemanticSupport.SUPPORTED
    assert [(item.attempt_ordinal, item.event_kind) for item in journal.events] == [
        (1, "START"),
        (1, "RAW"),
        (1, "TERMINAL"),
        (2, "START"),
        (2, "RAW"),
        (2, "RESULT"),
        (2, "TERMINAL"),
    ]
    assert journal.events[2].disposition == "retryable_status"
    assert len(sleeps) == 1 and 0 <= sleeps[0] <= 2


def test_unknown_start_never_resends() -> None:
    request, receipt = _request_and_receipt()
    journal = Journal()
    calls = 0

    def crash(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise RuntimeError("simulated process loss")

    port = _port(crash, journal, receipt)
    with pytest.raises(RuntimeError, match="process loss"):
        port.evaluate_v2(request)
    assert [item.event_kind for item in journal.events] == ["START"]
    with pytest.raises(SemanticCachePortError) as caught:
        port.evaluate_v2(request)
    assert caught.value.code is SemanticCachePortErrorCode.UNKNOWN_AFTER_START
    assert calls == 1


def test_credential_echo_is_terminal_without_raw_and_never_retried() -> None:
    request, receipt = _request_and_receipt()
    journal = Journal()
    calls = 0

    def echo(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            headers={"X-Request-ID": API_KEY},
            content=b"must not persist",
            extensions={"http_version": b"HTTP/2"},
        )

    port = _port(echo, journal, receipt)
    with pytest.raises(SemanticCachePortError) as caught:
        port.evaluate_v2(request)
    assert caught.value.disposition == "credential_echo"
    assert calls == 1
    assert [item.event_kind for item in journal.events] == ["START", "TERMINAL"]
    assert all(item.raw_body_bytes is None for item in journal.events)
    with pytest.raises(SemanticCachePortError):
        port.evaluate_v2(request)
    assert calls == 1


def test_three_retryable_http_attempts_are_finite_and_cached_failure() -> None:
    request, receipt = _request_and_receipt()
    journal = Journal()
    calls = 0

    def unavailable(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(503, headers={"Content-Type": "application/json"}, content=b"{}")

    port = _port(unavailable, journal, receipt)
    with pytest.raises(SemanticCachePortError) as caught:
        port.evaluate_v2(request)
    assert caught.value.disposition == "retryable_status"
    assert calls == 3
    assert [item.event_kind for item in journal.events].count("START") == 3
    with pytest.raises(SemanticCachePortError):
        port.evaluate_v2(request)
    assert calls == 3


def test_start_failure_prevents_network_and_result_failure_leaves_unknown() -> None:
    request, receipt = _request_and_receipt()
    calls = 0

    def success(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return _success()

    with pytest.raises(RuntimeError, match="START persistence failed"):
        _port(success, Journal("START"), receipt).evaluate_v2(request)
    assert calls == 0
    result_failure = Journal("RESULT")
    port = _port(success, result_failure, receipt)
    with pytest.raises(RuntimeError, match="RESULT persistence failed"):
        port.evaluate_v2(request)
    assert [item.event_kind for item in result_failure.events] == ["START", "RAW"]
    with pytest.raises(SemanticCachePortError) as caught:
        port.evaluate_v2(request)
    assert caught.value.code is SemanticCachePortErrorCode.UNKNOWN_AFTER_START
    assert calls == 1
    terminal_failure = Journal("TERMINAL")
    terminal_port = _port(success, terminal_failure, receipt)
    with pytest.raises(RuntimeError, match="TERMINAL persistence failed"):
        terminal_port.evaluate_v2(request)
    assert [item.event_kind for item in terminal_failure.events] == ["START", "RAW", "RESULT"]
    with pytest.raises(SemanticCachePortError) as caught:
        terminal_port.evaluate_v2(request)
    assert caught.value.code is SemanticCachePortErrorCode.UNKNOWN_AFTER_START
    assert calls == 2
    raw_failure = Journal("RAW")
    raw_port = _port(success, raw_failure, receipt)
    with pytest.raises(SemanticCachePortError) as caught:
        raw_port.evaluate_v2(request)
    assert caught.value.disposition == "evidence_persistence_failure"
    assert [item.event_kind for item in raw_failure.events] == ["START", "TERMINAL"]
    with pytest.raises(SemanticCachePortError):
        raw_port.evaluate_v2(request)
    assert calls == 3


def test_nonretryable_response_and_unsupported_encoding_never_retry_or_store_raw() -> None:
    request, receipt = _request_and_receipt()
    for response, expected_raw in (
        (
            httpx.Response(
                400,
                headers={"Content-Type": "application/json"},
                content=b'{"error":"permanent"}',
                extensions={"http_version": b"HTTP/2"},
            ),
            True,
        ),
        (
            httpx.Response(
                200,
                headers={"Content-Type": "application/json", "Content-Encoding": "gzip"},
                content=gzip.compress(b"body"),
                extensions={"http_version": b"HTTP/2"},
            ),
            False,
        ),
    ):
        journal = Journal()
        calls = 0

        def handler(_request: httpx.Request, response=response) -> httpx.Response:  # type: ignore[no-untyped-def]
            nonlocal calls
            calls += 1
            return response

        with pytest.raises(SemanticCachePortError):
            _port(handler, journal, receipt).evaluate_v2(request)
        assert calls == 1
        assert ("RAW" in [item.event_kind for item in journal.events]) is expected_raw
        assert journal.events[-1].event_kind == "TERMINAL"


def test_incomplete_and_oversized_bodies_are_never_persisted() -> None:
    request, receipt = _request_and_receipt()

    class BrokenStream(httpx.SyncByteStream):
        def __iter__(self):  # type: ignore[no-untyped-def]
            yield b"partial"
            raise httpx.ReadError("simulated incomplete body")

    cases = (
        (
            lambda: httpx.Response(
                200,
                headers={"Content-Type": "application/json"},
                stream=BrokenStream(),
                extensions={"http_version": b"HTTP/2"},
            ),
            3,
        ),
        (
            lambda: httpx.Response(
                200,
                headers={"Content-Type": "application/json"},
                content=b"x" * 131_073,
                extensions={"http_version": b"HTTP/2"},
            ),
            1,
        ),
    )
    for response, expected_calls in cases:
        journal = Journal()
        calls = 0

        def handler(_request: httpx.Request, response=response) -> httpx.Response:  # type: ignore[no-untyped-def]
            nonlocal calls
            calls += 1
            return response()

        with pytest.raises(SemanticCachePortError):
            _port(handler, journal, receipt).evaluate_v2(request)
        assert calls == expected_calls
        assert "RAW" not in [item.event_kind for item in journal.events]


def test_prior_citation_success_is_reused_after_later_citation_failure() -> None:
    requests, receipt = _two_requests_and_receipt()
    journal = Journal()
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return (
            _success()
            if calls == 1
            else httpx.Response(400, headers={"Content-Type": "application/json"}, content=b"{}")
        )

    port = _port(handler, journal, receipt)
    first = port.evaluate_v2(requests[0])
    with pytest.raises(SemanticCachePortError):
        port.evaluate_v2(requests[1])
    assert port.evaluate_v2(requests[0]) == first
    assert calls == 2


def test_retry_attempts_share_one_deadline_and_no_start_is_fabricated_after_expiry() -> None:
    request, receipt = _request_and_receipt()
    journal = Journal()
    calls = 0

    class Clock:
        value = 0.0

        def __call__(self) -> float:
            return self.value

        def sleep(self, _seconds: float) -> None:
            self.value += 46.0

    clock = Clock()

    def unavailable(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(503, headers={"Content-Type": "application/json"}, content=b"{}")

    port = DurableDeepSeekSemanticEvaluationPortV2(
        evaluator=DeepSeekResponsesSemanticEvaluatorV2(
            api_key=API_KEY, transport=httpx.MockTransport(unavailable)
        ),
        journal=journal,
        stage1_receipts=Stage1Store(receipt),
        monotonic_clock=clock,
        sleeper=clock.sleep,
    )
    with pytest.raises(SemanticCachePortError) as caught:
        port.evaluate_v2(request)
    assert caught.value.disposition == "retryable_status"
    assert calls == 1
    assert [item.event_kind for item in journal.events] == ["START", "RAW", "TERMINAL"]
    with pytest.raises(SemanticCachePortError) as repeated:
        port.evaluate_v2(request)
    assert repeated.value.disposition == "retryable_status"
    fresh = DurableDeepSeekSemanticEvaluationPortV2(
        evaluator=DeepSeekResponsesSemanticEvaluatorV2(
            api_key=API_KEY, transport=httpx.MockTransport(unavailable)
        ),
        journal=journal,
        stage1_receipts=Stage1Store(receipt),
        monotonic_clock=clock,
        sleeper=clock.sleep,
    )
    with pytest.raises(SemanticCachePortError) as restarted:
        fresh.evaluate_v2(request)
    assert restarted.value.disposition == "retryable_status"
    assert calls == 1


def test_concurrent_invocation_cannot_steal_retry_between_attempts() -> None:
    request, receipt = _request_and_receipt()
    journal = Journal()
    calls = 0
    concurrent_errors: list[SemanticCachePortError] = []

    def response(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return (
            httpx.Response(
                503,
                headers={"Content-Type": "application/json"},
                content=b"{}",
            )
            if calls == 1
            else _success()
        )

    concurrent = _port(response, journal, receipt)

    def between_attempts(_seconds: float) -> None:
        try:
            concurrent.evaluate_v2(request)
        except SemanticCachePortError as error:
            concurrent_errors.append(error)

    owner = DurableDeepSeekSemanticEvaluationPortV2(
        evaluator=DeepSeekResponsesSemanticEvaluatorV2(
            api_key=API_KEY, transport=httpx.MockTransport(response)
        ),
        journal=journal,
        stage1_receipts=Stage1Store(receipt),
        sleeper=between_attempts,
    )
    assert owner.evaluate_v2(request).result is SemanticSupport.SUPPORTED
    assert calls == 2
    assert len(concurrent_errors) == 1
    assert concurrent_errors[0].code is SemanticCachePortErrorCode.CACHED_FAILURE


@pytest.mark.parametrize("surface", ("result_link", "terminal_disposition", "timestamp"))
def test_cached_event_tampering_fails_before_provider(surface: str) -> None:
    request, receipt = _request_and_receipt()
    journal = Journal()
    calls = 0

    def success(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return _success()

    port = _port(success, journal, receipt)
    port.evaluate_v2(request)
    if surface == "result_link":
        journal.events[2] = _rebuild(journal.events[2], raw_event_id=journal.events[0].event_id)
    else:
        terminal = journal.events[3]
        payload = json.loads(terminal.payload_bytes)
        if surface == "terminal_disposition":
            payload["disposition"] = "provider_rejected"
        else:
            payload["observation"]["completed_at_utc"] = "2027-01-01T00:00:00+00:00"
        payload_bytes = canonical_json(payload).encode("utf-8")
        journal.events[3] = _rebuild(
            terminal,
            payload_bytes=payload_bytes,
            payload_hash="sha256:" + hashlib.sha256(payload_bytes).hexdigest(),
        )
    with pytest.raises(SemanticCachePortError) as caught:
        port.evaluate_v2(request)
    assert caught.value.code is SemanticCachePortErrorCode.CACHE_INTEGRITY
    assert calls == 1
