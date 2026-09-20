"""Immutable raw and receipt persistence for DeepSeek Generation V2."""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from tests.unit.tools.test_generation_v2_service import case, result

from medevidence.infrastructure.deepseek_generation_v2_receipts import (
    DeepSeekGenerationV2ReceiptStore,
)
from medevidence.ingestion.snapshots import (
    GENERATION_RECEIPT_BYTE_CAPACITY,
    SnapshotIntegrityError,
    SnapshotStore,
)
from medevidence.tools.generation_v2_service import (
    MAX_DEEPSEEK_GENERATION_V2_RESPONSE_BYTES,
    build_deepseek_generation_v2_receipt,
)


def _stored(tmp_path: Path):
    generation_input, evidence, _ = case()
    provider_result = result()
    snapshots = SnapshotStore(tmp_path / "snapshots", free_bytes=lambda _: 20_000_000_000)
    store = DeepSeekGenerationV2ReceiptStore(snapshots)
    receipt = build_deepseek_generation_v2_receipt(
        generation_input,
        evidence,
        provider_result,  # type: ignore[arg-type]
    )
    reference = store.save(receipt, provider_result.raw_response)
    return snapshots, store, reference, receipt, provider_result.raw_response


def test_raw_first_receipt_second_round_trip(tmp_path: Path) -> None:
    snapshots, store, reference, receipt, raw = _stored(tmp_path)
    loaded, loaded_raw = store.load(reference)
    assert loaded == receipt and loaded_raw == raw
    digest = receipt.response_hash.removeprefix("sha256:")
    assert (
        snapshots.root / "generation" / "deepseek" / "raw" / "sha256" / digest[:2] / f"{digest}.bin"
    ).read_bytes() == raw


@pytest.mark.parametrize("material", ("raw", "receipt"))
def test_tampered_material_fails_closed(tmp_path: Path, material: str) -> None:
    snapshots, store, reference, receipt, _ = _stored(tmp_path)
    digest = receipt.response_hash.removeprefix("sha256:")
    target = (
        snapshots.root / "generation" / "deepseek" / "raw" / "sha256" / digest[:2] / f"{digest}.bin"
        if material == "raw"
        else snapshots.root
        / "journal"
        / reference.run_id.removeprefix("run:")
        / "generation"
        / (reference.receipt_id.removeprefix("generation-receipt:sha256:") + ".json")
    )
    original = target.read_bytes()
    target.write_bytes(b"x" + original[1:])
    with pytest.raises(SnapshotIntegrityError):
        store.load(reference)


@pytest.mark.parametrize("material", ("raw", "receipt"))
def test_readback_caps_growing_untrusted_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, material: str
) -> None:
    snapshots, store, reference, receipt, _ = _stored(tmp_path)
    cap = (
        MAX_DEEPSEEK_GENERATION_V2_RESPONSE_BYTES
        if material == "raw"
        else GENERATION_RECEIPT_BYTE_CAPACITY
    )
    digest = receipt.response_hash.removeprefix("sha256:")
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
            assert 0 < size <= cap + 1
            return super().read(size)

    def changed_open(path: Path, *args: object, **kwargs: object):  # type: ignore[no-untyped-def]
        if path == target and args == ("rb",):
            return GrowingFile(b"x" * (cap + 100))
        return original_open(path, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(Path, "open", changed_open)
    with pytest.raises(SnapshotIntegrityError):
        store.load(reference)
    assert reads == [cap + 1]


def test_foreign_reference_and_raw_binding_reject(tmp_path: Path) -> None:
    _snapshots, store, reference, receipt, raw = _stored(tmp_path)
    with pytest.raises(SnapshotIntegrityError):
        store.load(reference.model_copy(update={"generation_material_hash": "sha256:" + "f" * 64}))
    with pytest.raises(SnapshotIntegrityError):
        store.save(receipt, raw + b"x")
