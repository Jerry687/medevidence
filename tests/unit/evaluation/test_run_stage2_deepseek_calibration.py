from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from pathlib import Path

import evaluation.run_stage2_deepseek_calibration as runner_module
import evaluation.stage2_deepseek_calibration as calibration_module
import httpx
import pytest
from evaluation.run_stage2_deepseek_calibration import run_live_calibration
from evaluation.stage2_deepseek_calibration import (
    DeepSeekCalibrationError,
    calibration_configuration,
    provider_attempt_run_id,
    verify_external_run,
)
from tests.unit.evaluation.test_stage2_deepseek_calibration import _cases

from medevidence.infrastructure.deepseek_semantic_evaluator import (
    DeepSeekSemanticEvaluatorError,
    parse_deepseek_completed_response,
)
from medevidence.persistence import ProviderAttemptEvent, make_provider_attempt_event
from medevidence.tools.semantic_evaluation import (
    DEEPSEEK_SEMANTIC_EVALUATION_CONFIGURATION_HASH,
)

CODE_REVISION = "a" * 40
MANIFEST_HASH = "sha256:" + "b" * 64


class _FakeLedger:
    def __init__(self) -> None:
        self.events: list[ProviderAttemptEvent] = []
        self.acquired = 0
        self.released = 0

    def append(self, event: ProviderAttemptEvent) -> ProviderAttemptEvent:
        key = (event.provider_run_id, event.case_ordinal, event.attempt_ordinal, event.event_slot)
        if any(
            (item.provider_run_id, item.case_ordinal, item.attempt_ordinal, item.event_slot) == key
            for item in self.events
        ):
            raise RuntimeError("duplicate event slot")
        self.events.append(event)
        return event

    def acquire_run_lease(self, _run_id: str):  # type: ignore[no-untyped-def]
        self.acquired += 1
        return object()

    def release_run_lease(self, _lease: object) -> None:
        self.released += 1
        return None

    def list_events(self, provider_run_id: str):  # type: ignore[no-untyped-def]
        return tuple(item for item in self.events if item.provider_run_id == provider_run_id)

    def reconcile_orphan_starts(self, _run_id: str, *, recovered_at_utc):  # type: ignore[no-untyped-def]
        del recovered_at_utc
        return ()

    def close(self) -> None:
        return None


class _FailingLedger(_FakeLedger):
    def __init__(self, event_kind: str) -> None:
        super().__init__()
        self.event_kind = event_kind

    def append(self, event: ProviderAttemptEvent) -> ProviderAttemptEvent:
        if event.event_kind == self.event_kind:
            raise RuntimeError(f"{self.event_kind} insert failed")
        return super().append(event)


class _RecoveringLedger(_FakeLedger):
    def reconcile_orphan_starts(self, run_id: str, *, recovered_at_utc):  # type: ignore[no-untyped-def]
        source = _cases()[0]
        start = make_provider_attempt_event(
            provider_run_id=run_id,
            case_id="M3-008B-CAL-001",
            case_ordinal=1,
            attempt_ordinal=1,
            event_kind="START",
            configuration_hash=DEEPSEEK_SEMANTIC_EVALUATION_CONFIGURATION_HASH,
            request_hash=source.assessment.provider_request_hash,
            started_at_utc=datetime(2026, 8, 31, tzinfo=UTC),
        )
        recovery = make_provider_attempt_event(
            provider_run_id=run_id,
            case_id=start.case_id,
            case_ordinal=1,
            attempt_ordinal=1,
            event_kind="RECOVERY",
            start_event=start,
            configuration_hash=start.configuration_hash,
            request_hash=start.request_hash,
            started_at_utc=start.started_at_utc,
            completed_at_utc=recovered_at_utc,
            disposition="interrupted_unknown_after_start",
            error_code="interrupted_unknown_after_start",
        )
        self.events[:] = [start, recovery]
        return (recovery,)


class _DeadlineStream(httpx.SyncByteStream):
    def __iter__(self):  # type: ignore[no-untyped-def]
        time.sleep(0.06)
        yield b"{}"


