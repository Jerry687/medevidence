"""Append-only Qwen semantic port with exact profile and raw-response replay."""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any, Protocol, cast

from pydantic import BaseModel

from medevidence.domain import canonical_json
from medevidence.infrastructure.deepseek_semantic_cache import (
    SemanticCachePortError,
    SemanticCachePortErrorCode,
    _retry_delay,
    _verify_stage1,
)
from medevidence.infrastructure.qwen_semantic_evaluator import (
    QWEN_TOTAL_DEADLINE_SECONDS,
    QwenChatSemanticEvaluatorV2,
    QwenObservation,
    QwenSemanticError,
    finalize_qwen_observation,
    qwen_provider_request_semantic_v2_bytes,
)
from medevidence.persistence.semantic_cache import (
    MAX_SEMANTIC_ATTEMPTS,
    SEMANTIC_CACHE_SCHEMA_VERSION,
    SemanticCacheConflict,
    SemanticCacheEvent,
    SemanticCacheIntegrityError,
    SemanticCacheLease,
    make_semantic_cache_event,
)
from medevidence.tools.report_validation_v3 import (
    M3_VALIDATION_CONFIGURATION_V4,
    M3_VALIDATION_POLICY_V4,
    RuntimeSemanticProfileIdentityV3,
)
from medevidence.tools.semantic_evaluation import (
    QWEN_SEMANTIC_V2_PROVIDER_CONFIGURATION_HASH,
    QWEN_SEMANTIC_V2_PROVIDER_CONFIGURATION_VERSION,
    QWEN_SEMANTIC_V2_PROVIDER_METHOD,
    SEMANTIC_EVALUATION_V2_CONFIGURATION_HASH_V3,
    SemanticEvaluationRequest,
    SemanticEvaluationResultV2,
    parse_semantic_evaluation_request,
    reconstruct_semantic_evaluation_result_v2,
    semantic_evaluation_request_bytes,
)


class SemanticCacheJournal(Protocol):
    def acquire_operation_lease(self, operation_id: str) -> SemanticCacheLease: ...
    def release_operation_lease(self, lease: SemanticCacheLease) -> None: ...
    def append(self, event: SemanticCacheEvent) -> SemanticCacheEvent: ...
    def list_events(self, operation_id: str) -> tuple[SemanticCacheEvent, ...]: ...


class Stage1ReceiptReader(Protocol):
    def load_stage1_receipt(self, receipt_id: str) -> Mapping[str, object] | None: ...


def _sha(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _payload(value: Mapping[str, object]) -> bytes:
    return canonical_json(dict(value)).encode("utf-8")


def _decoded(raw: bytes) -> dict[str, Any]:
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeError, ValueError, RecursionError):
        raise SemanticCachePortError(SemanticCachePortErrorCode.CACHE_INTEGRITY) from None
    if type(value) is not dict or _payload(value) != raw:
        raise SemanticCachePortError(SemanticCachePortErrorCode.CACHE_INTEGRITY)
    return cast(dict[str, Any], value)


def qwen_semantic_evaluation_operation_id(
    request: SemanticEvaluationRequest, endpoint_identity: str
) -> str:
    """Separate Qwen idempotency namespace from all historical DeepSeek attempts."""

    content = {
        "schema_version": "m3.runtime-semantic-operation.v1",
        "run_id": request.run_id,
        "citation_id": request.citation.citation_id,
        "input_digest": request.input_digest,
        "request_content_hash": request.request_content_hash,
        "stage1_admission_hash": request.stage1_admission.admission_hash,
        "provider_method": QWEN_SEMANTIC_V2_PROVIDER_METHOD,
        "provider_configuration_version": QWEN_SEMANTIC_V2_PROVIDER_CONFIGURATION_VERSION,
        "provider_configuration_hash": QWEN_SEMANTIC_V2_PROVIDER_CONFIGURATION_HASH,
        "endpoint_identity": endpoint_identity,
    }
    return "semantic-evaluation-operation:sha256:" + hashlib.sha256(_payload(content)).hexdigest()


