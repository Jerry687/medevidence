"""Replaceable local CADEC adapter with transient whole-document BM25 search."""

from __future__ import annotations

import hashlib
import math
from dataclasses import asdict
from pathlib import Path
from typing import final

from pydantic import ValidationError

from medevidence.connectors.cadec.loader import (
    CadecLoadError,
    _CadecAdmittedDocumentText,
    _load_cadec_archive_with_text,
)
from medevidence.domain import (
    CADEC_MANDATORY_LIMITATIONS,
    CoverageStatus,
    ExecutionBounds,
    ExecutionStatus,
    ResearchScope,
    ResultStatus,
    SourceOutcome,
    SourceType,
    derive_identity,
)
from medevidence.orchestration.contracts import (
    CollectedEvidenceResult,
    RequiredSourceOperation,
    SourceTaskAttemptRef,
    SourceTaskFailureRef,
    SourceTaskProgressResult,
    SourceTaskState,
    SourceTaskStatus,
)
from medevidence.orchestration.source_capabilities import (
    SourceCapabilities,
    collect_cadec_capability,
    plan_cadec_operations,
    terminal_source_task,
)
from medevidence.retrieval.core import BM25Index
from medevidence.tools.cadec_runtime import (
    CADEC_LIMITATION_WARNING,
    CadecDocumentEvidenceRef,
    CadecLocalSearchPlan,
    CadecRuntimeError,
    CadecRuntimeErrorCode,
    CadecSearchResult,
    CadecVerifiedCorpus,
    reconstruct_cadec_local_search_plan,
    reconstruct_cadec_search_result,
)


class _FrozenSlots:
    """Reject normal post-construction replacement of trusted composition fields."""

    __slots__ = ("_is_frozen",)

    def __setattr__(self, name: str, value: object) -> None:
        if getattr(self, "_is_frozen", False):
            raise AttributeError("canonical source composition fields are frozen")
        object.__setattr__(self, name, value)

    def _freeze(self) -> None:
        object.__setattr__(self, "_is_frozen", True)


@final
class CadecLocalSearchAdapter(_FrozenSlots):
    """Verify and search one explicitly configured approved local CADEC asset."""

    __slots__ = ("_archive_path", "_manifest_path")
    _archive_path: Path
    _manifest_path: Path

    def __init_subclass__(cls, **kwargs: object) -> None:
        del kwargs
        raise TypeError("CadecLocalSearchAdapter is a sealed infrastructure adapter")

    def __init__(self, *, archive_path: str | Path, manifest_path: str | Path) -> None:
        archive = Path(archive_path)
        manifest = Path(manifest_path)
        if not archive.is_absolute() or not manifest.is_absolute():
            raise ValueError("CADEC adapter paths must be explicit absolute paths")
        object.__setattr__(self, "_archive_path", archive)
        object.__setattr__(self, "_manifest_path", manifest)
        _FrozenSlots._freeze(self)

    def search(
        self,
        *,
        plan: CadecLocalSearchPlan,
        scope: ResearchScope,
    ) -> CadecSearchResult:
        """Verify, transiently score, and discard all exact admitted corpus text."""

        exact_plan = reconstruct_cadec_local_search_plan(plan, scope)
        try:
            loaded = _load_cadec_archive_with_text(self._archive_path, self._manifest_path)
        except CadecLoadError as error:
            raise CadecRuntimeError(
                CadecRuntimeErrorCode.ASSET_INTEGRITY,
                "exact CADEC archive or manifest admission failed",
            ) from error

        try:
            if tuple(item.document for item in loaded.document_texts) != (
                loaded.admitted.documents
            ):
                raise CadecRuntimeError(
                    CadecRuntimeErrorCode.MATERIALIZATION,
                    "CADEC transient handoff differs from exact admitted document metadata",
                )
            verification = CadecVerifiedCorpus.model_validate(
                asdict(loaded.admitted.verification), strict=True
            )
            eligible = _validate_transient_documents(
                loaded.document_texts,
                expected_count=verification.approved_document_count,
            )
            ranked = _score_all_eligible(eligible, exact_plan)
            references = tuple(_evidence_ref(document, score) for document, score in ranked)
            outcome = SourceOutcome(
                source=SourceType.CADEC,
                query_id=exact_plan.query_id,
                execution_status=ExecutionStatus.SUCCEEDED,
                coverage_status=CoverageStatus.COMPLETE,
                result_status=ResultStatus.MATCHES if references else ResultStatus.NO_MATCH,
                configured_bounds=ExecutionBounds.from_scope(scope),
                valid_result_count=len(references),
                pages_completed=1,
                truncated=False,
                warning_codes=(CADEC_LIMITATION_WARNING,),
            )
            candidate = CadecSearchResult(
                scope_id=scope.scope_id,
                query=exact_plan.query,
                query_id=exact_plan.query_id,
                bm25_k1=exact_plan.bm25_k1,
                bm25_b=exact_plan.bm25_b,
                result_limit=exact_plan.result_limit,
                scope_bounds=ExecutionBounds.from_scope(scope),
                documents_scored=len(eligible),
                verification=verification,
                evidence_refs=references,
                outcome=outcome,
                limitations=tuple(CADEC_MANDATORY_LIMITATIONS),
            )
            return reconstruct_cadec_search_result(candidate, scope=scope, plan=exact_plan)
        except CadecRuntimeError:
            raise
        except (KeyError, TypeError, ValueError, ValidationError) as error:
            raise CadecRuntimeError(
                CadecRuntimeErrorCode.SEARCH_INTEGRITY,
                "CADEC transient materialization or search failed closed",
            ) from error


