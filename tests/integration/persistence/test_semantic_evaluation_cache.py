"""Disposable PostgreSQL checks for the append-only runtime semantic cache."""

from __future__ import annotations

import hashlib
import os
from datetime import UTC, datetime

import httpx
import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from tests.contract.infrastructure.test_deepseek_semantic_evaluator import API_KEY
from tests.unit.infrastructure.test_deepseek_semantic_cache import (
    Stage1Store,
    _request_and_receipt,
    _success,
)

from medevidence.domain import canonical_json
from medevidence.infrastructure.deepseek_semantic_cache import (
    DurableDeepSeekSemanticEvaluationPortV2,
    SemanticCachePortError,
    SemanticCachePortErrorCode,
    semantic_evaluation_operation_id,
)
from medevidence.infrastructure.deepseek_semantic_evaluator import (
    DeepSeekResponsesSemanticEvaluatorV2,
)
from medevidence.persistence.config import DATABASE_URL_ENV, PersistenceSettings
from medevidence.persistence.semantic_cache import (
    MAX_SEMANTIC_OPERATIONS_PER_RUN,
    SEMANTIC_CACHE_SCHEMA_VERSION,
    SemanticCacheConflict,
    SemanticCacheRepository,
    make_semantic_cache_event,
    semantic_evaluation_events,
)

RUN_ID = "run:12345678-1234-4234-9234-123456789abc"
CITATION_ID = "citation:sha256:" + "c" * 64
DIGEST = "sha256:" + "d" * 64
PROFILE = "m3.semantic-evaluation.v2.deepseek-responses.v2"
NOW = datetime(2026, 9, 15, tzinfo=UTC)


def _operation(index: int) -> str:
    return "semantic-evaluation-operation:sha256:" + f"{index:064x}"


def _start(index: int, *, attempt: int = 1):  # type: ignore[no-untyped-def]
    payload = canonical_json({"operation": index, "attempt": attempt}).encode("utf-8")
    return make_semantic_cache_event(
        schema_version=SEMANTIC_CACHE_SCHEMA_VERSION,
        operation_id=_operation(index),
        run_id=RUN_ID,
        citation_id=CITATION_ID,
        request_content_hash=DIGEST,
        provider_configuration_version=PROFILE,
        provider_configuration_hash=DIGEST,
        attempt_ordinal=attempt,
        event_slot=0,
        event_kind="START",
        start_event_id=None,
        raw_event_id=None,
        result_event_id=None,
        payload_hash="sha256:" + hashlib.sha256(payload).hexdigest(),
        payload_bytes=payload,
        raw_body_hash=None,
        raw_body_bytes=None,
        started_at_utc=NOW,
        completed_at_utc=None,
        disposition=None,
        error_code=None,
    )


@pytest.fixture
def repository():  # type: ignore[no-untyped-def]
    if DATABASE_URL_ENV not in os.environ:
        pytest.skip(f"{DATABASE_URL_ENV} is required")
    command.upgrade(Config("alembic.ini"), "head")
    settings = PersistenceSettings.from_env()
    engine = sa.create_engine(settings.database_url)
    with engine.begin() as connection:
        connection.execute(semantic_evaluation_events.delete())
    engine.dispose()
    value = SemanticCacheRepository(settings)
    try:
        yield value
    finally:
        value.close()


def test_migration_catalog_and_insert_only_roundtrip(repository: SemanticCacheRepository) -> None:
    event = _start(1)
    assert repository.append(event) == event
    assert repository.list_events(event.operation_id) == (event,)
    with pytest.raises(SemanticCacheConflict, match="slot already exists"):
        repository.append(event)
    settings = PersistenceSettings.from_env()
    engine = sa.create_engine(settings.database_url)
    inspector = sa.inspect(engine)
    assert "m3_semantic_evaluation_events" in inspector.get_table_names(schema="medevidence")
    columns = {
        item["name"]
        for item in inspector.get_columns("m3_semantic_evaluation_events", schema="medevidence")
    }
    assert columns == set(semantic_evaluation_events.c.keys())
    uniques = {
        item["name"]
        for item in inspector.get_unique_constraints(
            "m3_semantic_evaluation_events", schema="medevidence"
        )
    }
    assert "uq_semantic_cache_event_slot" in uniques
    foreign_keys = inspector.get_foreign_keys("m3_semantic_evaluation_events", schema="medevidence")
    assert len(foreign_keys) == 3
    assert all(
        item["options"] == {"onupdate": "RESTRICT", "ondelete": "RESTRICT"}
        and item.get("deferrable") in {None, False}
        for item in foreign_keys
    )
    engine.dispose()


