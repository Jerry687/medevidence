"""Immutable SnapshotStore adapter for exact M3 generation receipts."""

from __future__ import annotations

from typing import final

from medevidence.ingestion.snapshots import SnapshotIntegrityError, SnapshotStore
from medevidence.tools.generation import (
    GenerationContractError,
    GenerationReceipt,
    GenerationReceiptRef,
    generation_receipt_bytes,
    generation_receipt_ref,
    parse_generation_receipt,
    reconstruct_generation_receipt,
    reconstruct_generation_receipt_ref,
)


@final
class GenerationReceiptStore:
    """Sealed immutable adapter over one concrete snapshot journal."""

    _store: SnapshotStore
    __slots__ = ("_store",)

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("GenerationReceiptStore is a sealed persistence authority")

    def __setattr__(self, name: str, value: object) -> None:
        del name, value
        raise AttributeError("GenerationReceiptStore is frozen after construction")

    def __init__(self, store: SnapshotStore) -> None:
        if type(store) is not SnapshotStore:
            raise TypeError("generation receipts require the exact SnapshotStore authority")
        object.__setattr__(self, "_store", store)

    def save(self, receipt: GenerationReceipt) -> GenerationReceiptRef:
        """Publish, reload, and verify one exact immutable receipt."""

        reconstruction_failed = False
        try:
            exact_receipt = reconstruct_generation_receipt(receipt)
            raw = generation_receipt_bytes(exact_receipt)
            expected_ref = generation_receipt_ref(exact_receipt)
        except (TypeError, ValueError):
            reconstruction_failed = True
        if reconstruction_failed:
            raise SnapshotIntegrityError("generation receipt failed reconstruction")
        store = self._store
        if store.has_writer_lock:
            SnapshotStore.publish_generation_receipt(
                store,
                raw,
                run_id=expected_ref.run_id,
                receipt_id=expected_ref.receipt_id,
            )
        else:
            with SnapshotStore.writer(store):
                SnapshotStore.publish_generation_receipt(
                    store,
                    raw,
                    run_id=expected_ref.run_id,
                    receipt_id=expected_ref.receipt_id,
                )
        loaded = GenerationReceiptStore.load(self, expected_ref)
        if loaded != exact_receipt or generation_receipt_ref(loaded) != expected_ref:
            raise SnapshotIntegrityError("persisted generation receipt changed exact content")
        return expected_ref

    def load(self, reference: GenerationReceiptRef) -> GenerationReceipt:
        """Load only the exact receipt identified by a reconstructed reference."""

        expected_ref = GenerationReceiptStore._validated_reference(reference)
        raw = SnapshotStore.read_generation_receipt(
            self._store,
            run_id=expected_ref.run_id,
            receipt_id=expected_ref.receipt_id,
        )
        validation_failed = False
        try:
            receipt = parse_generation_receipt(raw)
            if generation_receipt_bytes(receipt) != raw:
                raise GenerationContractError("generation_receipt_not_canonical")
            actual_ref = generation_receipt_ref(receipt)
        except (TypeError, ValueError):
            validation_failed = True
        if validation_failed:
            raise SnapshotIntegrityError("generation receipt bytes failed validation")
        if actual_ref != expected_ref:
            raise SnapshotIntegrityError("generation receipt reference binding mismatch")
        return receipt

    @staticmethod
    def _validated_reference(reference: GenerationReceiptRef) -> GenerationReceiptRef:
        validation_failed = False
        try:
            validated = reconstruct_generation_receipt_ref(reference)
        except (TypeError, ValueError):
            validation_failed = True
        if validation_failed:
            raise SnapshotIntegrityError("generation receipt reference is invalid")
        return validated
