from __future__ import annotations

import gzip
import json
import sys
from dataclasses import replace
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
    historical_attempt010_calibration_configuration,
    provider_attempt_run_id,
    verify_external_run,
)
from tests.unit.evaluation.test_stage2_deepseek_calibration import _cases, _rehash_v2_event

import medevidence.infrastructure.deepseek_semantic_evaluator as evaluator_module
from medevidence.infrastructure.deepseek_responses_transport import (
    DeepSeekOneOperationObservation,
    DeepSeekTransportErrorCode,
)
from medevidence.infrastructure.deepseek_semantic_evaluator import (
    DEEPSEEK_SEMANTIC_V2_PROVIDER_CONFIGURATION_HASH,
    DeepSeekSemanticEvaluatorError,
    parse_deepseek_completed_response_v2,
)
from medevidence.persistence import ProviderAttemptEvent, make_provider_attempt_event

CODE_REVISION = "a" * 40
MANIFEST_HASH = "sha256:" + "b" * 64


def _v2_response(*args: object, **kwargs: object) -> httpx.Response:
    kwargs.setdefault("extensions", {"http_version": b"HTTP/2"})
    return httpx.Response(*args, **kwargs)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("http_status", "transport_error", "credential_echo"),
    (
        (200, None, False),
        (429, None, False),
        (401, None, False),
        (418, None, False),
        (None, DeepSeekTransportErrorCode.PROVIDER_UNAVAILABLE, False),
        (200, None, True),
    ),
)
def test_runner_uses_one_i2_disposition_authority(
    http_status: int | None,
    transport_error: DeepSeekTransportErrorCode | None,
    credential_echo: bool,
) -> None:
    now = datetime(2026, 9, 1, tzinfo=UTC)
    observation = DeepSeekOneOperationObservation(
        http_status=http_status,
        approved_headers={},
        raw_body=None,
        body_complete=False,
        observed_body_bytes_lower_bound=0,
        credential_echo=credential_echo,
        transport_error=transport_error,
        started_at_utc=now,
        completed_at_utc=now,
    )
    expected = runner_module.derive_deepseek_v2_disposition(observation)
    assert runner_module._attempt_disposition(observation, None, stage="transport") == expected


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
            configuration_hash=DEEPSEEK_SEMANTIC_V2_PROVIDER_CONFIGURATION_HASH,
            request_hash=source.assessment.provider_request_hash,
            started_at_utc=datetime(2026, 8, 31, tzinfo=UTC),
            schema_version="M3_PROVIDER_ATTEMPT_EVENT_V2",
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
            schema_version="M3_PROVIDER_ATTEMPT_EVENT_V2",
        )
        self.events[:] = [start, recovery]
        return (recovery,)


