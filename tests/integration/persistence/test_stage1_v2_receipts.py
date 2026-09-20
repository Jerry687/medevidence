"""Disposable PostgreSQL checks for immutable V2 receipt persistence."""

from __future__ import annotations

import os
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from typing import cast

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine
from tests.unit.infrastructure.test_v2_receipt_store import _final_payload, _stage1_payload

from medevidence.infrastructure.v2_receipt_store import V2ReceiptStore
from medevidence.persistence import (
    DATABASE_URL_ENV,
    PersistenceConflict,
    PersistenceIntegrityError,
    PersistenceRepository,
    PersistenceSettings,
    models,
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


@pytest.fixture(autouse=True)
def empty_receipts(engine: Engine) -> Iterator[None]:
    with engine.begin() as connection:
        connection.execute(models.m3_stage1_receipts.delete())
        connection.execute(models.m3_validation_receipts.delete())
    yield
    with engine.begin() as connection:
        connection.execute(models.m3_stage1_receipts.delete())
        connection.execute(models.m3_validation_receipts.delete())


def _repository(engine: Engine) -> PersistenceRepository:
    return PersistenceRepository._from_engine_for_testing(engine)


def test_stage1_exact_save_replay_reopen_and_timestamp(engine: Engine) -> None:
    payload = _stage1_payload()
    repository = _repository(engine)
    store = V2ReceiptStore(repository)
    saved = store.save_stage1_receipt(payload)
    receipt_id = cast(str, saved["receipt_id"])
    with engine.connect() as connection:
        first_timestamp = connection.scalar(
            sa.select(models.m3_stage1_receipts.c.persisted_at_utc).where(
                models.m3_stage1_receipts.c.receipt_id == receipt_id
            )
        )
    assert store.save_stage1_receipt(payload) == saved
    with engine.connect() as connection:
        second_timestamp = connection.scalar(
            sa.select(models.m3_stage1_receipts.c.persisted_at_utc).where(
                models.m3_stage1_receipts.c.receipt_id == receipt_id
            )
        )
    assert second_timestamp == first_timestamp

    reopened_repository = PersistenceRepository(PersistenceSettings.from_env())
    try:
        assert V2ReceiptStore(reopened_repository).load_stage1_receipt(receipt_id) == saved
    finally:
        reopened_repository.close()


def test_stage1_concurrent_replay_converges(engine: Engine) -> None:
    payload = _stage1_payload()
    repository = _repository(engine)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = tuple(pool.map(repository.save_stage1_receipt, (payload, payload)))
    assert results[0] == results[1]
    with engine.connect() as connection:
        assert (
            connection.scalar(sa.select(sa.func.count()).select_from(models.m3_stage1_receipts))
            == 1
        )


def test_stage1_same_identity_different_payload_conflicts(engine: Engine) -> None:
    payload = _stage1_payload()
    repository = _repository(engine)
    stored = repository._stage1_receipt_values(payload)
    foreign = {**stored, "policy_version": "foreign"}
    with engine.begin() as connection:
        connection.execute(models.m3_stage1_receipts.insert().values(**foreign))
    with pytest.raises(PersistenceConflict) as captured:
        repository.save_stage1_receipt(payload)
    assert captured.value.constraint == "pk_m3_stage1_receipts"


@pytest.mark.parametrize("corruption", ("payload", "projection"))
def test_stage1_corrupted_row_fails_closed(engine: Engine, corruption: str) -> None:
    payload = _stage1_payload()
    repository = _repository(engine)
    saved = repository.save_stage1_receipt(payload)
    receipt_id = cast(str, saved["receipt_id"])
    with engine.begin() as connection:
        connection.execute(
            models.m3_stage1_receipts.update()
            .where(models.m3_stage1_receipts.c.receipt_id == receipt_id)
            .values(
                **(
                    {"receipt_payload": {**saved, "scope_id": "scope:foreign"}}
                    if corruption == "payload"
                    else {"policy_version": "foreign"}
                )
            )
        )
    with pytest.raises(PersistenceIntegrityError):
        V2ReceiptStore(repository).load_stage1_receipt(receipt_id)


def test_final_v2_receipt_persists_and_reloads_exactly(engine: Engine) -> None:
    payload = _final_payload()
    repository = _repository(engine)
    store = V2ReceiptStore(repository)
    saved = store.save_receipt(payload)
    receipt_id = cast(str, saved["receipt_id"])
    reopened_repository = PersistenceRepository(PersistenceSettings.from_env())
    try:
        assert V2ReceiptStore(reopened_repository).load_receipt(receipt_id) == saved
    finally:
        reopened_repository.close()


@pytest.mark.parametrize("corruption", ("payload", "projection"))
def test_final_v2_corrupted_row_fails_closed(engine: Engine, corruption: str) -> None:
    repository = _repository(engine)
    saved = V2ReceiptStore(repository).save_receipt(_final_payload())
    receipt_id = cast(str, saved["receipt_id"])
    with engine.begin() as connection:
        connection.execute(
            models.m3_validation_receipts.update()
            .where(models.m3_validation_receipts.c.receipt_id == receipt_id)
            .values(
                **(
                    {"receipt_payload": {**saved, "routing_policy_hash": "sha256:" + "0" * 64}}
                    if corruption == "payload"
                    else {"evaluator_version": "foreign"}
                )
            )
        )
    with pytest.raises(PersistenceIntegrityError):
        V2ReceiptStore(repository).load_receipt(receipt_id)
