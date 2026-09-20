"""Durable HIGH-profile SemanticEvaluationPortV2 with per-attempt evidence."""

from __future__ import annotations

import base64
import hashlib
import json
import math
import time
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from enum import StrEnum
from typing import Any, Final, Protocol, cast, final

from pydantic import BaseModel

from medevidence.domain import canonical_json
from medevidence.infrastructure.deepseek_responses_transport import (
    DeepSeekOneOperationObservation,
    DeepSeekTransportErrorCode,
)
from medevidence.infrastructure.deepseek_semantic_evaluator import (
    DEEPSEEK_SEMANTIC_V2_PROVIDER_CONFIG_VERSION,
    DEEPSEEK_SEMANTIC_V2_PROVIDER_CONFIGURATION_HASH,
    DeepSeekResponsesSemanticEvaluatorV2,
    DeepSeekSemanticEvaluatorError,
    DeepSeekSemanticEvaluatorErrorCode,
    deepseek_provider_request_semantic_v2_bytes,
    derive_deepseek_v2_disposition,
    finalize_deepseek_one_operation_semantic_v2,
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
from medevidence.tools.provider_attempt_framing import (
    normalize_approved_headers,
    raw_body_persistence_permitted,
)
from medevidence.tools.report_validation import (
    Stage1ReceiptV2,
    stage1_receipt_from_payload_v2,
)
from medevidence.tools.semantic_evaluation import (
    MAX_EVALUATION_PROVIDER_REQUEST_BYTES,
    MAX_EVALUATION_PROVIDER_RESPONSE_BYTES,
    SEMANTIC_EVALUATION_TOTAL_DEADLINE_SECONDS,
    SemanticEvaluationRequest,
    SemanticEvaluationResultV2,
    parse_semantic_evaluation_request,
    reconstruct_semantic_evaluation_result_v2,
    semantic_evaluation_request_bytes,
)

_TOTAL_DEADLINE_SECONDS: Final = SEMANTIC_EVALUATION_TOTAL_DEADLINE_SECONDS
_BACKOFF_BASE_SECONDS: Final = 0.25
_RETRY_AFTER_CAP_SECONDS: Final = 2.0
_RETRYABLE_DISPOSITIONS: Final = frozenset({"retryable_status", "transport_unavailable"})


class SemanticCachePortErrorCode(StrEnum):
    STAGE1_UNAVAILABLE = "stage1_unavailable"
    STAGE1_BINDING_DRIFT = "stage1_binding_drift"
    CACHE_BUSY = "cache_busy"
    CACHE_INTEGRITY = "cache_integrity"
    UNKNOWN_AFTER_START = "unknown_after_start"
    CACHED_FAILURE = "cached_failure"
    PERSISTENCE_FAILURE = "persistence_failure"


class SemanticCachePortError(RuntimeError):
    __slots__ = ("code", "disposition")

    def __init__(self, code: SemanticCachePortErrorCode, disposition: str | None = None) -> None:
        self.code = code
        self.disposition = disposition
        super().__init__(code.value)


class SemanticCacheJournal(Protocol):
    def acquire_operation_lease(self, operation_id: str) -> SemanticCacheLease: ...
    def release_operation_lease(self, lease: SemanticCacheLease) -> None: ...
    def append(self, event: SemanticCacheEvent) -> SemanticCacheEvent: ...
    def list_events(self, operation_id: str) -> tuple[SemanticCacheEvent, ...]: ...


class Stage1ReceiptReader(Protocol):
    def load_stage1_receipt(self, receipt_id: str) -> Mapping[str, object] | None: ...


def semantic_evaluation_operation_id(request: SemanticEvaluationRequest) -> str:
    """Bind one logical operation to run, citation, request, admission, and HIGH profile."""

    if type(request) is not SemanticEvaluationRequest:
        raise SemanticCachePortError(SemanticCachePortErrorCode.CACHE_INTEGRITY)
    payload = {
        "schema_version": "m3.runtime-semantic-operation.v1",
        "run_id": request.run_id,
        "citation_id": request.citation.citation_id,
        "input_digest": request.input_digest,
        "request_content_hash": request.request_content_hash,
        "stage1_admission_hash": request.stage1_admission.admission_hash,
        "provider_method": "deepseek.responses.independent_semantic_evaluation",
        "provider_configuration_version": DEEPSEEK_SEMANTIC_V2_PROVIDER_CONFIG_VERSION,
        "provider_configuration_hash": DEEPSEEK_SEMANTIC_V2_PROVIDER_CONFIGURATION_HASH,
    }
    return (
        "semantic-evaluation-operation:sha256:"
        + hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
    )


def _payload(value: Mapping[str, object]) -> bytes:
    return canonical_json(dict(value)).encode("utf-8")


def _decode(raw: bytes, keys: frozenset[str]) -> dict[str, Any]:
    if type(raw) is not bytes:
        raise SemanticCachePortError(SemanticCachePortErrorCode.CACHE_INTEGRITY)
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError, RecursionError):
        raise SemanticCachePortError(SemanticCachePortErrorCode.CACHE_INTEGRITY) from None
    if type(value) is not dict or set(value) != keys or _payload(value) != raw:
        raise SemanticCachePortError(SemanticCachePortErrorCode.CACHE_INTEGRITY)
    return cast(dict[str, Any], value)


