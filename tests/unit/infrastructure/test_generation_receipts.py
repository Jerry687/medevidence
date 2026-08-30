"""Adversarial tests for exact immutable generation receipt persistence."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

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
from medevidence.infrastructure.generation_receipts import GenerationReceiptStore
from medevidence.ingestion.snapshots import (
    INITIAL_FREE_SPACE_FLOOR_BYTES,
    SnapshotIntegrityError,
    SnapshotStore,
)
from medevidence.tools.generation import (
    GenerationCandidate,
    GenerationInput,
    GenerationProviderResult,
    GenerationReceipt,
    GenerationReceiptRef,
    GenerationSourceContext,
    GenerationUsage,
    build_generation_receipt,
    generation_receipt_bytes,
    generation_receipt_ref,
)

RUN_ID = "run:12345678-1234-4234-9234-123456789abc"
SCOPE_ID = "scope:sha256:" + "a" * 64


def _receipt(*, zdr_active: bool | None = None):
    outcome = SourceOutcome(
        source=SourceType.PUBMED,
        query_id="query-pubmed",
        execution_status=ExecutionStatus.SUCCEEDED,
        coverage_status=CoverageStatus.COMPLETE,
        result_status=ResultStatus.NO_MATCH,
        configured_bounds=ExecutionBounds(
            max_query_characters=100,
            max_pages=5,
            max_records=100,
            max_payload_bytes=100_000,
            max_total_seconds=30,
        ),
        valid_result_count=0,
        pages_completed=1,
        truncated=False,
        warning_codes=(),
    )
    generation_input = GenerationInput(
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
        evidence=(),
        comparisons=(),
        conflicts=(),
    )
    now = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)
    provider_result = GenerationProviderResult(
        candidate=GenerationCandidate(
            source_context_ids=tuple(item.context_id for item in generation_input.source_contexts),
            visible_comparison_ids=(),
            visible_conflict_ids=(),
            claims=(),
        ),
        request_hash="sha256:" + "c" * 64,
        response_hash="sha256:" + "d" * 64,
        provider_response_id="resp_receipt_test",
        attempts=1,
        usage=GenerationUsage(
            input_tokens=10,
            output_tokens=5,
            total_tokens=15,
            cached_input_tokens=0,
            reasoning_output_tokens=1,
        ),
        started_at_utc=now,
        completed_at_utc=now,
    )
    return build_generation_receipt(generation_input, provider_result, zdr_active=zdr_active)


def _adapter(tmp_path: Path) -> GenerationReceiptStore:
    store = SnapshotStore(
        tmp_path / "snapshots",
        free_bytes=lambda _path: INITIAL_FREE_SPACE_FLOOR_BYTES,
    )
    return GenerationReceiptStore(store)


def test_save_reloads_exact_canonical_receipt_and_reuses_immutable_bytes(
    tmp_path: Path,
) -> None:
    adapter = _adapter(tmp_path)
    receipt = _receipt(zdr_active=True)

    first = adapter.save(receipt)
    second = adapter.save(receipt)

    assert first == second == generation_receipt_ref(receipt)
    assert adapter.load(first) == receipt
    digest = receipt.receipt_id.removeprefix("generation-receipt:sha256:")
    target = (
        tmp_path
        / "snapshots"
        / "journal"
        / "12345678-1234-4234-9234-123456789abc"
        / "generation"
        / f"{digest}.json"
    )
    assert target.read_bytes() == generation_receipt_bytes(receipt)


def test_load_rejects_missing_substituted_stale_and_foreign_references(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)
    receipt = _receipt()
    exact_ref = adapter.save(receipt)

    variants = (
        exact_ref.model_copy(update={"receipt_content_hash": "sha256:" + "1" * 64}),
        exact_ref.model_copy(update={"candidate_hash": "sha256:" + "2" * 64}),
        exact_ref.model_copy(update={"scope_id": "scope:sha256:" + "3" * 64}),
    )
    for reference in variants:
        with pytest.raises(SnapshotIntegrityError, match="binding mismatch"):
            adapter.load(reference)
    missing = GenerationReceiptRef(
        receipt_id="generation-receipt:sha256:" + "4" * 64,
        receipt_content_hash="sha256:" + "5" * 64,
        run_id=RUN_ID,
        scope_id=SCOPE_ID,
        candidate_hash="sha256:" + "6" * 64,
    )
    with pytest.raises(SnapshotIntegrityError, match="missing"):
        adapter.load(missing)


def test_tamper_collision_and_instance_shadowing_fail_closed(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)
    receipt = _receipt()
    reference = adapter.save(receipt)
    digest = reference.receipt_id.removeprefix("generation-receipt:sha256:")
    target = (
        tmp_path
        / "snapshots"
        / "journal"
        / "12345678-1234-4234-9234-123456789abc"
        / "generation"
        / f"{digest}.json"
    )
    raw = target.read_bytes()
    target.write_bytes(b"x" + raw[1:])

    with pytest.raises(SnapshotIntegrityError, match="bytes failed validation"):
        adapter.load(reference)
    with pytest.raises(SnapshotIntegrityError, match="published bytes"):
        adapter.save(receipt)
    for name in ("save", "load", "_validated_reference", "_store"):
        with pytest.raises(AttributeError, match="frozen"):
            setattr(adapter, name, object())
    assert not hasattr(adapter, "__dict__")


def test_receipt_store_rejects_subclass_behavior(tmp_path: Path) -> None:
    class _ForeignReceipt(GenerationReceipt):
        pass

    adapter = _adapter(tmp_path)
    receipt = _receipt()
    foreign = _ForeignReceipt.model_validate(receipt.model_dump(mode="python"))

    with pytest.raises(SnapshotIntegrityError, match="failed reconstruction"):
        adapter.save(foreign)


def test_corrupted_receipt_secret_is_absent_from_public_exception_graph(
    tmp_path: Path,
) -> None:
    secret = "UNIQUE_SECRET_CORRUPTED_RECEIPT_83A71D"
    adapter = _adapter(tmp_path)
    receipt = _receipt()
    reference = adapter.save(receipt)
    digest = reference.receipt_id.removeprefix("generation-receipt:sha256:")
    target = (
        tmp_path
        / "snapshots"
        / "journal"
        / "12345678-1234-4234-9234-123456789abc"
        / "generation"
        / f"{digest}.json"
    )
    target.write_bytes((f'{{"marker":"{secret}"}}').encode())

    with pytest.raises(SnapshotIntegrityError, match="bytes failed validation") as captured:
        adapter.load(reference)

    pending: list[BaseException] = [captured.value]
    visited: set[int] = set()
    rendered: list[str] = []
    while pending:
        error = pending.pop()
        if id(error) in visited:
            continue
        visited.add(id(error))
        rendered.extend((str(error), repr(error), repr(error.args)))
        if error.__cause__ is not None:
            pending.append(error.__cause__)
        if error.__context__ is not None:
            pending.append(error.__context__)
    assert secret not in "\n".join(rendered)
    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None


def test_exact_receipt_model_dump_shadow_fails_before_publish(tmp_path: Path) -> None:
    marker = "RECEIPT_MODEL_DUMP_SHADOW_SECRET_6A28"
    calls = 0

    def shadow(*_args: object, **_kwargs: object) -> object:
        nonlocal calls
        calls += 1
        raise RuntimeError(marker)

    adapter = _adapter(tmp_path)
    receipt = _receipt()
    object.__setattr__(receipt, "model_dump", shadow)

    with pytest.raises(SnapshotIntegrityError, match="failed reconstruction") as captured:
        adapter.save(receipt)

    assert calls == 0
    assert marker not in repr(captured.value)
    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None
    assert not (tmp_path / "snapshots" / "journal").exists()


def test_nested_receipt_usage_poison_fails_before_publish_or_read(tmp_path: Path) -> None:
    marker = "NESTED_RECEIPT_USAGE_POISON_SECRET_195B"
    calls = 0

    def shadow(*_args: object, **_kwargs: object) -> object:
        nonlocal calls
        calls += 1
        raise RuntimeError(marker)

    adapter = _adapter(tmp_path)
    receipt = _receipt()
    object.__setattr__(receipt.usage, "model_dump", shadow)

    with pytest.raises(SnapshotIntegrityError, match="failed reconstruction") as captured:
        adapter.save(receipt)

    assert calls == 0
    assert marker not in repr(captured.value)
    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None
    assert not (tmp_path / "snapshots" / "journal").exists()


def test_exact_reference_model_dump_shadow_fails_before_read(tmp_path: Path) -> None:
    marker = "REFERENCE_MODEL_DUMP_SHADOW_SECRET_43D1"
    calls = 0

    def shadow(*_args: object, **_kwargs: object) -> object:
        nonlocal calls
        calls += 1
        raise RuntimeError(marker)

    adapter = _adapter(tmp_path)
    receipt = _receipt()
    reference = adapter.save(receipt)
    digest = reference.receipt_id.removeprefix("generation-receipt:sha256:")
    target = (
        tmp_path
        / "snapshots"
        / "journal"
        / "12345678-1234-4234-9234-123456789abc"
        / "generation"
        / f"{digest}.json"
    )
    target.unlink()
    object.__setattr__(reference, "model_dump", shadow)

    with pytest.raises(SnapshotIntegrityError, match="reference is invalid") as captured:
        adapter.load(reference)

    assert calls == 0
    assert marker not in repr(captured.value)
    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None
