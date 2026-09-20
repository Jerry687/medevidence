"""Durable bounded research-job registry; checkpoint truth remains in LangGraph."""

# ruff: noqa: E501  # Frozen PostgreSQL CHECK SQL literals remain byte-exact.

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import cast
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy import Engine
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError

from medevidence.domain import canonical_json, derive_identity, sha256_digest

from .config import PersistenceSettings
from .session import _create_engine

_SCHEMA = "medevidence"
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
_RUN_ID = re.compile(r"run:[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}")
_SCOPE_ID = re.compile(r"scope:sha256:[0-9a-f]{64}")
_PHASES = frozenset(
    {
        "submitted",
        "running",
        "pending_review",
        "reviewing",
        "blocked",
        "rejected",
        "exported",
        "unavailable",
    }
)
_TRANSITIONS = frozenset(
    {
        ("submitted", "running"),
        ("running", "pending_review"),
        ("running", "blocked"),
        ("running", "unavailable"),
        ("reviewing", "pending_review"),
        ("reviewing", "rejected"),
        ("reviewing", "exported"),
        ("reviewing", "unavailable"),
        ("reviewing", "blocked"),
        ("pending_review", "reviewing"),
    }
)
_MAX_SCOPE_BYTES = 65_536
_MAX_JOBS = 10_000

metadata = sa.MetaData()
m3_research_jobs = sa.Table(
    "m3_research_jobs",
    metadata,
    sa.Column("run_id", sa.String(40), nullable=False),
    sa.Column("idempotency_key", sa.CHAR(71), nullable=False),
    sa.Column("report_id", sa.String(96), nullable=False),
    sa.Column("scope_id", sa.String(96), nullable=False),
    sa.Column("scope_hash", sa.CHAR(71), nullable=False),
    sa.Column("scope_payload", postgresql.JSONB(), nullable=False),
    sa.Column("workflow_id", sa.String(96), nullable=False),
    sa.Column("checkpoint_id", sa.String(96), nullable=False),
    sa.Column("destination_id", sa.String(96), nullable=False),
    sa.Column("phase", sa.String(24), nullable=False),
    sa.Column("error_code", sa.String(64), nullable=True),
    sa.Column("review_command_key", sa.CHAR(71), nullable=True),
    sa.Column(
        "created_at_utc",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("CURRENT_TIMESTAMP"),
    ),
    sa.Column(
        "updated_at_utc",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("CURRENT_TIMESTAMP"),
    ),
    sa.PrimaryKeyConstraint("run_id", name="pk_m3_research_jobs"),
    sa.UniqueConstraint("idempotency_key", name="uq_m3_research_job_key"),
    sa.UniqueConstraint("report_id", name="uq_m3_research_job_report"),
    sa.CheckConstraint(
        "run_id ~ '^run:[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$' AND report_id ~ '^report:sha256:[0-9a-f]{64}$' AND scope_id ~ '^scope:sha256:[0-9a-f]{64}$'",
        name="ck_m3_research_jobs_identity",
    ),
    sa.CheckConstraint(
        "idempotency_key ~ '^sha256:[0-9a-f]{64}$' AND scope_hash ~ '^sha256:[0-9a-f]{64}$' AND (review_command_key IS NULL OR review_command_key ~ '^sha256:[0-9a-f]{64}$')",
        name="ck_m3_research_jobs_hashes",
    ),
    sa.CheckConstraint(
        "phase IN ('submitted','running','pending_review','reviewing','blocked','rejected','exported','unavailable') AND jsonb_typeof(scope_payload)='object'",
        name="ck_m3_research_jobs_phase_payload",
    ),
    sa.CheckConstraint(
        "(error_code IS NULL OR error_code IN ('execution_blocked','execution_unavailable','material_unavailable','review_unavailable')) AND (phase NOT IN ('blocked','unavailable') OR error_code IS NOT NULL)",
        name="ck_m3_research_jobs_error",
    ),
    sa.CheckConstraint(
        "workflow_id ~ '^workflow:sha256:[0-9a-f]{64}$' AND checkpoint_id ~ '^checkpoint:sha256:[0-9a-f]{64}$' AND destination_id ~ '^destination:sha256:[0-9a-f]{64}$'",
        name="ck_m3_research_jobs_allocated_ids",
    ),
    schema=_SCHEMA,
)


class ResearchJobConflict(RuntimeError):
    """An idempotency key was reused for different permitted scope content."""