def _verify_stage1(
    request: SemanticEvaluationRequest, store: Stage1ReceiptReader
) -> Stage1ReceiptV2:
    admission = request.stage1_admission
    try:
        raw = store.load_stage1_receipt(admission.validation_receipt_id)
    except Exception:
        raise SemanticCachePortError(SemanticCachePortErrorCode.STAGE1_UNAVAILABLE) from None
    if raw is None:
        raise SemanticCachePortError(SemanticCachePortErrorCode.STAGE1_UNAVAILABLE)
    try:
        receipt = stage1_receipt_from_payload_v2(dict(raw))
        claims = [item for item in receipt.claim_result_ids if item[0] == request.claim.claim_id]
        if (
            receipt.stage1_passed is not True
            or (
                receipt.receipt_id,
                receipt.receipt_content_hash,
                receipt.run_id,
                receipt.scope_id,
                receipt.report_id,
                receipt.report_content_hash,
                receipt.validation_input_hash,
                receipt.registry_binding_hash,
                receipt.task_binding_hash,
                receipt.stage1_result_id,
            )
            != (
                admission.validation_receipt_id,
                admission.validation_receipt_content_hash,
                admission.run_id,
                admission.scope_id,
                admission.report_id,
                admission.report_content_hash,
                admission.validation_input_hash,
                admission.registry_binding_hash,
                admission.task_binding_hash,
                admission.stage1_result_id,
            )
            or claims != [(request.claim.claim_id, admission.stage1_claim_result_id)]
            or receipt.citation_ids.count(request.citation.citation_id) != 1
            or len({item[0] for item in receipt.claim_result_ids}) != len(receipt.claim_result_ids)
            or len(set(receipt.citation_ids)) != len(receipt.citation_ids)
        ):
            raise ValueError
        return receipt
    except (TypeError, ValueError):
        raise SemanticCachePortError(SemanticCachePortErrorCode.STAGE1_BINDING_DRIFT) from None


def _common(request: SemanticEvaluationRequest, operation_id: str) -> dict[str, object]:
    return {
        "schema_version": SEMANTIC_CACHE_SCHEMA_VERSION,
        "operation_id": operation_id,
        "run_id": request.run_id,
        "citation_id": request.citation.citation_id,
        "request_content_hash": request.request_content_hash,
        "provider_configuration_version": DEEPSEEK_SEMANTIC_V2_PROVIDER_CONFIG_VERSION,
        "provider_configuration_hash": DEEPSEEK_SEMANTIC_V2_PROVIDER_CONFIGURATION_HASH,
    }


def _event(
    request: SemanticEvaluationRequest,
    operation_id: str,
    *,
    attempt_ordinal: int,
    event_kind: str,
    payload_bytes: bytes,
    started_at_utc: datetime,
    start_event_id: str | None = None,
    raw_event_id: str | None = None,
    result_event_id: str | None = None,
    raw_body_bytes: bytes | None = None,
    completed_at_utc: datetime | None = None,
    disposition: str | None = None,
    error_code: str | None = None,
) -> SemanticCacheEvent:
    return make_semantic_cache_event(
        **_common(request, operation_id),
        attempt_ordinal=attempt_ordinal,
        event_slot={"START": 0, "RAW": 1, "RESULT": 2, "TERMINAL": 3}[event_kind],
        event_kind=event_kind,
        start_event_id=start_event_id,
        raw_event_id=raw_event_id,
        result_event_id=result_event_id,
        payload_hash="sha256:" + hashlib.sha256(payload_bytes).hexdigest(),
        payload_bytes=payload_bytes,
        raw_body_hash=(
            None
            if raw_body_bytes is None
            else "sha256:" + hashlib.sha256(raw_body_bytes).hexdigest()
        ),
        raw_body_bytes=raw_body_bytes,
        started_at_utc=started_at_utc,
        completed_at_utc=completed_at_utc,
        disposition=disposition,
        error_code=error_code,
    )


