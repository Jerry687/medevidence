"""Append-only PostgreSQL journal for runtime semantic-evaluation operations."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, fields
from datetime import UTC, datetime
from typing import Final, Literal

import sqlalchemy as sa
from sqlalchemy import Engine
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError

from medevidence.domain import canonical_json

from . import models
from .config import PersistenceSettings
from .session import _create_engine

SEMANTIC_CACHE_SCHEMA_VERSION: Final = "M3_RUNTIME_SEMANTIC_CACHE_EVENT_V1"
MAX_SEMANTIC_OPERATIONS_PER_RUN: Final = 400
MAX_SEMANTIC_ATTEMPTS: Final = 3
MAX_SEMANTIC_EVENT_PAYLOAD_BYTES: Final = 524_288
MAX_SEMANTIC_RAW_BYTES: Final = 131_072

_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
_RUN_ID = re.compile(
    r"run:[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\Z"
)
_CITATION_ID = re.compile(r"citation:sha256:[0-9a-f]{64}\Z")
_OPERATION_ID = re.compile(r"semantic-evaluation-operation:sha256:[0-9a-f]{64}\Z")
_EVENT_ID = re.compile(r"semantic-cache-event:sha256:[0-9a-f]{64}\Z")
_PROFILE_VERSION = re.compile(r"[a-z0-9][a-z0-9._-]{0,255}\Z")
_SLOTS: Final = {"START": 0, "RAW": 1, "RESULT": 2, "TERMINAL": 3}
_DISPOSITIONS: Final = frozenset(
    {
        "success",
        "authentication_failed",
        "candidate_invalid",
        "credential_echo",
        "deadline_exceeded",
        "evidence_persistence_failure",
        "provider_rejected",
        "response_invalid",
        "response_too_large",
        "retryable_status",
        "transport_unavailable",
        "validation_internal_failure",
    }
)


def _valid_event_id(value: object) -> bool:
    return type(value) is str and _EVENT_ID.fullmatch(value) is not None


def _matches(pattern: re.Pattern[str], value: object) -> bool:
    return type(value) is str and pattern.fullmatch(value) is not None


class _DuplicateKey(ValueError):
    pass


def _unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise _DuplicateKey
        value[key] = item
    return value


def _reject_constant(_value: str) -> None:
    raise ValueError("non-finite JSON number")


def _canonical_payload(raw: bytes) -> dict[str, object]:
    try:
        value = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=_unique,
            parse_constant=_reject_constant,
        )
    except (UnicodeError, ValueError, json.JSONDecodeError, RecursionError):
        raise ValueError("semantic cache payload is invalid JSON") from None
    if type(value) is not dict or canonical_json(value).encode("utf-8") != raw:
        raise ValueError("semantic cache payload is not a canonical JSON object")
    return value


semantic_evaluation_events = sa.Table(
    "m3_semantic_evaluation_events",
    models.metadata,
    sa.Column("event_id", sa.Text(), primary_key=True),
    sa.Column("schema_version", sa.Text(), nullable=False),
    sa.Column("operation_id", sa.Text(), nullable=False),
    sa.Column("run_id", sa.Text(), nullable=False),
    sa.Column("citation_id", sa.Text(), nullable=False),
    sa.Column("request_content_hash", sa.Text(), nullable=False),
    sa.Column("provider_configuration_version", sa.Text(), nullable=False),
    sa.Column("provider_configuration_hash", sa.Text(), nullable=False),
    sa.Column("attempt_ordinal", sa.SmallInteger(), nullable=False),
    sa.Column("event_slot", sa.SmallInteger(), nullable=False),
    sa.Column("event_kind", sa.Text(), nullable=False),
    sa.Column(
        "start_event_id",
        sa.Text(),
        sa.ForeignKey(
            "medevidence.m3_semantic_evaluation_events.event_id",
            onupdate="RESTRICT",
            ondelete="RESTRICT",
        ),
        nullable=True,
    ),
    sa.Column(
        "raw_event_id",
        sa.Text(),
        sa.ForeignKey(
            "medevidence.m3_semantic_evaluation_events.event_id",
            onupdate="RESTRICT",
            ondelete="RESTRICT",
        ),
        nullable=True,
    ),
    sa.Column(
        "result_event_id",
        sa.Text(),
        sa.ForeignKey(
            "medevidence.m3_semantic_evaluation_events.event_id",
            onupdate="RESTRICT",
            ondelete="RESTRICT",
        ),
        nullable=True,
    ),
    sa.Column("payload_hash", sa.Text(), nullable=False),
    sa.Column("payload_json", postgresql.JSONB(), nullable=False),
    sa.Column("raw_body_hash", sa.Text(), nullable=True),
    sa.Column("raw_body_bytes", sa.LargeBinary(), nullable=True),
    sa.Column("started_at_utc", sa.DateTime(timezone=True), nullable=False),
    sa.Column("completed_at_utc", sa.DateTime(timezone=True), nullable=True),
    sa.Column("disposition", sa.Text(), nullable=True),
    sa.Column("error_code", sa.Text(), nullable=True),
    sa.Column(
        "persisted_at_utc",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("CURRENT_TIMESTAMP"),
    ),
    sa.UniqueConstraint(
        "operation_id", "attempt_ordinal", "event_slot", name="uq_semantic_cache_event_slot"
    ),
    schema="medevidence",
)


class SemanticCacheError(RuntimeError):
    """Base runtime semantic-cache persistence error."""


class SemanticCacheConflict(SemanticCacheError):
    """A concurrent or different event already occupies the immutable slot."""


class SemanticCacheIntegrityError(SemanticCacheError):
    """Stored bytes or projected columns violate the typed event contract."""


@dataclass(frozen=True, slots=True)
class SemanticCacheEvent:
    """One exact append-only event; infrastructure owns payload interpretation."""

    event_id: str
    schema_version: str
    operation_id: str
    run_id: str
    citation_id: str
    request_content_hash: str
    provider_configuration_version: str
    provider_configuration_hash: str
    attempt_ordinal: int
    event_slot: int
    event_kind: Literal["START", "RAW", "RESULT", "TERMINAL"]
    start_event_id: str | None
    raw_event_id: str | None
    result_event_id: str | None
    payload_hash: str
    payload_bytes: bytes
    raw_body_hash: str | None
    raw_body_bytes: bytes | None
    started_at_utc: datetime
    completed_at_utc: datetime | None
    disposition: str | None
    error_code: str | None


@dataclass(frozen=True, slots=True)
class SemanticCacheLease:
    connection: sa.Connection
    operation_id: str


def semantic_cache_event_id(event: SemanticCacheEvent) -> str:
    """Compute the event identity from all projections and byte identities."""

    payload = {
        field.name: getattr(event, field.name)
        for field in fields(event)
        if field.name not in {"event_id", "payload_bytes", "raw_body_bytes"}
    }
    payload["started_at_utc"] = event.started_at_utc.isoformat()
    payload["completed_at_utc"] = (
        None if event.completed_at_utc is None else event.completed_at_utc.isoformat()
    )
    payload["payload_byte_count"] = len(event.payload_bytes)
    payload["raw_body_byte_count"] = (
        None if event.raw_body_bytes is None else len(event.raw_body_bytes)
    )
    return (
        "semantic-cache-event:sha256:"
        + hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
    )


def validate_semantic_cache_event(event: SemanticCacheEvent) -> SemanticCacheEvent:
    """Reject noncanonical DTOs before insert and after every read."""

    if type(event) is not SemanticCacheEvent:
        raise ValueError("semantic cache event type is invalid")
    if (
        event.schema_version != SEMANTIC_CACHE_SCHEMA_VERSION
        or not _matches(_EVENT_ID, event.event_id)
        or not _matches(_OPERATION_ID, event.operation_id)
        or not _matches(_RUN_ID, event.run_id)
        or not _matches(_CITATION_ID, event.citation_id)
        or not _matches(_DIGEST, event.request_content_hash)
        or not _matches(_PROFILE_VERSION, event.provider_configuration_version)
        or not _matches(_DIGEST, event.provider_configuration_hash)
        or type(event.attempt_ordinal) is not int
        or not 1 <= event.attempt_ordinal <= MAX_SEMANTIC_ATTEMPTS
        or type(event.event_slot) is not int
        or type(event.event_kind) is not str
        or _SLOTS.get(event.event_kind) != event.event_slot
        or type(event.payload_bytes) is not bytes
        or not 1 <= len(event.payload_bytes) <= MAX_SEMANTIC_EVENT_PAYLOAD_BYTES
        or not _matches(_DIGEST, event.payload_hash)
        or event.payload_hash != "sha256:" + hashlib.sha256(event.payload_bytes).hexdigest()
        or type(event.started_at_utc) is not datetime
        or event.started_at_utc.tzinfo is None
        or event.started_at_utc.utcoffset() != UTC.utcoffset(event.started_at_utc)
        or (
            event.completed_at_utc is not None
            and (
                type(event.completed_at_utc) is not datetime
                or event.completed_at_utc.tzinfo is None
                or event.completed_at_utc.utcoffset() != UTC.utcoffset(event.completed_at_utc)
                or event.completed_at_utc < event.started_at_utc
            )
        )
    ):
        raise ValueError("semantic cache event projections are invalid")
    if event.raw_body_bytes is None:
        if event.raw_body_hash is not None:
            raise ValueError("semantic cache raw hash lacks bytes")
    elif (
        event.event_kind != "RAW"
        or type(event.raw_body_bytes) is not bytes
        or not 1 <= len(event.raw_body_bytes) <= MAX_SEMANTIC_RAW_BYTES
        or not _matches(_DIGEST, event.raw_body_hash)
        or event.raw_body_hash != "sha256:" + hashlib.sha256(event.raw_body_bytes).hexdigest()
    ):
        raise ValueError("semantic cache raw body is invalid")
    if event.event_kind != "RAW" and (
        event.raw_body_hash is not None or event.raw_body_bytes is not None
    ):
        raise ValueError("semantic cache raw bytes occupy the wrong event")
    _canonical_payload(event.payload_bytes)
    link_shape = {
        "START": (None, None, None),
        "RAW": (event.start_event_id, None, None),
        "RESULT": (event.start_event_id, event.raw_event_id, None),
        "TERMINAL": (event.start_event_id, event.raw_event_id, event.result_event_id),
    }[event.event_kind]
    if event.event_kind == "START":
        valid_links = link_shape == (None, None, None)
    elif event.event_kind == "RAW":
        valid_links = _valid_event_id(event.start_event_id)
    elif event.event_kind == "RESULT":
        valid_links = _valid_event_id(event.start_event_id) and _valid_event_id(event.raw_event_id)
    else:
        valid_links = (
            _valid_event_id(event.start_event_id)
            and (event.raw_event_id is None or _valid_event_id(event.raw_event_id))
            and (event.result_event_id is None or _valid_event_id(event.result_event_id))
        )
    if not valid_links:
        raise ValueError("semantic cache event links are invalid")
    if event.event_kind == "TERMINAL":
        if (
            event.completed_at_utc is None
            or type(event.disposition) is not str
            or event.disposition not in _DISPOSITIONS
            or (event.error_code is not None and type(event.error_code) is not str)
            or (event.disposition == "success")
            != (
                event.error_code is None
                and event.raw_event_id is not None
                and event.result_event_id is not None
            )
            or (event.disposition != "success" and event.error_code != event.disposition)
        ):
            raise ValueError("semantic cache terminal state is invalid")
    elif (
        event.completed_at_utc is not None
        or event.disposition is not None
        or event.error_code is not None
    ):
        raise ValueError("semantic cache nonterminal carries terminal facts")
    if event.event_id != semantic_cache_event_id(event):
        raise ValueError("semantic cache event identity drift")
    return event


def make_semantic_cache_event(**values: object) -> SemanticCacheEvent:
    """Build an exact event and derive its identity once."""

    provisional = SemanticCacheEvent(event_id="semantic-cache-event:sha256:" + "0" * 64, **values)  # type: ignore[arg-type]
    event = SemanticCacheEvent(
        **{
            field.name: getattr(provisional, field.name)
            for field in fields(provisional)
            if field.name != "event_id"
        },
        event_id=semantic_cache_event_id(provisional),
    )
    return validate_semantic_cache_event(event)


class SemanticCacheRepository:
    """Insert/list/lease API with no update or delete surface."""

    def __init__(self, settings: PersistenceSettings) -> None:
        self._engine = _create_engine(settings)

    @classmethod
    def _from_engine_for_testing(cls, engine: Engine) -> SemanticCacheRepository:
        value = cls.__new__(cls)
        value._engine = engine
        return value

    def close(self) -> None:
        self._engine.dispose()

    def acquire_operation_lease(self, operation_id: str) -> SemanticCacheLease:
        if not _matches(_OPERATION_ID, operation_id):
            raise ValueError("semantic operation identity is invalid")
        connection = self._engine.connect()
        acquired = connection.scalar(
            sa.text("SELECT pg_try_advisory_lock(hashtextextended(:operation_id, 0))"),
            {"operation_id": operation_id},
        )
        if acquired is not True:
            connection.close()
            raise SemanticCacheConflict("semantic operation lease is already held")
        return SemanticCacheLease(connection, operation_id)

    def release_operation_lease(self, lease: SemanticCacheLease) -> None:
        if type(lease) is not SemanticCacheLease:
            raise ValueError("semantic cache lease type is invalid")
        try:
            lease.connection.scalar(
                sa.text("SELECT pg_advisory_unlock(hashtextextended(:operation_id, 0))"),
                {"operation_id": lease.operation_id},
            )
        finally:
            lease.connection.close()

    def append(self, event: SemanticCacheEvent) -> SemanticCacheEvent:
        value = validate_semantic_cache_event(event)
        row = {field.name: getattr(value, field.name) for field in fields(value)}
        row["payload_json"] = _canonical_payload(value.payload_bytes)
        del row["payload_bytes"]
        try:
            with self._engine.begin() as connection:
                if value.event_kind == "START" and value.attempt_ordinal == 1:
                    connection.execute(
                        sa.text("SELECT pg_advisory_xact_lock(hashtextextended(:run_id, 1))"),
                        {"run_id": value.run_id},
                    )
                    existing = connection.scalar(
                        sa.select(
                            sa.func.count(sa.distinct(semantic_evaluation_events.c.operation_id))
                        ).where(
                            semantic_evaluation_events.c.run_id == value.run_id,
                            semantic_evaluation_events.c.event_kind == "START",
                            semantic_evaluation_events.c.attempt_ordinal == 1,
                        )
                    )
                    if type(existing) is not int or existing >= MAX_SEMANTIC_OPERATIONS_PER_RUN:
                        raise SemanticCacheConflict("semantic operation run capacity is exhausted")
                connection.execute(semantic_evaluation_events.insert().values(**row))
        except SemanticCacheConflict:
            raise
        except IntegrityError as error:
            raise SemanticCacheConflict("semantic cache event slot already exists") from error
        except Exception as error:
            raise SemanticCacheError("semantic cache event insert failed") from error
        return value

    def list_events(self, operation_id: str) -> tuple[SemanticCacheEvent, ...]:
        if not _matches(_OPERATION_ID, operation_id):
            raise ValueError("semantic operation identity is invalid")
        with self._engine.connect() as connection:
            rows = (
                connection.execute(
                    sa.select(semantic_evaluation_events)
                    .where(semantic_evaluation_events.c.operation_id == operation_id)
                    .order_by(
                        semantic_evaluation_events.c.attempt_ordinal,
                        semantic_evaluation_events.c.event_slot,
                    )
                )
                .mappings()
                .all()
            )
        events = []
        names = {field.name for field in fields(SemanticCacheEvent)}
        for row in rows:
            values = {name: row[name] for name in names if name != "payload_bytes"}
            values["payload_bytes"] = canonical_json(row["payload_json"]).encode("utf-8")
            try:
                events.append(validate_semantic_cache_event(SemanticCacheEvent(**values)))
            except (TypeError, ValueError) as error:
                raise SemanticCacheIntegrityError(
                    "stored semantic cache event is invalid"
                ) from error
        return tuple(events)
