"""Immutable planned-registry bytes and context binding without source calls."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from pydantic import ValidationError
from tests.unit.tools.test_report_validation import _empty_request, _v2_request

from medevidence.infrastructure.validation_registry_store import (
    SnapshotValidationRegistryStore,
    ValidationRegistryStoreError,
)
from medevidence.ingestion.snapshots import SnapshotStore
from medevidence.orchestration.contracts import RuntimeContext, ValidationRegistryRef
from medevidence.tools.report_validation import (
    M3_SEMANTIC_EVALUATION_V2,
    M3_STAGE2_SEMANTIC_PROVIDER_METHOD_V2,
    M3_VALIDATION_CONFIGURATION_V2,
    CitationRelationship,
    EvaluatorIdentityInput,
    PlannedStage2SemanticInputV2,
    SemanticSupport,
)


def _case(tmp_path: Path):
    request, _, projections = _v2_request(
        (CitationRelationship.SUPPORTS,), (SemanticSupport.SUPPORTED,)
    )
    registry = replace(
        request.registry,
        semantic_expectations=tuple(
            PlannedStage2SemanticInputV2(
                item.citation_id, item.input_digest, item.method, item.version
            )
            for item in projections
        ),
    )
    context = RuntimeContext(
        run_id=request.run_id, report_id=request.report_id, scope_id=request.scope.scope_id
    )
    snapshots = SnapshotStore(tmp_path / "snapshots", free_bytes=lambda _: 20_000_000_000)
    store = SnapshotValidationRegistryStore(snapshots)
    return request, registry, context, snapshots, store


def test_publish_and_replay_exact_planned_registry(tmp_path: Path) -> None:
    request, registry, context, _, store = _case(tmp_path)
    ref = store.publish_registry(
        context=context,
        report_content_hash=request.synthesis.report_content_hash,
        registry=registry,
    )
    assert ref.registry_id.startswith("validation-registry:sha256:")
    assert store.load_registry(ref) == registry
    assert (
        store.publish_registry(
            context=context,
            report_content_hash=request.synthesis.report_content_hash,
            registry=registry,
        )
        == ref
    )


def test_wrong_context_and_finalized_projection_cannot_be_published(tmp_path: Path) -> None:
    request, registry, context, _, store = _case(tmp_path)
    foreign = RuntimeContext(
        run_id="run:aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        report_id=context.report_id,
        scope_id=context.scope_id,
    )
    with pytest.raises(ValidationRegistryStoreError):
        store.publish_registry(
            context=foreign,
            report_content_hash=request.synthesis.report_content_hash,
            registry=registry,
        )
    with pytest.raises(ValidationRegistryStoreError):
        store.publish_registry(
            context=context,
            report_content_hash=request.synthesis.report_content_hash,
            registry=request.registry,
        )


def test_tampered_missing_and_symlink_registry_bytes_fail_closed(tmp_path: Path) -> None:
    request, registry, context, snapshots, store = _case(tmp_path)
    ref = store.publish_registry(
        context=context,
        report_content_hash=request.synthesis.report_content_hash,
        registry=registry,
    )
    digest = ref.registry_content_hash.removeprefix("sha256:")
    target = (
        snapshots.root / "m3" / "validation-registry" / "sha256" / digest[:2] / f"{digest}.json"
    )
    original = target.read_bytes()
    target.write_bytes(original.replace(b"pubmed", b"faersx", 1))
    with pytest.raises(ValidationRegistryStoreError):
        store.load_registry(ref)
    target.write_bytes(original)
    target.unlink()
    with pytest.raises(ValidationRegistryStoreError):
        store.load_registry(ref)
    target.write_bytes(original)
    backup = target.with_name("held-registry.json")
    target.rename(backup)
    try:
        target.symlink_to(backup)
    except OSError:
        pytest.skip("local host cannot create an unprivileged file symlink")
    with pytest.raises(ValidationRegistryStoreError):
        store.load_registry(ref)


def test_reference_hash_identity_and_foreign_run_fail_closed(tmp_path: Path) -> None:
    request, registry, context, _, store = _case(tmp_path)
    ref = store.publish_registry(
        context=context,
        report_content_hash=request.synthesis.report_content_hash,
        registry=registry,
    )
    with pytest.raises(ValidationError):
        ValidationRegistryRef.model_validate(
            {**ref.model_dump(mode="python"), "registry_content_hash": "sha256:" + "0" * 64},
            strict=True,
        )
    altered = ref.model_copy(update={"run_id": "run:aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"})
    with pytest.raises(ValidationRegistryStoreError):
        store.load_registry(altered)


def test_empty_no_result_registry_is_a_valid_explicit_pre_semantic_plan(tmp_path: Path) -> None:
    request = _empty_request()
    registry = replace(
        request.registry,
        evaluator_identity=EvaluatorIdentityInput(
            M3_STAGE2_SEMANTIC_PROVIDER_METHOD_V2, M3_SEMANTIC_EVALUATION_V2
        ),
        configuration_version=M3_VALIDATION_CONFIGURATION_V2,
        semantic_expectations=(),
    )
    context = RuntimeContext(
        run_id=request.run_id, report_id=request.report_id, scope_id=request.scope.scope_id
    )
    store = SnapshotValidationRegistryStore(
        SnapshotStore(tmp_path / "empty", free_bytes=lambda _: 20_000_000_000)
    )
    reference = store.publish_registry(
        context=context,
        report_content_hash=request.synthesis.report_content_hash,
        registry=registry,
    )
    assert store.load_registry(reference) == registry


def test_registry_growth_after_hash_verification_cannot_trigger_unbounded_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request, registry, context, snapshots, store = _case(tmp_path)
    ref = store.publish_registry(
        context=context,
        report_content_hash=request.synthesis.report_content_hash,
        registry=registry,
    )
    digest = ref.registry_content_hash.removeprefix("sha256:")
    target = (
        snapshots.root / "m3" / "validation-registry" / "sha256" / digest[:2] / f"{digest}.json"
    )
    original_verify = SnapshotStore._verify_file
    original_read = Path.read_bytes

    def verified_then_grows(self, path, *args, **kwargs):
        result = original_verify(self, path, *args, **kwargs)
        if path == target:
            path.write_bytes(b"x" * 2_097_253)
        return result

    def prohibit_unbounded_read(path: Path) -> bytes:
        if path == target:
            pytest.fail("registry read must be bounded at the file handle")
        return original_read(path)

    monkeypatch.setattr(SnapshotStore, "_verify_file", verified_then_grows)
    monkeypatch.setattr(Path, "read_bytes", prohibit_unbounded_read)
    with pytest.raises(ValidationRegistryStoreError):
        store.load_registry(ref)