def _validate_transient_documents(
    admitted: tuple[_CadecAdmittedDocumentText, ...],
    *,
    expected_count: int,
) -> tuple[_CadecAdmittedDocumentText, ...]:
    if len(admitted) != expected_count:
        raise CadecRuntimeError(
            CadecRuntimeErrorCode.MATERIALIZATION,
            "CADEC transient document count differs from exact admission",
        )
    document_ids = tuple(item.document.document_id for item in admitted)
    if len(set(document_ids)) != len(document_ids):
        raise CadecRuntimeError(
            CadecRuntimeErrorCode.MATERIALIZATION,
            "CADEC transient documents contain duplicate identities",
        )
    eligible: list[_CadecAdmittedDocumentText] = []
    for item in admitted:
        document = item.document
        text = item.text
        if len(text) != document.text_length:
            raise CadecRuntimeError(
                CadecRuntimeErrorCode.MATERIALIZATION,
                "CADEC transient text length differs from admitted metadata",
            )
        digest = f"sha256:{hashlib.sha256(text.encode('utf-8')).hexdigest()}"
        if digest != document.text_sha256 or digest != document.artifact_sha256:
            raise CadecRuntimeError(
                CadecRuntimeErrorCode.MATERIALIZATION,
                "CADEC transient text hash differs from admitted metadata",
            )
        if text:
            eligible.append(item)
    return tuple(eligible)


def _score_all_eligible(
    documents: tuple[_CadecAdmittedDocumentText, ...],
    plan: CadecLocalSearchPlan,
) -> tuple[tuple[_CadecAdmittedDocumentText, float], ...]:
    if not documents:
        return ()
    by_id = {item.document.document_id: item for item in documents}
    index = BM25Index(
        tuple(by_id),
        tuple(item.text for item in documents),
        k1=plan.bm25_k1,
        b=plan.bm25_b,
    )
    scores = index.search(plan.query, limit=len(documents))
    scored_ids = tuple(document_id for document_id, _score in scores)
    if len(set(scored_ids)) != len(scores) or any(item not in by_id for item in scored_ids):
        raise CadecRuntimeError(
            CadecRuntimeErrorCode.SEARCH_INTEGRITY,
            "CADEC search returned duplicate or foreign document identities",
        )
    score_by_id: dict[str, float] = {}
    for document_id, score in scores:
        if document_id not in by_id or not math.isfinite(score):
            raise CadecRuntimeError(
                CadecRuntimeErrorCode.SEARCH_INTEGRITY,
                "CADEC search returned a foreign identity or non-finite score",
            )
        if score > 0.0:
            score_by_id[document_id] = score
    positive = [(item, score_by_id.get(item.document.document_id, 0.0)) for item in documents]
    positive = [item for item in positive if item[1] > 0.0]
    positive.sort(key=lambda item: (-item[1], item[0].document.document_id.encode("utf-8")))
    return tuple(positive[: plan.result_limit])


def _evidence_ref(
    item: _CadecAdmittedDocumentText,
    score: float,
) -> CadecDocumentEvidenceRef:
    document = item.document
    locator_ref = derive_identity(
        "cadec-whole-document-locator",
        {
            "source": SourceType.CADEC,
            "document_id": document.document_id,
            "document_record_id": document.document_record_id,
            "member_path": document.member_path,
            "content_sha256": document.text_sha256,
            "split": document.split,
            "split_membership_sha256": document.split_membership_sha256,
            "artifact_id": document.artifact_id,
            "provenance_context_id": document.provenance.provenance_context_id,
            "char_start": 0,
            "char_end": document.text_length,
        },
    )
    return CadecDocumentEvidenceRef(
        document_id=document.document_id,
        document_record_id=document.document_record_id,
        member_path=document.member_path,
        member_sha256=document.text_sha256,
        artifact_id=document.artifact_id,
        artifact_sha256=document.artifact_sha256,
        content_sha256=document.text_sha256,
        split=document.split,
        split_membership_sha256=document.split_membership_sha256,
        provenance_context_id=document.provenance.provenance_context_id,
        provenance_lineage_artifact_ids=document.provenance.lineage_artifact_ids,
        locator_ref=locator_ref,
        char_end=document.text_length,
        score=score,
    )


