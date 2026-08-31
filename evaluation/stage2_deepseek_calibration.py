"""Frozen M3-008B DeepSeek calibration inputs, evidence, and acceptance authority."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, fields, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final, cast, final

from pydantic import BaseModel

from medevidence.domain import canonical_json
from medevidence.infrastructure.deepseek_responses_transport import (
    DeepSeekOneOperationObservation,
)
from medevidence.infrastructure.deepseek_semantic_evaluator import (
    DeepSeekRawSemanticObservation,
    DeepSeekSemanticAssessment,
    DeepSeekSemanticEvaluatorError,
    deepseek_provider_request_bytes,
    parse_deepseek_completed_response,
)
from medevidence.persistence import ProviderAttemptEvent, ProviderAttemptLedgerRepository
from medevidence.tools.report_validation import SemanticSupport
from medevidence.tools.semantic_evaluation import (
    DEEPSEEK_SEMANTIC_EVALUATION_CONFIG_VERSION,
    DEEPSEEK_SEMANTIC_EVALUATION_CONFIGURATION_HASH,
    DEEPSEEK_SEMANTIC_EVALUATION_ENDPOINT,
    DEEPSEEK_SEMANTIC_EVALUATION_METHOD,
    DEEPSEEK_SEMANTIC_EVALUATION_MODEL,
    DEEPSEEK_SEMANTIC_EVALUATION_REASONING_EFFORT,
    SEMANTIC_EVALUATION_PROMPT_HASH,
    SEMANTIC_EVALUATION_PROMPT_VERSION,
    SEMANTIC_EVALUATION_RUBRIC_HASH,
    SEMANTIC_EVALUATION_RUBRIC_VERSION,
    SEMANTIC_EVALUATION_SCHEMA_HASH,
    SEMANTIC_EVALUATION_SCHEMA_VERSION,
    SemanticEvaluationRequest,
    SemanticEvaluationResult,
    SemanticEvaluationUsage,
    SemanticRationaleCode,
    build_deepseek_semantic_evaluation_result,
    parse_semantic_evaluation_request,
    semantic_evaluation_input_bytes,
    semantic_evaluation_request_bytes,
)

CALIBRATION_DATASET_IDENTITY: Final = (
    "sha256:7256269fc1828da2d86424363a7275d06e0fbee2bc5e716c66fcbe94cd03807b"
)
OWNER_RESOLUTION_IDENTITY: Final = (
    "sha256:758aaccd90e2e545af2215640426a20b2c75c038d40f0d1d2b2e0cc716aaf806"
)
MACHINE_PACKET_SHA256: Final = "c3a0823cb101007417a6a0af1ccf02dae7a40f5a8863b1dfe3e266e6ed39e6c9"
RESOLUTION_PACKET_SHA256: Final = "7b0414269b70264c0d4237c908da7b4f3422a90d22a3e1522d5b2bb871fb4c98"
CASE_COUNT: Final = 36
FROZEN_CASE_INVENTORY_IDENTITY: Final = (
    "sha256:bed7441026b4e32e2b627fa33e9c57c8e6022cc962c130be1c72b0b8ca498378"
)
FROZEN_CATEGORY_COUNTS: Final = (
    ("applicable_contradiction", 8),
    ("direct_semantic_support", 4),
    ("explicit_negation", 4),
    ("insufficient_indirect_evidence", 4),
    ("irrelevant_limitation_context", 4),
    ("legitimate_partial_evidence", 4),
    ("qualified_contradiction", 4),
    ("source_specific_limitations", 4),
)
REPOSITORY_ROOT: Final = Path(__file__).resolve().parents[1]


class DeepSeekCalibrationError(ValueError):
    """Fail-closed M3-008B calibration contract error."""


@dataclass(frozen=True, slots=True)
class FrozenCalibrationCase:
    ordinal: int
    case_id: str
    category: str
    source: str
    citation_relationship: str
    semantic_request_hash: str
    stage1_admission_identity: str
    request: SemanticEvaluationRequest
    human_expected_state: SemanticSupport
    human_authority: str
    human_notes: str
    immutable_projection_hash: str


@dataclass(frozen=True, slots=True)
class CalibrationObservation:
    case: FrozenCalibrationCase
    assessment: DeepSeekSemanticAssessment


@dataclass(frozen=True, slots=True)
class RawProviderBodyBinding:
    relative_path: str
    content_hash: str
    byte_count: int


@final
class PendingCalibrationRun:
    """One absent append-only pending run created only after every preflight gate."""

    __slots__ = (
        "attempted_case_ids",
        "configuration",
        "output_root",
        "pending_root",
        "provider_attempt_authority",
        "raw_body_paths",
        "successful_case_ids",
    )
    attempted_case_ids: list[str]
    configuration: dict[str, object]
    output_root: Path
    pending_root: Path
    raw_body_paths: list[str]
    provider_attempt_authority: dict[str, object] | None
    successful_case_ids: list[str]

    def __init__(
        self,
        *,
        configuration: dict[str, object],
        output_root: Path,
        pending_root: Path,
    ) -> None:
        object.__setattr__(self, "configuration", configuration)
        object.__setattr__(self, "output_root", output_root)
        object.__setattr__(self, "pending_root", pending_root)
        object.__setattr__(self, "successful_case_ids", [])
        object.__setattr__(self, "attempted_case_ids", [])
        object.__setattr__(self, "raw_body_paths", [])
        object.__setattr__(self, "provider_attempt_authority", None)


def _canonical_bytes(value: object) -> bytes:
    return canonical_json(value).encode("utf-8")


def _sha256(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _load_exact(path: Path, expected_sha256: str, maximum: int) -> dict[str, Any]:
    if not path.is_absolute() or not path.is_file() or path.is_symlink():
        raise DeepSeekCalibrationError("frozen packet path is invalid")
    with path.open("rb") as handle:
        raw = handle.read(maximum + 1)
    if not raw or len(raw) > maximum or hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise DeepSeekCalibrationError("frozen packet bytes do not match approved identity")
    try:
        value = json.loads(raw.decode("utf-8", errors="strict"), object_pairs_hook=_unique)
    except (UnicodeDecodeError, json.JSONDecodeError, _DuplicateKeyError):
        raise DeepSeekCalibrationError("frozen packet JSON is invalid") from None
    if type(value) is not dict:
        raise DeepSeekCalibrationError("frozen packet root is invalid")
    return value


def load_frozen_calibration_cases(
    machine_packet_path: Path, resolution_packet_path: Path
) -> tuple[FrozenCalibrationCase, ...]:
    """Load and cross-bind the immutable provider-neutral cases and Owner labels."""

    machine = _load_exact(machine_packet_path, MACHINE_PACKET_SHA256, 1_000_000)
    resolution = _load_exact(resolution_packet_path, RESOLUTION_PACKET_SHA256, 100_000)
    frozen_packet = resolution.get("frozen_owner_adjudication_packet")
    if (
        machine.get("calibration_dataset_identity") != CALIBRATION_DATASET_IDENTITY
        or machine.get("case_count") != CASE_COUNT
        or machine.get("provider_called") is not False
        or machine.get("holdout_accessed") is not False
        or resolution.get("canonical_content_identity") != OWNER_RESOLUTION_IDENTITY
        or type(frozen_packet) is not dict
        or frozen_packet.get("calibration_dataset_identity") != CALIBRATION_DATASET_IDENTITY
        or resolution.get("case_count") != CASE_COUNT
        or resolution.get("provider_called") is not False
        or resolution.get("holdout_accessed") is not False
        or resolution.get("human_authority") != "project_owner"
    ):
        raise DeepSeekCalibrationError("frozen packet authority drift")
    machine_cases = machine.get("cases")
    resolution_cases = resolution.get("cases")
    ordered_ids = machine.get("ordered_case_ids")
    if (
        type(machine_cases) is not list
        or type(resolution_cases) is not list
        or type(ordered_ids) is not list
        or len(machine_cases) != CASE_COUNT
        or len(resolution_cases) != CASE_COUNT
        or resolution.get("ordered_case_ids") != ordered_ids
    ):
        raise DeepSeekCalibrationError("frozen case sequence drift")
    results: list[FrozenCalibrationCase] = []
    resolutions: Counter[str] = Counter()
    sources: Counter[str] = Counter()
    relationships: Counter[str] = Counter()
    categories: set[str] = set()
    request_hashes: set[str] = set()
    admission_ids: set[str] = set()
    for index, (machine_case, owner_case) in enumerate(
        zip(machine_cases, resolution_cases, strict=True), start=1
    ):
        if type(machine_case) is not dict or type(owner_case) is not dict:
            raise DeepSeekCalibrationError("frozen case shape is invalid")
        case_id = f"M3-008B-CAL-{index:03d}"
        if (
            machine_case.get("ordinal") != index
            or owner_case.get("ordinal") != index
            or machine_case.get("case_id") != case_id
            or owner_case.get("case_id") != case_id
            or ordered_ids[index - 1] != case_id
        ):
            raise DeepSeekCalibrationError("frozen case order drift")
        projection = dict(machine_case)
        projection.pop("human_resolution", None)
        projection.pop("human_notes", None)
        immutable_hash = _sha256(_canonical_bytes(projection))
        fields = (
            "case_id",
            "ordinal",
            "category",
            "source",
            "citation_relationship",
            "semantic_request_hash",
            "stage1_admission_identity",
        )
        if (
            owner_case.get("immutable_projection_hash") != immutable_hash
            or any(owner_case.get(field) != machine_case.get(field) for field in fields)
            or owner_case.get("human_resolution") != owner_case.get("human_expected_state")
            or owner_case.get("human_authority") != "project_owner"
            or type(owner_case.get("human_notes")) is not str
            or not owner_case["human_notes"]
        ):
            raise DeepSeekCalibrationError("Owner resolution binding drift")
        state = _support(owner_case["human_expected_state"])
        request_document = machine_case.get("semantic_request")
        if type(request_document) is not dict:
            raise DeepSeekCalibrationError("semantic request document is invalid")
        request_bytes = _canonical_bytes(request_document)
        if _sha256(request_bytes) != machine_case.get("semantic_request_hash"):
            raise DeepSeekCalibrationError("semantic request hash drift")
        if (
            machine_case["semantic_request_hash"] in request_hashes
            or machine_case["stage1_admission_identity"] in admission_ids
        ):
            raise DeepSeekCalibrationError("duplicate frozen case identity")
        request_hashes.add(machine_case["semantic_request_hash"])
        admission_ids.add(machine_case["stage1_admission_identity"])
        try:
            request = parse_semantic_evaluation_request(request_bytes)
        except Exception:
            raise DeepSeekCalibrationError("semantic request canonical admission failed") from None
        if semantic_evaluation_request_bytes(
            request
        ) != request_bytes or request.stage1_admission.admission_hash != machine_case.get(
            "stage1_admission_identity"
        ):
            raise DeepSeekCalibrationError("semantic request Stage-1 binding drift")
        category_value = machine_case.get("category")
        source_value = machine_case.get("source")
        relationship_value = machine_case.get("citation_relationship")
        if any(
            type(value) is not str or not value
            for value in (category_value, source_value, relationship_value)
        ):
            raise DeepSeekCalibrationError("case classification is invalid")
        category = cast(str, category_value)
        source = cast(str, source_value)
        relationship = cast(str, relationship_value)
        categories.add(category)
        resolutions[state.value] += 1
        sources[source] += 1
        relationships[relationship] += 1
        results.append(
            FrozenCalibrationCase(
                ordinal=index,
                case_id=case_id,
                category=category,
                source=source,
                citation_relationship=relationship,
                semantic_request_hash=machine_case["semantic_request_hash"],
                stage1_admission_identity=machine_case["stage1_admission_identity"],
                request=request,
                human_expected_state=state,
                human_authority="project_owner",
                human_notes=owner_case["human_notes"],
                immutable_projection_hash=immutable_hash,
            )
        )
    if resolutions != {"supported": 12, "uncertain": 12, "unsupported": 12}:
        raise DeepSeekCalibrationError("human state counts drift")
    if sources != {"pubmed": 9, "dailymed": 9, "faers": 9, "cadec": 9}:
        raise DeepSeekCalibrationError("frozen source counts drift")
    if relationships != {"supports": 12, "contradicts": 12, "context_only": 12}:
        raise DeepSeekCalibrationError("frozen relationship counts drift")
    if len(categories) < 3:
        raise DeepSeekCalibrationError("frozen category coverage is invalid")
    frozen = tuple(results)
    if tuple(sorted(Counter(case.category for case in frozen).items())) != FROZEN_CATEGORY_COUNTS:
        raise DeepSeekCalibrationError("frozen category inventory drift")
    if _case_inventory_identity(frozen) != FROZEN_CASE_INVENTORY_IDENTITY:
        raise DeepSeekCalibrationError("frozen ordered case inventory drift")
    return frozen


def calibration_configuration(
    *, code_revision: str, implementation_manifest_hash: str
) -> dict[str, object]:
    """Return the exact DeepSeek profile bound separately from frozen human truth."""

    _code_revision(code_revision)
    _digest(implementation_manifest_hash, "implementation manifest")
    return {
        "provider": "DeepSeek API",
        "calibration_prompt_rubric_version": 1,
        "maximum_development_versions": 3,
        "endpoint": DEEPSEEK_SEMANTIC_EVALUATION_ENDPOINT,
        "evaluator_method": DEEPSEEK_SEMANTIC_EVALUATION_METHOD,
        "configuration_version": DEEPSEEK_SEMANTIC_EVALUATION_CONFIG_VERSION,
        "configuration_hash": DEEPSEEK_SEMANTIC_EVALUATION_CONFIGURATION_HASH,
        "model": DEEPSEEK_SEMANTIC_EVALUATION_MODEL,
        "reasoning_effort": DEEPSEEK_SEMANTIC_EVALUATION_REASONING_EFFORT,
        "prompt_version": SEMANTIC_EVALUATION_PROMPT_VERSION,
        "prompt_hash": SEMANTIC_EVALUATION_PROMPT_HASH,
        "rubric_version": SEMANTIC_EVALUATION_RUBRIC_VERSION,
        "rubric_hash": SEMANTIC_EVALUATION_RUBRIC_HASH,
        "schema_version": SEMANTIC_EVALUATION_SCHEMA_VERSION,
        "schema_hash": SEMANTIC_EVALUATION_SCHEMA_HASH,
        "tools": [],
        "tool_choice": "none",
        "web_search_enabled": False,
        "provider_contract_url": "https://api-docs.deepseek.com/guides/responses_api",
        "provider_privacy_policy_url": (
            "https://cdn.deepseek.com/policies/en-US/deepseek-privacy-policy.html"
        ),
        "provider_policy_review_date": "2026-08-30",
        "provider_state_model": "stateless_response_and_conversation_state",
        "operational_privacy_retention_distinct": True,
        "public_research_data_only": True,
        "calibration_dataset_identity": CALIBRATION_DATASET_IDENTITY,
        "human_resolution_identity": OWNER_RESOLUTION_IDENTITY,
        "case_inventory_identity": FROZEN_CASE_INVENTORY_IDENTITY,
        "frozen_category_counts": dict(FROZEN_CATEGORY_COUNTS),
        "code_revision": code_revision,
        "implementation_manifest_hash": implementation_manifest_hash,
    }


def provider_attempt_run_id(configuration: Mapping[str, object]) -> str:
    """Bind one durable provider run to the exact frozen calibration configuration."""

    return (
        "provider-attempt-run:sha256:"
        + hashlib.sha256(_canonical_bytes(dict(configuration))).hexdigest()
    )


def persist_safe_raw_body(
    run: PendingCalibrationRun,
    case: FrozenCalibrationCase,
    attempt_ordinal: int,
    observation: DeepSeekOneOperationObservation,
    *,
    provider_run_id: str,
) -> RawProviderBodyBinding | None:
    """Persist only credential-clean, complete, within-cap raw bytes before validation."""

    _validate_pending_run(run)
    if observation.credential_echo or observation.raw_body is None:
        return None
    raw = observation.raw_body
    if not observation.body_complete or len(raw) > 131_072:
        return None
    name = f"case-{case.ordinal:03d}-attempt-{attempt_ordinal:03d}-raw.bin"
    run_digest = provider_run_id.removeprefix("provider-attempt-run:sha256:")
    relative = f"provider-attempt-raw/{run_digest}/{name}"
    store = run.output_root.parent / "provider-attempt-raw" / run_digest
    _validate_external_ancestry(run.output_root.parent, store)
    store.mkdir(parents=True, exist_ok=True)
    _validate_external_ancestry(run.output_root.parent, store)
    path = store / name
    _write_new_bytes(path, raw)
    digest = _sha256(raw)
    return RawProviderBodyBinding(relative, digest, len(raw))


def validate_authoritative_provider_events(
    events: Sequence[ProviderAttemptEvent],
    *,
    frozen_cases: Sequence[FrozenCalibrationCase],
    expected_provider_run_id: str,
) -> tuple[ProviderAttemptEvent, ...]:
    """Bind every event to the frozen run, provider config, case, and request."""

    ordered = tuple(events)
    cases = {case.ordinal: case for case in frozen_cases}
    if len(cases) != len(tuple(frozen_cases)):
        raise DeepSeekCalibrationError("frozen case inventory contains duplicate ordinals")
    starts_by_id = {item.event_id: item for item in ordered if item.event_kind == "START"}
    for event in ordered:
        case = cases.get(event.case_ordinal)
        if (
            event.provider_run_id != expected_provider_run_id
            or event.configuration_hash != DEEPSEEK_SEMANTIC_EVALUATION_CONFIGURATION_HASH
            or case is None
            or event.case_id != case.case_id
        ):
            raise DeepSeekCalibrationError("provider event differs from frozen authority")
        expected_request_hash = _sha256(deepseek_provider_request_bytes(case.request))
        if event.request_hash != expected_request_hash:
            raise DeepSeekCalibrationError("provider event request differs from frozen case")
        if event.event_kind != "START":
            start = starts_by_id.get(cast(str, event.start_event_id))
            if (
                start is None
                or start.case_ordinal != event.case_ordinal
                or start.attempt_ordinal != event.attempt_ordinal
            ):
                raise DeepSeekCalibrationError("provider closure lacks frozen START authority")
    return ordered


def provider_event_projection(
    events: Sequence[ProviderAttemptEvent],
    *,
    frozen_cases: Sequence[FrozenCalibrationCase],
    expected_provider_run_id: str,
    raw_root: Path | None = None,
) -> dict[str, object]:
    ordered = validate_authoritative_provider_events(
        events,
        frozen_cases=frozen_cases,
        expected_provider_run_id=expected_provider_run_id,
    )
    return _project_validated_events(ordered, raw_root=raw_root)


def _project_validated_events(
    events: Sequence[ProviderAttemptEvent], *, raw_root: Path | None = None
) -> dict[str, object]:
    """Build the external projection strictly from authoritative ordered ledger events."""

    ordered = tuple(events)
    if (
        tuple(
            sorted(
                ordered, key=lambda item: (item.case_ordinal, item.attempt_ordinal, item.event_slot)
            )
        )
        != ordered
    ):
        raise DeepSeekCalibrationError("provider ledger event order drift")
    for event in ordered:
        if event.body_relative_path is None:
            continue
        if raw_root is None:
            raise DeepSeekCalibrationError("raw root is required for bound provider body")
        path = raw_root / event.body_relative_path
        if not path.is_file() or path.is_symlink():
            raise DeepSeekCalibrationError("ledger-bound raw provider body is missing")
        with path.open("rb") as handle:
            raw = handle.read(131_073)
        if (
            len(raw) > 131_072
            or event.body_byte_count != len(raw)
            or event.body_hash != _sha256(raw)
        ):
            raise DeepSeekCalibrationError("ledger-bound raw provider body differs")
    rows = [
        {
            name: (
                value.isoformat()
                if isinstance(value, datetime)
                else list(value)
                if isinstance(value, tuple)
                else value
            )
            for field in fields(event)
            for name, value in ((field.name, getattr(event, field.name)),)
        }
        for event in ordered
    ]
    starts = [item for item in ordered if item.event_kind == "START"]
    terminal = [item for item in ordered if item.event_kind in {"TERMINAL", "RECOVERY"}]
    start_by_key = {(item.case_ordinal, item.attempt_ordinal): item for item in starts}
    closure_keys: set[tuple[int, int]] = set()
    for closure in terminal:
        key = (closure.case_ordinal, closure.attempt_ordinal)
        start = start_by_key.get(key)
        if (
            start is None
            or key in closure_keys
            or closure.start_event_id != start.event_id
            or closure.configuration_hash != start.configuration_hash
            or closure.request_hash != start.request_hash
        ):
            raise DeepSeekCalibrationError("provider ledger closure topology drift")
        closure_keys.add(key)
    terminal_keys = {(item.case_ordinal, item.attempt_ordinal) for item in terminal}
    orphan = any((item.case_ordinal, item.attempt_ordinal) not in terminal_keys for item in starts)
    case_ordinals = sorted({item.case_ordinal for item in starts})
    final_successes: set[int] = set()
    for case_ordinal in case_ordinals:
        case_starts = [item for item in starts if item.case_ordinal == case_ordinal]
        ordinals = [item.attempt_ordinal for item in case_starts]
        if ordinals != list(range(1, len(ordinals) + 1)) or len(ordinals) > 3:
            raise DeepSeekCalibrationError("provider ledger attempt ordinals are discontinuous")
        case_closures = {
            item.attempt_ordinal: item for item in terminal if item.case_ordinal == case_ordinal
        }
        for attempt in ordinals[:-1]:
            closure = case_closures.get(attempt)
            if closure is None or closure.disposition not in {
                "retryable_status",
                "transport_unavailable",
            }:
                raise DeepSeekCalibrationError("provider ledger retry transition is illegal")
        if ordinals and ordinals[-1] in case_closures:
            final = case_closures[ordinals[-1]]
            if final.disposition == "success":
                if (
                    final.body_complete is not True
                    or final.body_hash is None
                    or final.body_relative_path is None
                    or final.body_byte_count is None
                ):
                    raise DeepSeekCalibrationError(
                        "successful provider closure lacks exact raw binding"
                    )
                final_successes.add(case_ordinal)
        if any(attempt not in ordinals for attempt in case_closures):
            raise DeepSeekCalibrationError("provider ledger closure has no START ordinal")
    all_cases_complete = (
        case_ordinals == list(range(1, CASE_COUNT + 1))
        and final_successes == set(range(1, CASE_COUNT + 1))
        and not orphan
    )
    semantic = {
        "schema_version": "m3.provider-attempt-projection.v1",
        "event_count": len(ordered),
        "attempt_count": len(starts),
        "status": (
            "EMPTY"
            if not ordered
            else "NONFINAL"
            if starts and not terminal
            else "INTERRUPTED"
            if orphan or any(item.event_kind == "RECOVERY" for item in ordered)
            else "FAILED"
            if not all_cases_complete
            else "COMPLETE"
        ),
        "events": rows,
    }
    return {**semantic, "projection_hash": _sha256(_canonical_bytes(semantic))}


def validate_provider_event_projection(
    projection: Mapping[str, object],
    events: Sequence[ProviderAttemptEvent],
    *,
    frozen_cases: Sequence[FrozenCalibrationCase],
    expected_provider_run_id: str,
    raw_root: Path | None = None,
) -> None:
    """Reject caller-recomputed projections that differ from authoritative ledger truth."""

    if dict(projection) != provider_event_projection(
        events,
        frozen_cases=frozen_cases,
        expected_provider_run_id=expected_provider_run_id,
        raw_root=raw_root,
    ):
        raise DeepSeekCalibrationError("external provider-attempt projection differs from ledger")


def expected_run_status(
    *,
    configuration: Mapping[str, object],
    events: Sequence[ProviderAttemptEvent],
    frozen_cases: Sequence[FrozenCalibrationCase],
    expected_provider_run_id: str,
    raw_root: Path,
    artifact: Mapping[str, object] | None,
    artifact_bytes: bytes | None,
) -> dict[str, object]:
    """Build the sole closed run-status object from configuration, ledger, and artifact."""

    projection = provider_event_projection(
        events,
        frozen_cases=frozen_cases,
        expected_provider_run_id=expected_provider_run_id,
        raw_root=raw_root,
    )
    starts = [item for item in events if item.event_kind == "START"]
    closures = [item for item in events if item.event_kind in {"TERMINAL", "RECOVERY"}]
    attempted_ids = tuple(
        f"M3-008B-CAL-{ordinal:03d}" for ordinal in sorted({item.case_ordinal for item in starts})
    )
    successful_ids = tuple(
        f"M3-008B-CAL-{ordinal:03d}"
        for ordinal in sorted(
            {
                item.case_ordinal
                for item in closures
                if item.event_kind == "TERMINAL" and item.disposition == "success"
            }
        )
    )
    artifact_present = artifact is not None and artifact_bytes is not None
    metrics = artifact.get("metrics") if artifact is not None else None
    metrics_accepted = type(metrics) is dict and metrics.get("accepted") is True
    accepted = projection["status"] == "COMPLETE" and artifact_present and metrics_accepted
    status = (
        "PASS"
        if accepted
        else "INTERRUPTED"
        if projection["status"] in {"INTERRUPTED", "NONFINAL"}
        else "FAILED"
    )
    authority = {
        "projection_hash": projection["projection_hash"],
        "event_count": projection["event_count"],
        "attempt_count": projection["attempt_count"],
        "status": projection["status"],
    }
    semantic = {
        "schema_version": "m3.stage2.deepseek-run-status.v2",
        "status": status,
        "accepted": accepted,
        "calibration_artifact_present": artifact_present,
        "artifact_sha256": _sha256(artifact_bytes) if artifact_bytes is not None else None,
        "artifact_sidecar_present": artifact_present,
        "provider_attempt_authority": authority,
        "configuration_binding_hash": _sha256(_canonical_bytes(dict(configuration))),
        "total_http_attempts": len(starts),
        "attempted_case_count": len(attempted_ids),
        "attempted_case_ids": list(attempted_ids),
        "successful_case_count": len(successful_ids),
        "successful_case_ids": list(successful_ids),
    }
    return {**semantic, "status_binding_hash": _sha256(_canonical_bytes(semantic))}


def verify_external_run(
    repository: ProviderAttemptLedgerRepository,
    output_root: Path,
    *,
    expected_provider_run_id: str,
    expected_code_revision: str,
    expected_implementation_manifest_hash: str,
    frozen_cases: Sequence[FrozenCalibrationCase],
) -> dict[str, object]:
    """Verify the whole external run only from independent expected inputs and ledger."""

    expected_configuration = calibration_configuration(
        code_revision=expected_code_revision,
        implementation_manifest_hash=expected_implementation_manifest_hash,
    )
    if provider_attempt_run_id(expected_configuration) != expected_provider_run_id:
        raise DeepSeekCalibrationError("expected provider run identity drift")
    events = repository.list_events(expected_provider_run_id)
    expected = provider_event_projection(
        events,
        frozen_cases=frozen_cases,
        expected_provider_run_id=expected_provider_run_id,
        raw_root=output_root.parent,
    )
    projection = _load_external_json(output_root / "provider-attempt-projection.json")
    validate_provider_event_projection(
        projection,
        events,
        frozen_cases=frozen_cases,
        expected_provider_run_id=expected_provider_run_id,
        raw_root=output_root.parent,
    )
    run_configuration = _load_external_json(output_root / "run-configuration.json")
    if run_configuration != {
        "schema_version": "m3.stage2.deepseek-run-configuration.v1",
        "status": "PENDING",
        "configuration": expected_configuration,
        "configuration_binding_hash": _sha256(_canonical_bytes(expected_configuration)),
    }:
        raise DeepSeekCalibrationError("external run configuration differs")
    artifact_path = output_root / "m3-008b-deepseek-calibration.json"
    artifact: dict[str, object] | None = None
    artifact_raw: bytes | None = None
    if artifact_path.exists():
        artifact = _load_external_json(artifact_path)
        validate_calibration_artifact(
            artifact,
            code_revision=expected_code_revision,
            implementation_manifest_hash=expected_implementation_manifest_hash,
            provider_attempt_events=events,
            provider_raw_root=output_root.parent,
            frozen_cases=frozen_cases,
            expected_provider_run_id=expected_provider_run_id,
        )
        artifact_raw = artifact_path.read_bytes()
        sidecar = output_root / "m3-008b-deepseek-calibration.json.sha256"
        expected_sidecar = (
            f"{hashlib.sha256(artifact_raw).hexdigest()}  m3-008b-deepseek-calibration.json\n"
        ).encode("ascii")
        if not sidecar.is_file() or sidecar.read_bytes() != expected_sidecar:
            raise DeepSeekCalibrationError("external artifact/status binding drift")
    status = _load_external_json(output_root / "run-status.json")
    expected_status = expected_run_status(
        configuration=expected_configuration,
        events=events,
        frozen_cases=frozen_cases,
        expected_provider_run_id=expected_provider_run_id,
        raw_root=output_root.parent,
        artifact=artifact,
        artifact_bytes=artifact_raw,
    )
    if status != expected_status:
        raise DeepSeekCalibrationError("external run status differs from ledger")
    cases_by_id = {case.case_id: case for case in frozen_cases}
    for case_id in cast(list[str], status["successful_case_ids"]):
        case = cases_by_id.get(case_id)
        if case is None:
            raise DeepSeekCalibrationError("external successful case is not frozen")
        observed_case = _load_external_json(output_root / f"case-{case.ordinal:03d}-evidence.json")
        expected_case = canonical_case_evidence_document(
            case,
            events,
            output_root.parent,
            frozen_cases=frozen_cases,
            expected_provider_run_id=expected_provider_run_id,
        )
        if observed_case != expected_case:
            raise DeepSeekCalibrationError("external case evidence differs from ledger")
    expected_names = {
        "run-configuration.json",
        "run-status.json",
        "provider-attempt-projection.json",
    } | {
        f"case-{ordinal:03d}-evidence.json"
        for ordinal in range(1, cast(int, status["successful_case_count"]) + 1)
    }
    if artifact is not None:
        expected_names |= {
            "m3-008b-deepseek-calibration.json",
            "m3-008b-deepseek-calibration.json.sha256",
        }
    if {path.name for path in output_root.iterdir()} != expected_names:
        raise DeepSeekCalibrationError("external run file inventory differs")
    return expected


def _load_external_json(path: Path) -> dict[str, object]:
    if not path.is_file() or path.is_symlink():
        raise DeepSeekCalibrationError("external run evidence file is missing")
    with path.open("rb") as handle:
        raw = handle.read(40_000_001)
    if len(raw) > 40_000_000:
        raise DeepSeekCalibrationError("external run evidence exceeds bound")
    try:
        value = json.loads(raw.decode("utf-8", errors="strict"), object_pairs_hook=_unique)
    except (UnicodeDecodeError, json.JSONDecodeError, _DuplicateKeyError):
        raise DeepSeekCalibrationError("external run evidence JSON is invalid") from None
    if type(value) is not dict:
        raise DeepSeekCalibrationError("external run evidence root is invalid")
    return cast(dict[str, object], value)


def persist_provider_event_projection(
    run: PendingCalibrationRun,
    events: Sequence[ProviderAttemptEvent],
    *,
    frozen_cases: Sequence[FrozenCalibrationCase],
    expected_provider_run_id: str,
) -> dict[str, object]:
    projection = provider_event_projection(
        events,
        frozen_cases=frozen_cases,
        expected_provider_run_id=expected_provider_run_id,
        raw_root=run.output_root.parent,
    )
    name = "provider-attempt-projection.json"
    _write_new_json(run.pending_root / name, projection)
    run.raw_body_paths.append(name)
    run.provider_attempt_authority = {
        "projection_hash": projection["projection_hash"],
        "event_count": projection["event_count"],
        "attempt_count": projection["attempt_count"],
        "status": projection["status"],
    }
    return projection


def acceptance_metrics(observations: Sequence[CalibrationObservation]) -> dict[str, object]:
    """Recompute the frozen zero-tolerance and agreement acceptance criteria."""

    if type(observations) not in {list, tuple} or len(observations) != CASE_COUNT:
        raise DeepSeekCalibrationError("calibration requires exactly 36 observations")
    expected_ids = [f"M3-008B-CAL-{index:03d}" for index in range(1, CASE_COUNT + 1)]
    if [item.case.case_id for item in observations] != expected_ids:
        raise DeepSeekCalibrationError("observation order drift")
    confusion = {
        expected.value: {predicted.value: 0 for predicted in SemanticSupport}
        for expected in SemanticSupport
    }
    categories: Counter[str] = Counter()
    agreements = 0
    for item in observations:
        if type(item) is not CalibrationObservation:
            raise DeepSeekCalibrationError("observation type is invalid")
        predicted = item.assessment.result.result
        expected = item.case.human_expected_state
        confusion[expected.value][predicted.value] += 1
        categories[item.case.category] += 1
        agreements += predicted is expected
    state_metrics: dict[str, object] = {}
    recalls_pass = True
    state_counts_pass = True
    for state in SemanticSupport:
        denominator = sum(confusion[state.value].values())
        recall = confusion[state.value][state.value] / denominator if denominator else 0.0
        state_metrics[state.value] = {"n": denominator, "recall": recall}
        state_counts_pass &= denominator >= 8
        recalls_pass &= recall >= 0.75
    rate = agreements / CASE_COUNT
    zero_tolerance = (
        confusion["unsupported"]["supported"] == 0 and confusion["uncertain"]["supported"] == 0
    )
    passed = zero_tolerance and rate >= 0.85 and state_counts_pass and recalls_pass
    return {
        "agreement_count": agreements,
        "denominator": CASE_COUNT,
        "agreement_rate": rate,
        "confusion_matrix": confusion,
        "human_state_metrics": state_metrics,
        "categories_exercised": sorted(categories),
        "category_counts": dict(sorted(categories.items())),
        "zero_tolerance_passed": zero_tolerance,
        "human_state_counts_passed": state_counts_pass,
        "human_state_recall_passed": recalls_pass,
        "accepted": passed,
    }


def _case_evidence_payload(item: CalibrationObservation) -> dict[str, object]:
    if type(item) is not CalibrationObservation:
        raise DeepSeekCalibrationError("calibration observation type is invalid")
    assessment = item.assessment
    expected_request = deepseek_provider_request_bytes(item.case.request)
    expected_input = semantic_evaluation_input_bytes(item.case.request)
    semantic_request = semantic_evaluation_request_bytes(item.case.request)
    if (
        item.case.semantic_request_hash != _sha256(semantic_request)
        or item.case.stage1_admission_identity != item.case.request.stage1_admission.admission_hash
        or item.case.source != item.case.request.source.value
        or item.case.citation_relationship != item.case.request.citation.relationship.value
        or assessment.raw_provider_request_bytes != expected_request
        or assessment.provider_request_hash != _sha256(expected_request)
        or assessment.evaluator_input_hash != _sha256(expected_input)
        or assessment.result.input_digest != item.case.request.input_digest
        or assessment.result.configuration_hash != DEEPSEEK_SEMANTIC_EVALUATION_CONFIGURATION_HASH
    ):
        raise DeepSeekCalibrationError("provider observation binding drift")
    candidate, response_id, usage, structured = parse_deepseek_completed_response(
        assessment.raw_response_envelope_bytes
    )
    expected_result = build_deepseek_semantic_evaluation_result(item.case.request, candidate)
    if (
        response_id != assessment.provider_response_id
        or _sha256(assessment.raw_response_envelope_bytes) != assessment.provider_response_hash
        or structured != assessment.structured_output_bytes
        or _sha256(structured) != assessment.structured_output_hash
        or usage != assessment.usage
        or expected_result != assessment.result
    ):
        raise DeepSeekCalibrationError("provider response evidence drift")
    return {
        "case_id": item.case.case_id,
        "category": item.case.category,
        "source": item.case.source,
        "citation_relationship": item.case.citation_relationship,
        "semantic_request_hash": item.case.semantic_request_hash,
        "semantic_request_hex": semantic_request.hex(),
        "stage1_admission_identity": item.case.stage1_admission_identity,
        "immutable_projection_hash": item.case.immutable_projection_hash,
        "human_expected_state": item.case.human_expected_state.value,
        "human_authority": item.case.human_authority,
        "human_notes": item.case.human_notes,
        "provider_result": assessment.result.result.value,
        "parsed_result": BaseModel.model_dump(assessment.result, mode="json"),
        "disagreement": assessment.result.result is not item.case.human_expected_state,
        "evaluator_input_hash": assessment.evaluator_input_hash,
        "provider_request_hash": assessment.provider_request_hash,
        "raw_provider_request_hex": assessment.raw_provider_request_bytes.hex(),
        "provider_response_id": assessment.provider_response_id,
        "provider_response_hash": assessment.provider_response_hash,
        "raw_provider_response_hex": assessment.raw_response_envelope_bytes.hex(),
        "structured_output_hash": assessment.structured_output_hash,
        "structured_output_hex": assessment.structured_output_bytes.hex(),
        "usage": BaseModel.model_dump(assessment.usage, mode="json"),
        "attempts": assessment.attempts,
        "started_at_utc": assessment.started_at_utc.isoformat(),
        "completed_at_utc": assessment.completed_at_utc.isoformat(),
    }


def canonical_case_evidence_document(
    case: FrozenCalibrationCase,
    events: Sequence[ProviderAttemptEvent],
    raw_root: Path,
    *,
    frozen_cases: Sequence[FrozenCalibrationCase],
    expected_provider_run_id: str,
) -> dict[str, object]:
    """Reconstruct one successful case projection solely from frozen input and ledger/raw."""

    validate_authoritative_provider_events(
        events,
        frozen_cases=frozen_cases,
        expected_provider_run_id=expected_provider_run_id,
    )
    starts = sorted(
        (
            item
            for item in events
            if item.case_ordinal == case.ordinal and item.event_kind == "START"
        ),
        key=lambda item: item.attempt_ordinal,
    )
    successes = [
        item
        for item in events
        if item.case_ordinal == case.ordinal
        and item.event_kind == "TERMINAL"
        and item.disposition == "success"
    ]
    if not starts or len(successes) != 1:
        raise DeepSeekCalibrationError("case lacks one final successful ledger closure")
    terminal = successes[0]
    if terminal.attempt_ordinal != starts[-1].attempt_ordinal:
        raise DeepSeekCalibrationError("case success is not the final attempt")
    if terminal.body_relative_path is None or terminal.completed_at_utc is None:
        raise DeepSeekCalibrationError("case success lacks raw/timestamp binding")
    path = raw_root / terminal.body_relative_path
    with path.open("rb") as handle:
        raw = handle.read(131_073)
    if (
        len(raw) > 131_072
        or terminal.body_hash != _sha256(raw)
        or terminal.body_byte_count != len(raw)
    ):
        raise DeepSeekCalibrationError("case raw response differs from ledger")
    candidate, response_id, usage, structured = parse_deepseek_completed_response(raw)
    result = build_deepseek_semantic_evaluation_result(case.request, candidate)
    request_bytes = deepseek_provider_request_bytes(case.request)
    assessment = DeepSeekSemanticAssessment(
        result=result,
        evaluator_input_hash=_sha256(semantic_evaluation_input_bytes(case.request)),
        provider_request_hash=_sha256(request_bytes),
        raw_provider_request_bytes=request_bytes,
        provider_response_id=response_id,
        provider_response_hash=_sha256(raw),
        raw_response_envelope_bytes=raw,
        structured_output_bytes=structured,
        structured_output_hash=_sha256(structured),
        attempts=len(starts),
        usage=usage,
        started_at_utc=starts[0].started_at_utc,
        completed_at_utc=terminal.completed_at_utc,
    )
    payload = _case_evidence_payload(CalibrationObservation(case, assessment))
    return {
        "schema_version": "m3.stage2.deepseek-case-evidence.v1",
        "ordinal": case.ordinal,
        "evidence": payload,
        "evidence_binding_hash": _sha256(_canonical_bytes(payload)),
    }


def build_calibration_artifact(
    observations: Sequence[CalibrationObservation],
    *,
    completed_at_utc: datetime,
    code_revision: str,
    implementation_manifest_hash: str,
    provider_attempt_events: Sequence[ProviderAttemptEvent],
    provider_raw_root: Path,
    frozen_cases: Sequence[FrozenCalibrationCase],
    expected_provider_run_id: str,
) -> dict[str, object]:
    """Build one exact append-only raw-evidence artifact after all calls finish."""

    if completed_at_utc.tzinfo is None or completed_at_utc.utcoffset() != UTC.utcoffset(
        completed_at_utc
    ):
        raise DeepSeekCalibrationError("completion timestamp must be UTC")
    projection = provider_event_projection(
        provider_attempt_events,
        frozen_cases=frozen_cases,
        expected_provider_run_id=expected_provider_run_id,
        raw_root=provider_raw_root,
    )
    starts = [item for item in provider_attempt_events if item.event_kind == "START"]
    closed_cases = {
        item.case_ordinal
        for item in provider_attempt_events
        if item.event_kind == "TERMINAL" and item.disposition == "success"
    }
    if (
        projection["status"] != "COMPLETE"
        or not provider_attempt_events
        or closed_cases != set(range(1, CASE_COUNT + 1))
    ):
        raise DeepSeekCalibrationError("provider attempt authority is not complete")
    attempts_by_case = Counter(item.case_ordinal for item in starts)
    normalized = tuple(
        CalibrationObservation(
            item.case,
            replace(item.assessment, attempts=attempts_by_case[item.case.ordinal]),
        )
        for item in observations
    )
    metrics = acceptance_metrics(normalized)
    cases = [
        cast(
            dict[str, object],
            canonical_case_evidence_document(
                item.case,
                provider_attempt_events,
                provider_raw_root,
                frozen_cases=frozen_cases,
                expected_provider_run_id=expected_provider_run_id,
            )["evidence"],
        )
        for item in normalized
    ]
    semantic = {
        "schema_version": "m3.stage2.deepseek-calibration.v1",
        "work_item": "M3-008B-STAGE2-DEVELOPMENT-CALIBRATION",
        "holdout_accessed": False,
        "public_data_only": True,
        "configuration": calibration_configuration(
            code_revision=code_revision,
            implementation_manifest_hash=implementation_manifest_hash,
        ),
        "ordered_case_ids": [item.case.case_id for item in normalized],
        "cases": cases,
        "metrics": metrics,
        "provider_attempt_authority": {
            "projection_hash": projection["projection_hash"],
            "event_count": projection["event_count"],
            "attempt_count": projection["attempt_count"],
            "status": projection["status"],
        },
    }
    artifact = {
        **semantic,
        "completed_at_utc": completed_at_utc.isoformat(),
        "artifact_semantic_identity": _sha256(_canonical_bytes(semantic)),
    }
    validate_calibration_artifact(
        artifact,
        code_revision=code_revision,
        implementation_manifest_hash=implementation_manifest_hash,
        provider_attempt_events=provider_attempt_events,
        provider_raw_root=provider_raw_root,
        frozen_cases=frozen_cases,
        expected_provider_run_id=expected_provider_run_id,
    )
    return artifact


def validate_calibration_artifact(
    artifact: Mapping[str, object],
    *,
    code_revision: str,
    implementation_manifest_hash: str,
    provider_attempt_events: Sequence[ProviderAttemptEvent],
    provider_raw_root: Path,
    frozen_cases: Sequence[FrozenCalibrationCase],
    expected_provider_run_id: str,
) -> None:
    """Reparse every byte surface and recompute the saved acceptance evidence."""

    top = {
        "schema_version",
        "work_item",
        "holdout_accessed",
        "public_data_only",
        "configuration",
        "ordered_case_ids",
        "cases",
        "metrics",
        "completed_at_utc",
        "artifact_semantic_identity",
        "provider_attempt_authority",
    }
    if type(artifact) is not dict or set(artifact) != top:
        raise DeepSeekCalibrationError("calibration artifact shape is invalid")
    configuration = artifact["configuration"]
    if type(configuration) is not dict:
        raise DeepSeekCalibrationError("calibration configuration is invalid")
    projection = provider_event_projection(
        provider_attempt_events,
        frozen_cases=frozen_cases,
        expected_provider_run_id=expected_provider_run_id,
        raw_root=provider_raw_root,
    )
    expected_authority = {
        "projection_hash": projection["projection_hash"],
        "event_count": projection["event_count"],
        "attempt_count": projection["attempt_count"],
        "status": projection["status"],
    }
    if (
        artifact["schema_version"] != "m3.stage2.deepseek-calibration.v1"
        or artifact["work_item"] != "M3-008B-STAGE2-DEVELOPMENT-CALIBRATION"
        or artifact["holdout_accessed"] is not False
        or artifact["public_data_only"] is not True
        or artifact["provider_attempt_authority"] != expected_authority
        or configuration
        != calibration_configuration(
            code_revision=code_revision,
            implementation_manifest_hash=implementation_manifest_hash,
        )
    ):
        raise DeepSeekCalibrationError("calibration artifact boundary drift")
    semantic = dict(artifact)
    identity = semantic.pop("artifact_semantic_identity")
    semantic.pop("completed_at_utc")
    if identity != _sha256(_canonical_bytes(semantic)):
        raise DeepSeekCalibrationError("calibration artifact identity drift")
    _utc(artifact["completed_at_utc"])
    cases = artifact["cases"]
    ordered = artifact["ordered_case_ids"]
    if type(cases) is not list or type(ordered) is not list or len(cases) != CASE_COUNT:
        raise DeepSeekCalibrationError("calibration artifact cases are invalid")
    expected_ids = [f"M3-008B-CAL-{index:03d}" for index in range(1, CASE_COUNT + 1)]
    if ordered != expected_ids:
        raise DeepSeekCalibrationError("calibration artifact order drift")
    minimal: list[tuple[str, str, str]] = []
    attempts_by_case = Counter(
        item.case_ordinal for item in provider_attempt_events if item.event_kind == "START"
    )
    starts_by_case = {
        ordinal: [
            item
            for item in provider_attempt_events
            if item.event_kind == "START" and item.case_ordinal == ordinal
        ]
        for ordinal in range(1, CASE_COUNT + 1)
    }
    success_by_case = {
        item.case_ordinal: item
        for item in provider_attempt_events
        if item.event_kind == "TERMINAL" and item.disposition == "success"
    }
    inventory: list[dict[str, object]] = []
    response_ids: set[str] = set()
    semantic_request_hashes: set[str] = set()
    case_fields = {
        "case_id",
        "category",
        "source",
        "citation_relationship",
        "semantic_request_hash",
        "semantic_request_hex",
        "stage1_admission_identity",
        "immutable_projection_hash",
        "human_expected_state",
        "human_authority",
        "human_notes",
        "provider_result",
        "parsed_result",
        "disagreement",
        "evaluator_input_hash",
        "provider_request_hash",
        "raw_provider_request_hex",
        "provider_response_id",
        "provider_response_hash",
        "raw_provider_response_hex",
        "structured_output_hash",
        "structured_output_hex",
        "usage",
        "attempts",
        "started_at_utc",
        "completed_at_utc",
    }
    for index, value in enumerate(cases, start=1):
        if type(value) is not dict or set(value) != case_fields:
            raise DeepSeekCalibrationError("calibration case evidence shape is invalid")
        case_id = expected_ids[index - 1]
        if value["case_id"] != case_id:
            raise DeepSeekCalibrationError("calibration case identity drift")
        if value["attempts"] != attempts_by_case[index]:
            raise DeepSeekCalibrationError("calibration case attempts differ from ledger")
        if any(
            item.request_hash != value["provider_request_hash"] for item in starts_by_case[index]
        ):
            raise DeepSeekCalibrationError("calibration provider request differs from ledger")
        if value["semantic_request_hash"] in semantic_request_hashes:
            raise DeepSeekCalibrationError("duplicate calibration semantic request")
        semantic_request_hashes.add(cast(str, value["semantic_request_hash"]))
        request_raw = _hex_bytes(value["semantic_request_hex"], 1_000_000)
        request = parse_semantic_evaluation_request(request_raw)
        if (
            semantic_evaluation_request_bytes(request) != request_raw
            or _sha256(request_raw) != value["semantic_request_hash"]
            or request.stage1_admission.admission_hash != value["stage1_admission_identity"]
            or value["source"] != request.source.value
            or value["citation_relationship"] != request.citation.relationship.value
        ):
            raise DeepSeekCalibrationError("calibration semantic request drift")
        provider_request = _hex_bytes(value["raw_provider_request_hex"], 262_144)
        if (
            _sha256(semantic_evaluation_input_bytes(request)) != value["evaluator_input_hash"]
            or provider_request != deepseek_provider_request_bytes(request)
            or _sha256(provider_request) != value["provider_request_hash"]
        ):
            raise DeepSeekCalibrationError("calibration provider request drift")
        response_raw = _hex_bytes(value["raw_provider_response_hex"], 131_072)
        success = success_by_case.get(index)
        if (
            success is None
            or success.body_hash != value["provider_response_hash"]
            or success.body_relative_path is None
            or (provider_raw_root / success.body_relative_path).read_bytes() != response_raw
        ):
            raise DeepSeekCalibrationError("calibration provider response differs from ledger")
        candidate, response_id, usage, structured = parse_deepseek_completed_response(response_raw)
        stored_structured = _hex_bytes(value["structured_output_hex"], 16_384)
        expected_result = build_deepseek_semantic_evaluation_result(request, candidate)
        result_document = value["parsed_result"]
        if type(result_document) is not dict or set(result_document) != set(
            SemanticEvaluationResult.model_fields
        ):
            raise DeepSeekCalibrationError("calibration parsed result is invalid") from None
        result_codes = result_document["rationale_codes"]
        if type(result_codes) is not list or any(type(code) is not str for code in result_codes):
            raise DeepSeekCalibrationError("calibration parsed result is invalid")
        try:
            parsed_result = SemanticEvaluationResult(
                **{
                    **result_document,
                    "result": _support(result_document["result"]),
                    "rationale_codes": tuple(SemanticRationaleCode(code) for code in result_codes),
                }
            )
        except ValueError:
            raise DeepSeekCalibrationError("calibration parsed result is invalid") from None
        try:
            stored_usage = SemanticEvaluationUsage.model_validate(value["usage"])
        except ValueError:
            raise DeepSeekCalibrationError("calibration parsed usage is invalid") from None
        if (
            parsed_result != expected_result
            or value["provider_result"] != expected_result.result.value
            or response_id != value["provider_response_id"]
            or _sha256(response_raw) != value["provider_response_hash"]
            or _sha256(structured) != value["structured_output_hash"]
            or stored_structured != structured
            or stored_usage != usage
            or type(value["attempts"]) is not int
            or not 1 <= value["attempts"] <= 3
        ):
            raise DeepSeekCalibrationError("calibration provider response drift")
        if response_id in response_ids:
            raise DeepSeekCalibrationError("duplicate provider response identity")
        response_ids.add(response_id)
        human = _support(value["human_expected_state"])
        if (
            value["human_authority"] != "project_owner"
            or type(value["human_notes"]) is not str
            or not value["human_notes"]
            or value["disagreement"] is not (expected_result.result is not human)
        ):
            raise DeepSeekCalibrationError("calibration human binding drift")
        started = _utc(value["started_at_utc"])
        completed = _utc(value["completed_at_utc"])
        if completed < started:
            raise DeepSeekCalibrationError("calibration timestamps are reversed")
        category = value["category"]
        if type(category) is not str or not category:
            raise DeepSeekCalibrationError("calibration category is invalid")
        minimal.append((human.value, expected_result.result.value, category))
        inventory.append(
            {
                "case_id": value["case_id"],
                "category": value["category"],
                "source": value["source"],
                "citation_relationship": value["citation_relationship"],
                "semantic_request_hash": value["semantic_request_hash"],
                "stage1_admission_identity": value["stage1_admission_identity"],
                "immutable_projection_hash": value["immutable_projection_hash"],
                "human_expected_state": value["human_expected_state"],
            }
        )
    if _sha256(_canonical_bytes(inventory)) != FROZEN_CASE_INVENTORY_IDENTITY:
        raise DeepSeekCalibrationError("calibration ordered case inventory drift")
    if tuple(sorted(Counter(item["category"] for item in inventory).items())) != (
        FROZEN_CATEGORY_COUNTS
    ):
        raise DeepSeekCalibrationError("calibration frozen category counts drift")
    if artifact["metrics"] != _artifact_metrics(minimal):
        raise DeepSeekCalibrationError("calibration metrics drift")


def begin_pending_calibration_run(
    output_root: Path,
    *,
    code_revision: str,
    implementation_manifest_hash: str,
) -> PendingCalibrationRun:
    """Create the sole pending run after caller completes every zero-effect preflight."""

    configuration = calibration_configuration(
        code_revision=code_revision,
        implementation_manifest_hash=implementation_manifest_hash,
    )
    validate_output_target(output_root)
    pending = output_root.parent / f".{output_root.name}.pending"
    pending.mkdir()
    run = PendingCalibrationRun(
        configuration=configuration,
        output_root=output_root,
        pending_root=pending,
    )
    try:
        _write_new_json(
            pending / "run-configuration.json",
            {
                "schema_version": "m3.stage2.deepseek-run-configuration.v1",
                "status": "PENDING",
                "configuration": configuration,
                "configuration_binding_hash": _sha256(_canonical_bytes(configuration)),
            },
        )
    except Exception:
        if pending.exists() and not pending.is_symlink() and not any(pending.iterdir()):
            pending.rmdir()
        raise
    return run


def persist_successful_calibration_case(
    run: PendingCalibrationRun,
    observation: CalibrationObservation,
    *,
    provider_attempt_events: Sequence[ProviderAttemptEvent],
    provider_raw_root: Path,
    frozen_cases: Sequence[FrozenCalibrationCase],
    expected_provider_run_id: str,
) -> None:
    """Fsync one successful exact case before the next provider call begins."""

    _validate_pending_run(run)
    expected_ordinal = len(run.successful_case_ids) + 1
    if observation.case.ordinal != expected_ordinal:
        raise DeepSeekCalibrationError("pending case order drift")
    run.attempted_case_ids.append(observation.case.case_id)
    document = canonical_case_evidence_document(
        observation.case,
        provider_attempt_events,
        provider_raw_root,
        frozen_cases=frozen_cases,
        expected_provider_run_id=expected_provider_run_id,
    )
    try:
        _write_new_json(
            run.pending_root / f"case-{expected_ordinal:03d}-evidence.json",
            document,
        )
    except Exception:
        run.attempted_case_ids.pop()
        raise
    run.successful_case_ids.append(observation.case.case_id)


def reconcile_case_evidence(
    run: PendingCalibrationRun,
    frozen_cases: Sequence[FrozenCalibrationCase],
    provider_attempt_events: Sequence[ProviderAttemptEvent],
    provider_raw_root: Path,
    *,
    expected_provider_run_id: str,
) -> None:
    """Rebuild only deterministic case projections from ledger/raw, never resend."""

    successful_ordinals = sorted(
        {
            item.case_ordinal
            for item in provider_attempt_events
            if item.event_kind == "TERMINAL" and item.disposition == "success"
        }
    )
    if successful_ordinals != list(range(1, len(successful_ordinals) + 1)):
        raise DeepSeekCalibrationError("successful case projections are not a prefix")
    by_ordinal = {case.ordinal: case for case in frozen_cases}
    for ordinal in successful_ordinals:
        case = by_ordinal.get(ordinal)
        if case is None:
            raise DeepSeekCalibrationError("ledger success has no frozen case")
        document = canonical_case_evidence_document(
            case,
            provider_attempt_events,
            provider_raw_root,
            frozen_cases=frozen_cases,
            expected_provider_run_id=expected_provider_run_id,
        )
        _write_new_json(run.pending_root / f"case-{ordinal:03d}-evidence.json", document)
        run.attempted_case_ids.append(case.case_id)
        run.successful_case_ids.append(case.case_id)


def persist_raw_calibration_attempt(
    run: PendingCalibrationRun,
    case: FrozenCalibrationCase,
    observation: DeepSeekRawSemanticObservation,
) -> None:
    """Fsync exact raw request/response evidence before strict provider parsing."""

    _validate_pending_run(run)
    expected_ordinal = len(run.attempted_case_ids) + 1
    if case.ordinal != expected_ordinal:
        raise DeepSeekCalibrationError("pending raw attempt order drift")
    payload = _raw_attempt_payload(case, observation)
    _write_new_json(
        run.pending_root / f"case-{expected_ordinal:03d}-raw-observation.json",
        {
            "schema_version": "m3.stage2.deepseek-raw-observation.v1",
            "ordinal": expected_ordinal,
            "observation": payload,
            "observation_binding_hash": _sha256(_canonical_bytes(payload)),
        },
    )
    run.attempted_case_ids.append(case.case_id)


def _raw_attempt_payload(
    case: FrozenCalibrationCase,
    observation: DeepSeekRawSemanticObservation,
) -> dict[str, object]:
    if type(case) is not FrozenCalibrationCase or type(observation) is not (
        DeepSeekRawSemanticObservation
    ):
        raise DeepSeekCalibrationError("raw observation type is invalid")
    semantic_request = semantic_evaluation_request_bytes(case.request)
    evaluator_input = semantic_evaluation_input_bytes(case.request)
    provider_request = deepseek_provider_request_bytes(case.request)
    if (
        case.semantic_request_hash != _sha256(semantic_request)
        or case.stage1_admission_identity != case.request.stage1_admission.admission_hash
        or case.source != case.request.source.value
        or case.citation_relationship != case.request.citation.relationship.value
        or observation.evaluator_input_hash != _sha256(evaluator_input)
        or observation.provider_request_hash != _sha256(provider_request)
        or observation.raw_provider_request_bytes != provider_request
        or type(observation.raw_response_envelope_bytes) is not bytes
        or not observation.raw_response_envelope_bytes
        or len(observation.raw_response_envelope_bytes) > 131_072
        or observation.provider_response_hash != _sha256(observation.raw_response_envelope_bytes)
        or type(observation.status_code) is not int
        or observation.status_code != 200
        or type(observation.attempts) is not int
        or not 1 <= observation.attempts <= 3
        or not isinstance(observation.started_at_utc, datetime)
        or observation.started_at_utc.tzinfo is None
        or observation.started_at_utc.utcoffset() != UTC.utcoffset(observation.started_at_utc)
        or not isinstance(observation.completed_at_utc, datetime)
        or observation.completed_at_utc.tzinfo is None
        or observation.completed_at_utc.utcoffset() != UTC.utcoffset(observation.completed_at_utc)
        or observation.completed_at_utc < observation.started_at_utc
    ):
        raise DeepSeekCalibrationError("raw observation binding drift")
    return {
        "case_id": case.case_id,
        "semantic_request_hash": case.semantic_request_hash,
        "stage1_admission_identity": case.stage1_admission_identity,
        "evaluator_input_hash": observation.evaluator_input_hash,
        "provider_request_hash": observation.provider_request_hash,
        "raw_provider_request_hex": observation.raw_provider_request_bytes.hex(),
        "provider_response_hash": observation.provider_response_hash,
        "raw_provider_response_hex": observation.raw_response_envelope_bytes.hex(),
        "http_status_code": observation.status_code,
        "attempts": observation.attempts,
        "started_at_utc": observation.started_at_utc.isoformat(),
        "completed_at_utc": observation.completed_at_utc.isoformat(),
        "provider_usage_validated": False,
        "provider_result_validated": False,
    }


def publish_failed_calibration_run(
    run: PendingCalibrationRun,
    *,
    failed_case: FrozenCalibrationCase | None,
    error: Exception,
    provider_attempt_events: Sequence[ProviderAttemptEvent],
    provider_raw_root: Path,
    frozen_cases: Sequence[FrozenCalibrationCase],
    expected_provider_run_id: str,
) -> None:
    """Publish retained prior successes and redacted failure metadata, never a PASS."""

    _validate_pending_run(run)
    projection = provider_event_projection(
        provider_attempt_events,
        frozen_cases=frozen_cases,
        expected_provider_run_id=expected_provider_run_id,
        raw_root=provider_raw_root,
    )
    run.provider_attempt_authority = {
        "projection_hash": projection["projection_hash"],
        "event_count": projection["event_count"],
        "attempt_count": projection["attempt_count"],
        "status": projection["status"],
    }
    del failed_case, error
    status = expected_run_status(
        configuration=run.configuration,
        events=provider_attempt_events,
        frozen_cases=frozen_cases,
        expected_provider_run_id=expected_provider_run_id,
        raw_root=provider_raw_root,
        artifact=None,
        artifact_bytes=None,
    )
    _write_new_json(run.pending_root / "run-status.json", status)
    run.pending_root.rename(run.output_root)


def publish_successful_calibration_run(
    run: PendingCalibrationRun,
    artifact: Mapping[str, object],
    *,
    provider_attempt_events: Sequence[ProviderAttemptEvent],
    provider_raw_root: Path,
    frozen_cases: Sequence[FrozenCalibrationCase],
    expected_provider_run_id: str,
) -> None:
    """Publish a fully reparsed 36-case artifact and its prior per-case evidence."""

    _validate_pending_run(run)
    code_revision = run.configuration["code_revision"]
    implementation_manifest_hash = run.configuration["implementation_manifest_hash"]
    if type(code_revision) is not str or type(implementation_manifest_hash) is not str:
        raise DeepSeekCalibrationError("pending code identity drift")
    validate_calibration_artifact(
        artifact,
        code_revision=code_revision,
        implementation_manifest_hash=implementation_manifest_hash,
        provider_attempt_events=provider_attempt_events,
        provider_raw_root=provider_raw_root,
        frozen_cases=frozen_cases,
        expected_provider_run_id=expected_provider_run_id,
    )
    ordered = artifact["ordered_case_ids"]
    if (
        ordered != run.successful_case_ids
        or run.attempted_case_ids != run.successful_case_ids
        or len(run.successful_case_ids) != CASE_COUNT
    ):
        raise DeepSeekCalibrationError("pending successes differ from final artifact")
    metrics = artifact["metrics"]
    if type(metrics) is not dict or type(metrics.get("accepted")) is not bool:
        raise DeepSeekCalibrationError("final acceptance evidence is invalid")
    raw = _canonical_bytes(dict(artifact))
    artifact_path = run.pending_root / "m3-008b-deepseek-calibration.json"
    sidecar = f"{hashlib.sha256(raw).hexdigest()}  {artifact_path.name}\n".encode("ascii")
    sidecar_path = run.pending_root / f"{artifact_path.name}.sha256"
    status_path = run.pending_root / "run-status.json"
    status = expected_run_status(
        configuration=run.configuration,
        events=provider_attempt_events,
        frozen_cases=frozen_cases,
        expected_provider_run_id=expected_provider_run_id,
        raw_root=provider_raw_root,
        artifact=artifact,
        artifact_bytes=raw,
    )
    created: list[Path] = []
    try:
        _write_new_bytes(artifact_path, raw)
        created.append(artifact_path)
        _write_new_bytes(sidecar_path, sidecar)
        created.append(sidecar_path)
        _write_new_json(status_path, status)
        created.append(status_path)
        run.pending_root.rename(run.output_root)
    except Exception:
        if run.pending_root.exists() and not run.pending_root.is_symlink():
            for path in reversed(created):
                if path.is_file() and not path.is_symlink():
                    path.unlink()
        raise


def write_calibration_artifact(
    artifact: Mapping[str, object],
    output_root: Path,
    *,
    code_revision: str,
    implementation_manifest_hash: str,
    provider_attempt_events: Sequence[ProviderAttemptEvent],
    provider_raw_root: Path,
    frozen_cases: Sequence[FrozenCalibrationCase],
    expected_provider_run_id: str,
) -> None:
    """Atomically publish one absent external directory; overwrite is impossible."""

    validate_calibration_artifact(
        artifact,
        code_revision=code_revision,
        implementation_manifest_hash=implementation_manifest_hash,
        provider_attempt_events=provider_attempt_events,
        provider_raw_root=provider_raw_root,
        frozen_cases=frozen_cases,
        expected_provider_run_id=expected_provider_run_id,
    )
    validate_output_target(output_root)
    parent = output_root.parent
    pending = parent / f".{output_root.name}.pending"
    pending.mkdir()
    raw = _canonical_bytes(dict(artifact))
    try:
        artifact_path = pending / "m3-008b-deepseek-calibration.json"
        with artifact_path.open("xb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        sidecar = f"{hashlib.sha256(raw).hexdigest()}  {artifact_path.name}\n".encode("ascii")
        with (pending / f"{artifact_path.name}.sha256").open("xb") as handle:
            handle.write(sidecar)
            handle.flush()
            os.fsync(handle.fileno())
        pending.rename(output_root)
    except Exception:
        if pending.exists() and not pending.is_symlink():
            for child in pending.iterdir():
                if child.is_file() and not child.is_symlink():
                    child.unlink()
            pending.rmdir()
        raise


def validate_output_target(output_root: Path) -> None:
    """Fail before provider effects when append-only output cannot be safely created."""

    if not output_root.is_absolute() or output_root.resolve(strict=False).is_relative_to(
        REPOSITORY_ROOT
    ):
        raise DeepSeekCalibrationError("calibration output must be external")
    if output_root.exists() or output_root.is_symlink():
        raise DeepSeekCalibrationError("calibration output already exists")
    parent = output_root.parent
    _validate_external_ancestry(parent, output_root)
    ancestor = parent
    while True:
        if ancestor.exists() and ancestor.is_symlink():
            raise DeepSeekCalibrationError("symlinked output ancestry is forbidden")
        if ancestor == ancestor.parent:
            break
        ancestor = ancestor.parent
    if not parent.is_dir():
        raise DeepSeekCalibrationError("calibration output parent must already exist")
    pending = parent / f".{output_root.name}.pending"
    if pending.exists() or pending.is_symlink():
        raise DeepSeekCalibrationError("calibration pending output already exists")


def _validate_external_ancestry(root: Path, target: Path) -> None:
    if not root.is_absolute() or not target.is_absolute():
        raise DeepSeekCalibrationError("external path must be absolute")
    resolved_root = root.resolve(strict=True)
    resolved_target = target.resolve(strict=False)
    if not resolved_target.is_relative_to(resolved_root):
        raise DeepSeekCalibrationError("external path escapes intended root")
    current = target
    while True:
        if current.exists() or current.is_symlink():
            info = os.lstat(current)
            attributes = getattr(info, "st_file_attributes", 0)
            reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
            if current.is_symlink() or attributes & reparse_flag:
                raise DeepSeekCalibrationError("external path ancestry is reparse-backed")
        if current == root or current == current.parent:
            break
        current = current.parent


def _validate_pending_run(run: PendingCalibrationRun) -> None:
    if type(run) is not PendingCalibrationRun:
        raise DeepSeekCalibrationError("pending run type is invalid")
    if run.output_root.exists() or run.output_root.is_symlink():
        raise DeepSeekCalibrationError("pending run output target is no longer absent")
    if not run.pending_root.is_dir() or run.pending_root.is_symlink():
        raise DeepSeekCalibrationError("pending run directory is invalid")
    if run.pending_root != run.output_root.parent / f".{run.output_root.name}.pending":
        raise DeepSeekCalibrationError("pending run path drift")
    expected_attempted = [
        f"M3-008B-CAL-{index:03d}" for index in range(1, len(run.attempted_case_ids) + 1)
    ]
    expected_successful = expected_attempted[: len(run.successful_case_ids)]
    if run.attempted_case_ids != expected_attempted:
        raise DeepSeekCalibrationError("pending attempted case identity drift")
    if run.successful_case_ids != expected_successful:
        raise DeepSeekCalibrationError("pending successful case identity drift")
    expected_files = (
        {"run-configuration.json"}
        | {
            f"case-{index:03d}-evidence.json"
            for index in range(1, len(run.successful_case_ids) + 1)
        }
        | set(run.raw_body_paths)
    )
    children = tuple(run.pending_root.iterdir())
    if {child.name for child in children} != expected_files or any(
        not child.is_file() or child.is_symlink() for child in children
    ):
        raise DeepSeekCalibrationError("pending run file inventory drift")


def _redacted_failure(error: Exception) -> dict[str, object]:
    code = "internal_failure"
    status: int | None = None
    if type(error) is DeepSeekSemanticEvaluatorError:
        observed_code = object.__getattribute__(error, "code")
        observed_status = object.__getattribute__(error, "status_code")
        if hasattr(observed_code, "value") and type(observed_code.value) is str:
            code = observed_code.value
        if type(observed_status) is int and 100 <= observed_status <= 599:
            status = observed_status
    elif type(error) is DeepSeekCalibrationError:
        code = "calibration_contract_error"
    return {"code": code, "status_code": status}


def _write_new_json(path: Path, payload: Mapping[str, object]) -> None:
    _write_new_bytes(path, _canonical_bytes(dict(payload)))


def _write_new_bytes(path: Path, raw: bytes) -> None:
    if type(raw) is not bytes or len(raw) > 40_000_000:
        raise DeepSeekCalibrationError("run evidence bytes are invalid")
    try:
        with path.open("xb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        if path.is_file() and not path.is_symlink():
            path.unlink()
        raise


def _support(value: object) -> SemanticSupport:
    if type(value) is not str:
        raise DeepSeekCalibrationError("human state is invalid")
    try:
        return SemanticSupport(value)
    except ValueError:
        raise DeepSeekCalibrationError("human state is invalid") from None


def _case_inventory_identity(cases: Sequence[FrozenCalibrationCase]) -> str:
    inventory = [
        {
            "case_id": case.case_id,
            "category": case.category,
            "source": case.source,
            "citation_relationship": case.citation_relationship,
            "semantic_request_hash": case.semantic_request_hash,
            "stage1_admission_identity": case.stage1_admission_identity,
            "immutable_projection_hash": case.immutable_projection_hash,
            "human_expected_state": case.human_expected_state.value,
        }
        for case in cases
    ]
    return _sha256(_canonical_bytes(inventory))


def _code_revision(value: object) -> str:
    if (
        type(value) is not str
        or len(value) != 40
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise DeepSeekCalibrationError("code revision must be exact lowercase 40-hex")
    return value


def _digest(value: object, field: str) -> str:
    if (
        type(value) is not str
        or len(value) != 71
        or not value.startswith("sha256:")
        or any(character not in "0123456789abcdef" for character in value[7:])
    ):
        raise DeepSeekCalibrationError(f"{field} must be a lowercase sha256 digest")
    return value


def _artifact_metrics(cases: Sequence[tuple[str, str, str]]) -> dict[str, object]:
    confusion = {
        human.value: {predicted.value: 0 for predicted in SemanticSupport}
        for human in SemanticSupport
    }
    categories: Counter[str] = Counter()
    agreements = 0
    for human, predicted, category in cases:
        confusion[human][predicted] += 1
        categories[category] += 1
        agreements += human == predicted
    state_metrics: dict[str, object] = {}
    counts_pass = True
    recalls_pass = True
    for state in SemanticSupport:
        denominator = sum(confusion[state.value].values())
        recall = confusion[state.value][state.value] / denominator if denominator else 0.0
        state_metrics[state.value] = {"n": denominator, "recall": recall}
        counts_pass &= denominator >= 8
        recalls_pass &= recall >= 0.75
    zero = confusion["unsupported"]["supported"] == 0 and confusion["uncertain"]["supported"] == 0
    rate = agreements / CASE_COUNT
    return {
        "agreement_count": agreements,
        "denominator": CASE_COUNT,
        "agreement_rate": rate,
        "confusion_matrix": confusion,
        "human_state_metrics": state_metrics,
        "categories_exercised": sorted(categories),
        "category_counts": dict(sorted(categories.items())),
        "zero_tolerance_passed": zero,
        "human_state_counts_passed": counts_pass,
        "human_state_recall_passed": recalls_pass,
        "accepted": zero and rate >= 0.85 and counts_pass and recalls_pass,
    }


def _hex_bytes(value: object, maximum: int) -> bytes:
    if type(value) is not str or len(value) > maximum * 2:
        raise DeepSeekCalibrationError("calibration byte evidence is invalid")
    try:
        raw = bytes.fromhex(value)
    except ValueError:
        raise DeepSeekCalibrationError("calibration byte evidence is invalid") from None
    if len(raw) > maximum or raw.hex() != value:
        raise DeepSeekCalibrationError("calibration byte evidence is invalid")
    return raw


def _utc(value: object) -> datetime:
    if type(value) is not str:
        raise DeepSeekCalibrationError("calibration timestamp is invalid")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        raise DeepSeekCalibrationError("calibration timestamp is invalid") from None
    if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(parsed):
        raise DeepSeekCalibrationError("calibration timestamp must be UTC")
    return parsed


class _DuplicateKeyError(ValueError):
    pass


def _unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise _DuplicateKeyError
        value[key] = item
    return value