def _event(
    request: SemanticEvaluationRequest,
    operation_id: str,
    attempt: int,
    kind: str,
    payload: Mapping[str, object],
    started: datetime,
    *,
    start_id: str | None = None,
    raw_id: str | None = None,
    result_id: str | None = None,
    raw: bytes | None = None,
    completed: datetime | None = None,
    disposition: str | None = None,
) -> SemanticCacheEvent:
    payload_bytes = _payload(payload)
    return make_semantic_cache_event(
        schema_version=SEMANTIC_CACHE_SCHEMA_VERSION,
        operation_id=operation_id,
        run_id=request.run_id,
        citation_id=request.citation.citation_id,
        request_content_hash=request.request_content_hash,
        provider_configuration_version=QWEN_SEMANTIC_V2_PROVIDER_CONFIGURATION_VERSION,
        provider_configuration_hash=QWEN_SEMANTIC_V2_PROVIDER_CONFIGURATION_HASH,
        attempt_ordinal=attempt,
        event_slot={"START": 0, "RAW": 1, "RESULT": 2, "TERMINAL": 3}[kind],
        event_kind=kind,
        start_event_id=start_id,
        raw_event_id=raw_id,
        result_event_id=result_id,
        payload_hash=_sha(payload_bytes),
        payload_bytes=payload_bytes,
        raw_body_hash=None if raw is None else _sha(raw),
        raw_body_bytes=raw,
        started_at_utc=started,
        completed_at_utc=completed,
        disposition=disposition,
        error_code=None if disposition in (None, "success") else disposition,
    )


def _disposition(observation: QwenObservation) -> str:
    if observation.credential_echo:
        return "credential_echo"
    if observation.transport_error == "deadline_exceeded":
        return "deadline_exceeded"
    if observation.transport_error in ("response_invalid", "response_too_large"):
        return observation.transport_error
    if observation.transport_error is not None or not observation.body_complete:
        return "transport_unavailable"
    status = observation.http_status
    if status in (401, 403):
        return "authentication_failed"
    if status in (429, 500, 502, 503, 504):
        return "retryable_status"
    if status != 200:
        return "provider_rejected"
    return "success"