def _verify_external_failed_run(
    ledger: _FakeLedger,
    output: Path,
    cases: tuple[object, ...],
) -> dict[str, object]:
    run_id = provider_attempt_run_id(
        calibration_configuration(
            code_revision=CODE_REVISION,
            implementation_manifest_hash=MANIFEST_HASH,
        )
    )
    return verify_external_run(
        ledger,  # type: ignore[arg-type]
        output,
        expected_provider_run_id=run_id,
        expected_code_revision=CODE_REVISION,
        expected_implementation_manifest_hash=MANIFEST_HASH,
        frozen_cases=cases,  # type: ignore[arg-type]
    )


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
            ledger=_FakeLedger(),  # type: ignore[arg-type]
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
            ledger=_FakeLedger(),  # type: ignore[arg-type]
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
            ledger=_FakeLedger(),  # type: ignore[arg-type]
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
    ledger = _FakeLedger()
    with pytest.raises(DeepSeekCalibrationError):
        run_live_calibration(
            machine_packet_path=tmp_path / "machine.json",
            resolution_packet_path=tmp_path / "resolution.json",
            output_root=output,
            live=True,
            code_revision=CODE_REVISION,
            implementation_manifest_hash=MANIFEST_HASH,
            transport=httpx.MockTransport(handler),
            ledger=ledger,  # type: ignore[arg-type]
        )
    assert calls == 0
    assert ledger.acquired == 1 and ledger.released == 1


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
    secret = "provider-error-body"

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
            ledger=_FakeLedger(),  # type: ignore[arg-type]
        )
    assert calls == 2
    assert output.is_dir()
    status = json.loads((output / "run-status.json").read_text(encoding="utf-8"))
    assert status["status"] == "FAILED"
    assert status["accepted"] is False
    assert status["successful_case_ids"] == ["M3-008B-CAL-001"]
    assert status["attempted_case_ids"] == ["M3-008B-CAL-001", "M3-008B-CAL-002"]
    case_one = json.loads((output / "case-001-evidence.json").read_text(encoding="utf-8"))
    assert bytes.fromhex(case_one["evidence"]["raw_provider_response_hex"]) == first_response
    assert not (output / "m3-008b-deepseek-calibration.json").exists()
    assert (output / "provider-attempt-projection.json").is_file()


def test_case_one_parser_failure_preserves_exact_preparse_raw_observation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    observation = _cases()[0]
    cases = (observation.case,)
    invalid_document = json.loads(observation.assessment.raw_response_envelope_bytes)
    invalid_document["parallel_tool_calls"] = False
    invalid_response = json.dumps(
        invalid_document,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    monkeypatch.setattr(
        "evaluation.run_stage2_deepseek_calibration.load_frozen_calibration_cases",
        lambda *_args: cases,
    )
    key_marker = "key-marker-must-never-enter-evidence"
    monkeypatch.setenv("DEEPSEEK_API_KEY", key_marker)
    ledger = _FakeLedger()

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"Content-Type": "application/json"},
            content=invalid_response,
        )

    output = tmp_path / "parse-failed-run"
    with pytest.raises(DeepSeekSemanticEvaluatorError, match="response_invalid"):
        run_live_calibration(
            machine_packet_path=tmp_path / "machine.json",
            resolution_packet_path=tmp_path / "resolution.json",
            output_root=output,
            live=True,
            code_revision=CODE_REVISION,
            implementation_manifest_hash=MANIFEST_HASH,
            transport=httpx.MockTransport(handler),
            ledger=ledger,  # type: ignore[arg-type]
        )
    status = json.loads((output / "run-status.json").read_text(encoding="utf-8"))
    assert status["status"] == "FAILED"
    assert status["attempted_case_ids"] == ["M3-008B-CAL-001"]
    assert status["successful_case_ids"] == []
    terminal = next(item for item in ledger.events if item.event_kind == "TERMINAL")
    assert terminal.body_relative_path is not None
    raw_file = output.parent / terminal.body_relative_path
    assert raw_file.read_bytes() == invalid_response
    assert not (output / "case-001-evidence.json").exists()
    assert not (output / "m3-008b-deepseek-calibration.json").exists()
    with pytest.raises(DeepSeekSemanticEvaluatorError, match="response_invalid"):
        parse_deepseek_completed_response(invalid_response)
    assert key_marker.encode() not in b"".join(path.read_bytes() for path in output.iterdir())


def test_runner_has_no_openai_selector_or_conversation_chaining() -> None:
    source = Path("evaluation/run_stage2_deepseek_calibration.py").read_text(encoding="utf-8")
    lowered = source.lower()
    assert "openai" not in lowered
    assert "provider selector" not in lowered
    assert "previous_response_id" not in lowered
    assert "conversation" not in lowered


