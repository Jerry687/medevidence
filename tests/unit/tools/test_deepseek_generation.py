"""Offline contracts for a distinct DeepSeek generation and receipt family."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

import pytest
from tests.unit.tools.test_generation import candidate, generation_input

from medevidence.domain import canonical_json
from medevidence.infrastructure.deepseek_generation_receipts import DeepSeekGenerationReceiptStore
from medevidence.ingestion.snapshots import SnapshotIntegrityError, SnapshotStore
from medevidence.tools.deepseek_generation import (
    DEEPSEEK_GENERATION_CONFIGURATION_HASH,
    DEEPSEEK_GENERATION_MODEL_ALIAS,
    DeepSeekGenerationContractError,
    DeepSeekGenerationService,
    DeepSeekGenerationServiceError,
    DeepSeekGenerationServiceErrorCode,
    DeepSeekProviderResult,
    build_deepseek_receipt,
    deepseek_generation_request_bytes,
    deepseek_generation_response_format,
    deepseek_receipt_bytes,
    deepseek_receipt_ref,
    parse_deepseek_generation_response,
    parse_deepseek_receipt,
)
from medevidence.tools.generation import (
    GENERATION_PROMPT_BYTES,
    GenerationGatewayError,
    GenerationUsage,
    generation_candidate_bytes,
)


def _response() -> dict[str, object]:
    return {
        "id": "98b34880-b14e-48f4-8727-51cfa4b82cef",
        "object": "response",
        "created_at": 1,
        "status": "completed",
        "error": None,
        "incomplete_details": None,
        "model": DEEPSEEK_GENERATION_MODEL_ALIAS,
        "store": False,
        "previous_response_id": None,
        "instructions": GENERATION_PROMPT_BYTES.decode(),
        "reasoning": {"effort": "none", "summary": None},
        "text": {"format": deepseek_generation_response_format()},
        "tools": [],
        "tool_choice": "none",
        "max_output_tokens": 8192,
        "parallel_tool_calls": True,
        "output": [
            {
                "id": "message-1",
                "type": "message",
                "status": "completed",
                "role": "assistant",
                "content": [
                    {
                        "type": "output_text",
                        "text": generation_candidate_bytes(candidate()).decode(),
                        "annotations": [],
                    }
                ],
            }
        ],
        "usage": {
            "input_tokens": 100,
            "output_tokens": 40,
            "total_tokens": 140,
            "input_tokens_details": {"cached_tokens": 0},
            "output_tokens_details": {"reasoning_tokens": 0},
        },
    }


def _raw(document: dict[str, object] | None = None) -> bytes:
    return canonical_json(_response() if document is None else document).encode()


def _result(raw: bytes | None = None) -> DeepSeekProviderResult:
    body = _raw() if raw is None else raw
    value, response_id, usage, reported_model = parse_deepseek_generation_response(
        body, generation_input()
    )
    now = datetime(2026, 9, 14, tzinfo=UTC)
    request_hash = (
        "sha256:"
        + hashlib.sha256(deepseek_generation_request_bytes(generation_input())).hexdigest()
    )
    return DeepSeekProviderResult(
        candidate=value,
        requested_model_alias="deepseek-flash",
        reported_model=reported_model,
        request_hash=request_hash,
        response_hash="sha256:" + hashlib.sha256(body).hexdigest(),
        raw_response=body,
        provider_response_id=response_id,
        attempts=1,
        usage=usage,
        started_at_utc=now,
        completed_at_utc=now,
    )


def test_request_profile_uses_existing_prompt_schema_and_no_unsupported_capabilities() -> None:
    request = json.loads(deepseek_generation_request_bytes(generation_input()))
    assert set(request) == {
        "input",
        "instructions",
        "max_output_tokens",
        "model",
        "reasoning",
        "text",
        "tool_choice",
        "tools",
    }
    assert request["model"] == "deepseek-flash"
    assert request["reasoning"] == {"effort": "none"}
    assert request["tools"] == [] and request["tool_choice"] == "none"
    assert request["instructions"] == GENERATION_PROMPT_BYTES.decode()
    assert request["text"] == {"format": deepseek_generation_response_format()}
    assert DEEPSEEK_GENERATION_CONFIGURATION_HASH.startswith("sha256:")


def test_complete_text_response_and_exact_new_receipt_round_trip() -> None:
    parsed, response_id, usage, reported = parse_deepseek_generation_response(
        _raw(), generation_input()
    )
    assert parsed == candidate()
    assert response_id == _response()["id"]
    assert reported == "deepseek-flash"
    assert usage == GenerationUsage(
        input_tokens=100,
        output_tokens=40,
        total_tokens=140,
        cached_input_tokens=0,
        reasoning_output_tokens=0,
    )
    receipt = build_deepseek_receipt(generation_input(), _result())
    assert receipt.provider == "deepseek"
    assert receipt.operational_retention_unknown is True
    assert receipt.response_store_observed is False
    assert parse_deepseek_receipt(deepseek_receipt_bytes(receipt)) == receipt
    assert deepseek_receipt_ref(receipt).provider == "deepseek"


@pytest.mark.parametrize(
    "change",
    (
        "status",
        "model",
        "continuation",
        "store",
        "refusal",
        "tool",
        "reasoning",
        "reasoning_usage",
        "usage",
        "echo",
        "parallel_bool",
        "schema_bool",
        "candidate",
        "duplicate",
        "nonjson",
        "bom",
    ),
)
def test_untrusted_response_fails_closed(change: str) -> None:
    document = deepcopy(_response())
    if change == "status":
        document["status"] = "incomplete"
    elif change == "model":
        document["model"] = "deepseek-v4.1-flash"
    elif change == "continuation":
        document["previous_response_id"] = "other"
    elif change == "store":
        document["store"] = True
    elif change == "refusal":
        document["output"][0]["content"][0] = {"type": "refusal", "refusal": "no"}  # type: ignore[index]
    elif change == "tool":
        document["output"][0]["type"] = "function_call"  # type: ignore[index]
    elif change == "reasoning":
        document["reasoning"] = {"effort": "high", "summary": None}
    elif change == "reasoning_usage":
        document["usage"]["output_tokens_details"]["reasoning_tokens"] = 1  # type: ignore[index]
    elif change == "usage":
        document["usage"]["total_tokens"] = 139  # type: ignore[index]
    elif change == "echo":
        document["instructions"] = "changed prompt"
    elif change == "parallel_bool":
        document["parallel_tool_calls"] = 1
    elif change == "schema_bool":
        document["text"]["format"]["strict"] = 1  # type: ignore[index]
    elif change == "candidate":
        document["output"][0]["content"][0]["text"] = "{}"  # type: ignore[index]
    raw = _raw(document)
    if change == "duplicate":
        raw = raw[:-1] + b',"status":"completed"}'
    elif change == "nonjson":
        raw = b"<html>no response</html>"
    elif change == "bom":
        raw = b"\xef\xbb\xbf" + raw
    with pytest.raises(DeepSeekGenerationContractError):
        parse_deepseek_generation_response(raw, generation_input())


def test_service_returns_only_after_raw_and_receipt_readback(tmp_path: Path) -> None:
    result = _result()

    class Gateway:
        def generate(self, _value: object) -> DeepSeekProviderResult:
            return result

    snapshots = SnapshotStore(tmp_path / "snapshots", free_bytes=lambda _: 20_000_000_000)
    receipts = DeepSeekGenerationReceiptStore(snapshots)
    service = DeepSeekGenerationService(gateway=Gateway(), store=receipts)
    durable = service.generate(generation_input())
    loaded, raw = receipts.load(durable.receipt_ref)
    assert durable.candidate == candidate()
    assert loaded.provider == "deepseek"
    assert raw == result.raw_response
    assert durable.receipt_ref.receipt_id.startswith("generation-receipt:sha256:")


def test_service_rejects_misbound_input_and_forged_receipt_ref(tmp_path: Path) -> None:
    result = _result()

    class Gateway:
        def generate(self, _value: object) -> DeepSeekProviderResult:
            return result

    snapshots = SnapshotStore(tmp_path / "snapshots", free_bytes=lambda _: 20_000_000_000)
    store = DeepSeekGenerationReceiptStore(snapshots)
    service = DeepSeekGenerationService(gateway=Gateway(), store=store)
    with pytest.raises(DeepSeekGenerationServiceError) as captured:
        service.generate(generation_input(injected_excerpt="A changed current-run excerpt."))
    assert captured.value.code is DeepSeekGenerationServiceErrorCode.GATEWAY_INVALID
    receipt = build_deepseek_receipt(generation_input(), result)
    reference = store.save(receipt, result.raw_response)
    forged = reference.model_copy(update={"provider": "openai"})
    with pytest.raises(SnapshotIntegrityError):
        store.load(forged)


def test_service_preserves_only_stable_redacted_provider_error(tmp_path: Path) -> None:
    class UnavailableGateway:
        def generate(self, _value: object) -> DeepSeekProviderResult:
            raise GenerationGatewayError("provider_unavailable")

    snapshots = SnapshotStore(tmp_path / "snapshots", free_bytes=lambda _: 20_000_000_000)
    service = DeepSeekGenerationService(
        gateway=UnavailableGateway(), store=DeepSeekGenerationReceiptStore(snapshots)
    )
    with pytest.raises(GenerationGatewayError, match="provider_unavailable"):
        service.generate(generation_input())
    assert not snapshots.root.exists()


@pytest.mark.parametrize("tamper", ("raw", "receipt"))
def test_persisted_deepseek_material_rejects_byte_tampering(tmp_path: Path, tamper: str) -> None:
    result = _result()
    snapshots = SnapshotStore(tmp_path / "snapshots", free_bytes=lambda _: 20_000_000_000)
    store = DeepSeekGenerationReceiptStore(snapshots)
    reference = store.save(build_deepseek_receipt(generation_input(), result), result.raw_response)
    if tamper == "raw":
        digest = result.response_hash.removeprefix("sha256:")
        target = (
            snapshots.root
            / "generation"
            / "deepseek"
            / "raw"
            / "sha256"
            / digest[:2]
            / f"{digest}.bin"
        )
    else:
        run_uuid = reference.run_id.removeprefix("run:")
        receipt_digest = reference.receipt_id.removeprefix("generation-receipt:sha256:")
        target = snapshots.root / "journal" / run_uuid / "generation" / f"{receipt_digest}.json"
    original = target.read_bytes()
    target.write_bytes(b"x" + original[1:])
    with pytest.raises(SnapshotIntegrityError):
        store.load(reference)


@pytest.mark.parametrize("material", ("raw", "receipt"))
def test_growth_between_stat_and_read_uses_a_bounded_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, material: str
) -> None:
    import io

    from medevidence.ingestion.snapshots import GENERATION_RECEIPT_BYTE_CAPACITY
    from medevidence.tools.deepseek_generation import MAX_DEEPSEEK_RESPONSE_BYTES

    result = _result()
    snapshots = SnapshotStore(tmp_path / "snapshots", free_bytes=lambda _: 20_000_000_000)
    store = DeepSeekGenerationReceiptStore(snapshots)
    reference = store.save(build_deepseek_receipt(generation_input(), result), result.raw_response)
    cap = MAX_DEEPSEEK_RESPONSE_BYTES if material == "raw" else GENERATION_RECEIPT_BYTE_CAPACITY
    digest = result.response_hash.removeprefix("sha256:")
    target = (
        snapshots.root / "generation" / "deepseek" / "raw" / "sha256" / digest[:2] / f"{digest}.bin"
        if material == "raw"
        else snapshots.root
        / "journal"
        / reference.run_id.removeprefix("run:")
        / "generation"
        / (reference.receipt_id.removeprefix("generation-receipt:sha256:") + ".json")
    )
    reads: list[int] = []
    original_open = Path.open

    class GrowingFile(io.BytesIO):
        def read(self, size: int = -1) -> bytes:
            reads.append(size)
            assert 0 < size <= cap + 1, "untrusted file read must have an explicit cap"
            return super().read(size)

    def changed_open(path: Path, *args: object, **kwargs: object):  # type: ignore[no-untyped-def]
        if path == target and args == ("rb",):
            return GrowingFile(b"x" * (cap + 100))
        return original_open(path, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(Path, "open", changed_open)
    with pytest.raises(SnapshotIntegrityError):
        store.load(reference)
    assert reads == [cap + 1]
