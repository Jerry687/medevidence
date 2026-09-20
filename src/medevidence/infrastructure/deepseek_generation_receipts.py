"""Immutable SnapshotStore adapter for clean DeepSeek generation bytes and receipts."""

from __future__ import annotations

import hashlib
from typing import final

from pydantic import BaseModel

from medevidence.ingestion.snapshots import SnapshotIntegrityError, SnapshotStore
from medevidence.tools.deepseek_generation import (
    MAX_DEEPSEEK_RESPONSE_BYTES,
    DeepSeekGenerationReceipt,
    DeepSeekGenerationReceiptRef,
    deepseek_receipt_bytes,
    deepseek_receipt_ref,
    parse_deepseek_receipt,
    verify_deepseek_receipt,
)


def _raw_relative_path(response_hash: str) -> str:
    digest = response_hash.removeprefix("sha256:")
    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        raise SnapshotIntegrityError("DeepSeek raw response hash is invalid")
    return f"generation/deepseek/raw/sha256/{digest[:2]}/{digest}.bin"


@final
class DeepSeekGenerationReceiptStore:
    """Publish exact clean response first, then receipt; verify both on readback."""

    __slots__ = ("_store",)
    _store: SnapshotStore

    def __init__(self, store: SnapshotStore) -> None:
        if type(store) is not SnapshotStore:
            raise TypeError("DeepSeek receipts require the exact SnapshotStore")
        object.__setattr__(self, "_store", store)

    def __setattr__(self, name: str, value: object) -> None:
        del name, value
        raise AttributeError("DeepSeek receipt store is frozen")

    def save(
        self, receipt: DeepSeekGenerationReceipt, clean_raw_response: bytes
    ) -> DeepSeekGenerationReceiptRef:
        if type(clean_raw_response) is not bytes:
            raise SnapshotIntegrityError("DeepSeek response bytes must be exact")
        exact = verify_deepseek_receipt(receipt)
        if (
            not clean_raw_response
            or len(clean_raw_response) > MAX_DEEPSEEK_RESPONSE_BYTES
            or len(clean_raw_response) != exact.response_byte_count
            or "sha256:" + hashlib.sha256(clean_raw_response).hexdigest() != exact.response_hash
        ):
            raise SnapshotIntegrityError("DeepSeek receipt raw response binding differs")
        reference = deepseek_receipt_ref(exact)
        raw_path = _raw_relative_path(exact.response_hash)
        store = self._store
        if store.has_writer_lock:
            SnapshotStore.publish_bytes(store, raw_path, clean_raw_response, artifact_class="raw")
            SnapshotStore.publish_generation_receipt(
                store,
                deepseek_receipt_bytes(exact),
                run_id=reference.run_id,
                receipt_id=reference.receipt_id,
            )
        else:
            with SnapshotStore.writer(store):
                SnapshotStore.publish_bytes(
                    store, raw_path, clean_raw_response, artifact_class="raw"
                )
                SnapshotStore.publish_generation_receipt(
                    store,
                    deepseek_receipt_bytes(exact),
                    run_id=reference.run_id,
                    receipt_id=reference.receipt_id,
                )
        loaded, raw = self.load(reference)
        if loaded != exact or raw != clean_raw_response:
            raise SnapshotIntegrityError("DeepSeek receipt publication failed readback")
        return reference

    def load(
        self, reference: DeepSeekGenerationReceiptRef
    ) -> tuple[DeepSeekGenerationReceipt, bytes]:
        if type(reference) is not DeepSeekGenerationReceiptRef:
            raise SnapshotIntegrityError("DeepSeek receipt reference type is invalid")
        try:
            exact_ref = DeepSeekGenerationReceiptRef.model_validate(
                BaseModel.model_dump(reference, mode="python")
            )
            receipt_bytes = SnapshotStore.read_generation_receipt(
                self._store, run_id=exact_ref.run_id, receipt_id=exact_ref.receipt_id
            )
            receipt = parse_deepseek_receipt(receipt_bytes)
            if deepseek_receipt_ref(receipt) != exact_ref:
                raise SnapshotIntegrityError("DeepSeek receipt reference differs")
            relative = _raw_relative_path(receipt.response_hash)
            target = self._store.root.joinpath(*relative.split("/"))
            SnapshotStore._require_safe_path(self._store, target, allow_missing_leaf=True)
            if not target.is_file() or not 0 < target.stat().st_size <= MAX_DEEPSEEK_RESPONSE_BYTES:
                raise SnapshotIntegrityError("DeepSeek raw response is missing or oversized")
            with target.open("rb") as handle:
                raw = handle.read(MAX_DEEPSEEK_RESPONSE_BYTES + 1)
            SnapshotStore._require_safe_path(self._store, target, allow_missing_leaf=False)
            if (
                len(raw) > MAX_DEEPSEEK_RESPONSE_BYTES
                or len(raw) != receipt.response_byte_count
                or "sha256:" + hashlib.sha256(raw).hexdigest() != receipt.response_hash
            ):
                raise SnapshotIntegrityError("DeepSeek raw response differs from receipt")
            return receipt, raw
        except (TypeError, ValueError, OSError) as error:
            raise SnapshotIntegrityError("DeepSeek receipt readback is invalid") from error