def test_credential_echo_terminal_has_no_raw_file_or_hash(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    case = _cases()[0].case
    monkeypatch.setattr(
        "evaluation.run_stage2_deepseek_calibration.load_frozen_calibration_cases",
        lambda *_args: (case,),
    )
    key = "credential-marker-123"
    monkeypatch.setenv("DEEPSEEK_API_KEY", key)
    ledger = _FakeLedger()
    output = tmp_path / "credential-echo"
    with pytest.raises(Exception, match="credential_echo"):
        run_live_calibration(
            machine_packet_path=tmp_path / "machine.json",
            resolution_packet_path=tmp_path / "resolution.json",
            output_root=output,
            live=True,
            code_revision=CODE_REVISION,
            implementation_manifest_hash=MANIFEST_HASH,
            transport=httpx.MockTransport(
                lambda _request: httpx.Response(
                    200,
                    headers={"Content-Type": "application/json"},
                    content=(b'{"echo":"' + key.encode() + b'"}'),
                )
            ),
            ledger=ledger,  # type: ignore[arg-type]
        )
    terminal = next(item for item in ledger.events if item.event_kind == "TERMINAL")
    assert terminal.disposition == "credential_echo"
    assert terminal.credential_echo is True
    assert terminal.body_hash is None and terminal.body_relative_path is None
    assert not any(path.suffix == ".bin" for path in output.iterdir())
    assert key.encode() not in b"".join(path.read_bytes() for path in output.iterdir())


def test_orphan_start_recovers_and_stops_before_send(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    case = _cases()[0].case
    monkeypatch.setattr(
        "evaluation.run_stage2_deepseek_calibration.load_frozen_calibration_cases",
        lambda *_args: (case,),
    )
    monkeypatch.setenv("DEEPSEEK_API_KEY", "must-not-be-used")
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise AssertionError("orphan recovery must stop before send")

    output = tmp_path / "orphan-recovery"
    with pytest.raises(DeepSeekCalibrationError, match="resend forbidden"):
        run_live_calibration(
            machine_packet_path=tmp_path / "machine.json",
            resolution_packet_path=tmp_path / "resolution.json",
            output_root=output,
            live=True,
            code_revision=CODE_REVISION,
            implementation_manifest_hash=MANIFEST_HASH,
            transport=httpx.MockTransport(handler),
            ledger=_RecoveringLedger(),  # type: ignore[arg-type]
        )
    assert calls == 0
    projection = json.loads(
        (output / "provider-attempt-projection.json").read_text(encoding="utf-8")
    )
    assert projection["status"] == "INTERRUPTED"
    assert projection["attempt_count"] == 1


def test_existing_foreign_request_rejects_before_output_or_send(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = _cases()[0]
    monkeypatch.setattr(
        "evaluation.run_stage2_deepseek_calibration.load_frozen_calibration_cases",
        lambda *_args: (source.case,),
    )
    monkeypatch.setenv("DEEPSEEK_API_KEY", "must-not-be-used")
    run_id = provider_attempt_run_id(
        calibration_configuration(
            code_revision=CODE_REVISION,
            implementation_manifest_hash=MANIFEST_HASH,
        )
    )
    ledger = _FakeLedger()
    ledger.events.append(
        make_provider_attempt_event(
            provider_run_id=run_id,
            case_id=source.case.case_id,
            case_ordinal=source.case.ordinal,
            attempt_ordinal=1,
            event_kind="START",
            configuration_hash=DEEPSEEK_SEMANTIC_EVALUATION_CONFIGURATION_HASH,
            request_hash="sha256:" + "0" * 64,
            started_at_utc=datetime(2026, 8, 31, tzinfo=UTC),
        )
    )
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise AssertionError("foreign existing event must stop before send")

    output = tmp_path / "foreign-existing"
    with pytest.raises(DeepSeekCalibrationError, match="request differs"):
        run_live_calibration(
            machine_packet_path=tmp_path / "machine.json",
            resolution_packet_path=tmp_path / "resolution.json",
            output_root=output,
            live=True,
            code_revision=CODE_REVISION,
            implementation_manifest_hash=MANIFEST_HASH,
            transport=httpx.MockTransport(handler),
            ledger=ledger,  # type: ignore[arg-type]
        )
    assert calls == 0
    assert not output.exists()
    assert not (tmp_path / ".foreign-existing.pending").exists()


@pytest.mark.parametrize("failure_kind", ("START", "TERMINAL"))
def test_ledger_insert_failure_never_causes_network_retry(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, failure_kind: str
) -> None:
    case = _cases()[0].case
    response = _cases()[0].assessment.raw_response_envelope_bytes
    monkeypatch.setattr(
        "evaluation.run_stage2_deepseek_calibration.load_frozen_calibration_cases",
        lambda *_args: (case,),
    )
    monkeypatch.setenv("DEEPSEEK_API_KEY", "bounded-test-key")
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, headers={"Content-Type": "application/json"}, content=response)

    with pytest.raises(RuntimeError, match="insert failed"):
        run_live_calibration(
            machine_packet_path=tmp_path / "machine.json",
            resolution_packet_path=tmp_path / "resolution.json",
            output_root=tmp_path / f"failed-{failure_kind.lower()}",
            live=True,
            code_revision=CODE_REVISION,
            implementation_manifest_hash=MANIFEST_HASH,
            transport=httpx.MockTransport(handler),
            ledger=_FailingLedger(failure_kind),  # type: ignore[arg-type]
        )
    assert calls == (0 if failure_kind == "START" else 1)


def test_retry_coordination_uses_three_distinct_ledger_attempts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = _cases()[0]
    monkeypatch.setattr(
        "evaluation.run_stage2_deepseek_calibration.load_frozen_calibration_cases",
        lambda *_args: (source.case,),
    )
    monkeypatch.setenv("DEEPSEEK_API_KEY", "bounded-test-key")
    ledger = _FakeLedger()
    calls = 0
    sleeps: list[float] = []
    monkeypatch.setattr(runner_module.time, "sleep", sleeps.append)

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls < 3:
            return httpx.Response(503, headers={"Content-Type": "application/json"}, content=b"{}")
        return httpx.Response(
            200,
            headers={"Content-Type": "application/json"},
            content=source.assessment.raw_response_envelope_bytes,
        )

    with pytest.raises(DeepSeekCalibrationError):
        run_live_calibration(
            machine_packet_path=tmp_path / "machine.json",
            resolution_packet_path=tmp_path / "resolution.json",
            output_root=tmp_path / "three-attempts",
            live=True,
            code_revision=CODE_REVISION,
            implementation_manifest_hash=MANIFEST_HASH,
            transport=httpx.MockTransport(handler),
            ledger=ledger,  # type: ignore[arg-type]
        )
    assert calls == 3
    assert [item.attempt_ordinal for item in ledger.events if item.event_kind == "START"] == [
        1,
        2,
        3,
    ]
    assert [item.disposition for item in ledger.events if item.event_kind == "TERMINAL"] == [
        "retryable_status",
        "retryable_status",
        "success",
    ]
    request_hash = next(item.request_hash for item in ledger.events if item.event_kind == "START")
    assert sleeps == [
        runner_module._retry_delay_seconds(request_hash, 1, None, now_utc=datetime.now(UTC)),
        runner_module._retry_delay_seconds(request_hash, 2, None, now_utc=datetime.now(UTC)),
    ]


def test_retry_after_is_capped_and_jitter_is_deterministic() -> None:
    digest = "sha256:" + "a" * 64
    now = datetime(2026, 8, 31, tzinfo=UTC)
    first = runner_module._retry_delay_seconds(digest, 1, None, now_utc=now)
    assert first == runner_module._retry_delay_seconds(digest, 1, None, now_utc=now)
    assert runner_module._retry_delay_seconds(digest, 1, "99", now_utc=now) == 2.0
    assert (
        runner_module._retry_delay_seconds(digest, 1, "Wed, 31 Aug 2033 12:00:00 GMT", now_utc=now)
        == 2.0
    )


def test_projection_failure_reprojects_from_ledger_without_resend(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = _cases()[0]
    monkeypatch.setattr(
        "evaluation.run_stage2_deepseek_calibration.load_frozen_calibration_cases",
        lambda *_args: (source.case,),
    )
    monkeypatch.setenv("DEEPSEEK_API_KEY", "bounded-test-key")
    ledger = _FakeLedger()
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            headers={"Content-Type": "application/json"},
            content=source.assessment.raw_response_envelope_bytes,
        )

    original = runner_module.persist_provider_event_projection
    monkeypatch.setattr(
        runner_module,
        "persist_provider_event_projection",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("projection write failed")),
    )
    with pytest.raises(OSError, match="projection write failed"):
        run_live_calibration(
            machine_packet_path=tmp_path / "machine.json",
            resolution_packet_path=tmp_path / "resolution.json",
            output_root=tmp_path / "first-projection",
            live=True,
            code_revision=CODE_REVISION,
            implementation_manifest_hash=MANIFEST_HASH,
            transport=httpx.MockTransport(handler),
            ledger=ledger,  # type: ignore[arg-type]
        )
    monkeypatch.setattr(runner_module, "persist_provider_event_projection", original)
    with pytest.raises(DeepSeekCalibrationError, match="resend forbidden"):
        run_live_calibration(
            machine_packet_path=tmp_path / "machine.json",
            resolution_packet_path=tmp_path / "resolution.json",
            output_root=tmp_path / "reprojected",
            live=True,
            code_revision=CODE_REVISION,
            implementation_manifest_hash=MANIFEST_HASH,
            transport=httpx.MockTransport(handler),
            ledger=ledger,  # type: ignore[arg-type]
        )
    assert calls == 1
    projection = json.loads(
        (tmp_path / "reprojected" / "provider-attempt-projection.json").read_text(encoding="utf-8")
    )
    assert projection["attempt_count"] == 1


def test_case_evidence_write_failure_repairs_from_ledger_without_resend(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = _cases()[0]
    cases = (source.case,)
    monkeypatch.setattr(
        runner_module,
        "load_frozen_calibration_cases",
        lambda *_args: cases,
    )
    monkeypatch.setenv("DEEPSEEK_API_KEY", "bounded-test-key")
    ledger = _FakeLedger()
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            headers={"Content-Type": "application/json"},
            content=source.assessment.raw_response_envelope_bytes,
        )

    original_write = calibration_module._write_new_json
    failed = False

    def fail_case_once(path: Path, payload):  # type: ignore[no-untyped-def]
        nonlocal failed
        if path.name == "case-001-evidence.json" and not failed:
            failed = True
            raise OSError("case evidence write failed")
        return original_write(path, payload)

    monkeypatch.setattr(calibration_module, "_write_new_json", fail_case_once)
    first_output = tmp_path / "case-write-failed"
    with pytest.raises(OSError, match="case evidence write failed"):
        run_live_calibration(
            machine_packet_path=tmp_path / "machine.json",
            resolution_packet_path=tmp_path / "resolution.json",
            output_root=first_output,
            live=True,
            code_revision=CODE_REVISION,
            implementation_manifest_hash=MANIFEST_HASH,
            transport=httpx.MockTransport(handler),
            ledger=ledger,  # type: ignore[arg-type]
        )
    assert calls == 1
    assert not (first_output / "case-001-evidence.json").exists()
    assert (
        json.loads((first_output / "run-status.json").read_text(encoding="utf-8"))["status"]
        == "FAILED"
    )
    terminal = next(item for item in ledger.events if item.event_kind == "TERMINAL")
    assert terminal.disposition == "success"

    monkeypatch.setattr(calibration_module, "_write_new_json", original_write)
    repaired_output = tmp_path / "case-write-repaired"
    with pytest.raises(DeepSeekCalibrationError, match="resend forbidden"):
        run_live_calibration(
            machine_packet_path=tmp_path / "machine.json",
            resolution_packet_path=tmp_path / "resolution.json",
            output_root=repaired_output,
            live=True,
            code_revision=CODE_REVISION,
            implementation_manifest_hash=MANIFEST_HASH,
            transport=httpx.MockTransport(handler),
            ledger=ledger,  # type: ignore[arg-type]
        )
    assert calls == 1
    evidence = json.loads((repaired_output / "case-001-evidence.json").read_text(encoding="utf-8"))
    assert (
        bytes.fromhex(evidence["evidence"]["raw_provider_response_hex"])
        == source.assessment.raw_response_envelope_bytes
    )
    projection = _verify_external_failed_run(ledger, repaired_output, cases)
    assert projection["attempt_count"] == 1


def test_shared_deadline_stops_after_retry_closure_before_next_start(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = _cases()[0]
    cases = (source.case,)
    monkeypatch.setattr(runner_module, "load_frozen_calibration_cases", lambda *_args: cases)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "bounded-test-key")
    monkeypatch.setattr(runner_module, "_TOTAL_DEADLINE_SECONDS", 0.1)
    monkeypatch.setattr(runner_module, "_retry_delay_seconds", lambda *_args, **_kwargs: 0.1)
    ledger = _FakeLedger()
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            503,
            headers={"Content-Type": "application/json"},
            content=b"{}",
        )

    output = tmp_path / "deadline-before-retry"
    with pytest.raises(DeepSeekCalibrationError, match="deadline exhausted after terminal"):
        run_live_calibration(
            machine_packet_path=tmp_path / "machine.json",
            resolution_packet_path=tmp_path / "resolution.json",
            output_root=output,
            live=True,
            code_revision=CODE_REVISION,
            implementation_manifest_hash=MANIFEST_HASH,
            transport=httpx.MockTransport(handler),
            ledger=ledger,  # type: ignore[arg-type]
        )
    starts = [item for item in ledger.events if item.event_kind == "START"]
    terminals = [item for item in ledger.events if item.event_kind == "TERMINAL"]
    assert calls == 1
    assert [item.attempt_ordinal for item in starts] == [1]
    assert [item.disposition for item in terminals] == ["retryable_status"]
    projection = _verify_external_failed_run(ledger, output, cases)
    assert projection["attempt_count"] == 1


