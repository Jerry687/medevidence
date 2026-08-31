"""Explicit live-only entry point for one frozen M3-008B DeepSeek calibration run."""

from __future__ import annotations

import argparse
import hashlib
import math
import os
import time
from dataclasses import replace
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Final

import httpx

from evaluation.stage2_deepseek_calibration import (
    CalibrationObservation,
    DeepSeekCalibrationError,
    begin_pending_calibration_run,
    build_calibration_artifact,
    calibration_configuration,
    load_frozen_calibration_cases,
    persist_provider_event_projection,
    persist_safe_raw_body,
    persist_successful_calibration_case,
    provider_attempt_run_id,
    publish_failed_calibration_run,
    publish_successful_calibration_run,
    reconcile_case_evidence,
    validate_authoritative_provider_events,
    validate_output_target,
)
from medevidence.infrastructure.deepseek_responses_transport import (
    DeepSeekOneOperationObservation,
    DeepSeekTransportErrorCode,
)
from medevidence.infrastructure.deepseek_semantic_evaluator import (
    DeepSeekResponsesSemanticEvaluator,
    DeepSeekSemanticEvaluatorError,
    deepseek_provider_request_bytes,
    finalize_deepseek_one_operation,
)
from medevidence.persistence import (
    PersistenceSettings,
    ProviderAttemptLedgerRepository,
    make_provider_attempt_event,
)
from medevidence.tools.semantic_evaluation import (
    DEEPSEEK_SEMANTIC_EVALUATION_CONFIGURATION_HASH,
)

_KEY_NAME: Final = "DEEPSEEK_API_KEY"
_TOTAL_DEADLINE_SECONDS: Final = 45.0
_BACKOFF_BASE_SECONDS: Final = 0.25
_RETRY_AFTER_CAP_SECONDS: Final = 2.0


