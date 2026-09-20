"""Offline Qwen cache ordering, replay and unknown-after-send checks."""

from __future__ import annotations

from dataclasses import replace

import httpx
import pytest
from tests.contract.infrastructure.test_qwen_semantic_evaluator import ENDPOINT, KEY, _envelope
from tests.unit.infrastructure.test_deepseek_semantic_cache import Journal, Stage1Store
from tests.unit.tools.test_report_validation import _rebind, _v2_request

import medevidence.tools.report_validation_v2 as validation_v2
from medevidence.domain import (
    AdverseEventConcept,
    DrugConcept,
    QueryBounds,
    ResearchScope,
    ResultBounds,
)
from medevidence.infrastructure.deepseek_semantic_cache import (
    SemanticCachePortError,
    SemanticCachePortErrorCode,
)
from medevidence.infrastructure.qwen_semantic_cache import DurableQwenSemanticEvaluationPortV2
from medevidence.infrastructure.qwen_semantic_evaluator import QwenChatSemanticEvaluatorV2
from medevidence.tools.report_validation import (
    M3_SEMANTIC_EVALUATION_V2,
    CitationRelationship,
    EvaluatorIdentityInput,
    ExecutionBoundsInput,
    PlannedStage2SemanticInputV2,
    SemanticSupport,
    ValidationMode,
    canonical_stage1_receipt_payload_v2,
    canonical_validate_report,
)
from medevidence.tools.report_validation_v3 import M3_VALIDATION_CONFIGURATION_V4
from medevidence.tools.runtime_source_bounds import expected_runtime_source_bounds_v3
from medevidence.tools.semantic_evaluation import QWEN_SEMANTIC_V2_PROVIDER_METHOD


def _request_and_receipt():  # type: ignore[no-untyped-def]
    report, _, projections = _v2_request(
        (CitationRelationship.SUPPORTS,), (SemanticSupport.SUPPORTED,)
    )
    task = report.tasks[0]
    scope = report.scope
    scope = replace(
        scope,
        max_query_characters=512,
        max_pages=5,
        max_payload_bytes=5_242_880,
    )
    rebuilt = ResearchScope.create(
        drugs=tuple(DrugConcept(concept_id=row[0], preferred_term=row[1]) for row in scope.drugs),
        adverse_reactions=tuple(
            AdverseEventConcept(concept_id=row[0], preferred_term=row[1])
            for row in scope.adverse_reactions
        ),
        date_range=None,
        selected_sources=scope.selected_sources,
        comparison_intent=scope.comparison_intent,
        query_bounds=QueryBounds(
            max_query_characters=scope.max_query_characters,
            max_pages=scope.max_pages,
            max_total_seconds=scope.max_total_seconds,
        ),
        result_bounds=ResultBounds(
            max_records=scope.max_records,
            max_payload_bytes=scope.max_payload_bytes,
        ),
    )
    scope = replace(scope, scope_id=rebuilt.scope_id)
    master = (
        scope.max_query_characters,
        scope.max_pages,
        scope.max_records,
        scope.max_payload_bytes,
        scope.max_total_seconds,
    )
    bounds = expected_runtime_source_bounds_v3(task.source, master)
    adjusted_task = replace(
        task,
        outcome=replace(task.outcome, configured_bounds=ExecutionBoundsInput(*bounds)),
    )
    identity = EvaluatorIdentityInput(QWEN_SEMANTIC_V2_PROVIDER_METHOD, M3_SEMANTIC_EVALUATION_V2)
    planned = tuple(
        PlannedStage2SemanticInputV2(
            item.citation_id, item.input_digest, identity.method, identity.version
        )
        for item in projections
    )
    report = _rebind(
        replace(
            report,
            scope=scope,
            tasks=(adjusted_task,),
            registry=replace(
                report.registry,
                scope_id=scope.scope_id,
                configuration_version=M3_VALIDATION_CONFIGURATION_V4,
                evaluator_identity=identity,
                semantic_expectations=planned,
            ),
        )
    )
    preflight = canonical_validate_report(report, mode=ValidationMode.PREPARE_STAGE1)
    receipt = preflight.stage1_receipt
    assert receipt is not None
    current = validation_v2.SemanticEvaluationInput(
        report.run_id,
        report.registry.claims[0],
        report.registry.citations[0],
        report.registry.evidence[0],
    )
    request = validation_v2._planned_semantic_request_v2(
        report, receipt, report.registry.claims[0], current
    )
    return report, request, receipt, canonical_stage1_receipt_payload_v2(receipt)