def test_streaming_deadline_publishes_verifiable_failed_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = _cases()[0]
    cases = (source.case,)
    monkeypatch.setattr(runner_module, "load_frozen_calibration_cases", lambda *_args: cases)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "bounded-test-key")
    monkeypatch.setattr(runner_module, "_TOTAL_DEADLINE_SECONDS", 0.05)
    ledger = _FakeLedger()
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            headers={"Content-Type": "application/json"},
            stream=_DeadlineStream(),
        )

    output = tmp_path / "streaming-deadline"
    with pytest.raises(DeepSeekSemanticEvaluatorError, match="deadline_exceeded"):
        run_live_calibration(
            machine_packet_path=tmp_path / "machine.json",
            resolution_packet_path=tmp_path / "resolution.json",
            output_root=output,
            live=True,
            code_revision=CODE_REVISION,
            implementation_manifest_hash=MANIFEST_HASH,
            transport=httpx.MockTransport(handler),
            ledger=ledger,  # type: ignore[arg-type]
        )
    terminal = next(item for item in ledger.events if item.event_kind == "TERMINAL")
    assert calls == 1
    assert terminal.http_status == 200
    assert terminal.disposition == "deadline_exceeded"
    assert terminal.body_hash is None and terminal.body_relative_path is None
    projection = _verify_external_failed_run(ledger, output, cases)
    assert projection["status"] == "FAILED"