def _observation_payload(value: DeepSeekOneOperationObservation) -> dict[str, object]:
    return {
        "http_status": value.http_status,
        "approved_headers": dict(value.approved_headers),
        "body_complete": value.body_complete,
        "observed_body_bytes_lower_bound": value.observed_body_bytes_lower_bound,
        "credential_echo": value.credential_echo,
        "transport_error": None if value.transport_error is None else value.transport_error.value,
        "started_at_utc": value.started_at_utc.isoformat(),
        "completed_at_utc": value.completed_at_utc.isoformat(),
        "retry_after": value.retry_after,
        "response_http_version": value.response_http_version,
        "response_header_items": [list(item) for item in value.response_header_items],
        "response_header_field_count": value.response_header_field_count,
    }


_OBSERVATION_KEYS = frozenset(
    {
        "http_status",
        "approved_headers",
        "body_complete",
        "observed_body_bytes_lower_bound",
        "credential_echo",
        "transport_error",
        "started_at_utc",
        "completed_at_utc",
        "retry_after",
        "response_http_version",
        "response_header_items",
        "response_header_field_count",
    }
)


def _observation(value: object, raw: bytes | None) -> DeepSeekOneOperationObservation:
    if type(value) is not dict or set(value) != _OBSERVATION_KEYS:
        raise SemanticCachePortError(SemanticCachePortErrorCode.CACHE_INTEGRITY)
    try:
        transport_error = (
            None
            if value["transport_error"] is None
            else DeepSeekTransportErrorCode(value["transport_error"])
        )
        header_rows = value["response_header_items"]
        if type(header_rows) is not list:
            raise ValueError
        started = datetime.fromisoformat(value["started_at_utc"])
        completed = datetime.fromisoformat(value["completed_at_utc"])
        if (
            started.tzinfo is None
            or started.utcoffset() != UTC.utcoffset(started)
            or completed.tzinfo is None
            or completed.utcoffset() != UTC.utcoffset(completed)
            or completed < started
        ):
            raise ValueError
        return DeepSeekOneOperationObservation(
            http_status=value["http_status"],
            approved_headers=value["approved_headers"],
            raw_body=raw,
            body_complete=value["body_complete"],
            observed_body_bytes_lower_bound=value["observed_body_bytes_lower_bound"],
            credential_echo=value["credential_echo"],
            transport_error=transport_error,
            started_at_utc=started,
            completed_at_utc=completed,
            retry_after=value["retry_after"],
            response_http_version=value["response_http_version"],
            response_header_items=tuple(tuple(item) for item in header_rows),
            response_header_field_count=value["response_header_field_count"],
        )
    except (TypeError, ValueError, KeyError):
        raise SemanticCachePortError(SemanticCachePortErrorCode.CACHE_INTEGRITY) from None


def _raw_reference(operation_id: str, attempt_ordinal: int) -> str:
    return (
        "postgres-semantic-cache/"
        + operation_id.removeprefix("semantic-evaluation-operation:sha256:")
        + f"/attempt-{attempt_ordinal:03d}/raw.bin"
    )


def _safe_raw(observation: DeepSeekOneOperationObservation) -> bytes | None:
    try:
        headers = normalize_approved_headers(
            observation.response_header_items,
            raw_header_field_count=observation.response_header_field_count,
        )
        raw = observation.raw_body
        if (
            not raw_body_persistence_permitted(headers)
            or observation.credential_echo
            or type(raw) is not bytes
            or not observation.body_complete
            or not 1 <= len(raw) <= MAX_EVALUATION_PROVIDER_RESPONSE_BYTES
        ):
            return None
        return raw
    except (TypeError, ValueError):
        return None


