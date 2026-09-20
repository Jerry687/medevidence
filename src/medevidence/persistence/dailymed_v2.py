"""Bounded immutable PostgreSQL rows for typed outer DailyMed V2 records."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from medevidence.domain import canonical_json, derive_identity, sha256_digest

from . import models
from .repositories import PersistenceConflict, PersistenceIntegrityError, PersistenceRepository

MAX_DAILYMED_V2_RECORD_BYTES = 2_097_152
_KINDS = frozenset({"discovery", "packaging", "decision", "selected_spl", "chunk"})


@dataclass(frozen=True, slots=True)
class DailyMedV2RecordInput:
    record_kind: str
    run_id: str
    scope_id: str
    task_id: str
    attempt_id: str
    query_id: str
    acquisition_id: str
    acquisition_intent_id: str
    snapshot_id: str
    manifest_id: str
    item_ordinal: int
    payload_bytes: bytes
    created_at_utc: datetime

    @property
    def payload_hash(self) -> str:
        return sha256_digest(self.payload_bytes)

    @property
    def record_id(self) -> str:
        return derive_identity(
            "dailymed-v2-record",
            {
                "record_kind": self.record_kind,
                "run_id": self.run_id,
                "scope_id": self.scope_id,
                "task_id": self.task_id,
                "attempt_id": self.attempt_id,
                "query_id": self.query_id,
                "acquisition_id": self.acquisition_id,
                "acquisition_intent_id": self.acquisition_intent_id,
                "snapshot_id": self.snapshot_id,
                "manifest_id": self.manifest_id,
                "item_ordinal": self.item_ordinal,
                "payload_hash": self.payload_hash,
            },
        )


@dataclass(frozen=True, slots=True)
class DailyMedV2MemberInput:
    run_id: str
    acquisition_id: str
    snapshot_id: str
    ordinal: int
    link_id: str
    artifact_id: str
    content_hash: str
    relative_path: str
    byte_size: int
    media_type: str
    http_status: int
    observed_at_utc: datetime
    body_complete: bool
    termination_reason: str
    page_number: int
    attempt_count: int
    request_url: str
    final_url: str


def _unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("DailyMed V2 record contains duplicate JSON keys")
        value[key] = item
    return value


def _invalid_constant(_value: str) -> None:
    raise ValueError("DailyMed V2 record contains a nonfinite number")


def _document(raw: bytes) -> dict[str, object]:
    if type(raw) is not bytes or not 2 <= len(raw) <= MAX_DAILYMED_V2_RECORD_BYTES:
        raise ValueError("DailyMed V2 record byte size is invalid")
    try:
        document = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=_unique,
            parse_constant=_invalid_constant,
        )
    except (UnicodeError, ValueError, OverflowError, RecursionError) as error:
        raise ValueError("DailyMed V2 record JSON is invalid") from error
    if type(document) is not dict or canonical_json(document).encode("utf-8") != raw:
        raise ValueError("DailyMed V2 record is not canonical JSON")
    return document


class DailyMedV2Repository:
    """Insert-or-verify primitive metadata; outer adapters own typed reconstruction."""

    def __init__(self, repository: PersistenceRepository) -> None:
        if type(repository) is not PersistenceRepository:
            raise TypeError("DailyMed V2 repository requires exact persistence authority")
        self._repository = repository

    def save(self, value: DailyMedV2RecordInput) -> DailyMedV2RecordInput:
        if type(value) is not DailyMedV2RecordInput:
            raise TypeError("DailyMed V2 record input must be exact")
        document = _document(value.payload_bytes)
        offset = (
            value.created_at_utc.utcoffset()
            if type(value.created_at_utc) is datetime and value.created_at_utc.tzinfo is not None
            else None
        )
        if (
            value.record_kind not in _KINDS
            or any(
                type(item) is not str or not 1 <= len(item) <= 512
                for item in (
                    value.run_id,
                    value.scope_id,
                    value.task_id,
                    value.attempt_id,
                    value.query_id,
                    value.acquisition_id,
                    value.acquisition_intent_id,
                    value.snapshot_id,
                    value.manifest_id,
                )
            )
            or type(value.item_ordinal) is not int
            or not 0 <= value.item_ordinal < 100
            or type(value.created_at_utc) is not datetime
            or value.created_at_utc.tzinfo is None
            or offset is None
            or offset.total_seconds() != 0
        ):
            raise ValueError("DailyMed V2 record identity or time is invalid")
        row = {
            "record_id": value.record_id,
            "schema_version": "m3.dailymed-v2-record.v1",
            "record_kind": value.record_kind,
            "run_id": value.run_id,
            "scope_id": value.scope_id,
            "task_id": value.task_id,
            "attempt_id": value.attempt_id,
            "query_id": value.query_id,
            "acquisition_id": value.acquisition_id,
            "acquisition_intent_id": value.acquisition_intent_id,
            "snapshot_id": value.snapshot_id,
            "manifest_id": value.manifest_id,
            "item_ordinal": value.item_ordinal,
            "payload_hash": value.payload_hash,
            "payload_bytes": len(value.payload_bytes),
            "payload_json": document,
            "created_at_utc": value.created_at_utc,
        }
        table = models.m3_dailymed_v2_records
        engine = self._repository._engine
        with engine.begin() as connection:
            existing = (
                connection.execute(sa.select(table).where(table.c.record_id == value.record_id))
                .mappings()
                .one_or_none()
            )
            if existing is None:
                try:
                    with connection.begin_nested():
                        connection.execute(table.insert().values(**row))
                except IntegrityError as error:
                    existing = (
                        connection.execute(
                            sa.select(table).where(table.c.record_id == value.record_id)
                        )
                        .mappings()
                        .one_or_none()
                    )
                    if existing is None:
                        raise PersistenceConflict(
                            "m3_dailymed_v2_records", "uq_m3_dailymed_v2_record_slot"
                        ) from error
            if existing is not None and any(
                existing[name] != expected for name, expected in row.items()
            ):
                raise PersistenceConflict("m3_dailymed_v2_records", "pk_m3_dailymed_v2_records")
        loaded = self.load(value.record_id)
        if loaded != value:
            raise PersistenceIntegrityError("DailyMed V2 record readback differs")
        return loaded

    def load(self, record_id: str) -> DailyMedV2RecordInput | None:
        if type(record_id) is not str or not record_id.startswith("dailymed-v2-record:sha256:"):
            raise ValueError("DailyMed V2 record lookup identity is invalid")
        table = models.m3_dailymed_v2_records
        with self._repository._engine.connect() as connection:
            row = (
                connection.execute(sa.select(table).where(table.c.record_id == record_id))
                .mappings()
                .one_or_none()
            )
        if row is None:
            return None
        try:
            raw = canonical_json(row["payload_json"]).encode("utf-8")
            _document(raw)
            value = DailyMedV2RecordInput(
                record_kind=row["record_kind"],
                run_id=row["run_id"],
                scope_id=row["scope_id"],
                task_id=row["task_id"],
                attempt_id=row["attempt_id"],
                query_id=row["query_id"],
                acquisition_id=row["acquisition_id"],
                acquisition_intent_id=row["acquisition_intent_id"],
                snapshot_id=row["snapshot_id"],
                manifest_id=row["manifest_id"],
                item_ordinal=row["item_ordinal"],
                payload_bytes=raw,
                created_at_utc=row["created_at_utc"],
            )
        except (KeyError, TypeError, ValueError) as error:
            raise PersistenceIntegrityError("DailyMed V2 stored row is invalid") from error
        if (
            row["schema_version"] != "m3.dailymed-v2-record.v1"
            or row["payload_bytes"] != len(raw)
            or row["payload_hash"] != value.payload_hash
            or row["record_id"] != value.record_id
            or row["record_id"] != record_id
            or value.record_kind not in _KINDS
        ):
            raise PersistenceIntegrityError("DailyMed V2 stored record identity differs")
        return value

    def load_slot(
        self,
        *,
        run_id: str,
        attempt_id: str,
        record_kind: str,
        query_id: str,
        item_ordinal: int = 0,
    ) -> DailyMedV2RecordInput | None:
        """Resolve one immutable slot without accepting a caller-supplied payload hash."""

        if (
            any(
                type(item) is not str or not 1 <= len(item) <= 512
                for item in (run_id, attempt_id, record_kind, query_id)
            )
            or record_kind not in _KINDS
            or type(item_ordinal) is not int
            or not 0 <= item_ordinal < 100
        ):
            raise ValueError("DailyMed V2 record slot is invalid")
        table = models.m3_dailymed_v2_records
        with self._repository._engine.connect() as connection:
            record_id = connection.scalar(
                sa.select(table.c.record_id).where(
                    table.c.run_id == run_id,
                    table.c.attempt_id == attempt_id,
                    table.c.record_kind == record_kind,
                    table.c.query_id == query_id,
                    table.c.item_ordinal == item_ordinal,
                )
            )
        return None if record_id is None else self.load(record_id)

    def load_source_graph(
        self,
        *,
        run_id: str,
        acquisition_id: str,
        query_id: str,
        snapshot_id: str,
    ) -> dict[str, object] | None:
        """Read bounded source rows so the outer adapter can verify exact raw ancestry."""

        if any(
            type(value) is not str or not 1 <= len(value) <= 512
            for value in (run_id, acquisition_id, query_id, snapshot_id)
        ):
            raise ValueError("DailyMed V2 source graph lookup identity is invalid")
        engine = self._repository._engine
        with engine.connect() as connection:
            acquisition = (
                connection.execute(
                    sa.select(models.m1b_acquisitions).where(
                        models.m1b_acquisitions.c.run_id == run_id,
                        models.m1b_acquisitions.c.source == "dailymed",
                        models.m1b_acquisitions.c.acquisition_id == acquisition_id,
                        models.m1b_acquisitions.c.query_id == query_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            snapshot = (
                connection.execute(
                    sa.select(models.m1b_snapshots).where(
                        models.m1b_snapshots.c.run_id == run_id,
                        models.m1b_snapshots.c.source == "dailymed",
                        models.m1b_snapshots.c.acquisition_id == acquisition_id,
                        models.m1b_snapshots.c.query_id == query_id,
                        models.m1b_snapshots.c.snapshot_id == snapshot_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            outcome = (
                connection.execute(
                    sa.select(models.m1b_source_outcomes).where(
                        models.m1b_source_outcomes.c.run_id == run_id,
                        models.m1b_source_outcomes.c.source == "dailymed",
                        models.m1b_source_outcomes.c.acquisition_id == acquisition_id,
                        models.m1b_source_outcomes.c.query_id == query_id,
                        models.m1b_source_outcomes.c.snapshot_id == snapshot_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            membership = tuple(
                dict(row)
                for row in connection.execute(
                    sa.select(models.m3_dailymed_v2_members)
                    .where(
                        models.m3_dailymed_v2_members.c.run_id == run_id,
                        models.m3_dailymed_v2_members.c.acquisition_id == acquisition_id,
                        models.m3_dailymed_v2_members.c.snapshot_id == snapshot_id,
                    )
                    .order_by(models.m3_dailymed_v2_members.c.ordinal)
                    .limit(21)
                ).mappings()
            )
            artifact_ids = tuple(row["artifact_id"] for row in membership)
            if snapshot is not None:
                artifact_ids += (snapshot["manifest_artifact_id"],)
            artifacts = tuple(
                dict(row)
                for row in connection.execute(
                    sa.select(models.m1b_artifacts)
                    .where(models.m1b_artifacts.c.artifact_id.in_(artifact_ids))
                    .limit(22)
                ).mappings()
            )
        if acquisition is None or snapshot is None or outcome is None:
            return None
        if len(membership) > 20 or len(artifacts) > 21:
            raise PersistenceIntegrityError("DailyMed V2 source graph exceeds bounds")
        return {
            "acquisition": dict(acquisition),
            "snapshot": dict(snapshot),
            "outcome": dict(outcome),
            "membership": membership,
            "artifacts": artifacts,
        }

    def load_chunk_by_evidence_id(
        self, *, run_id: str, evidence_id: str
    ) -> DailyMedV2RecordInput | None:
        if (
            type(run_id) is not str
            or type(evidence_id) is not str
            or not evidence_id.startswith("evidence:sha256:")
        ):
            raise ValueError("DailyMed V2 chunk evidence lookup is invalid")
        table = models.m3_dailymed_v2_records
        with self._repository._engine.connect() as connection:
            ids = tuple(
                connection.execute(
                    sa.select(table.c.record_id)
                    .where(
                        table.c.run_id == run_id,
                        table.c.record_kind == "chunk",
                        table.c.payload_json["evidence_id"].astext == evidence_id,
                    )
                    .limit(2)
                ).scalars()
            )
        if len(ids) > 1:
            raise PersistenceIntegrityError("DailyMed V2 evidence ID has duplicate rows")
        return None if not ids else self.load(ids[0])

    def get_artifact(self, artifact_id: str) -> dict[str, object] | None:
        if type(artifact_id) is not str or not artifact_id.startswith("sha256:"):
            raise ValueError("DailyMed V2 artifact identity is invalid")
        with self._repository._engine.connect() as connection:
            row = (
                connection.execute(
                    sa.select(models.m1b_artifacts).where(
                        models.m1b_artifacts.c.artifact_id == artifact_id
                    )
                )
                .mappings()
                .one_or_none()
            )
        return None if row is None else dict(row)

    def save_member(self, value: DailyMedV2MemberInput) -> DailyMedV2MemberInput:
        """Insert one response ordinal, permitting duplicate content at another ordinal."""

        if type(value) is not DailyMedV2MemberInput:
            raise TypeError("DailyMed V2 member type is invalid")
        fields = value.__dataclass_fields__
        values = {name: getattr(value, name) for name in fields}
        if (
            type(value.ordinal) is not int
            or not 0 <= value.ordinal < 20
            or type(value.byte_size) is not int
            or not 0 <= value.byte_size <= 5_242_880
            or type(value.page_number) is not int
            or not 1 <= value.page_number <= 5
            or type(value.attempt_count) is not int
            or not 1 <= value.attempt_count <= 2
            or value.artifact_id != value.content_hash
            or type(value.body_complete) is not bool
            or value.body_complete != (value.termination_reason == "complete_response")
        ):
            raise ValueError("DailyMed V2 member primitive bounds are invalid")
        table = models.m3_dailymed_v2_members
        with self._repository._engine.begin() as connection:
            existing = (
                connection.execute(
                    sa.select(table).where(
                        table.c.acquisition_id == value.acquisition_id,
                        table.c.ordinal == value.ordinal,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if existing is None:
                try:
                    with connection.begin_nested():
                        connection.execute(table.insert().values(**values))
                except IntegrityError as error:
                    existing = (
                        connection.execute(
                            sa.select(table).where(
                                table.c.acquisition_id == value.acquisition_id,
                                table.c.ordinal == value.ordinal,
                            )
                        )
                        .mappings()
                        .one_or_none()
                    )
                    if existing is None:
                        raise PersistenceConflict(
                            "m3_dailymed_v2_members", "uq_m3_dailymed_v2_member_link"
                        ) from error
            if existing is not None and any(
                existing[name] != expected for name, expected in values.items()
            ):
                raise PersistenceConflict("m3_dailymed_v2_members", "pk_m3_dailymed_v2_members")
        return value