def _retry_delay_seconds(
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
            if math.isfinite(parsed) and parsed >= 0:
                base = parsed
            else:
                raise ValueError
        except ValueError:
            try:
                value = parsedate_to_datetime(retry_after)
                if value.tzinfo is None:
                    value = value.replace(tzinfo=UTC)
                base = max(0.0, (value - now_utc).total_seconds())
            except (TypeError, ValueError, OverflowError):
                base = _BACKOFF_BASE_SECONDS * (2 ** (attempt_ordinal - 1))
    base = min(base, _RETRY_AFTER_CAP_SECONDS)
    jitter_seed = hashlib.sha256(f"{request_hash}:{attempt_ordinal}".encode("ascii")).digest()
    jitter = int.from_bytes(jitter_seed[:2], "big") / 65535 * 0.01
    return min(_RETRY_AFTER_CAP_SECONDS, base + jitter)


def _attempt_disposition(one: object, error: Exception | None, *, stage: str) -> str:
    if stage == "raw_persistence" and error is not None:
        return "evidence_persistence_failure"
    if type(one) is not DeepSeekOneOperationObservation:
        return "transport_unavailable"
    if one.credential_echo:
        return "credential_echo"
    if one.transport_error is DeepSeekTransportErrorCode.DEADLINE_EXCEEDED:
        return "deadline_exceeded"
    if one.transport_error is DeepSeekTransportErrorCode.RESPONSE_TOO_LARGE:
        return "response_too_large"
    if one.transport_error is not None or one.http_status is None:
        return "transport_unavailable"
    if one.http_status in {429, 500, 502, 503, 504}:
        return "retryable_status"
    if one.http_status in {401, 403}:
        return "authentication_failed"
    if one.http_status != 200:
        return "provider_rejected"
    if type(error) is DeepSeekSemanticEvaluatorError:
        if error.code.value in {
            "response_incomplete",
            "response_refused",
            "response_tool_output",
            "response_model_mismatch",
            "candidate_invalid",
        }:
            return "response_invalid"
        return error.code.value
    if error is not None:
        return "transport_unavailable"
    return "success"


def run_live_calibration(
    *,
    machine_packet_path: Path,
    resolution_packet_path: Path,
    output_root: Path,
    live: bool,
    code_revision: str,
    implementation_manifest_hash: str,
    transport: httpx.BaseTransport | None = None,
    ledger: ProviderAttemptLedgerRepository | None = None,
) -> dict[str, object]:
    """Run exactly 36 cases only after frozen input and explicit-live gates pass."""

    cases = load_frozen_calibration_cases(machine_packet_path, resolution_packet_path)
    if live is not True:
        raise DeepSeekCalibrationError("explicit --live-deepseek-provider flag is required")
    configuration = calibration_configuration(
        code_revision=code_revision,
        implementation_manifest_hash=implementation_manifest_hash,
    )
    durable_run_id = provider_attempt_run_id(configuration)
    owns_ledger = ledger is None
    attempt_ledger = ledger or ProviderAttemptLedgerRepository(PersistenceSettings.from_env())
    lease = attempt_ledger.acquire_run_lease(durable_run_id)
    try:
        recovered = attempt_ledger.reconcile_orphan_starts(
            durable_run_id, recovered_at_utc=datetime.now(UTC)
        )
    except Exception:
        attempt_ledger.release_run_lease(lease)
        if owns_ledger:
            attempt_ledger.close()
        raise
    if recovered:
        try:
            recovered_events = attempt_ledger.list_events(durable_run_id)
            validate_authoritative_provider_events(
                recovered_events,
                frozen_cases=cases,
                expected_provider_run_id=durable_run_id,
            )
            pending = begin_pending_calibration_run(
                output_root,
                code_revision=code_revision,
                implementation_manifest_hash=implementation_manifest_hash,
            )
            reconcile_case_evidence(
                pending,
                cases,
                recovered_events,
                output_root.parent,
                expected_provider_run_id=durable_run_id,
            )
            persist_provider_event_projection(
                pending,
                recovered_events,
                frozen_cases=cases,
                expected_provider_run_id=durable_run_id,
            )
            publish_failed_calibration_run(
                pending,
                failed_case=None,
                error=DeepSeekCalibrationError("interrupted_unknown_after_start"),
                provider_attempt_events=recovered_events,
                provider_raw_root=output_root.parent,
                frozen_cases=cases,
                expected_provider_run_id=durable_run_id,
            )
        finally:
            attempt_ledger.release_run_lease(lease)
            if owns_ledger:
                attempt_ledger.close()
        raise DeepSeekCalibrationError("orphan provider attempt recovered; resend forbidden")
    existing_events = attempt_ledger.list_events(durable_run_id)
    if existing_events:
        try:
            validate_authoritative_provider_events(
                existing_events,
                frozen_cases=cases,
                expected_provider_run_id=durable_run_id,
            )
            pending = begin_pending_calibration_run(
                output_root,
                code_revision=code_revision,
                implementation_manifest_hash=implementation_manifest_hash,
            )
            reconcile_case_evidence(
                pending,
                cases,
                existing_events,
                output_root.parent,
                expected_provider_run_id=durable_run_id,
            )
            persist_provider_event_projection(
                pending,
                existing_events,
                frozen_cases=cases,
                expected_provider_run_id=durable_run_id,
            )
            publish_failed_calibration_run(
                pending,
                failed_case=None,
                error=DeepSeekCalibrationError(
                    "existing provider events reprojected; resend forbidden"
                ),
                provider_attempt_events=existing_events,
                provider_raw_root=output_root.parent,
                frozen_cases=cases,
                expected_provider_run_id=durable_run_id,
            )
        finally:
            attempt_ledger.release_run_lease(lease)
            if owns_ledger:
                attempt_ledger.close()
        raise DeepSeekCalibrationError("existing provider events reprojected; resend forbidden")
    try:
        validate_output_target(output_root)
    except Exception:
        attempt_ledger.release_run_lease(lease)
        if owns_ledger:
            attempt_ledger.close()
        raise
    api_key = os.environ.get(_KEY_NAME)
    if api_key is None:
        attempt_ledger.release_run_lease(lease)
        if owns_ledger:
            attempt_ledger.close()
        raise DeepSeekCalibrationError("DEEPSEEK_API_KEY is absent")
    owns_transport = transport is None
    provider_transport = transport if transport is not None else httpx.HTTPTransport(retries=0)
    try:
        evaluator = DeepSeekResponsesSemanticEvaluator(
            api_key=api_key,
            transport=provider_transport,
        )
        pending = begin_pending_calibration_run(
            output_root,
            code_revision=code_revision,
            implementation_manifest_hash=implementation_manifest_hash,
        )
    except Exception:
        if owns_transport:
            provider_transport.close()
        attempt_ledger.release_run_lease(lease)
        if owns_ledger:
            attempt_ledger.close()
        raise
    observations: list[CalibrationObservation] = []
    current_case = None
    try:
        for case in cases:
            current_case = case
            assessment = None
            request_bytes = deepseek_provider_request_bytes(case.request)
            request_hash = "sha256:" + hashlib.sha256(request_bytes).hexdigest()
            case_started_monotonic = time.monotonic()
            for attempt_ordinal in range(1, 4):
                remaining = _TOTAL_DEADLINE_SECONDS - (time.monotonic() - case_started_monotonic)
                if remaining <= 0:
                    raise DeepSeekCalibrationError(
                        "provider retry deadline exhausted before next START"
                    )
                started = datetime.now(UTC)
                start_event = make_provider_attempt_event(
                    provider_run_id=durable_run_id,
                    case_id=case.case_id,
                    case_ordinal=case.ordinal,
                    attempt_ordinal=attempt_ordinal,
                    event_kind="START",
                    configuration_hash=DEEPSEEK_SEMANTIC_EVALUATION_CONFIGURATION_HASH,
                    request_hash=request_hash,
                    started_at_utc=started,
                )
                attempt_ledger.append(start_event)
                one = None
                binding = None
                candidate = None
                caught = None
                stage = "transport"
                try:
                    one = DeepSeekResponsesSemanticEvaluator.observe(
                        evaluator,
                        case.request,
                        total_deadline_seconds=remaining,
                    )
                    stage = "raw_persistence"
                    binding = persist_safe_raw_body(
                        pending,
                        case,
                        attempt_ordinal,
                        one,
                        provider_run_id=durable_run_id,
                    )
                    stage = "validation"
                    candidate = finalize_deepseek_one_operation(case.request, one)
                except Exception as error:
                    caught = error
                disposition = _attempt_disposition(one, caught, stage=stage)
                terminal = make_provider_attempt_event(
                    provider_run_id=durable_run_id,
                    case_id=case.case_id,
                    case_ordinal=case.ordinal,
                    attempt_ordinal=attempt_ordinal,
                    event_kind="TERMINAL",
                    start_event=start_event,
                    configuration_hash=DEEPSEEK_SEMANTIC_EVALUATION_CONFIGURATION_HASH,
                    request_hash=request_hash,
                    started_at_utc=started,
                    completed_at_utc=(
                        one.completed_at_utc if one is not None else datetime.now(UTC)
                    ),
                    http_status=one.http_status if one is not None else None,
                    disposition=disposition,
                    error_code=None if disposition == "success" else disposition,
                    credential_echo=(one.credential_echo if one is not None else False),
                    body_complete=(
                        None
                        if disposition == "evidence_persistence_failure"
                        else True
                        if binding is not None
                        else one.body_complete
                        if one is not None
                        else None
                    ),
                    body_byte_count=(binding.byte_count if binding else None),
                    body_hash=(binding.content_hash if binding else None),
                    body_relative_path=(binding.relative_path if binding else None),
                    observed_body_bytes_lower_bound=(
                        one.observed_body_bytes_lower_bound if one is not None else None
                    ),
                    approved_header_names=(
                        tuple(sorted(one.approved_headers)) if one is not None else ()
                    ),
                )
                attempt_ledger.append(terminal)
                if disposition == "success":
                    assert candidate is not None
                    assessment = replace(candidate, attempts=attempt_ordinal)
                    break
                if (
                    disposition in {"retryable_status", "transport_unavailable"}
                    and (caught is None or type(caught) is DeepSeekSemanticEvaluatorError)
                    and attempt_ordinal < 3
                ):
                    delay = _retry_delay_seconds(
                        request_hash,
                        attempt_ordinal,
                        one.retry_after if one is not None else None,
                        now_utc=datetime.now(UTC),
                    )
                    if time.monotonic() - case_started_monotonic + delay >= _TOTAL_DEADLINE_SECONDS:
                        raise DeepSeekCalibrationError(
                            "provider retry deadline exhausted after terminal"
                        )
                    time.sleep(delay)
                    continue
                if caught is not None:
                    raise caught
                raise DeepSeekCalibrationError(f"provider attempt failed: {disposition}")
            if assessment is None:
                raise DeepSeekCalibrationError("provider attempt sequence produced no result")
            observation = CalibrationObservation(case, assessment)
            persist_successful_calibration_case(
                pending,
                observation,
                provider_attempt_events=attempt_ledger.list_events(durable_run_id),
                provider_raw_root=output_root.parent,
                frozen_cases=cases,
                expected_provider_run_id=durable_run_id,
            )
            observations.append(observation)
        current_case = None
        persist_provider_event_projection(
            pending,
            attempt_ledger.list_events(durable_run_id),
            frozen_cases=cases,
            expected_provider_run_id=durable_run_id,
        )
        artifact = build_calibration_artifact(
            tuple(observations),
            completed_at_utc=datetime.now(UTC),
            code_revision=code_revision,
            implementation_manifest_hash=implementation_manifest_hash,
            provider_attempt_events=attempt_ledger.list_events(durable_run_id),
            provider_raw_root=output_root.parent,
            frozen_cases=cases,
            expected_provider_run_id=durable_run_id,
        )
        publish_successful_calibration_run(
            pending,
            artifact,
            provider_attempt_events=attempt_ledger.list_events(durable_run_id),
            provider_raw_root=output_root.parent,
            frozen_cases=cases,
            expected_provider_run_id=durable_run_id,
        )
    except Exception as error:
        projection_path = pending.pending_root / "provider-attempt-projection.json"
        if not projection_path.exists():
            persist_provider_event_projection(
                pending,
                attempt_ledger.list_events(durable_run_id),
                frozen_cases=cases,
                expected_provider_run_id=durable_run_id,
            )
        publish_failed_calibration_run(
            pending,
            failed_case=current_case,
            error=error,
            provider_attempt_events=attempt_ledger.list_events(durable_run_id),
            provider_raw_root=output_root.parent,
            frozen_cases=cases,
            expected_provider_run_id=durable_run_id,
        )
        raise
    finally:
        try:
            if owns_transport:
                provider_transport.close()
        finally:
            attempt_ledger.release_run_lease(lease)
            if owns_ledger:
                attempt_ledger.close()
    return artifact


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--machine-packet", required=True, type=Path)
    parser.add_argument("--resolution-packet", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--code-revision", required=True)
    parser.add_argument("--implementation-manifest-hash", required=True)
    parser.add_argument("--live-deepseek-provider", action="store_true")
    args = parser.parse_args(argv)
    artifact = run_live_calibration(
        machine_packet_path=args.machine_packet,
        resolution_packet_path=args.resolution_packet,
        output_root=args.output_root,
        live=args.live_deepseek_provider,
        code_revision=args.code_revision,
        implementation_manifest_hash=args.implementation_manifest_hash,
    )
    return 0 if artifact["metrics"]["accepted"] is True else 2  # type: ignore[index]


if __name__ == "__main__":
    raise SystemExit(main())
