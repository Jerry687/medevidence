"""Explicit live-only entry point for one frozen M3-008B DeepSeek calibration run."""

from __future__ import annotations

import argparse
import hashlib
import math
import os
import time
from collections.abc import Callable
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
)
from medevidence.infrastructure.deepseek_semantic_evaluator import (
    DEEPSEEK_SEMANTIC_V2_PROVIDER_CONFIGURATION_HASH,
    DeepSeekResponsesSemanticEvaluatorV2,
    DeepSeekSemanticEvaluatorError,
    build_deepseek_v2_framing_observation,
    deepseek_provider_request_semantic_v2_bytes,
    derive_deepseek_v2_disposition,
    finalize_deepseek_one_operation_semantic_v2,
)
from medevidence.persistence import (
    PersistenceSettings,
    ProviderAttemptLedgerRepository,
    make_provider_attempt_event,
)
from medevidence.tools.provider_attempt_framing import Observation, build_unavailable_observation

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
    return float(min(_RETRY_AFTER_CAP_SECONDS, base + jitter))


def _attempt_disposition(one: object, error: Exception | None, *, stage: str) -> str:
    if stage == "raw_persistence" and error is not None:
        return "evidence_persistence_failure"
    if type(one) is not DeepSeekOneOperationObservation:
        return "transport_unavailable"
    disposition = derive_deepseek_v2_disposition(one)
    if (
        error is not None
        and type(error) is not DeepSeekSemanticEvaluatorError
        and stage == "validation"
        and one.http_status is not None
    ):
        return "validation_internal_failure"
    if disposition != "success":
        return disposition
    if type(error) is DeepSeekSemanticEvaluatorError:
        if error.code.value == "candidate_invalid":
            return "candidate_invalid"
        if error.code.value in {
            "response_incomplete",
            "response_refused",
            "response_tool_output",
            "response_model_mismatch",
        }:
            return "response_invalid"
        return error.code.value
    if error is not None:
        return "transport_unavailable"
    return disposition


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
    monotonic_clock: Callable[[], float] | None = None,
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
    clock = monotonic_clock if monotonic_clock is not None else time.monotonic
    first_case_deadline_monotonic = clock() + _TOTAL_DEADLINE_SECONDS
    owns_ledger = ledger is None
    attempt_ledger = ledger or ProviderAttemptLedgerRepository(PersistenceSettings.from_env())
    try:
        lease = attempt_ledger.acquire_run_lease(durable_run_id)
    except Exception:
        if owns_ledger:
            attempt_ledger.close()
        raise
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
        evaluator = DeepSeekResponsesSemanticEvaluatorV2(
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
        for case_index, case in enumerate(cases):
            current_case = case
            assessment = None
            case_deadline_monotonic = (
                first_case_deadline_monotonic
                if case_index == 0
                else clock() + _TOTAL_DEADLINE_SECONDS
            )
            request_bytes = deepseek_provider_request_semantic_v2_bytes(case.request)
            request_hash = "sha256:" + hashlib.sha256(request_bytes).hexdigest()
            for attempt_ordinal in range(1, 4):
                started = datetime.now(UTC)
                start_event = make_provider_attempt_event(
                    provider_run_id=durable_run_id,
                    case_id=case.case_id,
                    case_ordinal=case.ordinal,
                    attempt_ordinal=attempt_ordinal,
                    event_kind="START",
                    configuration_hash=DEEPSEEK_SEMANTIC_V2_PROVIDER_CONFIGURATION_HASH,
                    request_hash=request_hash,
                    started_at_utc=started,
                    schema_version="M3_PROVIDER_ATTEMPT_EVENT_V2",
                )
                attempt_ledger.append(start_event)
                remaining = case_deadline_monotonic - clock()
                if remaining <= 0:
                    attempt_ledger.append(
                        make_provider_attempt_event(
                            provider_run_id=durable_run_id,
                            case_id=case.case_id,
                            case_ordinal=case.ordinal,
                            attempt_ordinal=attempt_ordinal,
                            event_kind="TERMINAL",
                            start_event=start_event,
                            configuration_hash=(DEEPSEEK_SEMANTIC_V2_PROVIDER_CONFIGURATION_HASH),
                            request_hash=request_hash,
                            started_at_utc=started,
                            completed_at_utc=datetime.now(UTC),
                            disposition="deadline_exceeded",
                            error_code="deadline_exceeded",
                            schema_version="M3_PROVIDER_ATTEMPT_EVENT_V2",
                        )
                    )
                    raise DeepSeekCalibrationError(
                        "provider retry deadline exhausted after durable START"
                    )
                one = None
                binding = None
                candidate = None
                caught = None
                stage = "transport"
                try:
                    one = DeepSeekResponsesSemanticEvaluatorV2.observe(
                        evaluator,
                        case.request,
                        absolute_deadline_monotonic=case_deadline_monotonic,
                        monotonic_clock=clock,
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
                    candidate = finalize_deepseek_one_operation_semantic_v2(
                        case.request,
                        one,
                        raw_body_hash=(binding.content_hash if binding is not None else None),
                        raw_relative_path=(binding.relative_path if binding is not None else None),
                    )
                except Exception as error:
                    caught = error
                disposition = _attempt_disposition(one, caught, stage=stage)
                framing_observation: Observation | None = None
                if one is not None and one.http_status is not None:
                    if disposition in {"credential_echo", "evidence_persistence_failure"}:
                        framing_observation = build_unavailable_observation(
                            disposition=disposition,
                            http_status=one.http_status,
                        )
                    else:
                        framing_observation = build_deepseek_v2_framing_observation(
                            one,
                            disposition=disposition,
                            raw_body_hash=(binding.content_hash if binding is not None else None),
                            raw_relative_path=(
                                binding.relative_path if binding is not None else None
                            ),
                        )
                terminal = make_provider_attempt_event(
                    provider_run_id=durable_run_id,
                    case_id=case.case_id,
                    case_ordinal=case.ordinal,
                    attempt_ordinal=attempt_ordinal,
                    event_kind="TERMINAL",
                    start_event=start_event,
                    configuration_hash=DEEPSEEK_SEMANTIC_V2_PROVIDER_CONFIGURATION_HASH,
                    request_hash=request_hash,
                    started_at_utc=started,
                    completed_at_utc=(
                        one.completed_at_utc if one is not None else datetime.now(UTC)
                    ),
                    http_status=one.http_status if one is not None else None,
                    disposition=disposition,
                    error_code=None if disposition == "success" else disposition,
                    credential_echo=disposition == "credential_echo",
                    schema_version="M3_PROVIDER_ATTEMPT_EVENT_V2",
                    framing_observation=framing_observation,
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
                    if clock() + delay >= case_deadline_monotonic:
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
