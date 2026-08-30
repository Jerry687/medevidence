from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from evaluation.run_stage2_deepseek_calibration import run_live_calibration
from evaluation.stage2_deepseek_calibration import DeepSeekCalibrationError
from tests.unit.evaluation.test_stage2_deepseek_calibration import _cases

CODE_REVISION = "a" * 40
MANIFEST_HASH = "sha256:" + "b" * 64


def test_missing_live_flag_and_key_fail_before_network_or_output(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        "evaluation.run_stage2_deepseek_calibration.load_frozen_calibration_cases",
        lambda *_args: (),
    )
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise AssertionError("network must not be invoked")

    output = tmp_path / "absent"
    with pytest.raises(DeepSeekCalibrationError, match="explicit"):
        run_live_calibration(
            machine_packet_path=tmp_path / "machine.json",
            resolution_packet_path=tmp_path / "resolution.json",
            output_root=output,
            live=False,
            code_revision=CODE_REVISION,
            implementation_manifest_hash=MANIFEST_HASH,
            transport=httpx.MockTransport(handler),
        )
    with pytest.raises(DeepSeekCalibrationError, match="is absent"):
        run_live_calibration(
            machine_packet_path=tmp_path / "machine.json",
            resolution_packet_path=tmp_path / "resolution.json",
            output_root=output,
            live=True,
            code_revision=CODE_REVISION,
            implementation_manifest_hash=MANIFEST_HASH,
            transport=httpx.MockTransport(handler),
        )
    assert calls == 0 and not output.exists()


def test_packet_validation_failure_precedes_key_and_network(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "must-not-be-used")

    def invalid(*_args: object) -> object:
        raise DeepSeekCalibrationError("frozen packet authority drift")

    monkeypatch.setattr(
        "evaluation.run_stage2_deepseek_calibration.load_frozen_calibration_cases",
        invalid,
    )
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise AssertionError("network must not be invoked")

    output = tmp_path / "absent"
    with pytest.raises(DeepSeekCalibrationError, match="packet authority drift"):
        run_live_calibration(
            machine_packet_path=tmp_path / "substituted.json",
            resolution_packet_path=tmp_path / "resolution.json",
            output_root=output,
            live=True,
            code_revision=CODE_REVISION,
            implementation_manifest_hash=MANIFEST_HASH,
            transport=httpx.MockTransport(handler),
        )
    assert calls == 0 and not output.exists()


@pytest.mark.parametrize("conflict", ("output", "pending"))
def test_output_conflicts_fail_before_provider(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, conflict: str
) -> None:
    monkeypatch.setattr(
        "evaluation.run_stage2_deepseek_calibration.load_frozen_calibration_cases",
        lambda *_args: (),
    )
    monkeypatch.setenv("DEEPSEEK_API_KEY", "must-not-be-used")
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise AssertionError("provider must not be invoked")

    output = tmp_path / "conflicted-run"
    if conflict == "output":
        output.mkdir()
    else:
        (tmp_path / ".conflicted-run.pending").mkdir()
    with pytest.raises(DeepSeekCalibrationError):
        run_live_calibration(
            machine_packet_path=tmp_path / "machine.json",
            resolution_packet_path=tmp_path / "resolution.json",
            output_root=output,
            live=True,
            code_revision=CODE_REVISION,
            implementation_manifest_hash=MANIFEST_HASH,
            transport=httpx.MockTransport(handler),
        )
    assert calls == 0


def test_case_one_evidence_survives_case_two_provider_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    observations = _cases()
    cases = tuple(item.case for item in observations[:2])
    first_response = observations[0].assessment.raw_response_envelope_bytes
    monkeypatch.setattr(
        "evaluation.run_stage2_deepseek_calibration.load_frozen_calibration_cases",
        lambda *_args: cases,
    )
    monkeypatch.setenv("DEEPSEEK_API_KEY", "bounded-test-key")
    calls = 0
    secret = "provider-body-secret-must-not-persist"

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(
                200,
                headers={"Content-Type": "application/json"},
                content=first_response,
            )
        return httpx.Response(
            400,
            headers={"Content-Type": "application/json"},
            content=json.dumps({"error": secret}).encode(),
        )

    output = tmp_path / "failed-run"
    with pytest.raises(Exception, match="provider_rejected"):
        run_live_calibration(
            machine_packet_path=tmp_path / "machine.json",
            resolution_packet_path=tmp_path / "resolution.json",
            output_root=output,
            live=True,
            code_revision=CODE_REVISION,
            implementation_manifest_hash=MANIFEST_HASH,
            transport=httpx.MockTransport(handler),
        )
    assert calls == 2
    assert output.is_dir()
    status = json.loads((output / "run-status.json").read_text(encoding="utf-8"))
    assert status["status"] == "FAILED"
    assert status["accepted"] is False
    assert status["successful_case_ids"] == ["M3-008B-CAL-001"]
    assert status["failed_case_id"] == "M3-008B-CAL-002"
    assert status["failure"] == {"code": "provider_rejected", "status_code": 400}
    case_one = json.loads((output / "case-001-evidence.json").read_text(encoding="utf-8"))
    assert bytes.fromhex(case_one["evidence"]["raw_provider_response_hex"]) == first_response
    assert not (output / "m3-008b-deepseek-calibration.json").exists()
    assert secret.encode() not in b"".join(path.read_bytes() for path in output.iterdir())


def test_runner_has_no_openai_selector_or_conversation_chaining() -> None:
    source = Path("evaluation/run_stage2_deepseek_calibration.py").read_text(encoding="utf-8")
    lowered = source.lower()
    assert "openai" not in lowered
    assert "provider selector" not in lowered
    assert "previous_response_id" not in lowered
    assert "conversation" not in lowered