class ResearchJobIntegrityError(RuntimeError):
    """A stored job differs from its canonical identity or phase contract."""


def allocated_ids(idempotency_key: str) -> dict[str, str]:
    if type(idempotency_key) is not str or _DIGEST.fullmatch(idempotency_key) is None:
        raise ValueError("job idempotency key is invalid")
    encoded = sha256(("medevidence-research-job:" + idempotency_key).encode("ascii")).digest()
    run_id = "run:" + str(UUID(bytes=encoded[:16], version=4))
    return {
        "run_id": run_id,
        "report_id": derive_identity("report", {"run_id": run_id}),
        "workflow_id": derive_identity("workflow", {"run_id": run_id}),
        "checkpoint_id": derive_identity("checkpoint", {"run_id": run_id, "phase": "allocated"}),
        "destination_id": derive_identity("destination", {"run_id": run_id}),
    }


def _scope_payload(scope_payload: Mapping[str, object]) -> tuple[dict[str, object], str]:
    """Copy only bounded JSON primitives; outer service owns typed scope parsing."""

    if type(scope_payload) is not dict:
        raise ValueError("research scope must be an exact JSON object")
    stack: list[tuple[object, int]] = [(scope_payload, 0)]
    nodes = 0
    while stack:
        value, depth = stack.pop()
        nodes += 1
        if nodes > 5_000 or depth > 16:
            raise ValueError("research scope exceeds JSON structure bounds")
        if type(value) is dict:
            for key, child in value.items():
                if type(key) is not str or len(key) > 128:
                    raise ValueError("research scope JSON key is invalid")
                stack.append((child, depth + 1))
        elif type(value) is list:
            stack.extend((child, depth + 1) for child in value)
        elif value is not None and type(value) not in (str, int, bool):
            raise ValueError("research scope JSON scalar is invalid")
        elif type(value) is str and len(value) > 16_384:
            raise ValueError("research scope JSON string exceeds bound")
    text = canonical_json(scope_payload)
    if len(text.encode("utf-8")) > _MAX_SCOPE_BYTES:
        raise ValueError("research scope exceeds the 65,536 byte bound")
    return json.loads(text), sha256_digest(text)


def _utc(value: object) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ResearchJobIntegrityError("stored job timestamp is not UTC")
    return value.astimezone(UTC)


def _checked_row(value: dict[str, object]) -> dict[str, object]:
    try:
        key = value["idempotency_key"]
        if type(key) is not str or _DIGEST.fullmatch(key) is None:
            raise ValueError("invalid key")
        identities = allocated_ids(key)
        if any(value.get(name) != identity for name, identity in identities.items()):
            raise ValueError("allocated job identity drift")
        scope_id = value["scope_id"]
        if type(scope_id) is not str or _SCOPE_ID.fullmatch(scope_id) is None:
            raise ValueError("scope identity drift")
        phase = value["phase"]
        if phase not in _PHASES:
            raise ValueError("phase drift")
        error_code = value["error_code"]
        allowed_errors = {
            "execution_blocked",
            "execution_unavailable",
            "material_unavailable",
            "review_unavailable",
        }
        if (
            (error_code is not None and error_code not in allowed_errors)
            or (phase in ("blocked", "unavailable") and error_code is None)
            or (phase not in ("blocked", "unavailable") and error_code is not None)
        ):
            raise ValueError("job error classification drift")
        review_key = value["review_command_key"]
        if review_key is not None and (
            type(review_key) is not str or _DIGEST.fullmatch(review_key) is None
        ):
            raise ValueError("review command key drift")
        raw_scope = value["scope_payload"]
        payload, scope_hash = _scope_payload(cast(dict[str, object], raw_scope))
        if payload.get("scope_id") != scope_id or scope_hash != value["scope_hash"]:
            raise ValueError("permitted job scope binding drift")
        if _utc(value["updated_at_utc"]) < _utc(value["created_at_utc"]):
            raise ValueError("job timestamp order drift")
    except (KeyError, TypeError, ValueError) as error:
        raise ResearchJobIntegrityError(
            "stored research job violates canonical contract"
        ) from error
    return value