def _attempt_disposition(
    observation: DeepSeekOneOperationObservation | None,
    error: Exception | None,
    *,
    stage: str,
) -> str:
    if stage == "raw_persistence" and error is not None:
        return "evidence_persistence_failure"
    if observation is None:
        if type(error) is DeepSeekSemanticEvaluatorError:
            return {
                DeepSeekSemanticEvaluatorErrorCode.AUTHENTICATION: "authentication_failed",
                DeepSeekSemanticEvaluatorErrorCode.CREDENTIAL_ECHO: "credential_echo",
                DeepSeekSemanticEvaluatorErrorCode.DEADLINE_EXCEEDED: "deadline_exceeded",
                DeepSeekSemanticEvaluatorErrorCode.PROVIDER_REJECTED: "provider_rejected",
                DeepSeekSemanticEvaluatorErrorCode.RESPONSE_TOO_LARGE: "response_too_large",
            }.get(error.code, "transport_unavailable")
        return "transport_unavailable"
    disposition = derive_deepseek_v2_disposition(observation)
    if disposition != "success":
        return disposition
    if type(error) is DeepSeekSemanticEvaluatorError:
        if error.code is DeepSeekSemanticEvaluatorErrorCode.CANDIDATE_INVALID:
            return "candidate_invalid"
        if error.code in {
            DeepSeekSemanticEvaluatorErrorCode.RESPONSE_INCOMPLETE,
            DeepSeekSemanticEvaluatorErrorCode.RESPONSE_REFUSED,
            DeepSeekSemanticEvaluatorErrorCode.RESPONSE_TOOL_OUTPUT,
            DeepSeekSemanticEvaluatorErrorCode.RESPONSE_MODEL_MISMATCH,
        }:
            return "response_invalid"
        return error.code.value
    return "validation_internal_failure" if error is not None else disposition


def _retry_delay(
    request_hash: str,
    attempt_ordinal: int,
    retry_after: str | None,
    *,
    now_utc: datetime,
) -> float:
    base = _BACKOFF_BASE_SECONDS * (2 ** (attempt_ordinal - 1))
    if retry_after is not None:
        try:
            parsed = float(retry_after)
            if not math.isfinite(parsed) or parsed < 0:
                raise ValueError
            base = parsed
        except ValueError:
            try:
                value = parsedate_to_datetime(retry_after)
                if value.tzinfo is None:
                    value = value.replace(tzinfo=UTC)
                base = max(0.0, (value - now_utc).total_seconds())
            except (TypeError, ValueError, OverflowError):
                base = _BACKOFF_BASE_SECONDS * (2 ** (attempt_ordinal - 1))
    base = min(base, _RETRY_AFTER_CAP_SECONDS)
    seed = hashlib.sha256(f"{request_hash}:{attempt_ordinal}".encode("ascii")).digest()
    return float(
        min(_RETRY_AFTER_CAP_SECONDS, base + int.from_bytes(seed[:2], "big") / 65535 * 0.01)
    )


