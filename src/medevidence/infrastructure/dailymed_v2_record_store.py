"""Typed DailyMed V2 journal and PostgreSQL readback authority."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast

from pydantic import BaseModel

from medevidence.domain import canonical_json
from medevidence.domain.dailymed_enrichment import (
    DailyMedDiscoveryGroupV2,
    DailyMedSelectionDecisionV2,
)
from medevidence.domain.dailymed_v2_execution import (
    DailyMedV2PackagingResult,
    DailyMedV2SelectedSplResult,
)
from medevidence.ingestion.snapshots import SnapshotIntegrityError, SnapshotStore
from medevidence.persistence.dailymed_v2 import (
    MAX_DAILYMED_V2_RECORD_BYTES,
    DailyMedV2RecordInput,
    DailyMedV2Repository,
)
from medevidence.tools.dailymed_v2_material import DailyMedV2EvidenceChunk

type DailyMedV2Payload = (
    DailyMedDiscoveryGroupV2
    | DailyMedV2PackagingResult
    | DailyMedSelectionDecisionV2
    | DailyMedV2SelectedSplResult
    | DailyMedV2EvidenceChunk
)
type DailyMedV2RecordKind = Literal["discovery", "packaging", "decision", "selected_spl", "chunk"]
_TYPES: dict[str, type[BaseModel]] = {
    "discovery": DailyMedDiscoveryGroupV2,
    "packaging": DailyMedV2PackagingResult,
    "decision": DailyMedSelectionDecisionV2,
    "selected_spl": DailyMedV2SelectedSplResult,
    "chunk": DailyMedV2EvidenceChunk,
}
_RUN = re.compile(r"^run:([0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12})$")


@dataclass(frozen=True, slots=True)
class LoadedDailyMedV2Record:
    record: DailyMedV2RecordInput
    payload: DailyMedV2Payload


def _path(root: Path, record: DailyMedV2RecordInput) -> Path:
    match = _RUN.fullmatch(record.run_id)
    digest = record.record_id.removeprefix("dailymed-v2-record:sha256:")
    if match is None or len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        raise SnapshotIntegrityError("DailyMed V2 journal identity is invalid")
    return root / "journal" / match.group(1) / "dailymed-v2" / digest[:2] / f"{digest}.json"


class DailyMedV2RecordStore:
    """Accept one closed typed payload and reparse journal plus SQL before return."""

    def __init__(self, *, snapshots: SnapshotStore, repository: DailyMedV2Repository) -> None:
        if type(snapshots) is not SnapshotStore or type(repository) is not DailyMedV2Repository:
            raise TypeError("DailyMed V2 record store requires exact authorities")
        self._snapshots = snapshots
        self._repository = repository

    @staticmethod
    def _payload(kind: str, value: DailyMedV2Payload) -> bytes:
        expected = _TYPES.get(kind)
        if expected is None:
            raise ValueError("DailyMed V2 record kind is invalid")
        if type(value) is not expected:
            raise TypeError("DailyMed V2 record payload type differs from kind")
        rebuilt = expected.model_validate(value.model_dump(mode="python"), strict=True)
        if rebuilt != value:
            raise ValueError("DailyMed V2 record payload reconstruction differs")
        raw = canonical_json(value).encode("utf-8")
        if not 2 <= len(raw) <= MAX_DAILYMED_V2_RECORD_BYTES:
            raise ValueError("DailyMed V2 typed payload exceeds 2 MiB")
        return raw

    @staticmethod
    def _require_binding(record: DailyMedV2RecordInput, value: DailyMedV2Payload) -> None:
        if type(value) is DailyMedDiscoveryGroupV2:
            if value.discovery_query_id != record.query_id or any(
                (
                    item.parent.run_id,
                    item.parent.attempt_id,
                    item.parent.query_id,
                    item.parent.acquisition_id,
                    item.parent.acquisition_intent_id,
                    item.parent.snapshot_id,
                    item.parent.manifest_id,
                )
                != (
                    record.run_id,
                    record.attempt_id,
                    record.query_id,
                    record.acquisition_id,
                    record.acquisition_intent_id,
                    record.snapshot_id,
                    record.manifest_id,
                )
                for item in value.summaries
            ):
                raise SnapshotIntegrityError("DailyMed V2 discovery record is foreign")
        elif type(value) is DailyMedV2PackagingResult:
            if value.packaging_query_id != record.query_id:
                raise SnapshotIntegrityError("DailyMed V2 packaging query is foreign")
            if value.execution is not None:
                parent = value.execution.parent
                if (
                    parent.run_id,
                    parent.attempt_id,
                    parent.query_id,
                    parent.acquisition_id,
                    parent.acquisition_intent_id,
                    parent.snapshot_id,
                    parent.manifest_id,
                ) != (
                    record.run_id,
                    record.attempt_id,
                    record.query_id,
                    record.acquisition_id,
                    record.acquisition_intent_id,
                    record.snapshot_id,
                    record.manifest_id,
                ):
                    raise SnapshotIntegrityError("DailyMed V2 packaging record is foreign")
        elif type(value) is DailyMedSelectionDecisionV2:
            if value.discovery_query_id != record.query_id:
                raise SnapshotIntegrityError("DailyMed V2 decision query is foreign")
        elif type(value) is DailyMedV2SelectedSplResult:
            selected = value.selected
            if value.source_outcome.query_id != record.query_id or (
                selected is not None
                and (
                    selected.run_id != record.run_id
                    or selected.attempt_id != record.attempt_id
                    or selected.fetch_query_id != record.query_id
                    or selected.fetch_snapshot_id != record.snapshot_id
                    or selected.fetch_manifest_id != record.manifest_id
                )
            ):
                raise SnapshotIntegrityError("DailyMed V2 selected SPL record is foreign")
        elif type(value) is DailyMedV2EvidenceChunk and (
            value.run_id != record.run_id
            or value.snapshot_id != record.snapshot_id
            or value.chunk_ordinal != record.item_ordinal
        ):
            raise SnapshotIntegrityError("DailyMed V2 evidence chunk is foreign")

    def save(
        self, record: DailyMedV2RecordInput, payload: DailyMedV2Payload
    ) -> LoadedDailyMedV2Record:
        """Publish immutable typed journal first, then SQL, then exact reload."""

        if type(record) is not DailyMedV2RecordInput:
            raise TypeError("DailyMed V2 record input type is invalid")
        raw = self._payload(record.record_kind, payload)
        self._require_binding(record, payload)
        if raw != record.payload_bytes:
            raise ValueError("DailyMed V2 record bytes differ from typed payload")
        target = _path(self._snapshots.root, record)
        relative = target.relative_to(self._snapshots.root).as_posix()
        if self._snapshots.has_writer_lock:
            SnapshotStore.publish_bytes(self._snapshots, relative, raw, artifact_class="journal")
        else:
            with SnapshotStore.writer(self._snapshots):
                SnapshotStore.publish_bytes(
                    self._snapshots, relative, raw, artifact_class="journal"
                )
        self._repository.save(record)
        loaded = self.load(record.record_id)
        if loaded is None or loaded.record != record or loaded.payload != payload:
            raise SnapshotIntegrityError("DailyMed V2 typed record readback differs")
        return loaded

    def load(self, record_id: str) -> LoadedDailyMedV2Record | None:
        """Read only generated content-addressed journal and exact SQL projection."""

        record = self._repository.load(record_id)
        if record is None:
            return None
        target = _path(self._snapshots.root, record)
        SnapshotStore._require_safe_path(self._snapshots, target, allow_missing_leaf=False)
        if not target.is_file() or not 2 <= target.stat().st_size <= MAX_DAILYMED_V2_RECORD_BYTES:
            raise SnapshotIntegrityError("DailyMed V2 typed journal is missing or oversized")
        size = target.stat().st_size
        with target.open("rb") as handle:
            raw = handle.read(MAX_DAILYMED_V2_RECORD_BYTES + 1)
        SnapshotStore._require_safe_path(self._snapshots, target, allow_missing_leaf=False)
        if len(raw) != size or raw != record.payload_bytes:
            raise SnapshotIntegrityError("DailyMed V2 typed journal differs from SQL")
        expected = _TYPES.get(record.record_kind)
        if expected is None:
            raise SnapshotIntegrityError("DailyMed V2 typed record kind is invalid")
        try:
            parsed = expected.model_validate_json(raw, strict=False)
            payload = expected.model_validate(parsed.model_dump(mode="python"), strict=True)
        except (TypeError, ValueError) as error:
            raise SnapshotIntegrityError("DailyMed V2 typed journal is invalid") from error
        if canonical_json(payload).encode("utf-8") != raw:
            raise SnapshotIntegrityError("DailyMed V2 typed journal is noncanonical")
        typed = cast(DailyMedV2Payload, payload)
        self._require_binding(record, typed)
        return LoadedDailyMedV2Record(record, typed)

    def load_slot(
        self,
        *,
        run_id: str,
        attempt_id: str,
        record_kind: DailyMedV2RecordKind,
        query_id: str,
        item_ordinal: int = 0,
    ) -> LoadedDailyMedV2Record | None:
        record = self._repository.load_slot(
            run_id=run_id,
            attempt_id=attempt_id,
            record_kind=record_kind,
            query_id=query_id,
            item_ordinal=item_ordinal,
        )
        return None if record is None else self.load(record.record_id)

    def load_chunk_evidence(
        self, *, run_id: str, evidence_id: str
    ) -> LoadedDailyMedV2Record | None:
        record = self._repository.load_chunk_by_evidence_id(run_id=run_id, evidence_id=evidence_id)
        return None if record is None else self.load(record.record_id)
