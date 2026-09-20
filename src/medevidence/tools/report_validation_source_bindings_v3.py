"""V3 source-operation evidence authority; legacy task reconstruction stays exact."""

from __future__ import annotations

import re
from dataclasses import dataclass

from medevidence.domain import SourceType, derive_identity

from . import report_validation as rv

_ACQUISITION_ID = re.compile(r"source-operation-acquisition:sha256:[0-9a-f]{64}\Z")
_KINDS = {
    SourceType.PUBMED: frozenset({"pubmed_search", "pubmed_fetch"}),
    SourceType.DAILYMED: frozenset(
        {"dailymed_discovery", "dailymed_candidate_enrichment", "dailymed_fetch"}
    ),
    SourceType.FAERS: frozenset({"faers_aggregate"}),
    SourceType.CADEC: frozenset({"cadec_verify", "cadec_search"}),
}


@dataclass(frozen=True, slots=True)
class EvidenceChildAcquisitionBindingV3:
    """One evidence ref tied to the actual operation that captured its snapshot."""

    run_id: str
    task_id: str
    attempt_id: str
    source: SourceType
    kind: str
    ordinal: int
    query_id: str
    operation_id: str
    acquisition_id: str
    acquisition_intent_id: str
    source_outcome_id: str
    snapshot_id: str
    evidence_id: str
    content_hash: str
    locator_ref: str


@dataclass(frozen=True, slots=True)
class TerminalTaskInputV3(rv.TerminalTaskInput):
    """Terminal task with every operation acquisition and ordered evidence bindings."""

    operation_acquisition_ids: tuple[str, ...]
    evidence_child_bindings: tuple[EvidenceChildAcquisitionBindingV3, ...]

    def __post_init__(self) -> None:
        rv.TerminalTaskInput.__post_init__(self)
        if type(self.operation_acquisition_ids) is not tuple or not 1 <= len(
            self.operation_acquisition_ids
        ) <= (101 if self.source is SourceType.PUBMED else 8):
            raise rv.CanonicalValidationError("task_operation_acquisition_cardinality_invalid")
        if type(self.evidence_child_bindings) is not tuple or len(
            self.evidence_child_bindings
        ) != len(self.evidence_refs):
            raise rv.CanonicalValidationError("task_child_evidence_binding_cardinality_invalid")


def _copy_legacy_task(value: rv.TerminalTaskInput) -> rv.TerminalTaskInput:
    """Preserve the original V1/V2 task parser and its error order."""

    rv._exact(value, rv.TerminalTaskInput, "task_wrong_type")
    if type(value.evidence_refs) is not tuple or len(value.evidence_refs) > 100:
        raise rv.CanonicalValidationError("task_evidence_cardinality_exceeded")
    if type(value.terminal) is not bool or not value.terminal:
        raise rv.CanonicalValidationError("task_not_terminal")
    acquisition = rv._exact(value.acquisition, rv.AcquisitionInput, "acquisition_wrong_type")
    if (
        type(acquisition.acquisition_ordinal) is not int
        or not 0 <= acquisition.acquisition_ordinal <= 7
        or acquisition.operation not in ("search", "fetch")
    ):
        raise rv.CanonicalValidationError("acquisition_primitive_invalid")
    intent = rv._text(acquisition.acquisition_intent_id, "acquisition_intent_invalid")
    if rv._ACQUISITION_INTENT.fullmatch(intent) is None:
        raise rv.CanonicalValidationError("acquisition_intent_invalid")
    acquisition = rv.AcquisitionInput(
        rv._text(acquisition.run_id, "acquisition_run_invalid"),
        rv._exact(acquisition.source, SourceType, "acquisition_source_wrong_type"),
        rv._text(acquisition.acquisition_id, "acquisition_id_invalid"),
        intent,
        acquisition.acquisition_ordinal,
        acquisition.operation,
        rv._text(acquisition.query_id, "acquisition_query_invalid"),
        rv._text(acquisition.source_outcome_id, "source_outcome_id_invalid"),
        rv._text(acquisition.snapshot_id, "acquisition_snapshot_invalid"),
    )
    outcome = rv._copy_outcome(value.outcome)
    refs: list[rv.EvidenceReferenceInput] = []
    for raw in value.evidence_refs:
        ref = rv._exact(raw, rv.EvidenceReferenceInput, "evidence_reference_wrong_type")
        refs.append(
            rv.EvidenceReferenceInput(
                rv._text(ref.evidence_id, "evidence_reference_id_invalid"),
                rv._exact(ref.source, SourceType, "evidence_reference_source_wrong_type"),
                rv._text(ref.snapshot_id, "evidence_reference_snapshot_invalid"),
                rv._digest(ref.content_hash, "evidence_reference_hash_invalid"),
                rv._text(ref.locator_ref, "evidence_reference_locator_invalid"),
            )
        )
    source = rv._exact(value.source, SourceType, "task_source_wrong_type")
    if (
        source is not acquisition.source
        or source is not outcome.source
        or acquisition.query_id != outcome.query_id
        or any(item.source is not source for item in refs)
    ):
        raise rv.CanonicalValidationError("task_source_binding_invalid")
    return rv.TerminalTaskInput(
        rv._text(value.task_id, "task_id_invalid"),
        source,
        True,
        acquisition,
        outcome,
        tuple(refs),
    )