class DurableQwenSemanticEvaluationPortV2:
    """One Qwen operation with START before HTTP and RAW before interpretation."""

    __slots__ = ("_clock", "_evaluator", "_journal", "_sleep", "_stage1")

    def __init__(
        self,
        *,
        evaluator: QwenChatSemanticEvaluatorV2,
        journal: SemanticCacheJournal,
        stage1_receipts: Stage1ReceiptReader,
        monotonic_clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        if type(evaluator) is not QwenChatSemanticEvaluatorV2:
            raise TypeError("Qwen semantic cache needs the fixed evaluator")
        self._evaluator = evaluator
        self._journal = journal
        self._stage1 = stage1_receipts
        self._clock = monotonic_clock
        self._sleep = sleeper

    @property
    def profile_identity(self) -> RuntimeSemanticProfileIdentityV3:
        return RuntimeSemanticProfileIdentityV3(
            method=QWEN_SEMANTIC_V2_PROVIDER_METHOD,
            semantic_configuration_hash=SEMANTIC_EVALUATION_V2_CONFIGURATION_HASH_V3,
            provider_configuration_version=QWEN_SEMANTIC_V2_PROVIDER_CONFIGURATION_VERSION,
            provider_configuration_hash=QWEN_SEMANTIC_V2_PROVIDER_CONFIGURATION_HASH,
        )

    def _events(
        self, operation_id: str, request: SemanticEvaluationRequest
    ) -> tuple[SemanticCacheEvent, ...]:
        try:
            events = self._journal.list_events(operation_id)
        except SemanticCacheIntegrityError:
            raise SemanticCachePortError(SemanticCachePortErrorCode.CACHE_INTEGRITY) from None
        expected = (
            operation_id,
            request.run_id,
            request.citation.citation_id,
            request.request_content_hash,
            QWEN_SEMANTIC_V2_PROVIDER_CONFIGURATION_VERSION,
            QWEN_SEMANTIC_V2_PROVIDER_CONFIGURATION_HASH,
        )
        if any(
            (
                item.operation_id,
                item.run_id,
                item.citation_id,
                item.request_content_hash,
                item.provider_configuration_version,
                item.provider_configuration_hash,
            )
            != expected
            for item in events
        ):
            raise SemanticCachePortError(SemanticCachePortErrorCode.CACHE_INTEGRITY)
        if events != tuple(
            sorted(events, key=lambda item: (item.attempt_ordinal, item.event_slot))
        ):
            raise SemanticCachePortError(SemanticCachePortErrorCode.CACHE_INTEGRITY)
        return events

    def _replay(
        self,
        request: SemanticEvaluationRequest,
        events: tuple[SemanticCacheEvent, ...],
        *,
        retry_owned_ordinals: frozenset[int],
    ) -> tuple[SemanticEvaluationResultV2 | None, int]:
        if not events:
            return None, 1
        by_attempt: dict[int, list[SemanticCacheEvent]] = {}
        for item in events:
            by_attempt.setdefault(item.attempt_ordinal, []).append(item)
        if sorted(by_attempt) != list(range(1, max(by_attempt) + 1)):
            raise SemanticCachePortError(SemanticCachePortErrorCode.CACHE_INTEGRITY)
        request_bytes = semantic_evaluation_request_bytes(request)
        provider_hash = _sha(qwen_provider_request_semantic_v2_bytes(request))
        for ordinal, rows in by_attempt.items():
            kinds = tuple(item.event_kind for item in rows)
            if kinds not in (
                ("START",),
                ("START", "RAW"),
                ("START", "RAW", "RESULT"),
                ("START", "TERMINAL"),
                ("START", "RAW", "TERMINAL"),
                ("START", "RAW", "RESULT", "TERMINAL"),
            ):
                raise SemanticCachePortError(SemanticCachePortErrorCode.CACHE_INTEGRITY)
            start = rows[0]
            start_payload = _decoded(start.payload_bytes)
            if start_payload != {
                "schema_version": "m3.runtime-qwen-cache.start.v1",
                "operation_id": start.operation_id,
                "attempt_ordinal": ordinal,
                "request_bytes_hex": request_bytes.hex(),
                "provider_request_hash": provider_hash,
                "stage1_admission_hash": request.stage1_admission.admission_hash,
                "endpoint_identity": self._evaluator.endpoint_identity,
            }:
                raise SemanticCachePortError(SemanticCachePortErrorCode.CACHE_INTEGRITY)
            if any(item.start_event_id != start.event_id for item in rows[1:]):
                raise SemanticCachePortError(SemanticCachePortErrorCode.CACHE_INTEGRITY)
            terminal = rows[-1] if rows[-1].event_kind == "TERMINAL" else None
            if terminal is None:
                raise SemanticCachePortError(SemanticCachePortErrorCode.UNKNOWN_AFTER_START)
            if ordinal != max(by_attempt) and terminal.disposition != "retryable_status":
                raise SemanticCachePortError(SemanticCachePortErrorCode.CACHE_INTEGRITY)
            raw = next((item for item in rows if item.event_kind == "RAW"), None)
            result_event = next((item for item in rows if item.event_kind == "RESULT"), None)
            if terminal.raw_event_id != (
                None if raw is None else raw.event_id
            ) or terminal.result_event_id != (
                None if result_event is None else result_event.event_id
            ):
                raise SemanticCachePortError(SemanticCachePortErrorCode.CACHE_INTEGRITY)
            if raw is not None and (
                terminal.raw_event_id != raw.event_id
                or raw.raw_body_bytes is None
                or _decoded(raw.payload_bytes)
                != {
                    "schema_version": "m3.runtime-qwen-cache.raw.v1",
                    "operation_id": start.operation_id,
                    "attempt_ordinal": ordinal,
                }
            ):
                raise SemanticCachePortError(SemanticCachePortErrorCode.CACHE_INTEGRITY)
            if result_event is not None and (
                raw is None
                or result_event.raw_event_id != raw.event_id
                or terminal.result_event_id != result_event.event_id
            ):
                raise SemanticCachePortError(SemanticCachePortErrorCode.CACHE_INTEGRITY)
            terminal_payload = _decoded(terminal.payload_bytes)
            if (
                terminal_payload.get("schema_version") != "m3.runtime-qwen-cache.terminal.v1"
                or terminal_payload.get("disposition") != terminal.disposition
            ):
                raise SemanticCachePortError(SemanticCachePortErrorCode.CACHE_INTEGRITY)
            if terminal.disposition == "success":
                if ordinal != max(by_attempt):
                    raise SemanticCachePortError(SemanticCachePortErrorCode.CACHE_INTEGRITY)
                if (
                    raw is None
                    or result_event is None
                    or raw.raw_body_bytes is None
                    or terminal.completed_at_utc is None
                ):
                    raise SemanticCachePortError(SemanticCachePortErrorCode.CACHE_INTEGRITY)
                if not self._evaluator.raw_response_is_safe(raw.raw_body_bytes):
                    raise SemanticCachePortError(SemanticCachePortErrorCode.CACHE_INTEGRITY)
                observation = QwenObservation(
                    http_status=200,
                    raw_body=raw.raw_body_bytes,
                    body_complete=True,
                    observed_body_bytes_lower_bound=len(raw.raw_body_bytes),
                    credential_echo=False,
                    transport_error=None,
                    started_at_utc=start.started_at_utc,
                    completed_at_utc=terminal.completed_at_utc,
                    retry_after=None,
                )
                try:
                    assessment = finalize_qwen_observation(request, observation)
                    saved = SemanticEvaluationResultV2.model_validate_json(
                        result_event.payload_bytes, strict=True
                    )
                    reconstructed = reconstruct_semantic_evaluation_result_v2(request, saved)
                except (TypeError, ValueError, QwenSemanticError):
                    raise SemanticCachePortError(
                        SemanticCachePortErrorCode.CACHE_INTEGRITY
                    ) from None
                if reconstructed != assessment.result:
                    raise SemanticCachePortError(SemanticCachePortErrorCode.CACHE_INTEGRITY)
                return reconstructed, ordinal + 1
        latest = by_attempt[max(by_attempt)][-1]
        if (
            latest.disposition == "retryable_status"
            and max(by_attempt) < MAX_SEMANTIC_ATTEMPTS
            and max(by_attempt) in retry_owned_ordinals
        ):
            return None, max(by_attempt) + 1
        raise SemanticCachePortError(SemanticCachePortErrorCode.CACHED_FAILURE, latest.disposition)

    def evaluate_v2(self, value: SemanticEvaluationRequest) -> SemanticEvaluationResultV2:
        request = parse_semantic_evaluation_request(semantic_evaluation_request_bytes(value))
        receipt = _verify_stage1(request, self._stage1)
        if (
            receipt.configuration_version != M3_VALIDATION_CONFIGURATION_V4
            or receipt.policy_version != M3_VALIDATION_POLICY_V4
        ):
            raise SemanticCachePortError(SemanticCachePortErrorCode.STAGE1_BINDING_DRIFT)
        operation_id = qwen_semantic_evaluation_operation_id(
            request, self._evaluator.endpoint_identity
        )
        deadline = self._clock() + QWEN_TOTAL_DEADLINE_SECONDS
        owned_attempts: set[int] = set()
        while True:
            try:
                lease = self._journal.acquire_operation_lease(operation_id)
            except SemanticCacheConflict:
                raise SemanticCachePortError(SemanticCachePortErrorCode.CACHE_BUSY) from None
            try:
                cached, ordinal = self._replay(
                    request,
                    self._events(operation_id, request),
                    retry_owned_ordinals=frozenset(owned_attempts),
                )
                if cached is not None:
                    return cached
                if ordinal > MAX_SEMANTIC_ATTEMPTS or self._clock() >= deadline:
                    raise SemanticCachePortError(
                        SemanticCachePortErrorCode.CACHED_FAILURE, "deadline_exceeded"
                    )
                started = datetime.now(UTC)
                start = self._journal.append(
                    _event(
                        request,
                        operation_id,
                        ordinal,
                        "START",
                        {
                            "schema_version": "m3.runtime-qwen-cache.start.v1",
                            "operation_id": operation_id,
                            "attempt_ordinal": ordinal,
                            "request_bytes_hex": semantic_evaluation_request_bytes(request).hex(),
                            "provider_request_hash": _sha(
                                qwen_provider_request_semantic_v2_bytes(request)
                            ),
                            "stage1_admission_hash": request.stage1_admission.admission_hash,
                            "endpoint_identity": self._evaluator.endpoint_identity,
                        },
                        started,
                    )
                )
                owned_attempts.add(ordinal)
            finally:
                self._journal.release_operation_lease(lease)
            try:
                observation = self._evaluator.observe(
                    request,
                    absolute_deadline_monotonic=deadline,
                    monotonic_clock=self._clock,
                )
            except QwenSemanticError as error:
                observation = QwenObservation(
                    None,
                    None,
                    False,
                    0,
                    False,
                    (
                        error.code.value
                        if error.code.value in ("deadline_exceeded", "response_invalid")
                        else "transport_unavailable"
                    ),
                    started,
                    datetime.now(UTC),
                    None,
                )
            raw_event: SemanticCacheEvent | None = None
            result_event: SemanticCacheEvent | None = None
            disposition = _disposition(observation)
            if observation.raw_body is not None:
                raw_event = self._journal.append(
                    _event(
                        request,
                        operation_id,
                        ordinal,
                        "RAW",
                        {
                            "schema_version": "m3.runtime-qwen-cache.raw.v1",
                            "operation_id": operation_id,
                            "attempt_ordinal": ordinal,
                        },
                        started,
                        start_id=start.event_id,
                        raw=observation.raw_body,
                    )
                )
            if disposition == "success":
                try:
                    assessment = finalize_qwen_observation(request, observation)
                except QwenSemanticError as error:
                    disposition = error.code.value
                else:
                    if raw_event is None:
                        raise SemanticCachePortError(SemanticCachePortErrorCode.CACHE_INTEGRITY)
                    result = BaseModel.model_dump(assessment.result, mode="json")
                    result_event = self._journal.append(
                        _event(
                            request,
                            operation_id,
                            ordinal,
                            "RESULT",
                            result,
                            started,
                            start_id=start.event_id,
                            raw_id=raw_event.event_id,
                        )
                    )
            self._journal.append(
                _event(
                    request,
                    operation_id,
                    ordinal,
                    "TERMINAL",
                    {
                        "schema_version": "m3.runtime-qwen-cache.terminal.v1",
                        "operation_id": operation_id,
                        "attempt_ordinal": ordinal,
                        "disposition": disposition,
                        "http_status": observation.http_status,
                        "body_complete": observation.body_complete,
                        "observed_body_bytes_lower_bound": (
                            observation.observed_body_bytes_lower_bound
                        ),
                    },
                    started,
                    start_id=start.event_id,
                    raw_id=None if raw_event is None else raw_event.event_id,
                    result_id=None if result_event is None else result_event.event_id,
                    completed=observation.completed_at_utc,
                    disposition=disposition,
                )
            )
            if disposition == "retryable_status" and ordinal < MAX_SEMANTIC_ATTEMPTS:
                remaining = deadline - self._clock()
                if remaining > 0:
                    delay = _retry_delay(
                        _sha(qwen_provider_request_semantic_v2_bytes(request)),
                        ordinal,
                        observation.retry_after,
                        now_utc=datetime.now(UTC),
                    )
                    self._sleep(min(delay, remaining))
                    continue
            replayed, _ = self._replay(
                request,
                self._events(operation_id, request),
                retry_owned_ordinals=frozenset(owned_attempts),
            )
            if replayed is not None:
                return replayed
            raise SemanticCachePortError(SemanticCachePortErrorCode.CACHED_FAILURE, disposition)