class ResearchJobRepository:
    """PostgreSQL CAS registry with no automatic retry of an unknown running job."""

    def __init__(self, settings: PersistenceSettings) -> None:
        self._engine = _create_engine(settings)

    @classmethod
    def _from_engine_for_testing(cls, engine: Engine) -> ResearchJobRepository:
        instance = cls.__new__(cls)
        instance._engine = engine
        return instance

    def close(self) -> None:
        self._engine.dispose()

    def create(
        self, *, idempotency_key: str, scope_id: str, scope_payload: Mapping[str, object]
    ) -> tuple[dict[str, object], bool]:
        if type(scope_id) is not str or _SCOPE_ID.fullmatch(scope_id) is None:
            raise ValueError("research scope identity is invalid")
        identities = allocated_ids(idempotency_key)
        payload, scope_hash = _scope_payload(scope_payload)
        if payload.get("scope_id") != scope_id:
            raise ValueError("research scope projection differs from payload")
        values: dict[str, object] = {
            **identities,
            "idempotency_key": idempotency_key,
            "scope_id": scope_id,
            "scope_hash": scope_hash,
            "scope_payload": payload,
            "phase": "submitted",
            "error_code": None,
            "review_command_key": None,
        }
        with self._engine.begin() as connection:
            connection.execute(
                sa.text('LOCK TABLE "medevidence"."m3_research_jobs" IN SHARE ROW EXCLUSIVE MODE')
            )
            existing = (
                connection.execute(
                    sa.select(m3_research_jobs).where(
                        m3_research_jobs.c.idempotency_key == idempotency_key
                    )
                )
                .mappings()
                .one_or_none()
            )
            if existing is not None:
                row = _checked_row(dict(existing))
                if row["scope_id"] != scope_id or row["scope_hash"] != scope_hash:
                    raise ResearchJobConflict("idempotency key conflicts with scope or policy")
                return row, False
            count = connection.scalar(sa.select(sa.func.count()).select_from(m3_research_jobs))
            if count is None or count >= _MAX_JOBS:
                raise ResearchJobConflict("research job capacity is exhausted")
            try:
                connection.execute(m3_research_jobs.insert().values(**values))
            except IntegrityError as error:
                raise ResearchJobConflict("research job identity slot conflicts") from error
            stored = (
                connection.execute(
                    sa.select(m3_research_jobs).where(
                        m3_research_jobs.c.run_id == identities["run_id"]
                    )
                )
                .mappings()
                .one()
            )
        return _checked_row(dict(stored)), True

    def load(self, run_id: str) -> dict[str, object] | None:
        if type(run_id) is not str or _RUN_ID.fullmatch(run_id) is None:
            raise ValueError("research run identity is invalid")
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    sa.select(m3_research_jobs).where(m3_research_jobs.c.run_id == run_id)
                )
                .mappings()
                .one_or_none()
            )
        return None if row is None else _checked_row(dict(row))

    def list(self, *, limit: int, offset: int) -> tuple[dict[str, object], ...]:
        if (
            type(limit) is not int
            or not 1 <= limit <= 50
            or type(offset) is not int
            or not 0 <= offset <= 100_000
        ):
            raise ValueError("research job listing bounds are invalid")
        with self._engine.connect() as connection:
            rows = (
                connection.execute(
                    sa.select(m3_research_jobs)
                    .order_by(m3_research_jobs.c.created_at_utc, m3_research_jobs.c.run_id)
                    .limit(limit)
                    .offset(offset)
                )
                .mappings()
                .all()
            )
        return tuple(_checked_row(dict(row)) for row in rows)

    def transition(
        self,
        run_id: str,
        *,
        expected: str,
        target: str,
        error_code: str | None = None,
        review_command_key: str | None = None,
    ) -> dict[str, object] | None:
        if (expected, target) not in _TRANSITIONS:
            raise ValueError("research job phase transition is invalid")
        if error_code is not None and error_code not in {
            "execution_blocked",
            "execution_unavailable",
            "material_unavailable",
            "review_unavailable",
        }:
            raise ValueError("research job error code is invalid")
        if review_command_key is not None and _DIGEST.fullmatch(review_command_key) is None:
            raise ValueError("review command key is invalid")
        with self._engine.begin() as connection:
            result = (
                connection.execute(
                    m3_research_jobs.update()
                    .where(
                        m3_research_jobs.c.run_id == run_id, m3_research_jobs.c.phase == expected
                    )
                    .values(
                        phase=target,
                        error_code=error_code,
                        review_command_key=review_command_key,
                        updated_at_utc=datetime.now(UTC),
                    )
                    .returning(*m3_research_jobs.c)
                )
                .mappings()
                .one_or_none()
            )
        return None if result is None else _checked_row(dict(result))
