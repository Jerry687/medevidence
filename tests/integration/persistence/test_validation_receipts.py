"""Disposable PostgreSQL tests for immutable M3 validation receipts."""

from __future__ import annotations

import os
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine
from tests.unit.tools import test_report_validation as validation_fixtures

from medevidence.persistence import (
    DATABASE_URL_ENV,
    PersistenceConflict,
    PersistenceIntegrityError,
    PersistenceRepository,
    models,
)
from medevidence.tools.report_validation import (
    SemanticSupport,
    canonical_validation_receipt_payload,
    validation_receipt_from_payload,
)


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    value = os.environ.get(DATABASE_URL_ENV)
    if value is None:
        pytest.skip(f"{DATABASE_URL_ENV} is required for disposable PostgreSQL tests")
    config = Config("alembic.ini")
    command.downgrade(config, "base")
    command.upgrade(config, "head")
    instance = sa.create_engine(value, hide_parameters=True)
    yield instance
    instance.dispose()


@pytest.fixture(scope="module")
def repository(engine: Engine) -> PersistenceRepository:
    return PersistenceRepository._from_engine_for_testing(engine)


@pytest.fixture(autouse=True)
def empty_receipt_store(engine: Engine) -> Iterator[None]:
    with engine.begin() as connection:
        connection.execute(models.m3_validation_receipts.delete())
    yield
    with engine.begin() as connection:
        connection.execute(models.m3_validation_receipts.delete())


def _passing_receipt_payload() -> dict[str, object]:
    audit, provider = validation_fixtures._assess(validation_fixtures._empty_request())
    assert audit.summary.passed
    assert provider.calls == []
    assert audit.receipt is not None
    return canonical_validation_receipt_payload(audit.receipt)


def _failed_receipt_payload() -> dict[str, object]:
    support = SemanticSupport.UNSUPPORTED
    audit, provider = validation_fixtures._assess(
        validation_fixtures._material_request(support=support),
        validation_fixtures.Provider(support),
    )
    assert not audit.summary.passed
    assert provider.calls
    assert audit.receipt is not None
    return canonical_validation_receipt_payload(audit.receipt)


def _row_count(engine: Engine) -> int:
    with engine.connect() as connection:
        return (
            connection.scalar(sa.select(sa.func.count()).select_from(models.m3_validation_receipts))
            or 0
        )


def _unrelated_table_counts(engine: Engine) -> dict[str, int]:
    with engine.connect() as connection:
        return {
            table.name: connection.scalar(sa.select(sa.func.count()).select_from(table)) or 0
            for table in models.metadata.tables.values()
            if table is not models.m3_validation_receipts
        }


@pytest.mark.parametrize(
    "receipt_factory",
    (_passing_receipt_payload, _failed_receipt_payload),
)
def test_receipt_save_load_roundtrip_and_exact_replay_preserve_timestamp(
    engine: Engine,
    repository: PersistenceRepository,
    receipt_factory: Callable[[], dict[str, object]],
) -> None:
    payload = receipt_factory()
    receipt = validation_receipt_from_payload(payload)
    unrelated_before = _unrelated_table_counts(engine)

    first_saved = repository.save_receipt(payload)
    assert first_saved == payload
    assert validation_receipt_from_payload(first_saved) == receipt
    with engine.connect() as connection:
        first_timestamp = connection.scalar(
            sa.select(models.m3_validation_receipts.c.persisted_at_utc).where(
                models.m3_validation_receipts.c.receipt_id == receipt.receipt_id
            )
        )
    assert isinstance(first_timestamp, datetime)

    replayed = repository.save_receipt(payload)
    assert replayed == payload
    assert validation_receipt_from_payload(replayed) == receipt
    loaded = repository.load_receipt(receipt.receipt_id)
    assert loaded == payload
    assert loaded is not None
    assert validation_receipt_from_payload(loaded) == receipt
    with engine.connect() as connection:
        second_timestamp = connection.scalar(
            sa.select(models.m3_validation_receipts.c.persisted_at_utc).where(
                models.m3_validation_receipts.c.receipt_id == receipt.receipt_id
            )
        )
    assert second_timestamp == first_timestamp
    assert _row_count(engine) == 1
    assert _unrelated_table_counts(engine) == unrelated_before