@pytest.mark.allow_hosts(["127.0.0.1", "::1"])
def test_qwen_cache_start_raw_result_terminal_and_replay() -> None:
    report, request, stage1_receipt, receipt = _request_and_receipt()
    calls = 0

    def handle(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200, headers={"content-type": "application/json"}, content=_envelope()
        )

    evaluator = QwenChatSemanticEvaluatorV2(
        api_key=KEY, endpoint=ENDPOINT, transport=httpx.MockTransport(handle)
    )
    journal = Journal()
    port = DurableQwenSemanticEvaluationPortV2(
        evaluator=evaluator, journal=journal, stage1_receipts=Stage1Store(receipt)
    )
    try:
        first = port.evaluate_v2(request)
        second = port.evaluate_v2(request)
        assert first == second
        audit = canonical_validate_report(
            report,
            mode=ValidationMode.ASSESS,
            semantic_result_provider_v2=port,
            stage1_receipt=stage1_receipt,
        )
        assert audit.summary.passed
        assert calls == 1
        assert [event.event_kind for event in journal.events] == [
            "START",
            "RAW",
            "RESULT",
            "TERMINAL",
        ]
        assert journal.events[0].provider_configuration_version.startswith(
            "m3.semantic-evaluation.v2.qwen"
        )
    finally:
        evaluator.close()


@pytest.mark.allow_hosts(["127.0.0.1", "::1"])
def test_qwen_cache_never_resends_partial_200() -> None:
    _, request, _, receipt = _request_and_receipt()
    calls = 0

    class BrokenStream(httpx.AsyncByteStream):
        async def __aiter__(self):  # type: ignore[no-untyped-def]
            yield b"{" * 100
            raise httpx.ReadError("partial body")

    def handle(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200, headers={"content-type": "application/json"}, stream=BrokenStream()
        )

    evaluator = QwenChatSemanticEvaluatorV2(
        api_key=KEY, endpoint=ENDPOINT, transport=httpx.MockTransport(handle)
    )
    journal = Journal()
    port = DurableQwenSemanticEvaluationPortV2(
        evaluator=evaluator, journal=journal, stage1_receipts=Stage1Store(receipt)
    )
    try:
        with pytest.raises(SemanticCachePortError) as caught:
            port.evaluate_v2(request)
        assert caught.value.code is SemanticCachePortErrorCode.CACHED_FAILURE
        assert calls == 1
        assert [event.event_kind for event in journal.events] == ["START", "TERMINAL"]
        with pytest.raises(SemanticCachePortError):
            port.evaluate_v2(request)
        assert calls == 1
    finally:
        evaluator.close()


@pytest.mark.allow_hosts(["127.0.0.1", "::1"])
def test_qwen_cache_retries_only_complete_retryable_status() -> None:
    _, request, _, receipt = _request_and_receipt()
    calls = 0

    def handle(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(
                429,
                headers={"content-type": "application/json"},
                content=b'{"error":{"code":"rate_limited"}}',
            )
        return httpx.Response(
            200, headers={"content-type": "application/json"}, content=_envelope()
        )

    evaluator = QwenChatSemanticEvaluatorV2(
        api_key=KEY, endpoint=ENDPOINT, transport=httpx.MockTransport(handle)
    )
    journal = Journal()
    port = DurableQwenSemanticEvaluationPortV2(
        evaluator=evaluator,
        journal=journal,
        stage1_receipts=Stage1Store(receipt),
        sleeper=lambda _: None,
    )
    try:
        assert port.evaluate_v2(request).method == QWEN_SEMANTIC_V2_PROVIDER_METHOD
        assert calls == 2
        assert [(event.attempt_ordinal, event.event_kind) for event in journal.events] == [
            (1, "START"),
            (1, "RAW"),
            (1, "TERMINAL"),
            (2, "START"),
            (2, "RAW"),
            (2, "RESULT"),
            (2, "TERMINAL"),
        ]
    finally:
        evaluator.close()


@pytest.mark.allow_hosts(["127.0.0.1", "::1"])
def test_qwen_cache_unknown_after_start_does_not_resend() -> None:
    _, request, _, receipt = _request_and_receipt()
    calls = 0

    def handle(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200, headers={"content-type": "application/json"}, content=_envelope()
        )

    evaluator = QwenChatSemanticEvaluatorV2(
        api_key=KEY, endpoint=ENDPOINT, transport=httpx.MockTransport(handle)
    )
    journal = Journal(fail_kind="TERMINAL")
    port = DurableQwenSemanticEvaluationPortV2(
        evaluator=evaluator, journal=journal, stage1_receipts=Stage1Store(receipt)
    )
    try:
        with pytest.raises(RuntimeError):
            port.evaluate_v2(request)
        assert calls == 1
        assert [event.event_kind for event in journal.events] == ["START", "RAW", "RESULT"]
        with pytest.raises(SemanticCachePortError) as caught:
            port.evaluate_v2(request)
        assert caught.value.code is SemanticCachePortErrorCode.UNKNOWN_AFTER_START
        assert calls == 1
    finally:
        evaluator.close()
