"""Fail-closed tests for durable provider-neutral generation service."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime

import pytest

from medevidence.domain import (
    CoverageStatus,
    ExecutionBounds,
    ExecutionStatus,
    M1BSourcePlanEntryV1,
    PlanningStatus,
    ResultStatus,
    SourceOutcome,
    SourceType,
)
from medevidence.tools.generation import (
    CandidateCitation,
    CandidateCitationRelationship,
    CandidateClaim,
    CandidateClaimClass,
    CandidateInferenceUse,
    GenerationCandidate,
    GenerationEvidence,
    GenerationGatewayError,
    GenerationInput,
    GenerationProviderResult,
    GenerationReceipt,
    GenerationReceiptRef,
    GenerationSourceContext,
    GenerationUsage,
    build_generation_receipt,
    generation_receipt_ref,
)
from medevidence.tools.generation_service import (
    GenerationService,
    GenerationServiceError,
    GenerationServiceErrorCode,
)

RUN_ID = "run:12345678-1234-4234-9234-123456789abc"
SCOPE_ID = "scope:sha256:" + "a" * 64
EVIDENCE_ID = "evidence:sha256:" + "c" * 64


def _input() -> GenerationInput:
    outcome = SourceOutcome(
        source=SourceType.PUBMED,
        query_id="query-pubmed",
        execution_status=ExecutionStatus.SUCCEEDED,
        coverage_status=CoverageStatus.COMPLETE,
        result_status=ResultStatus.MATCHES,
        configured_bounds=ExecutionBounds(
            max_query_characters=100,
            max_pages=5,
            max_records=100,
            max_payload_bytes=100_000,
            max_total_seconds=30,
        ),
        valid_result_count=1,
        pages_completed=1,
        truncated=False,
        warning_codes=(),
    )
    return GenerationInput(
        run_id=RUN_ID,
        scope_id=SCOPE_ID,
        research_question="What does the supplied evidence report?",
        selected_sources=(SourceType.PUBMED,),
        source_plan=(
            M1BSourcePlanEntryV1(
                source=SourceType.PUBMED,
                planning_status=PlanningStatus.SELECTED,
            ),
        ),
        source_contexts=(
            GenerationSourceContext.create(
                run_id=RUN_ID,
                source=SourceType.PUBMED,
                outcome=outcome,
                limitation_ids=(),
            ),
        ),
        evidence=(
            GenerationEvidence.create(
                evidence_id=EVIDENCE_ID,
                run_id=RUN_ID,
                source=SourceType.PUBMED,
                source_record_id="record-1",
                source_version="source-version-1",
                snapshot_id="snapshot-1",
                content_hash="sha256:" + "d" * 64,
                locators=("abstract:0-20",),
                permitted_claim_classes=(CandidateClaimClass.DESCRIPTIVE,),
                permitted_inference_uses=(CandidateInferenceUse.DESCRIPTIVE,),
                excerpt="A bounded public research excerpt.",
            ),
        ),
        comparisons=(),
        conflicts=(),
    )


def _provider_result() -> GenerationProviderResult:
    generation_input = _input()
    candidate = GenerationCandidate(
        source_context_ids=tuple(item.context_id for item in generation_input.source_contexts),
        visible_comparison_ids=(),
        visible_conflict_ids=(),
        claims=(
            CandidateClaim(
                ordinal=1,
                source=SourceType.PUBMED,
                statement="The cited source reports a bounded observation.",
                claim_class=CandidateClaimClass.DESCRIPTIVE,
                inference_use=CandidateInferenceUse.DESCRIPTIVE,
                citations=(
                    CandidateCitation(
                        evidence_id=EVIDENCE_ID,
                        relationship=CandidateCitationRelationship.SUPPORTS,
                    ),
                ),
                presented_limitation_ids=(),
                conflict_ids=(),
            ),
        ),
    )
    now = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)
    return GenerationProviderResult(
        candidate=candidate,
        request_hash="sha256:" + "e" * 64,
        response_hash="sha256:" + "f" * 64,
        provider_response_id="resp_service_test",
        attempts=1,
        usage=GenerationUsage(
            input_tokens=20,
            output_tokens=10,
            total_tokens=30,
            cached_input_tokens=0,
            reasoning_output_tokens=2,
        ),
        started_at_utc=now,
        completed_at_utc=now,
    )


def _assert_redacted_service_error(
    error: GenerationServiceError,
    *,
    code: GenerationServiceErrorCode,
    markers: tuple[str, ...],
) -> None:
    assert error.code is code
    pending: list[BaseException] = [error]
    visited: set[int] = set()
    rendered: list[str] = []
    while pending:
        current = pending.pop()
        if id(current) in visited:
            continue
        visited.add(id(current))
        rendered.extend((str(current), repr(current), repr(current.args)))
        if current.__cause__ is not None:
            pending.append(current.__cause__)
        if current.__context__ is not None:
            pending.append(current.__context__)
    surface = "\n".join(rendered)
    assert all(marker not in surface for marker in markers)
    assert error.__cause__ is None
    assert error.__context__ is None


class _Gateway:
    def __init__(self, result: GenerationProviderResult) -> None:
        self.result = result
        self.calls = 0

    def generate(self, generation_input: GenerationInput) -> GenerationProviderResult:
        assert generation_input == _input()
        self.calls += 1
        return self.result


class _FailingGateway:
    def __init__(self, error: Exception) -> None:
        self.error = error

    def generate(self, generation_input: GenerationInput) -> GenerationProviderResult:
        assert generation_input == _input()
        raise self.error


class _MaliciousGatewayError(GenerationGatewayError):
    __slots__ = ("status_code",)

    def __init__(self, code: str, marker: str) -> None:
        super().__init__(code)
        self.status_code = 599
        self.args = (code, marker)


class _PropertyGatewayError(GenerationGatewayError):
    calls = 0

    def __init__(self, marker: str) -> None:
        RuntimeError.__init__(self, marker)

    @property
    def code(self) -> str:
        type(self).calls += 1
        return "provider_unavailable"


class _EvilTuple(tuple[object, ...]):
    behavior = 0

    def __iter__(self) -> Iterator[object]:
        type(self).behavior += 1
        raise RuntimeError("EVIL_TUPLE_BEHAVIOR_SECRET_2D7A")


class _ReceiptStore:
    def __init__(self) -> None:
        self.receipt: GenerationReceipt | None = None
        self.saved = 0
        self.loaded = 0
        self.save_error: Exception | None = None
        self.load_override: GenerationReceipt | None = None
        self.reference_override: GenerationReceiptRef | None = None

    def save(self, receipt: GenerationReceipt) -> GenerationReceiptRef:
        self.saved += 1
        if self.save_error is not None:
            raise self.save_error
        self.receipt = receipt
        return self.reference_override or generation_receipt_ref(receipt)

    def load(self, reference: GenerationReceiptRef) -> GenerationReceipt:
        self.loaded += 1
        assert self.receipt is not None
        assert reference == generation_receipt_ref(self.receipt)
        return self.load_override or self.receipt


def test_service_returns_only_after_exact_receipt_round_trip_and_binds_zdr() -> None:
    gateway = _Gateway(_provider_result())
    receipts = _ReceiptStore()
    service = GenerationService(gateway=gateway, receipts=receipts, zdr_active=True)

    result = service.generate(_input())

    assert result.candidate == gateway.result.candidate
    assert receipts.receipt is not None
    assert receipts.receipt.zdr_active is True
    assert result.receipt_ref == generation_receipt_ref(receipts.receipt)
    assert (gateway.calls, receipts.saved, receipts.loaded) == (1, 1, 1)


def test_already_redacted_typed_provider_failure_is_preserved() -> None:
    marker = "GATEWAY_BASE_ARGS_SECRET_7B02"
    failure = GenerationGatewayError("provider_unavailable")
    failure.args = (failure.code, marker)
    receipts = _ReceiptStore()
    service = GenerationService(
        gateway=_FailingGateway(failure),
        receipts=receipts,
        zdr_active=None,
    )

    with pytest.raises(GenerationGatewayError) as captured:
        service.generate(_input())

    assert captured.value is not failure
    assert type(captured.value) is GenerationGatewayError
    assert captured.value.code == failure.code
    assert captured.value.args == (failure.code,)
    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None
    assert marker not in repr(captured.value)
    assert (receipts.saved, receipts.loaded) == (0, 0)


def test_typed_gateway_error_subtype_maps_generic_and_discards_args_and_chain() -> None:
    marker = "GATEWAY_TYPED_SECRET_80D31"
    try:
        raise RuntimeError(marker)
    except RuntimeError:
        try:
            raise _MaliciousGatewayError("provider_unavailable", marker)
        except _MaliciousGatewayError as caught:
            failure = caught
    assert failure.__context__ is not None
    receipts = _ReceiptStore()
    service = GenerationService(
        gateway=_FailingGateway(failure),
        receipts=receipts,
        zdr_active=None,
    )

    with pytest.raises(GenerationServiceError) as captured:
        service.generate(_input())

    assert captured.value is not failure
    assert captured.value.code is GenerationServiceErrorCode.GATEWAY_EXECUTION_INVALID
    pending: list[BaseException] = [captured.value]
    rendered: list[str] = []
    while pending:
        current = pending.pop()
        rendered.extend((str(current), repr(current), repr(current.args)))
        if current.__cause__ is not None:
            pending.append(current.__cause__)
        if current.__context__ is not None:
            pending.append(current.__context__)
    assert marker not in "\n".join(rendered)
    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None
    assert (receipts.saved, receipts.loaded) == (0, 0)


def test_gateway_error_subtype_code_property_is_never_invoked() -> None:
    marker = "GATEWAY_PROPERTY_SECRET_4F819"
    _PropertyGatewayError.calls = 0
    failure = _PropertyGatewayError(marker)
    receipts = _ReceiptStore()
    service = GenerationService(
        gateway=_FailingGateway(failure),
        receipts=receipts,
        zdr_active=None,
    )

    with pytest.raises(GenerationServiceError) as captured:
        service.generate(_input())

    _assert_redacted_service_error(
        captured.value,
        code=GenerationServiceErrorCode.GATEWAY_EXECUTION_INVALID,
        markers=(marker,),
    )
    assert _PropertyGatewayError.calls == 0
    assert (receipts.saved, receipts.loaded) == (0, 0)


@pytest.mark.parametrize("delete_code", [False, True])
def test_exact_gateway_error_mutated_or_deleted_slot_is_sanitized(delete_code: bool) -> None:
    marker = "GATEWAY_SLOT_SECRET_1A49"
    failure = GenerationGatewayError("provider_unavailable")
    if delete_code:
        object.__delattr__(failure, "code")
    else:
        object.__setattr__(failure, "code", marker)
    failure.args = (marker,)
    receipts = _ReceiptStore()
    service = GenerationService(
        gateway=_FailingGateway(failure),
        receipts=receipts,
        zdr_active=None,
    )

    with pytest.raises(GenerationServiceError) as captured:
        service.generate(_input())

    _assert_redacted_service_error(
        captured.value,
        code=GenerationServiceErrorCode.GATEWAY_EXECUTION_INVALID,
        markers=(marker,),
    )
    assert (receipts.saved, receipts.loaded) == (0, 0)


def test_arbitrary_gateway_exception_is_redacted_and_has_zero_store_effects() -> None:
    marker = "GATEWAY_SECRET_4217F"
    failure = ValueError(marker, {"raw": marker})
    receipts = _ReceiptStore()
    service = GenerationService(
        gateway=_FailingGateway(failure),
        receipts=receipts,
        zdr_active=None,
    )

    with pytest.raises(GenerationServiceError) as captured:
        service.generate(_input())

    _assert_redacted_service_error(
        captured.value,
        code=GenerationServiceErrorCode.GATEWAY_EXECUTION_INVALID,
        markers=(marker,),
    )
    assert (receipts.saved, receipts.loaded) == (0, 0)


def test_service_fails_closed_when_save_fails_or_returns_foreign_reference() -> None:
    gateway = _Gateway(_provider_result())
    receipts = _ReceiptStore()
    receipts.save_error = RuntimeError("storage unavailable")
    service = GenerationService(gateway=gateway, receipts=receipts, zdr_active=None)
    with pytest.raises(GenerationServiceError) as save_failure:
        service.generate(_input())
    _assert_redacted_service_error(
        save_failure.value,
        code=GenerationServiceErrorCode.RECEIPT_STORE_INVALID,
        markers=("storage unavailable",),
    )
    assert receipts.loaded == 0

    receipts.save_error = None
    receipts.reference_override = GenerationReceiptRef(
        receipt_id="generation-receipt:sha256:" + "1" * 64,
        receipt_content_hash="sha256:" + "2" * 64,
        run_id=RUN_ID,
        scope_id=SCOPE_ID,
        candidate_hash="sha256:" + "3" * 64,
    )
    with pytest.raises(GenerationServiceError) as reference_failure:
        service.generate(_input())
    _assert_redacted_service_error(
        reference_failure.value,
        code=GenerationServiceErrorCode.RECEIPT_STORE_INVALID,
        markers=("mismatched reference",),
    )
    assert receipts.loaded == 0


def test_service_rejects_stale_reloaded_receipt_and_instance_shadowing() -> None:
    result = _provider_result()
    gateway = _Gateway(result)
    receipts = _ReceiptStore()
    receipts.load_override = build_generation_receipt(_input(), result, zdr_active=False)
    service = GenerationService(gateway=gateway, receipts=receipts, zdr_active=True)

    with pytest.raises(GenerationServiceError) as replay_failure:
        service.generate(_input())
    _assert_redacted_service_error(
        replay_failure.value,
        code=GenerationServiceErrorCode.RECEIPT_STORE_INVALID,
        markers=("changed its exact reference",),
    )
    for name in ("generate", "_gateway", "_receipts", "_zdr_active"):
        with pytest.raises(AttributeError, match="frozen"):
            setattr(service, name, object())
    assert not hasattr(service, "__dict__")


def test_invalid_exact_input_never_leaks_research_or_secret_markers() -> None:
    research_marker = "PRIVATE_RESEARCH_QUESTION_MARKER_76A1"
    evidence_marker = "PRIVATE_EVIDENCE_MARKER_11B9"
    valid = _input()
    invalid = GenerationInput.model_construct(
        schema_version=valid.schema_version,
        run_id=valid.run_id,
        scope_id=research_marker,
        research_question=evidence_marker,
        selected_sources=valid.selected_sources,
        source_plan=valid.source_plan,
        source_contexts=valid.source_contexts,
        evidence=valid.evidence,
        comparisons=valid.comparisons,
        conflicts=valid.conflicts,
    )
    gateway = _Gateway(_provider_result())
    receipts = _ReceiptStore()
    service = GenerationService(gateway=gateway, receipts=receipts, zdr_active=None)

    with pytest.raises(GenerationServiceError) as captured:
        service.generate(invalid)

    _assert_redacted_service_error(
        captured.value,
        code=GenerationServiceErrorCode.INPUT_INVALID,
        markers=(research_marker, evidence_marker),
    )
    assert (gateway.calls, receipts.saved, receipts.loaded) == (0, 0, 0)


def test_exact_input_model_dump_shadow_is_rejected_without_invocation_or_effect() -> None:
    marker = "INPUT_MODEL_DUMP_SHADOW_SECRET_6E2B"
    calls = 0

    def shadow(*_args: object, **_kwargs: object) -> object:
        nonlocal calls
        calls += 1
        raise RuntimeError(marker)

    generation_input = _input()
    object.__setattr__(generation_input, "model_dump", shadow)
    gateway = _Gateway(_provider_result())
    receipts = _ReceiptStore()
    service = GenerationService(gateway=gateway, receipts=receipts, zdr_active=None)

    with pytest.raises(GenerationServiceError) as captured:
        service.generate(generation_input)

    _assert_redacted_service_error(
        captured.value,
        code=GenerationServiceErrorCode.INPUT_INVALID,
        markers=(marker,),
    )
    assert calls == 0
    assert (gateway.calls, receipts.saved, receipts.loaded) == (0, 0, 0)


def test_nested_input_poison_rejects_before_gateway_or_store() -> None:
    marker = "NESTED_INPUT_POISON_SECRET_8D40"
    calls = 0

    def shadow(*_args: object, **_kwargs: object) -> object:
        nonlocal calls
        calls += 1
        raise RuntimeError(marker)

    generation_input = _input()
    object.__setattr__(generation_input.evidence[0], "model_dump", shadow)
    gateway = _Gateway(_provider_result())
    receipts = _ReceiptStore()
    service = GenerationService(gateway=gateway, receipts=receipts, zdr_active=None)

    with pytest.raises(GenerationServiceError) as captured:
        service.generate(generation_input)

    _assert_redacted_service_error(
        captured.value,
        code=GenerationServiceErrorCode.INPUT_INVALID,
        markers=(marker,),
    )
    assert calls == 0
    assert (gateway.calls, receipts.saved, receipts.loaded) == (0, 0, 0)


def test_evil_tuple_rejects_before_iteration_gateway_or_store() -> None:
    _EvilTuple.behavior = 0
    generation_input = _input()
    object.__setattr__(
        generation_input,
        "selected_sources",
        _EvilTuple(generation_input.selected_sources),
    )
    gateway = _Gateway(_provider_result())
    receipts = _ReceiptStore()
    service = GenerationService(gateway=gateway, receipts=receipts, zdr_active=None)

    with pytest.raises(GenerationServiceError) as captured:
        service.generate(generation_input)

    _assert_redacted_service_error(
        captured.value,
        code=GenerationServiceErrorCode.INPUT_INVALID,
        markers=("EVIL_TUPLE_BEHAVIOR_SECRET_2D7A",),
    )
    assert _EvilTuple.behavior == 0
    assert (gateway.calls, receipts.saved, receipts.loaded) == (0, 0, 0)


def test_malicious_exact_provider_result_never_leaks_candidate_marker() -> None:
    candidate_marker = "PRIVATE_CANDIDATE_SECRET_MARKER_924C"
    valid_result = _provider_result()
    valid_candidate = valid_result.candidate
    valid_claim = valid_candidate.claims[0]
    malicious_claim = CandidateClaim.model_construct(
        ordinal=2,
        source=valid_claim.source,
        statement=candidate_marker,
        claim_class=valid_claim.claim_class,
        inference_use=valid_claim.inference_use,
        citations=valid_claim.citations,
        presented_limitation_ids=valid_claim.presented_limitation_ids,
        conflict_ids=valid_claim.conflict_ids,
    )
    malicious_candidate = GenerationCandidate.model_construct(
        schema_version=valid_candidate.schema_version,
        source_context_ids=valid_candidate.source_context_ids,
        visible_comparison_ids=valid_candidate.visible_comparison_ids,
        visible_conflict_ids=valid_candidate.visible_conflict_ids,
        claims=(malicious_claim,),
    )
    malicious_result = GenerationProviderResult.model_construct(
        candidate=malicious_candidate,
        provider=valid_result.provider,
        model=valid_result.model,
        request_hash=valid_result.request_hash,
        response_hash=valid_result.response_hash,
        provider_response_id=valid_result.provider_response_id,
        attempts=valid_result.attempts,
        usage=valid_result.usage,
        started_at_utc=valid_result.started_at_utc,
        completed_at_utc=valid_result.completed_at_utc,
    )
    gateway = _Gateway(malicious_result)
    receipts = _ReceiptStore()
    service = GenerationService(gateway=gateway, receipts=receipts, zdr_active=None)

    with pytest.raises(GenerationServiceError) as captured:
        service.generate(_input())

    _assert_redacted_service_error(
        captured.value,
        code=GenerationServiceErrorCode.GATEWAY_RESULT_INVALID,
        markers=(candidate_marker,),
    )
    assert (gateway.calls, receipts.saved, receipts.loaded) == (1, 0, 0)


def test_exact_provider_result_model_dump_shadow_is_rejected_without_invocation() -> None:
    marker = "PROVIDER_MODEL_DUMP_SHADOW_SECRET_90C5"
    calls = 0

    def shadow(*_args: object, **_kwargs: object) -> object:
        nonlocal calls
        calls += 1
        raise RuntimeError(marker)

    provider_result = _provider_result()
    object.__setattr__(provider_result, "model_dump", shadow)
    gateway = _Gateway(provider_result)
    receipts = _ReceiptStore()
    service = GenerationService(gateway=gateway, receipts=receipts, zdr_active=None)

    with pytest.raises(GenerationServiceError) as captured:
        service.generate(_input())

    _assert_redacted_service_error(
        captured.value,
        code=GenerationServiceErrorCode.GATEWAY_RESULT_INVALID,
        markers=(marker,),
    )
    assert calls == 0
    assert (gateway.calls, receipts.saved, receipts.loaded) == (1, 0, 0)


def test_nested_provider_poison_rejects_before_receipt_store() -> None:
    marker = "NESTED_PROVIDER_POISON_SECRET_771E"
    calls = 0

    def shadow(*_args: object, **_kwargs: object) -> object:
        nonlocal calls
        calls += 1
        raise RuntimeError(marker)

    provider_result = _provider_result()
    object.__setattr__(provider_result.usage, "model_dump", shadow)
    gateway = _Gateway(provider_result)
    receipts = _ReceiptStore()
    service = GenerationService(gateway=gateway, receipts=receipts, zdr_active=None)

    with pytest.raises(GenerationServiceError) as captured:
        service.generate(_input())

    _assert_redacted_service_error(
        captured.value,
        code=GenerationServiceErrorCode.GATEWAY_RESULT_INVALID,
        markers=(marker,),
    )
    assert calls == 0
    assert (gateway.calls, receipts.saved, receipts.loaded) == (1, 0, 0)
