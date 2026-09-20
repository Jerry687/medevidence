"""Canonical V2 receipt boundary around immutable PostgreSQL storage."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import cast

from medevidence.domain import canonical_json
from medevidence.persistence.repositories import PersistenceIntegrityError, PersistenceRepository
from medevidence.tools.report_validation import (
    ValidationReceiptV2,
    canonical_stage1_receipt_payload_v2,
    canonical_validation_receipt_payload,
    stage1_receipt_from_payload_v2,
    validation_receipt_from_payload,
)


class V2ReceiptStore:
    """Apply exact V2 parsers on both sides of a durable receipt repository."""

    def __init__(self, repository: PersistenceRepository) -> None:
        self._repository = repository

    @staticmethod
    def _stage1_payload(value: Mapping[str, object]) -> dict[str, object]:
        if type(value) is not dict:
            raise ValueError("stage1 receipt must be an exact JSON object")
        parsed = stage1_receipt_from_payload_v2(value)
        return cast(
            dict[str, object],
            json.loads(canonical_json(canonical_stage1_receipt_payload_v2(parsed))),
        )

    @staticmethod
    def _final_payload(value: Mapping[str, object]) -> dict[str, object]:
        if type(value) is not dict:
            raise ValueError("final receipt must be an exact JSON object")
        parsed = validation_receipt_from_payload(value)
        if type(parsed) is not ValidationReceiptV2:
            raise ValueError("V2 receipt store accepts only final V2 receipts")
        return canonical_validation_receipt_payload(parsed)

    def save_stage1_receipt(self, receipt_payload: Mapping[str, object]) -> Mapping[str, object]:
        canonical = self._stage1_payload(receipt_payload)
        stored = self._repository.save_stage1_receipt(canonical)
        try:
            loaded = self._stage1_payload(stored)
        except ValueError as error:
            raise PersistenceIntegrityError("stored stage1 receipt is noncanonical") from error
        if loaded != canonical:
            raise PersistenceIntegrityError("stored stage1 receipt differs from input")
        return loaded

    def load_stage1_receipt(self, receipt_id: str) -> Mapping[str, object] | None:
        stored = self._repository.load_stage1_receipt(receipt_id)
        if stored is None:
            return None
        try:
            loaded = self._stage1_payload(stored)
        except ValueError as error:
            raise PersistenceIntegrityError("stored stage1 receipt is noncanonical") from error
        if loaded["receipt_id"] != receipt_id:
            raise PersistenceIntegrityError("stored stage1 receipt identity differs from lookup")
        return loaded

    def save_receipt(self, receipt_payload: Mapping[str, object]) -> Mapping[str, object]:
        canonical = self._final_payload(receipt_payload)
        stored = self._repository.save_receipt(canonical)
        try:
            loaded = self._final_payload(stored)
        except ValueError as error:
            raise PersistenceIntegrityError("stored final receipt is noncanonical") from error
        if loaded != canonical:
            raise PersistenceIntegrityError("stored final receipt differs from input")
        return loaded

    def load_receipt(self, receipt_id: str) -> Mapping[str, object] | None:
        stored = self._repository.load_receipt(receipt_id)
        if stored is None:
            return None
        try:
            loaded = self._final_payload(stored)
        except ValueError as error:
            raise PersistenceIntegrityError("stored final receipt is noncanonical") from error
        if loaded["receipt_id"] != receipt_id:
            raise PersistenceIntegrityError("stored final receipt identity differs from lookup")
        return loaded