def _copy_child_binding(
    value: EvidenceChildAcquisitionBindingV3,
    *,
    task: rv.TerminalTaskInput,
    acquisition_ids: tuple[str, ...],
    evidence_ref: rv.EvidenceReferenceInput,
) -> EvidenceChildAcquisitionBindingV3:
    rv._exact(value, EvidenceChildAcquisitionBindingV3, "child_binding_wrong_type")
    source = rv._exact(value.source, SourceType, "child_binding_source_wrong_type")
    kind = rv._text(value.kind, "child_binding_kind_invalid")
    ordinal = value.ordinal
    if (
        source is not task.source
        or kind not in _KINDS[source]
        or type(ordinal) is not int
        or not 0 <= ordinal < len(acquisition_ids)
    ):
        raise rv.CanonicalValidationError("child_binding_operation_invalid")
    copied = EvidenceChildAcquisitionBindingV3(
        run_id=rv._text(value.run_id, "child_binding_run_invalid"),
        task_id=rv._text(value.task_id, "child_binding_task_invalid"),
        attempt_id=rv._text(value.attempt_id, "child_binding_attempt_invalid"),
        source=source,
        kind=kind,
        ordinal=ordinal,
        query_id=rv._text(value.query_id, "child_binding_query_invalid"),
        operation_id=rv._text(value.operation_id, "child_binding_operation_id_invalid"),
        acquisition_id=rv._text(value.acquisition_id, "child_binding_acquisition_invalid"),
        acquisition_intent_id=rv._text(value.acquisition_intent_id, "child_binding_intent_invalid"),
        source_outcome_id=rv._text(value.source_outcome_id, "child_binding_outcome_invalid"),
        snapshot_id=rv._text(value.snapshot_id, "child_binding_snapshot_invalid"),
        evidence_id=rv._text(value.evidence_id, "child_binding_evidence_invalid"),
        content_hash=rv._digest(value.content_hash, "child_binding_hash_invalid"),
        locator_ref=rv._text(value.locator_ref, "child_binding_locator_invalid"),
    )
    acquisition_payload = {
        "acquisition_intent_id": copied.acquisition_intent_id,
        "run_id": copied.run_id,
        "task_id": copied.task_id,
        "attempt_id": copied.attempt_id,
        "source": copied.source,
        "ordinal": copied.ordinal,
        "operation_id": copied.operation_id,
        "kind": copied.kind,
        "query_id": copied.query_id,
        "source_outcome_id": copied.source_outcome_id,
        "snapshot_id": copied.snapshot_id,
    }
    if (
        copied.run_id != task.acquisition.run_id
        or copied.task_id != task.task_id
        or copied.acquisition_id != acquisition_ids[ordinal]
        or copied.acquisition_id
        != derive_identity("source-operation-acquisition", acquisition_payload)
        or rv._ACQUISITION_INTENT.fullmatch(copied.acquisition_intent_id) is None
        or (
            copied.evidence_id,
            copied.source,
            copied.snapshot_id,
            copied.content_hash,
            copied.locator_ref,
        )
        != (
            evidence_ref.evidence_id,
            evidence_ref.source,
            evidence_ref.snapshot_id,
            evidence_ref.content_hash,
            evidence_ref.locator_ref,
        )
    ):
        raise rv.CanonicalValidationError("child_binding_authority_drift")
    return copied