def test_same_identity_different_semantic_content_conflicts(
    engine: Engine,
    repository: PersistenceRepository,
) -> None:
    payload = _passing_receipt_payload()
    foreign_values = PersistenceRepository._validation_receipt_values(_failed_receipt_payload())
    foreign_values["receipt_id"] = payload["receipt_id"]
    with engine.begin() as connection:
        connection.execute(models.m3_validation_receipts.insert().values(**foreign_values))

    with pytest.raises(PersistenceConflict) as captured:
        repository.save_receipt(payload)
    assert captured.value.table == "m3_validation_receipts"
    assert captured.value.constraint == "pk_m3_validation_receipts"
    assert _row_count(engine) == 1


def test_unique_content_conflict_is_not_misclassified_as_replay(
    engine: Engine,
    repository: PersistenceRepository,
) -> None:
    payload = _passing_receipt_payload()
    conflicting_values = PersistenceRepository._validation_receipt_values(payload)
    conflicting_values["receipt_id"] = "validation-receipt:sha256:" + "f" * 64
    with engine.begin() as connection:
        connection.execute(models.m3_validation_receipts.insert().values(**conflicting_values))

    with pytest.raises(PersistenceConflict) as captured:
        repository.save_receipt(payload)
    assert captured.value.table == "m3_validation_receipts"
    assert captured.value.constraint == "uq_m3_validation_receipts_content_hash"
    assert _row_count(engine) == 1


def test_missing_and_malformed_receipt_identity_fail_closed(
    repository: PersistenceRepository,
) -> None:
    missing = "validation-receipt:sha256:" + "0" * 64
    assert repository.load_receipt(missing) is None
    for malformed in ("", "validation-receipt:sha256:short", None):
        with pytest.raises(ValueError, match="exact validation-receipt identity"):
            repository.load_receipt(malformed)  # type: ignore[arg-type]


@pytest.mark.parametrize("corruption", ("payload", "projection"))
def test_persisted_receipt_corruption_fails_closed(
    engine: Engine,
    repository: PersistenceRepository,
    corruption: str,
) -> None:
    payload = _passing_receipt_payload()
    receipt = validation_receipt_from_payload(payload)
    repository.save_receipt(payload)
    with engine.begin() as connection:
        if corruption == "payload":
            connection.execute(
                models.m3_validation_receipts.update()
                .where(models.m3_validation_receipts.c.receipt_id == receipt.receipt_id)
                .values(receipt_payload={"marker": "M3_VALIDATION_RECEIPT_V1"})
            )
            message = "payload violates the bounded storage contract"
        else:
            connection.execute(
                models.m3_validation_receipts.update()
                .where(models.m3_validation_receipts.c.receipt_id == receipt.receipt_id)
                .values(evaluator_version="corrupted-v2")
            )
            message = "projections differ from canonical payload"

    with pytest.raises(PersistenceIntegrityError, match=message):
        repository.load_receipt(receipt.receipt_id)


def test_invalid_payload_is_rejected_without_leaving_receipt(
    engine: Engine,
    repository: PersistenceRepository,
) -> None:
    invalid_payload = {
        **_passing_receipt_payload(),
        "run_id": "run:12345678-1234-6234-9234-123456789abc",
    }

    with pytest.raises(ValueError, match="validation receipt run_id is invalid"):
        repository.save_receipt(invalid_payload)
    assert _row_count(engine) == 0


def test_concurrent_identical_receipt_saves_converge(
    engine: Engine,
    repository: PersistenceRepository,
) -> None:
    payload = _passing_receipt_payload()
    receipt = validation_receipt_from_payload(payload)
    with ThreadPoolExecutor(max_workers=2) as pool:
        stored = tuple(pool.map(repository.save_receipt, (payload, payload)))

    assert stored == (payload, payload)
    assert tuple(validation_receipt_from_payload(item) for item in stored) == (
        receipt,
        receipt,
    )
    loaded = repository.load_receipt(receipt.receipt_id)
    assert loaded == payload
    assert loaded is not None
    assert validation_receipt_from_payload(loaded) == receipt
    assert _row_count(engine) == 1