@final
class CanonicalCadecEvidenceCollection(_FrozenSlots):
    """Only production collection authority that can execute local CADEC search."""

    __slots__ = ("_delegate", "_search")
    _delegate: SourceCapabilities
    _search: CadecLocalSearchAdapter

    def __init_subclass__(cls, **kwargs: object) -> None:
        del kwargs
        raise TypeError("CanonicalCadecEvidenceCollection is sealed")

    def __init__(
        self,
        *,
        archive_path: str | Path,
        manifest_path: str | Path,
        delegate: SourceCapabilities,
    ) -> None:
        if type(delegate) is not SourceCapabilities:
            raise TypeError("CADEC collection requires the exact sealed three-source delegate")
        object.__setattr__(self, "_delegate", delegate)
        object.__setattr__(
            self,
            "_search",
            CadecLocalSearchAdapter(
                archive_path=archive_path,
                manifest_path=manifest_path,
            ),
        )
        _FrozenSlots._freeze(self)

    def plan_operations(
        self,
        task: SourceTaskState,
        scope: ResearchScope,
        attempt: SourceTaskAttemptRef,
    ) -> tuple[RequiredSourceOperation, ...]:
        """Intercept CADEC planning; delegate only exact non-CADEC inputs."""

        task, scope, attempt = _reconstruct_collection_inputs(task, scope, attempt)
        if task.source is SourceType.CADEC:
            return plan_cadec_operations(task=task, scope=scope, attempt=attempt)
        return SourceCapabilities.plan_operations(self._delegate, task, scope, attempt)

    def collect(
        self,
        task: SourceTaskState,
        scope: ResearchScope,
        attempt: SourceTaskAttemptRef,
    ) -> CollectedEvidenceResult | SourceTaskFailureRef | SourceTaskProgressResult:
        """Intercept CADEC execution through the internally constructed exact adapter."""

        task, scope, attempt = _reconstruct_collection_inputs(task, scope, attempt)
        if task.source is SourceType.CADEC:
            return collect_cadec_capability(
                task=task,
                scope=scope,
                attempt=attempt,
                search=self._search,
            )
        return SourceCapabilities.collect(self._delegate, task, scope, attempt)

    def validate_terminal_task(
        self,
        task: SourceTaskState,
        scope: ResearchScope,
    ) -> None:
        """Replay CADEC from exact assets or delegate non-CADEC validation."""

        if type(task) is not SourceTaskState or type(scope) is not ResearchScope:
            raise ValueError("terminal validation requires exact task and scope types")
        task = SourceTaskState.model_validate(task.model_dump(mode="python"), strict=True)
        scope = ResearchScope.model_validate(scope.model_dump(mode="python"), strict=True)
        if task.source is not SourceType.CADEC:
            SourceCapabilities.validate_terminal_task(self._delegate, task, scope)
            return
        if (
            task.status.value != "terminal"
            or task.source not in scope.selected_sources
            or not task.operation_results
        ):
            raise ValueError("CADEC replay requires one exact terminal selected task")
        attempt = task.operation_results[0].attempt
        running = SourceTaskState(
            task_id=task.task_id,
            source=task.source,
            required_operations=task.required_operations,
            status=SourceTaskStatus.RUNNING,
            attempts=task.attempts,
            active_attempt=attempt,
            failure_history=task.failure_history,
        )
        expected_result = collect_cadec_capability(
            task=running,
            scope=scope,
            attempt=attempt,
            search=self._search,
        )
        expected = terminal_source_task(
            running,
            expected_result,
            task.required_operations[0].run_id,
        )
        if task != expected:
            raise ValueError("terminal CADEC task differs from exact concrete asset replay")


def _reconstruct_collection_inputs(
    task: SourceTaskState,
    scope: ResearchScope,
    attempt: SourceTaskAttemptRef,
) -> tuple[SourceTaskState, ResearchScope, SourceTaskAttemptRef]:
    if (
        type(task) is not SourceTaskState
        or type(scope) is not ResearchScope
        or type(attempt) is not SourceTaskAttemptRef
    ):
        raise ValueError("source collection inputs require exact contract types")
    return (
        SourceTaskState.model_validate(task.model_dump(mode="python"), strict=True),
        ResearchScope.model_validate(scope.model_dump(mode="python"), strict=True),
        SourceTaskAttemptRef.model_validate(attempt.model_dump(mode="python"), strict=True),
    )


__all__ = ["CadecLocalSearchAdapter", "CanonicalCadecEvidenceCollection"]