def test_operation_lease_is_nonblocking_and_attempt_two_does_not_consume_run_capacity(
    repository: SemanticCacheRepository,
) -> None:
    operation_id = _operation(1)
    lease = repository.acquire_operation_lease(operation_id)
    other = SemanticCacheRepository(PersistenceSettings.from_env())
    try:
        with pytest.raises(SemanticCacheConflict, match="already held"):
            other.acquire_operation_lease(operation_id)
    finally:
        repository.release_operation_lease(lease)
        other.close()
    repository.append(_start(1))
    repository.append(_start(1, attempt=2))
    assert [item.attempt_ordinal for item in repository.list_events(operation_id)] == [1, 2]


def test_run_operation_capacity_is_exact(repository: SemanticCacheRepository) -> None:
    for index in range(1, MAX_SEMANTIC_OPERATIONS_PER_RUN + 1):
        repository.append(_start(index))
    with pytest.raises(SemanticCacheConflict, match="capacity is exhausted"):
        repository.append(_start(MAX_SEMANTIC_OPERATIONS_PER_RUN + 1))


def test_real_repository_caches_success_without_second_provider_call(
    repository: SemanticCacheRepository,
) -> None:
    request, receipt = _request_and_receipt()
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return _success()

    port = DurableDeepSeekSemanticEvaluationPortV2(
        evaluator=DeepSeekResponsesSemanticEvaluatorV2(
            api_key=API_KEY, transport=httpx.MockTransport(handler)
        ),
        journal=repository,
        stage1_receipts=Stage1Store(receipt),
        sleeper=lambda _: None,
    )
    assert port.evaluate_v2(request) == port.evaluate_v2(request)
    assert calls == 1
    events = repository.list_events(semantic_evaluation_operation_id(request))
    assert [item.event_kind for item in events] == ["START", "RAW", "RESULT", "TERMINAL"]


def test_operation_lease_blocks_provider_and_stored_raw_tamper_fails_closed(
    repository: SemanticCacheRepository,
) -> None:
    request, receipt = _request_and_receipt()
    operation_id = semantic_evaluation_operation_id(request)
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return _success()

    port = DurableDeepSeekSemanticEvaluationPortV2(
        evaluator=DeepSeekResponsesSemanticEvaluatorV2(
            api_key=API_KEY, transport=httpx.MockTransport(handler)
        ),
        journal=repository,
        stage1_receipts=Stage1Store(receipt),
        sleeper=lambda _: None,
    )
    lease = repository.acquire_operation_lease(operation_id)
    try:
        with pytest.raises(SemanticCachePortError) as caught:
            port.evaluate_v2(request)
        assert caught.value.code is SemanticCachePortErrorCode.CACHE_BUSY
        assert calls == 0
    finally:
        repository.release_operation_lease(lease)
    port.evaluate_v2(request)
    engine = sa.create_engine(PersistenceSettings.from_env().database_url)
    with engine.begin() as connection:
        connection.execute(
            semantic_evaluation_events.update()
            .where(
                semantic_evaluation_events.c.operation_id == operation_id,
                semantic_evaluation_events.c.event_kind == "RAW",
            )
            .values(raw_body_bytes=b"tampered")
        )
    engine.dispose()
    with pytest.raises(SemanticCachePortError) as caught:
        port.evaluate_v2(request)
    assert caught.value.code is SemanticCachePortErrorCode.CACHE_INTEGRITY
    assert calls == 1