@final
class DurableDeepSeekSemanticEvaluationPortV2:
    """HIGH-only runtime port with durable per-attempt cache and fail-closed recovery."""

    __slots__ = ("_clock", "_evaluator", "_journal", "_sleep", "_stage1", "_utc_now")
    _clock: Callable[[], float]
    _evaluator: DeepSeekResponsesSemanticEvaluatorV2
    _journal: SemanticCacheJournal
    _sleep: Callable[[float], None]
    _stage1: Stage1ReceiptReader
    _utc_now: Callable[[], datetime]

    def __init__(
        self,
        *,
        evaluator: DeepSeekResponsesSemanticEvaluatorV2,
        journal: SemanticCacheJournal,
        stage1_receipts: Stage1ReceiptReader,
        monotonic_clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
        utc_now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        if type(evaluator) is not DeepSeekResponsesSemanticEvaluatorV2:
            raise TypeError("semantic cache requires the named HIGH evaluator")
        object.__setattr__(self, "_evaluator", evaluator)
        object.__setattr__(self, "_journal", journal)
        object.__setattr__(self, "_stage1", stage1_receipts)
        object.__setattr__(self, "_clock", monotonic_clock)
        object.__setattr__(self, "_sleep", sleeper)
        object.__setattr__(self, "_utc_now", utc_now)

    def __setattr__(self, name: str, value: object) -> None:
        del name, value
        raise AttributeError("semantic cache runtime authority is frozen")

    def _lease(self, operation_id: str) -> SemanticCacheLease:
        try:
            return self._journal.acquire_operation_lease(operation_id)
        except SemanticCacheConflict:
            raise SemanticCachePortError(SemanticCachePortErrorCode.CACHE_BUSY) from None

    def _clock_value(self) -> float:
        value = self._clock()
        if type(value) not in (int, float) or not math.isfinite(value):
            raise SemanticCachePortError(SemanticCachePortErrorCode.CACHE_INTEGRITY)
        return float(value)

    def _events(
        self, request: SemanticEvaluationRequest, operation_id: str
    ) -> tuple[SemanticCacheEvent, ...]:
        try:
            events = self._journal.list_events(operation_id)
        except SemanticCacheIntegrityError:
            raise SemanticCachePortError(SemanticCachePortErrorCode.CACHE_INTEGRITY) from None
        common = _common(request, operation_id)
        if any(
            any(getattr(event, key) != value for key, value in common.items()) for event in events
        ):
            raise SemanticCachePortError(SemanticCachePortErrorCode.CACHE_INTEGRITY)
        ordered = tuple(sorted(events, key=lambda item: (item.attempt_ordinal, item.event_slot)))
        if events != ordered:
            raise SemanticCachePortError(SemanticCachePortErrorCode.CACHE_INTEGRITY)
        ordinals = sorted({item.attempt_ordinal for item in events})
        if ordinals and ordinals != list(range(1, ordinals[-1] + 1)):
            raise SemanticCachePortError(SemanticCachePortErrorCode.CACHE_INTEGRITY)
        request_bytes = semantic_evaluation_request_bytes(request)
        expected_provider_hash = (
            "sha256:"
            + hashlib.sha256(deepseek_provider_request_semantic_v2_bytes(request)).hexdigest()
        )
        for ordinal in ordinals:
            rows = tuple(item for item in events if item.attempt_ordinal == ordinal)
            kinds = tuple(item.event_kind for item in rows)
            allowed = {
                ("START",),
                ("START", "RAW"),
                ("START", "RAW", "RESULT"),
                ("START", "TERMINAL"),
                ("START", "RAW", "TERMINAL"),
                ("START", "RAW", "RESULT", "TERMINAL"),
            }
            if kinds not in allowed or rows[0].start_event_id is not None:
                raise SemanticCachePortError(SemanticCachePortErrorCode.CACHE_INTEGRITY)
            start_id = rows[0].event_id
            if any(item.start_event_id != start_id for item in rows[1:]):
                raise SemanticCachePortError(SemanticCachePortErrorCode.CACHE_INTEGRITY)
            raw = next((item for item in rows if item.event_kind == "RAW"), None)
            result = next((item for item in rows if item.event_kind == "RESULT"), None)
            terminal = next((item for item in rows if item.event_kind == "TERMINAL"), None)
            if terminal is None and ordinal != ordinals[-1]:
                raise SemanticCachePortError(SemanticCachePortErrorCode.CACHE_INTEGRITY)
            if result is not None and result.raw_event_id != (
                None if raw is None else raw.event_id
            ):
                raise SemanticCachePortError(SemanticCachePortErrorCode.CACHE_INTEGRITY)
            if terminal is not None and (
                terminal.raw_event_id != (None if raw is None else raw.event_id)
                or terminal.result_event_id != (None if result is None else result.event_id)
            ):
                raise SemanticCachePortError(SemanticCachePortErrorCode.CACHE_INTEGRITY)
            if any(item.started_at_utc != rows[0].started_at_utc for item in rows):
                raise SemanticCachePortError(SemanticCachePortErrorCode.CACHE_INTEGRITY)
            start_payload = _decode(
                rows[0].payload_bytes,
                frozenset(
                    {
                        "schema_version",
                        "operation_id",
                        "attempt_ordinal",
                        "request_bytes_base64",
                        "provider_request_hash",
                        "stage1_receipt_id",
                        "stage1_receipt_content_hash",
                        "stage1_admission_hash",
                    }
                ),
            )
            try:
                stored_request = base64.b64decode(
                    start_payload["request_bytes_base64"], validate=True
                )
            except (TypeError, ValueError):
                raise SemanticCachePortError(SemanticCachePortErrorCode.CACHE_INTEGRITY) from None
            if (
                start_payload["schema_version"] != "m3.runtime-semantic-cache.start.v1"
                or start_payload["operation_id"] != operation_id
                or start_payload["attempt_ordinal"] != ordinal
                or stored_request != request_bytes
                or start_payload["provider_request_hash"] != expected_provider_hash
                or start_payload["stage1_receipt_id"]
                != request.stage1_admission.validation_receipt_id
                or start_payload["stage1_receipt_content_hash"]
                != request.stage1_admission.validation_receipt_content_hash
                or start_payload["stage1_admission_hash"] != request.stage1_admission.admission_hash
            ):
                raise SemanticCachePortError(SemanticCachePortErrorCode.CACHE_INTEGRITY)
            if raw is not None:
                raw_payload = _decode(
                    raw.payload_bytes,
                    frozenset(
                        {"schema_version", "operation_id", "attempt_ordinal", "raw_reference"}
                    ),
                )
                if (
                    raw_payload["schema_version"] != "m3.runtime-semantic-cache.raw.v1"
                    or raw_payload["operation_id"] != operation_id
                    or raw_payload["attempt_ordinal"] != ordinal
                    or raw_payload["raw_reference"] != _raw_reference(operation_id, ordinal)
                ):
                    raise SemanticCachePortError(SemanticCachePortErrorCode.CACHE_INTEGRITY)
            if result is not None:
                try:
                    parsed_result = SemanticEvaluationResultV2.model_validate_json(
                        result.payload_bytes, strict=True
                    )
                    reconstruct_semantic_evaluation_result_v2(request, parsed_result)
                except (TypeError, ValueError):
                    raise SemanticCachePortError(
                        SemanticCachePortErrorCode.CACHE_INTEGRITY
                    ) from None
            if terminal is not None:
                terminal_payload = _decode(
                    terminal.payload_bytes,
                    frozenset(
                        {
                            "schema_version",
                            "operation_id",
                            "attempt_ordinal",
                            "observation",
                            "disposition",
                        }
                    ),
                )
                if (
                    terminal_payload["schema_version"] != "m3.runtime-semantic-cache.terminal.v1"
                    or terminal_payload["operation_id"] != operation_id
                    or terminal_payload["attempt_ordinal"] != ordinal
                    or terminal_payload["disposition"] != terminal.disposition
                    or type(terminal_payload["observation"]) is not dict
                    or set(terminal_payload["observation"]) != _OBSERVATION_KEYS
                ):
                    raise SemanticCachePortError(SemanticCachePortErrorCode.CACHE_INTEGRITY)
                stored_observation = _observation(
                    terminal_payload["observation"],
                    None if raw is None else raw.raw_body_bytes,
                )
                if stored_observation.completed_at_utc != terminal.completed_at_utc or (
                    _safe_raw(stored_observation) is None
                ) != (raw is None):
                    raise SemanticCachePortError(SemanticCachePortErrorCode.CACHE_INTEGRITY)
                observed_disposition = derive_deepseek_v2_disposition(stored_observation)
                if terminal.disposition != "success":
                    if (
                        terminal.disposition == "evidence_persistence_failure"
                        and raw is None
                        and stored_observation.raw_body is None
                        and stored_observation.body_complete
                    ) or (
                        terminal.disposition == "validation_internal_failure"
                        and observed_disposition == "success"
                    ):
                        pass
                    elif observed_disposition != "success":
                        if terminal.disposition != observed_disposition:
                            raise SemanticCachePortError(SemanticCachePortErrorCode.CACHE_INTEGRITY)
                    else:
                        try:
                            finalize_deepseek_one_operation_semantic_v2(
                                request,
                                stored_observation,
                                raw_body_hash=None if raw is None else raw.raw_body_hash,
                                raw_relative_path=(
                                    None if raw is None else _raw_reference(operation_id, ordinal)
                                ),
                            )
                            reproduced_error = None
                        except Exception as caught:
                            reproduced_error = caught
                        if reproduced_error is None or terminal.disposition != _attempt_disposition(
                            stored_observation,
                            reproduced_error,
                            stage="validation",
                        ):
                            raise SemanticCachePortError(SemanticCachePortErrorCode.CACHE_INTEGRITY)
                if ordinal < ordinals[-1] and terminal.disposition not in _RETRYABLE_DISPOSITIONS:
                    raise SemanticCachePortError(SemanticCachePortErrorCode.CACHE_INTEGRITY)
        return events

    def _cached(
        self,
        request: SemanticEvaluationRequest,
        events: tuple[SemanticCacheEvent, ...],
        *,
        allow_owned_retry: bool = False,
    ) -> SemanticEvaluationResultV2 | None:
        if not events:
            return None
        latest = max(item.attempt_ordinal for item in events)
        rows = tuple(item for item in events if item.attempt_ordinal == latest)
        terminal = next((item for item in rows if item.event_kind == "TERMINAL"), None)
        if terminal is None:
            raise SemanticCachePortError(SemanticCachePortErrorCode.UNKNOWN_AFTER_START)
        if terminal.disposition != "success":
            if (
                allow_owned_retry
                and terminal.disposition in _RETRYABLE_DISPOSITIONS
                and latest < MAX_SEMANTIC_ATTEMPTS
            ):
                return None
            raise SemanticCachePortError(
                SemanticCachePortErrorCode.CACHED_FAILURE, terminal.disposition
            )
        raw_event = next(item for item in rows if item.event_kind == "RAW")
        result_event = next(item for item in rows if item.event_kind == "RESULT")
        terminal_payload = _decode(
            terminal.payload_bytes,
            frozenset(
                {"schema_version", "operation_id", "attempt_ordinal", "observation", "disposition"}
            ),
        )
        observation = _observation(terminal_payload["observation"], raw_event.raw_body_bytes)
        reference_payload = _decode(
            raw_event.payload_bytes,
            frozenset({"schema_version", "operation_id", "attempt_ordinal", "raw_reference"}),
        )
        try:
            assessment = finalize_deepseek_one_operation_semantic_v2(
                request,
                observation,
                raw_body_hash=raw_event.raw_body_hash,
                raw_relative_path=reference_payload["raw_reference"],
            )
            parsed = SemanticEvaluationResultV2.model_validate_json(
                result_event.payload_bytes, strict=True
            )
            result = reconstruct_semantic_evaluation_result_v2(request, parsed)
        except (DeepSeekSemanticEvaluatorError, TypeError, ValueError):
            raise SemanticCachePortError(SemanticCachePortErrorCode.CACHE_INTEGRITY) from None
        if assessment.result != result:
            raise SemanticCachePortError(SemanticCachePortErrorCode.CACHE_INTEGRITY)
        return result

    def evaluate_v2(self, value: SemanticEvaluationRequest) -> SemanticEvaluationResultV2:
        request = parse_semantic_evaluation_request(semantic_evaluation_request_bytes(value))
        _verify_stage1(request, self._stage1)
        operation_id = semantic_evaluation_operation_id(request)
        deadline = self._clock_value() + _TOTAL_DEADLINE_SECONDS
        events = self._events(request, operation_id)
        cached = self._cached(request, events)
        if cached is not None:
            return cached
        attempt = 1
        owned_start_ids: set[str] = set()
        request_bytes = semantic_evaluation_request_bytes(request)
        if len(request_bytes) > MAX_EVALUATION_PROVIDER_REQUEST_BYTES:
            raise SemanticCachePortError(SemanticCachePortErrorCode.CACHE_INTEGRITY)
        provider_request_hash = (
            "sha256:"
            + hashlib.sha256(deepseek_provider_request_semantic_v2_bytes(request)).hexdigest()
        )
        while attempt <= MAX_SEMANTIC_ATTEMPTS:
            lease = self._lease(operation_id)
            try:
                current = self._events(request, operation_id)
                current_start_ids = {
                    item.event_id for item in current if item.event_kind == "START"
                }
                if current_start_ids - owned_start_ids:
                    cached = self._cached(request, current)
                else:
                    cached = self._cached(
                        request,
                        current,
                        allow_owned_retry=bool(current_start_ids),
                    )
                if cached is not None:
                    return cached
                if self._clock_value() >= deadline:
                    latest_terminal = next(
                        (item for item in reversed(current) if item.event_kind == "TERMINAL"),
                        None,
                    )
                    raise SemanticCachePortError(
                        SemanticCachePortErrorCode.CACHED_FAILURE,
                        None if latest_terminal is None else latest_terminal.disposition,
                    )
                expected_attempt = (
                    1 if not current else max(item.attempt_ordinal for item in current) + 1
                )
                if attempt != expected_attempt:
                    raise SemanticCachePortError(SemanticCachePortErrorCode.CACHE_INTEGRITY)
                started = self._utc_now()
                start_payload = _payload(
                    {
                        "schema_version": "m3.runtime-semantic-cache.start.v1",
                        "operation_id": operation_id,
                        "attempt_ordinal": attempt,
                        "request_bytes_base64": base64.b64encode(request_bytes).decode("ascii"),
                        "provider_request_hash": provider_request_hash,
                        "stage1_receipt_id": request.stage1_admission.validation_receipt_id,
                        "stage1_receipt_content_hash": (
                            request.stage1_admission.validation_receipt_content_hash
                        ),
                        "stage1_admission_hash": request.stage1_admission.admission_hash,
                    }
                )
                start_event = self._journal.append(
                    _event(
                        request,
                        operation_id,
                        attempt_ordinal=attempt,
                        event_kind="START",
                        payload_bytes=start_payload,
                        started_at_utc=started,
                    )
                )
                owned_start_ids.add(start_event.event_id)
            finally:
                self._journal.release_operation_lease(lease)
            if self._clock_value() >= deadline:
                observation = None
                error: Exception | None = DeepSeekSemanticEvaluatorError(
                    DeepSeekSemanticEvaluatorErrorCode.DEADLINE_EXCEEDED
                )
            else:
                try:
                    observation = self._evaluator.observe(
                        request,
                        absolute_deadline_monotonic=deadline,
                        monotonic_clock=self._clock_value,
                    )
                    error = None
                except DeepSeekSemanticEvaluatorError as caught:
                    observation, error = None, caught
            raw_event: SemanticCacheEvent | None = None
            result_event: SemanticCacheEvent | None = None
            stage = "transport"
            assessment = None
            if observation is not None:
                raw = _safe_raw(observation)
                if raw is not None:
                    raw_payload = _payload(
                        {
                            "schema_version": "m3.runtime-semantic-cache.raw.v1",
                            "operation_id": operation_id,
                            "attempt_ordinal": attempt,
                            "raw_reference": _raw_reference(operation_id, attempt),
                        }
                    )
                    try:
                        raw_event = self._journal.append(
                            _event(
                                request,
                                operation_id,
                                attempt_ordinal=attempt,
                                event_kind="RAW",
                                payload_bytes=raw_payload,
                                raw_body_bytes=raw,
                                started_at_utc=started,
                                start_event_id=start_event.event_id,
                            )
                        )
                    except Exception as caught:
                        stage, error = "raw_persistence", caught
                if error is None:
                    stage = "validation"
                    try:
                        assessment = finalize_deepseek_one_operation_semantic_v2(
                            request,
                            observation,
                            raw_body_hash=(None if raw_event is None else raw_event.raw_body_hash),
                            raw_relative_path=(
                                None if raw_event is None else _raw_reference(operation_id, attempt)
                            ),
                        )
                    except Exception as caught:
                        error = caught
            disposition = _attempt_disposition(observation, error, stage=stage)
            if disposition == "success" and assessment is not None:
                result_bytes = canonical_json(
                    BaseModel.model_dump(assessment.result, mode="json")
                ).encode("utf-8")
                result_event = self._journal.append(
                    _event(
                        request,
                        operation_id,
                        attempt_ordinal=attempt,
                        event_kind="RESULT",
                        payload_bytes=result_bytes,
                        started_at_utc=started,
                        start_event_id=start_event.event_id,
                        raw_event_id=cast(SemanticCacheEvent, raw_event).event_id,
                    )
                )
            unobserved_completed = self._utc_now() if observation is None else None
            observation_payload = (
                {
                    "http_status": None,
                    "approved_headers": {},
                    "body_complete": False,
                    "observed_body_bytes_lower_bound": 0,
                    "credential_echo": False,
                    "transport_error": (
                        DeepSeekTransportErrorCode.DEADLINE_EXCEEDED.value
                        if type(error) is DeepSeekSemanticEvaluatorError
                        and error.code is DeepSeekSemanticEvaluatorErrorCode.DEADLINE_EXCEEDED
                        else None
                    ),
                    "started_at_utc": started.isoformat(),
                    "completed_at_utc": cast(datetime, unobserved_completed).isoformat(),
                    "retry_after": None,
                    "response_http_version": None,
                    "response_header_items": [],
                    "response_header_field_count": 0,
                }
                if observation is None
                else _observation_payload(observation)
            )
            terminal_payload = _payload(
                {
                    "schema_version": "m3.runtime-semantic-cache.terminal.v1",
                    "operation_id": operation_id,
                    "attempt_ordinal": attempt,
                    "observation": observation_payload,
                    "disposition": disposition,
                }
            )
            terminal = self._journal.append(
                _event(
                    request,
                    operation_id,
                    attempt_ordinal=attempt,
                    event_kind="TERMINAL",
                    payload_bytes=terminal_payload,
                    started_at_utc=started,
                    completed_at_utc=(
                        cast(datetime, unobserved_completed)
                        if observation is None
                        else observation.completed_at_utc
                    ),
                    start_event_id=start_event.event_id,
                    raw_event_id=None if raw_event is None else raw_event.event_id,
                    result_event_id=None if result_event is None else result_event.event_id,
                    disposition=disposition,
                    error_code=None if disposition == "success" else disposition,
                )
            )
            del terminal
            verified = self._cached(
                request,
                self._events(request, operation_id),
                allow_owned_retry=True,
            )
            if verified is not None:
                return verified
            if disposition not in _RETRYABLE_DISPOSITIONS or attempt >= MAX_SEMANTIC_ATTEMPTS:
                raise SemanticCachePortError(SemanticCachePortErrorCode.CACHED_FAILURE, disposition)
            remaining = deadline - self._clock_value()
            if remaining <= 0:
                raise SemanticCachePortError(SemanticCachePortErrorCode.CACHED_FAILURE, disposition)
            delay = _retry_delay(
                provider_request_hash,
                attempt,
                None if observation is None else observation.retry_after,
                now_utc=self._utc_now(),
            )
            self._sleep(min(delay, remaining))
            attempt += 1
        raise SemanticCachePortError(SemanticCachePortErrorCode.CACHED_FAILURE)
