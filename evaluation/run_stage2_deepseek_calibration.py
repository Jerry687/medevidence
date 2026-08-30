"""Explicit live-only entry point for one frozen M3-008B DeepSeek calibration run."""

from __future__ import annotations

import argparse
import os
from datetime import UTC, datetime
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
    persist_successful_calibration_case,
    publish_failed_calibration_run,
    publish_successful_calibration_run,
    validate_output_target,
)
from medevidence.infrastructure.deepseek_semantic_evaluator import (
    DeepSeekResponsesSemanticEvaluator,
)

_KEY_NAME: Final = "DEEPSEEK_API_KEY"


def run_live_calibration(
    *,
    machine_packet_path: Path,
    resolution_packet_path: Path,
    output_root: Path,
    live: bool,
    code_revision: str,
    implementation_manifest_hash: str,
    transport: httpx.BaseTransport | None = None,
) -> dict[str, object]:
    """Run exactly 36 cases only after frozen input and explicit-live gates pass."""

    cases = load_frozen_calibration_cases(machine_packet_path, resolution_packet_path)
    if live is not True:
        raise DeepSeekCalibrationError("explicit --live-deepseek-provider flag is required")
    validate_output_target(output_root)
    calibration_configuration(
        code_revision=code_revision,
        implementation_manifest_hash=implementation_manifest_hash,
    )
    api_key = os.environ.get(_KEY_NAME)
    if api_key is None:
        raise DeepSeekCalibrationError("DEEPSEEK_API_KEY is absent")
    owns_transport = transport is None
    provider_transport = transport if transport is not None else httpx.HTTPTransport(retries=0)
    evaluator = DeepSeekResponsesSemanticEvaluator(
        api_key=api_key,
        transport=provider_transport,
    )
    pending = begin_pending_calibration_run(
        output_root,
        code_revision=code_revision,
        implementation_manifest_hash=implementation_manifest_hash,
    )
    observations: list[CalibrationObservation] = []
    current_case = None
    try:
        for case in cases:
            current_case = case
            observation = CalibrationObservation(case, evaluator.evaluate(case.request))
            persist_successful_calibration_case(pending, observation)
            observations.append(observation)
        current_case = None
        artifact = build_calibration_artifact(
            tuple(observations),
            completed_at_utc=datetime.now(UTC),
            code_revision=code_revision,
            implementation_manifest_hash=implementation_manifest_hash,
        )
        publish_successful_calibration_run(pending, artifact)
    except Exception as error:
        publish_failed_calibration_run(
            pending,
            failed_case=current_case,
            error=error,
        )
        raise
    finally:
        if owns_transport:
            provider_transport.close()
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