class _FakeMonotonic:
    def __init__(self, now: float = 100.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


class _ClockAdvancingLedger(_FakeLedger):
    def __init__(
        self,
        clock: _FakeMonotonic,
        *,
        acquire_seconds: float = 0.0,
        start_seconds: float = 0.0,
    ) -> None:
        super().__init__()
        self._clock = clock
        self._acquire_seconds = acquire_seconds
        self._start_seconds = start_seconds

    def acquire_run_lease(self, run_id: str):  # type: ignore[no-untyped-def]
        lease = super().acquire_run_lease(run_id)
        self._clock.now += self._acquire_seconds
        return lease

    def append(self, event: ProviderAttemptEvent) -> ProviderAttemptEvent:
        appended = super().append(event)
        if event.event_kind == "START":
            self._clock.now += self._start_seconds
        return appended


class _LeaseConflictLedger(_FakeLedger):
    def acquire_run_lease(self, _run_id: str):  # type: ignore[no-untyped-def]
        self.acquired += 1
        raise RuntimeError("lease conflict")


class _DeadlineStream(httpx.SyncByteStream):
    def __init__(self, clock: _FakeMonotonic, deadline_at: float) -> None:
        self._clock = clock
        self._deadline_at = deadline_at

    def __iter__(self):  # type: ignore[no-untyped-def]
        yield b"{"
        self._clock.now = self._deadline_at
        raise httpx.ReadTimeout("second read reached the absolute deadline")


def _incomplete_stream_observation(*, observed: int = 0) -> DeepSeekOneOperationObservation:
    now = datetime.now(UTC)
    return DeepSeekOneOperationObservation(
        http_status=200,
        approved_headers={"content-type": "application/json"},
        raw_body=None,
        body_complete=False,
        observed_body_bytes_lower_bound=observed,
        credential_echo=False,
        transport_error=DeepSeekTransportErrorCode.PROVIDER_UNAVAILABLE,
        started_at_utc=now,
        completed_at_utc=now,
        response_http_version="HTTP/2",
        response_header_items=(("content-type", "application/json"),),
        response_header_field_count=1,
    )


def _complete_observation(raw: bytes) -> DeepSeekOneOperationObservation:
    now = datetime.now(UTC)
    return DeepSeekOneOperationObservation(
        http_status=200,
        approved_headers={"content-type": "application/json"},
        raw_body=raw,
        body_complete=True,
        observed_body_bytes_lower_bound=len(raw),
        credential_echo=False,
        transport_error=None,
        started_at_utc=now,
        completed_at_utc=now,
        response_http_version="HTTP/2",
        response_header_items=(("content-type", "application/json"),),
        response_header_field_count=1,
    )


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
            return _v2_response(
                200,
                headers={"Content-Type": "application/json"},
                content=first_response,
            )
        return _v2_response(
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
    clock = _FakeMonotonic()

    def handler(_request: httpx.Request) -> httpx.Response:
        return _v2_response(
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
            monotonic_clock=clock,
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
        parse_deepseek_completed_response_v2(invalid_response)
    assert key_marker.encode() not in b"".join(path.read_bytes() for path in output.iterdir())


def test_runner_has_no_openai_selector_or_conversation_chaining() -> None:
    source = Path("evaluation/run_stage2_deepseek_calibration.py").read_text(encoding="utf-8")
    lowered = source.lower()
    assert "openai" not in lowered
    assert "provider selector" not in lowered
    assert "previous_response_id" not in lowered
    assert "conversation" not in lowered
    assert "finalize_deepseek_one_operation_v4" not in source
    assert "deepseek_provider_request_bytes" not in source
    assert "DeepSeekResponsesSemanticEvaluatorV2" in source
    assert "finalize_deepseek_one_operation_semantic_v2" in source


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
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return _v2_response(
            200,
            headers={"Content-Type": "application/json"},
            content=(b'{"echo":"' + key.encode() + b'"}'),
        )

    with pytest.raises(Exception, match="credential_echo"):
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
    assert calls == 1
    terminal = next(item for item in ledger.events if item.event_kind == "TERMINAL")
    assert terminal.disposition == "credential_echo"
    assert terminal.credential_echo is True
    assert terminal.body_hash is None and terminal.body_relative_path is None
    assert not any(path.suffix == ".bin" for path in output.iterdir())
    assert key.encode() not in b"".join(path.read_bytes() for path in output.iterdir())


def test_evidence_persistence_failure_is_fact_free_terminal_and_stops(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = _cases()[0]
    monkeypatch.setattr(
        runner_module, "load_frozen_calibration_cases", lambda *_args: (source.case,)
    )
    monkeypatch.setattr(
        runner_module,
        "persist_safe_raw_body",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("raw persistence failed")),
    )
    monkeypatch.setenv("DEEPSEEK_API_KEY", "bounded-test-key")
    ledger = _FakeLedger()
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return _v2_response(
            200,
            headers={"Content-Type": "application/json"},
            content=source.assessment.raw_response_envelope_bytes,
        )

    output = tmp_path / "evidence-persistence-failure"
    with pytest.raises(OSError, match="raw persistence failed"):
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
    assert calls == 1
    assert [item.event_kind for item in ledger.events] == ["START", "TERMINAL"]
    terminal = ledger.events[-1]
    assert terminal.disposition == "evidence_persistence_failure"
    assert terminal.http_status == 200
    assert terminal.framing_status == "unavailable_not_classified"
    assert terminal.body_hash is None and terminal.body_relative_path is None
    assert terminal.normalized_header_names == ()
    assert terminal.normalized_content_type_values is None
    assert not (output / "case-001-evidence.json").exists()
    assert _verify_external_failed_run(ledger, output, (source.case,))["status"] == "FAILED"

    start = ledger.events[0]
    bad_start = _rehash_v2_event(replace(start, case_ordinal=True))
    bad_terminal = _rehash_v2_event(
        replace(terminal, case_ordinal=True, start_event_id=bad_start.event_id)
    )
    ledger.events[:] = [bad_start, bad_terminal]
    with pytest.raises(DeepSeekCalibrationError, match="canonical validation failed"):
        _verify_external_failed_run(ledger, output, (source.case,))


def test_injected_gzip_observation_never_persists_or_hashes_compressed_key(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = _cases()[0]
    monkeypatch.setattr(
        runner_module, "load_frozen_calibration_cases", lambda *_args: (source.case,)
    )
    key = "synthetic-compressed-key-must-not-persist"
    monkeypatch.setenv("DEEPSEEK_API_KEY", key)
    compressed = gzip.compress(key.encode("ascii"), mtime=0)

    def injected_observation() -> DeepSeekOneOperationObservation:
        observed_at = datetime.now(UTC)
        return DeepSeekOneOperationObservation(
            http_status=200,
            approved_headers={
                "content-encoding": "gzip",
                "content-type": "application/json",
            },
            raw_body=compressed,
            body_complete=True,
            observed_body_bytes_lower_bound=len(compressed),
            credential_echo=False,
            transport_error=None,
            started_at_utc=observed_at,
            completed_at_utc=observed_at,
            response_http_version="HTTP/2",
            response_header_items=(
                ("content-encoding", "gzip"),
                ("content-type", "application/json"),
            ),
            response_header_field_count=2,
        )

    monkeypatch.setattr(
        runner_module.DeepSeekResponsesSemanticEvaluatorV2,
        "observe",
        lambda *_args, **_kwargs: injected_observation(),
    )
    original_sha256 = calibration_module._sha256

    def reject_compressed_hash(value: bytes) -> str:
        if value == compressed:
            raise AssertionError("compressed provider bytes must not be hashed")
        return original_sha256(value)

    monkeypatch.setattr(calibration_module, "_sha256", reject_compressed_hash)
    ledger = _FakeLedger()
    output = tmp_path / "injected-compressed-response"

    with pytest.raises(DeepSeekSemanticEvaluatorError, match="response_invalid"):
        run_live_calibration(
            machine_packet_path=tmp_path / "machine.json",
            resolution_packet_path=tmp_path / "resolution.json",
            output_root=output,
            live=True,
            code_revision=CODE_REVISION,
            implementation_manifest_hash=MANIFEST_HASH,
            transport=httpx.MockTransport(lambda _request: pytest.fail("send is injected")),
            ledger=ledger,  # type: ignore[arg-type]
        )

    terminal = ledger.events[-1]
    assert terminal.disposition == "response_invalid"
    assert terminal.content_encoding_state == "unsupported"
    assert terminal.framing_rejection_code == "compression_not_identity"
    assert terminal.body_hash is None and terminal.body_relative_path is None
    assert terminal.raw_body_hash is None and terminal.raw_relative_path is None
    raw_root = output.parent / "provider-attempt-raw"
    assert not raw_root.exists()
    assert _verify_external_failed_run(ledger, output, (source.case,))["status"] == "FAILED"


def test_http_200_validation_runtime_error_is_truthful_nonretryable_terminal(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = _cases()[0]
    monkeypatch.setattr(
        runner_module, "load_frozen_calibration_cases", lambda *_args: (source.case,)
    )
    monkeypatch.setenv("DEEPSEEK_API_KEY", "bounded-test-key")
    monkeypatch.setattr(
        runner_module,
        "finalize_deepseek_one_operation_semantic_v2",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("validation exploded")),
    )
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return _v2_response(
            200,
            headers={"Content-Type": "application/json"},
            content=source.assessment.raw_response_envelope_bytes,
        )

    ledger = _FakeLedger()
    output = tmp_path / "validation-internal-failure"
    with pytest.raises(RuntimeError, match="validation exploded"):
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

    assert calls == 1
    terminal = ledger.events[-1]
    assert terminal.disposition == "validation_internal_failure"
    assert terminal.error_code == "validation_internal_failure"
    assert terminal.body_hash is not None and terminal.body_relative_path is not None
    assert terminal.framing_status == "accepted"
    projection = _verify_external_failed_run(ledger, output, (source.case,))
    assert projection["status"] == "FAILED"
    assert projection["events"][-1]["disposition"] == "validation_internal_failure"
    assert projection["events"][-1]["error_code"] == "validation_internal_failure"


def test_missing_http_version_precedes_invalid_content_length_and_closes_terminal(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = _cases()[0]
    monkeypatch.setattr(
        runner_module, "load_frozen_calibration_cases", lambda *_args: (source.case,)
    )
    monkeypatch.setenv("DEEPSEEK_API_KEY", "bounded-test-key")
    ledger = _FakeLedger()

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"Content-Type": "application/json", "Content-Length": "01"},
            content=source.assessment.raw_response_envelope_bytes,
        )

    output = tmp_path / "missing-version-precedence"
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
    terminal = ledger.events[-1]
    assert terminal.event_kind == "TERMINAL"
    assert terminal.disposition == "response_invalid"
    assert terminal.framing_status == "rejected"
    assert terminal.framing_rejection_code == "missing_http_version"
    assert terminal.content_length_state == "invalid"
    assert terminal.body_hash is not None


def test_response_overflow_preserves_exact_transport_lower_bound_in_projection(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = _cases()[0]
    monkeypatch.setattr(
        runner_module, "load_frozen_calibration_cases", lambda *_args: (source.case,)
    )
    monkeypatch.setenv("DEEPSEEK_API_KEY", "bounded-test-key")
    ledger = _FakeLedger()
    observed = 131_073

    def handler(_request: httpx.Request) -> httpx.Response:
        return _v2_response(
            200,
            headers={"Content-Type": "application/json"},
            content=b"x" * observed,
        )

    output = tmp_path / "response-overflow-lower-bound"
    with pytest.raises(DeepSeekSemanticEvaluatorError, match="response_too_large"):
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
    terminal = ledger.events[-1]
    assert terminal.disposition == "response_too_large"
    assert terminal.body_complete is False
    assert terminal.observed_body_bytes_lower_bound == observed
    assert terminal.body_byte_count is None
    assert terminal.body_hash is None and terminal.body_relative_path is None
    projection = json.loads(
        (output / "provider-attempt-projection.json").read_text(encoding="utf-8")
    )
    projected_terminal = projection["events"][-1]
    assert projected_terminal["observed_body_bytes_lower_bound"] == observed
    assert projected_terminal["framing_input_identity"] == terminal.framing_input_identity


def test_129_header_surface_count_rejects_and_replays_exact_ledger_metadata(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = _cases()[0]
    monkeypatch.setattr(
        runner_module, "load_frozen_calibration_cases", lambda *_args: (source.case,)
    )
    monkeypatch.setenv("DEEPSEEK_API_KEY", "bounded-test-key")
    ledger = _FakeLedger()
    filler = [(f"X-Unapproved-{index}", "safe") for index in range(127)]

    def handler(_request: httpx.Request) -> httpx.Response:
        return _v2_response(
            200,
            headers=[("Content-Type", "application/json"), *filler],
            content=source.assessment.raw_response_envelope_bytes,
        )

    output = tmp_path / "header-surface-count-129"
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
    terminal = ledger.events[-1]
    assert terminal.disposition == "response_invalid"
    assert terminal.raw_header_field_count == 129
    assert terminal.framing_rejection_code == "invalid_approved_header_surface"
    assert terminal.credential_echo is False
    assert terminal.error_code == "response_invalid"
    projection = _verify_external_failed_run(ledger, output, (source.case,))
    projected_terminal = projection["events"][-1]
    assert projected_terminal["raw_header_field_count"] == 129
    assert projected_terminal["credential_echo"] is False
    assert projected_terminal["error_code"] == "response_invalid"


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
            configuration_hash=DEEPSEEK_SEMANTIC_V2_PROVIDER_CONFIGURATION_HASH,
            request_hash="sha256:" + "0" * 64,
            started_at_utc=datetime(2026, 8, 31, tzinfo=UTC),
            schema_version="M3_PROVIDER_ATTEMPT_EVENT_V2",
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


def test_attempt011_isolated_from_attempt010_and_same_run_resend_remains_forbidden(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = _cases()[0]
    monkeypatch.setattr(
        "evaluation.run_stage2_deepseek_calibration.load_frozen_calibration_cases",
        lambda *_args: (source.case,),
    )
    monkeypatch.setenv("DEEPSEEK_API_KEY", "bounded-test-key")
    historical_run_id = provider_attempt_run_id(
        historical_attempt010_calibration_configuration(
            code_revision=CODE_REVISION,
            implementation_manifest_hash=MANIFEST_HASH,
        )
    )
    active_run_id = provider_attempt_run_id(
        calibration_configuration(
            code_revision=CODE_REVISION,
            implementation_manifest_hash=MANIFEST_HASH,
        )
    )
    assert historical_run_id != active_run_id
    ledger = _FakeLedger()
    historical_start = make_provider_attempt_event(
        provider_run_id=historical_run_id,
        case_id=source.case.case_id,
        case_ordinal=source.case.ordinal,
        attempt_ordinal=1,
        event_kind="START",
        configuration_hash=DEEPSEEK_SEMANTIC_V2_PROVIDER_CONFIGURATION_HASH,
        request_hash=source.assessment.provider_request_hash,
        started_at_utc=datetime(2026, 9, 3, tzinfo=UTC),
        schema_version="M3_PROVIDER_ATTEMPT_EVENT_V2",
    )
    ledger.events.append(historical_start)
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return _v2_response(401, headers={"Content-Type": "application/json"}, content=b"{}")

    with pytest.raises(DeepSeekSemanticEvaluatorError):
        run_live_calibration(
            machine_packet_path=tmp_path / "machine.json",
            resolution_packet_path=tmp_path / "resolution.json",
            output_root=tmp_path / "attempt011-first",
            live=True,
            code_revision=CODE_REVISION,
            implementation_manifest_hash=MANIFEST_HASH,
            transport=httpx.MockTransport(handler),
            ledger=ledger,  # type: ignore[arg-type]
        )
    assert calls == 1
    assert ledger.events[0] == historical_start
    assert len(ledger.list_events(historical_run_id)) == 1
    assert len(ledger.list_events(active_run_id)) == 2

    with pytest.raises(DeepSeekCalibrationError, match="resend forbidden"):
        run_live_calibration(
            machine_packet_path=tmp_path / "machine.json",
            resolution_packet_path=tmp_path / "resolution.json",
            output_root=tmp_path / "attempt011-reprojection",
            live=True,
            code_revision=CODE_REVISION,
            implementation_manifest_hash=MANIFEST_HASH,
            transport=httpx.MockTransport(handler),
            ledger=ledger,  # type: ignore[arg-type]
        )
    assert calls == 1
    assert ledger.events[0] == historical_start


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
        return _v2_response(200, headers={"Content-Type": "application/json"}, content=response)

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
            return _v2_response(503, headers={"Content-Type": "application/json"}, content=b"{}")
        return _v2_response(
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


def test_incomplete_stream_then_success_reuses_deadline_and_records_attempt_two(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = _cases()[0]
    monkeypatch.setattr(
        runner_module, "load_frozen_calibration_cases", lambda *_args: (source.case,)
    )
    monkeypatch.setenv("DEEPSEEK_API_KEY", "bounded-test-key")
    monkeypatch.setattr(runner_module, "_retry_delay_seconds", lambda *_args, **_kwargs: 0.0)
    monkeypatch.setattr(runner_module.time, "sleep", lambda _seconds: None)
    ledger = _FakeLedger()
    deadlines: list[float] = []
    captured_attempts: list[int] = []

    def observe(
        *_args: object,
        absolute_deadline_monotonic: float,
        **_kwargs: object,
    ) -> DeepSeekOneOperationObservation:
        deadlines.append(absolute_deadline_monotonic)
        if len(deadlines) == 1:
            return _incomplete_stream_observation(observed=0)
        return _complete_observation(source.assessment.raw_response_envelope_bytes)

    def stop_after_case(_run: object, item: object, **_kwargs: object) -> None:
        captured_attempts.append(item.assessment.attempts)  # type: ignore[attr-defined]
        raise RuntimeError("stop after persisted assessment inspection")

    monkeypatch.setattr(runner_module.DeepSeekResponsesSemanticEvaluatorV2, "observe", observe)
    monkeypatch.setattr(runner_module, "persist_successful_calibration_case", stop_after_case)
    with pytest.raises(RuntimeError, match="persisted assessment inspection"):
        run_live_calibration(
            machine_packet_path=tmp_path / "machine.json",
            resolution_packet_path=tmp_path / "resolution.json",
            output_root=tmp_path / "incomplete-then-success",
            live=True,
            code_revision=CODE_REVISION,
            implementation_manifest_hash=MANIFEST_HASH,
            transport=httpx.MockTransport(lambda _request: pytest.fail("observe is patched")),
            ledger=ledger,  # type: ignore[arg-type]
        )
    assert deadlines[0] == deadlines[1]
    assert captured_attempts == [2]
    assert [event.attempt_ordinal for event in ledger.events if event.event_kind == "START"] == [
        1,
        2,
    ]
    terminals = [event for event in ledger.events if event.event_kind == "TERMINAL"]
    assert [event.disposition for event in terminals] == ["transport_unavailable", "success"]
    assert terminals[0].body_hash is None and terminals[0].body_relative_path is None
    assert terminals[0].observed_body_bytes_lower_bound == 0
    assert terminals[1].body_hash is not None


def test_repeated_incomplete_streams_stop_after_three_attempts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = _cases()[0]
    monkeypatch.setattr(
        runner_module, "load_frozen_calibration_cases", lambda *_args: (source.case,)
    )
    monkeypatch.setenv("DEEPSEEK_API_KEY", "bounded-test-key")
    monkeypatch.setattr(runner_module, "_retry_delay_seconds", lambda *_args, **_kwargs: 0.0)
    monkeypatch.setattr(runner_module.time, "sleep", lambda _seconds: None)
    ledger = _FakeLedger()
    calls = 0

    def observe(*_args: object, **_kwargs: object) -> DeepSeekOneOperationObservation:
        nonlocal calls
        calls += 1
        return _incomplete_stream_observation()

    monkeypatch.setattr(runner_module.DeepSeekResponsesSemanticEvaluatorV2, "observe", observe)
    with pytest.raises(DeepSeekSemanticEvaluatorError, match="provider_unavailable"):
        run_live_calibration(
            machine_packet_path=tmp_path / "machine.json",
            resolution_packet_path=tmp_path / "resolution.json",
            output_root=tmp_path / "three-incomplete-streams",
            live=True,
            code_revision=CODE_REVISION,
            implementation_manifest_hash=MANIFEST_HASH,
            transport=httpx.MockTransport(lambda _request: pytest.fail("observe is patched")),
            ledger=ledger,  # type: ignore[arg-type]
        )
    assert calls == 3
    assert [event.attempt_ordinal for event in ledger.events if event.event_kind == "START"] == [
        1,
        2,
        3,
    ]
    terminals = [event for event in ledger.events if event.event_kind == "TERMINAL"]
    assert [event.disposition for event in terminals] == ["transport_unavailable"] * 3
    assert all(event.body_hash is None and event.body_relative_path is None for event in terminals)


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
        return _v2_response(
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
        return _v2_response(
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


def test_first_case_deadline_counts_lease_and_start_then_passes_original_absolute(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = _cases()[0]
    monkeypatch.setattr(
        runner_module, "load_frozen_calibration_cases", lambda *_args: (source.case,)
    )
    monkeypatch.setenv("DEEPSEEK_API_KEY", "bounded-test-key")
    clock = _FakeMonotonic()
    ledger = _ClockAdvancingLedger(clock, acquire_seconds=40.0, start_seconds=4.0)
    observed_deadlines: list[float] = []
    observed_clocks: list[object] = []

    def observe(
        *_args: object,
        absolute_deadline_monotonic: float,
        monotonic_clock: object,
        **_kwargs: object,
    ) -> object:
        observed_deadlines.append(absolute_deadline_monotonic)
        observed_clocks.append(monotonic_clock)
        raise RuntimeError("stop after absolute deadline capture")

    monkeypatch.setattr(runner_module.DeepSeekResponsesSemanticEvaluatorV2, "observe", observe)
    with pytest.raises(RuntimeError, match="absolute deadline capture"):
        run_live_calibration(
            machine_packet_path=tmp_path / "machine.json",
            resolution_packet_path=tmp_path / "resolution.json",
            output_root=tmp_path / "fresh-remaining",
            live=True,
            code_revision=CODE_REVISION,
            implementation_manifest_hash=MANIFEST_HASH,
            transport=httpx.MockTransport(lambda _request: pytest.fail("send is patched")),
            ledger=ledger,  # type: ignore[arg-type]
            monotonic_clock=clock,
        )
    assert observed_deadlines == [145.0]
    assert observed_clocks == [clock]
    assert clock.now == 144.0
    assert [event.event_kind for event in ledger.events] == ["START", "TERMINAL"]


def test_transport_receives_only_true_post_start_remainder(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = _cases()[0]
    monkeypatch.setattr(
        runner_module, "load_frozen_calibration_cases", lambda *_args: (source.case,)
    )
    monkeypatch.setenv("DEEPSEEK_API_KEY", "bounded-test-key")
    monkeypatch.setattr(runner_module, "_retry_delay_seconds", lambda *_args, **_kwargs: 2.0)
    clock = _FakeMonotonic()
    ledger = _ClockAdvancingLedger(clock, acquire_seconds=40.0, start_seconds=4.0)
    timeout_facts: list[dict[str, float]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        timeout_facts.append(request.extensions["timeout"])
        return _v2_response(
            503,
            headers={"Content-Type": "application/json"},
            content=b"{}",
        )

    with pytest.raises(DeepSeekCalibrationError, match="deadline exhausted after terminal"):
        run_live_calibration(
            machine_packet_path=tmp_path / "machine.json",
            resolution_packet_path=tmp_path / "resolution.json",
            output_root=tmp_path / "true-post-start-remainder",
            live=True,
            code_revision=CODE_REVISION,
            implementation_manifest_hash=MANIFEST_HASH,
            transport=httpx.MockTransport(handler),
            ledger=ledger,  # type: ignore[arg-type]
            monotonic_clock=clock,
        )

    assert timeout_facts == [{"connect": 1.0, "read": 1.0, "write": 1.0, "pool": 1.0}]


def test_deadline_exhausted_by_durable_start_closes_fact_free_without_evaluator(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = _cases()[0]
    monkeypatch.setattr(
        runner_module, "load_frozen_calibration_cases", lambda *_args: (source.case,)
    )
    monkeypatch.setenv("DEEPSEEK_API_KEY", "bounded-test-key")
    clock = _FakeMonotonic()
    ledger = _ClockAdvancingLedger(clock, acquire_seconds=44.0, start_seconds=1.0)
    monkeypatch.setattr(
        runner_module.DeepSeekResponsesSemanticEvaluatorV2,
        "observe",
        lambda *_args, **_kwargs: pytest.fail("deadline-exhausted START must not evaluate"),
    )

    with pytest.raises(DeepSeekCalibrationError, match="after durable START"):
        run_live_calibration(
            machine_packet_path=tmp_path / "machine.json",
            resolution_packet_path=tmp_path / "resolution.json",
            output_root=tmp_path / "exhausted-after-start",
            live=True,
            code_revision=CODE_REVISION,
            implementation_manifest_hash=MANIFEST_HASH,
            transport=httpx.MockTransport(lambda _request: pytest.fail("must not send")),
            ledger=ledger,  # type: ignore[arg-type]
            monotonic_clock=clock,
        )
    assert [event.event_kind for event in ledger.events] == ["START", "TERMINAL"]
    terminal = ledger.events[-1]
    assert terminal.disposition == "deadline_exceeded"
    assert terminal.error_code == "deadline_exceeded"
    assert terminal.http_status is None
    assert terminal.body_complete is None
    assert terminal.body_hash is None and terminal.body_relative_path is None
    assert terminal.framing_status is None


def test_successful_lease_exhausting_budget_still_closes_durable_start_without_evaluator(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = _cases()[0]
    monkeypatch.setattr(
        runner_module, "load_frozen_calibration_cases", lambda *_args: (source.case,)
    )
    monkeypatch.setenv("DEEPSEEK_API_KEY", "bounded-test-key")
    clock = _FakeMonotonic()
    ledger = _ClockAdvancingLedger(clock, acquire_seconds=45.0)
    monkeypatch.setattr(
        runner_module.DeepSeekResponsesSemanticEvaluatorV2,
        "observe",
        lambda *_args, **_kwargs: pytest.fail("expired lease budget must not evaluate"),
    )

    with pytest.raises(DeepSeekCalibrationError, match="after durable START"):
        run_live_calibration(
            machine_packet_path=tmp_path / "machine.json",
            resolution_packet_path=tmp_path / "resolution.json",
            output_root=tmp_path / "exhausted-during-lease",
            live=True,
            code_revision=CODE_REVISION,
            implementation_manifest_hash=MANIFEST_HASH,
            transport=httpx.MockTransport(lambda _request: pytest.fail("must not send")),
            ledger=ledger,  # type: ignore[arg-type]
            monotonic_clock=clock,
        )
    assert [event.event_kind for event in ledger.events] == ["START", "TERMINAL"]
    terminal = ledger.events[-1]
    assert terminal.disposition == "deadline_exceeded"
    assert terminal.error_code == "deadline_exceeded"
    assert ledger.acquired == 1 and ledger.released == 1


def test_lease_conflict_without_ownership_has_zero_events_and_zero_http(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = _cases()[0]
    monkeypatch.setattr(
        runner_module, "load_frozen_calibration_cases", lambda *_args: (source.case,)
    )
    monkeypatch.setenv("DEEPSEEK_API_KEY", "bounded-test-key")
    ledger = _LeaseConflictLedger()
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise AssertionError("lease conflict must prevent HTTP")

    with pytest.raises(RuntimeError, match="lease conflict"):
        run_live_calibration(
            machine_packet_path=tmp_path / "machine.json",
            resolution_packet_path=tmp_path / "resolution.json",
            output_root=tmp_path / "lease-conflict",
            live=True,
            code_revision=CODE_REVISION,
            implementation_manifest_hash=MANIFEST_HASH,
            transport=httpx.MockTransport(handler),
            ledger=ledger,  # type: ignore[arg-type]
        )

    assert ledger.events == []
    assert calls == 0


def test_evaluator_setup_expiry_persists_deadline_terminal_without_http(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = _cases()[0]
    monkeypatch.setattr(
        runner_module, "load_frozen_calibration_cases", lambda *_args: (source.case,)
    )
    monkeypatch.setenv("DEEPSEEK_API_KEY", "bounded-test-key")
    clock = _FakeMonotonic()
    ledger = _FakeLedger()
    calls = 0
    original = evaluator_module.deepseek_provider_request_semantic_v2_bytes

    def delayed_request_bytes(request: object) -> bytes:
        result = original(request)  # type: ignore[arg-type]
        clock.now = 145.0
        return result

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise AssertionError("expired evaluator setup must prevent HTTP")

    monkeypatch.setattr(
        evaluator_module,
        "deepseek_provider_request_semantic_v2_bytes",
        delayed_request_bytes,
    )
    with pytest.raises(DeepSeekSemanticEvaluatorError, match="deadline_exceeded"):
        run_live_calibration(
            machine_packet_path=tmp_path / "machine.json",
            resolution_packet_path=tmp_path / "resolution.json",
            output_root=tmp_path / "setup-deadline",
            live=True,
            code_revision=CODE_REVISION,
            implementation_manifest_hash=MANIFEST_HASH,
            transport=httpx.MockTransport(handler),
            ledger=ledger,  # type: ignore[arg-type]
            monotonic_clock=clock,
        )

    assert calls == 0
    assert [event.event_kind for event in ledger.events] == ["START", "TERMINAL"]
    assert ledger.events[-1].disposition == "deadline_exceeded"


def test_retries_reuse_coordinator_absolute_deadline_and_clock(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = _cases()[0]
    monkeypatch.setattr(
        runner_module, "load_frozen_calibration_cases", lambda *_args: (source.case,)
    )
    monkeypatch.setenv("DEEPSEEK_API_KEY", "bounded-test-key")
    monkeypatch.setattr(runner_module, "_retry_delay_seconds", lambda *_args, **_kwargs: 1.0)
    clock = _FakeMonotonic()
    monkeypatch.setattr(
        runner_module.time,
        "sleep",
        lambda seconds: setattr(clock, "now", clock.now + seconds),
    )
    ledger = _FakeLedger()
    deadlines: list[float] = []
    clocks: list[object] = []

    def observe(
        *_args: object,
        absolute_deadline_monotonic: float,
        monotonic_clock: object,
        **_kwargs: object,
    ) -> DeepSeekOneOperationObservation:
        deadlines.append(absolute_deadline_monotonic)
        clocks.append(monotonic_clock)
        clock.now += 2.0
        if len(deadlines) == 2:
            raise RuntimeError("stop after retry deadline capture")
        now = datetime.now(UTC)
        return DeepSeekOneOperationObservation(
            http_status=None,
            approved_headers={},
            raw_body=None,
            body_complete=False,
            observed_body_bytes_lower_bound=0,
            credential_echo=False,
            transport_error=DeepSeekTransportErrorCode.PROVIDER_UNAVAILABLE,
            started_at_utc=now,
            completed_at_utc=now,
        )

    monkeypatch.setattr(runner_module.DeepSeekResponsesSemanticEvaluatorV2, "observe", observe)
    with pytest.raises(RuntimeError, match="retry deadline capture"):
        run_live_calibration(
            machine_packet_path=tmp_path / "machine.json",
            resolution_packet_path=tmp_path / "resolution.json",
            output_root=tmp_path / "retry-shared-deadline",
            live=True,
            code_revision=CODE_REVISION,
            implementation_manifest_hash=MANIFEST_HASH,
            transport=httpx.MockTransport(lambda _request: pytest.fail("observe is patched")),
            ledger=ledger,  # type: ignore[arg-type]
            monotonic_clock=clock,
        )
    assert deadlines == [145.0, 145.0]
    assert clocks == [clock, clock]
    assert clock.now == 105.0


def test_shared_deadline_stops_after_retry_closure_before_next_start(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = _cases()[0]
    cases = (source.case,)
    monkeypatch.setattr(runner_module, "load_frozen_calibration_cases", lambda *_args: cases)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "bounded-test-key")
    monkeypatch.setattr(runner_module, "_TOTAL_DEADLINE_SECONDS", 0.1)
    monkeypatch.setattr(runner_module, "_retry_delay_seconds", lambda *_args, **_kwargs: 0.1)
    clock = _FakeMonotonic()
    sleeps: list[float] = []
    monkeypatch.setattr(runner_module.time, "sleep", sleeps.append)
    ledger = _FakeLedger()
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return _v2_response(
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
            monotonic_clock=clock,
        )
    starts = [item for item in ledger.events if item.event_kind == "START"]
    terminals = [item for item in ledger.events if item.event_kind == "TERMINAL"]
    assert calls == 1
    assert sleeps == []
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
    clock = _FakeMonotonic()
    sleeps: list[float] = []
    monkeypatch.setattr(runner_module.time, "monotonic", clock)
    monkeypatch.setattr(runner_module.time, "sleep", sleeps.append)
    ledger = _FakeLedger()
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return _v2_response(
            200,
            headers={"Content-Type": "application/json"},
            stream=_DeadlineStream(clock, clock.now + 0.05),
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
    assert sleeps == []
    assert [item.attempt_ordinal for item in ledger.events if item.event_kind == "START"] == [1]
    assert terminal.http_status == 200
    assert terminal.disposition == "deadline_exceeded"
    assert terminal.body_hash is None and terminal.body_relative_path is None
    assert not (output.parent / "provider-attempt-raw").exists()
    projection = _verify_external_failed_run(ledger, output, cases)
    assert projection["status"] == "FAILED"
    assert projection["attempt_count"] == 1


@pytest.mark.parametrize(
    ("failure_name", "headers", "raw"),
    (
        (
            "invalid-framing",
            {"Content-Type": "application/json", "Content-Length": "999999"},
            _cases()[0].assessment.raw_response_envelope_bytes,
        ),
        (
            "invalid-media-type",
            {"Content-Type": "text/html"},
            _cases()[0].assessment.raw_response_envelope_bytes,
        ),
        ("invalid-json", {"Content-Type": "application/json"}, b"{"),
        (
            "json-integer-digit-limit",
            {"Content-Type": "application/json"},
            _cases()[0].assessment.raw_response_envelope_bytes.replace(
                b'"created_at":1', b'"created_at":' + (b"9" * 5_000), 1
            ),
        ),
        (
            "json-lone-surrogate",
            {"Content-Type": "application/json"},
            _cases()[0].assessment.raw_response_envelope_bytes.replace(
                b'"model":"deepseek-v4-pro"', b'"model":"\\ud800"', 1
            ),
        ),
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
        return _v2_response(200, headers=headers, content=raw)

    output = tmp_path / failure_name
    previous_integer_limit = sys.get_int_max_str_digits()
    try:
        if failure_name == "json-integer-digit-limit":
            sys.set_int_max_str_digits(0)
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
    finally:
        sys.set_int_max_str_digits(previous_integer_limit)
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