def copy_task(value: rv.TerminalTaskInput) -> rv.TerminalTaskInput:
    """Reconstruct the exact legacy or V3 task without trusting subclass fields."""

    if type(value) is rv.TerminalTaskInput:
        return _copy_legacy_task(value)
    if type(value) is not TerminalTaskInputV3:
        raise rv.CanonicalValidationError("task_wrong_type")
    base = _copy_legacy_task(
        rv.TerminalTaskInput(
            value.task_id,
            value.source,
            value.terminal,
            value.acquisition,
            value.outcome,
            value.evidence_refs,
        )
    )
    acquisition_ids = value.operation_acquisition_ids
    if type(acquisition_ids) is not tuple or not 1 <= len(acquisition_ids) <= (
        101 if base.source is SourceType.PUBMED else 8
    ):
        raise rv.CanonicalValidationError("task_operation_acquisition_cardinality_invalid")
    ids = tuple(rv._text(item, "task_operation_acquisition_id_invalid") for item in acquisition_ids)
    if (
        len(set(ids)) != len(ids)
        or any(_ACQUISITION_ID.fullmatch(item) is None for item in ids)
        or base.acquisition.acquisition_id not in ids
    ):
        raise rv.CanonicalValidationError("task_operation_acquisition_identity_invalid")
    bindings = value.evidence_child_bindings
    if type(bindings) is not tuple or len(bindings) != len(base.evidence_refs):
        raise rv.CanonicalValidationError("task_child_evidence_binding_cardinality_invalid")
    copied_bindings = tuple(
        _copy_child_binding(item, task=base, acquisition_ids=ids, evidence_ref=ref)
        for item, ref in zip(bindings, base.evidence_refs, strict=True)
    )
    if len({item.attempt_id for item in copied_bindings}) > 1:
        raise rv.CanonicalValidationError("task_child_attempt_mismatch")
    return TerminalTaskInputV3(
        task_id=base.task_id,
        source=base.source,
        terminal=True,
        acquisition=base.acquisition,
        outcome=base.outcome,
        evidence_refs=base.evidence_refs,
        operation_acquisition_ids=ids,
        evidence_child_bindings=copied_bindings,
    )


def validate_task_configuration(
    tasks: tuple[rv.TerminalTaskInput, ...], configuration_version: str
) -> None:
    v3_count = sum(type(task) is TerminalTaskInputV3 for task in tasks)
    if (
        configuration_version
        not in (
            rv.M3_VALIDATION_CONFIGURATION_V3,
            rv.M3_VALIDATION_CONFIGURATION_V4,
        )
        and v3_count
    ):
        raise rv.CanonicalValidationError("v3_child_binding_forbidden_in_legacy")
    if 0 < v3_count < len(tasks):
        raise rv.CanonicalValidationError("v3_child_binding_task_mode_ambiguous")


def evidence_acquisition_matches(
    task: rv.TerminalTaskInput, evidence_ref: rv.EvidenceReferenceInput
) -> bool:
    if type(task) is TerminalTaskInputV3:
        return any(
            binding.evidence_id == evidence_ref.evidence_id
            and binding.snapshot_id == evidence_ref.snapshot_id
            and binding.content_hash == evidence_ref.content_hash
            and binding.locator_ref == evidence_ref.locator_ref
            for binding in task.evidence_child_bindings
        )
    return task.acquisition.snapshot_id == evidence_ref.snapshot_id


def evidence_locator_matches(
    task: rv.TerminalTaskInput, durable: str, raw: str, version: str
) -> bool:
    """Bind a PubMed child reference to its exact raw citation span identity."""

    return durable == raw or (
        type(task) is TerminalTaskInputV3
        and version in (rv.M3_VALIDATION_CONFIGURATION_V3, rv.M3_VALIDATION_CONFIGURATION_V4)
        and task.source is SourceType.PUBMED
        and durable == derive_identity("pubmed-material-locator", raw)
    )