@pytest.mark.parametrize(
    ("failure_name", "headers", "raw"),
    (
        (
            "invalid-framing",
            {"Content-Type": "application/json", "Content-Length": "999999"},
            _cases()[0].assessment.raw_response_envelope_bytes,
        ),
        ("invalid-json", {"Content-Type": "application/json"}, b"{"),
    ),
)
def test_invalid_response_preserves_safe_raw_and_publishes_verifiable_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    failure_name: str,
    headers: dict[str, str],
    raw: bytes,
) -> None:
    observations = _cases()
    cases = (observations[0].case, observations[1].case)
    monkeypatch.setattr(runner_module, "load_frozen_calibration_cases", lambda *_args: cases)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "bounded-test-key")
    ledger = _FakeLedger()
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, headers=headers, content=raw)

    output = tmp_path / failure_name
    with pytest.raises(DeepSeekSemanticEvaluatorError, match="response_invalid"):
        run_live_calibration(
            machine_packet_path=tmp_path / "machine.json",
            resolution_packet_path=tmp_path / "resolution.json",
            output_root=output,
            live=True,
            code_revision=CODE_REVISION,
            implementation_manifest_hash=MANIFEST_HASH,
            transport=httpx.MockTransport(handler),
            ledger=ledger,  # type: ignore[arg-type]
        )
    terminal = next(item for item in ledger.events if item.event_kind == "TERMINAL")
    assert calls == 1
    assert terminal.case_ordinal == 1
    assert terminal.disposition == "response_invalid"
    assert terminal.body_relative_path is not None
    assert (output.parent / terminal.body_relative_path).read_bytes() == raw
    assert not (output / "case-001-evidence.json").exists()
    assert not (output / "case-002-evidence.json").exists()
    projection = _verify_external_failed_run(ledger, output, cases)
    assert projection["status"] == "FAILED"
