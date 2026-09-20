"""Disposable PostgreSQL job identity and compare-and-set behavior."""

from __future__ import annotations

import os
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine
from tests.unit.orchestration.test_workflow import _scope

from medevidence.domain import ResearchScope, SourceType
from medevidence.persistence.config import DATABASE_URL_ENV
from medevidence.persistence.research_jobs import (
    ResearchJobConflict,
    ResearchJobIntegrityError,
    ResearchJobRepository,
    m3_research_jobs,
)

KEY = "sha256:" + "a" * 64


def _create(
    repository: ResearchJobRepository, scope: ResearchScope
) -> tuple[dict[str, object], bool]:
    return repository.create(
        idempotency_key=KEY,
        scope_id=scope.scope_id,
        scope_payload=scope.model_dump(mode="json"),
    )


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    url = os.environ.get(DATABASE_URL_ENV)
    if url is None:
        pytest.skip(f"{DATABASE_URL_ENV} is required for disposable PostgreSQL tests")
    config = Config("alembic.ini")
    command.downgrade(config, "base")
    command.upgrade(config, "head")
    instance = sa.create_engine(url, hide_parameters=True)
    yield instance
    instance.dispose()


@pytest.fixture(autouse=True)
def empty_jobs(engine: Engine) -> Iterator[None]:
    with engine.begin() as connection:
        connection.execute(m3_research_jobs.delete())
    yield
    with engine.begin() as connection:
        connection.execute(m3_research_jobs.delete())


def test_job_insert_replay_conflict_and_reload(engine: Engine) -> None:
    repository = ResearchJobRepository._from_engine_for_testing(engine)
    scope = _scope()
    first, created = _create(repository, scope)
    assert created and first["phase"] == "submitted"
    second, created = _create(repository, scope)
    assert not created and second == first
    assert repository.load(first["run_id"]) == first
    assert repository.list(limit=20, offset=0) == (first,)
    with pytest.raises(ResearchJobConflict):
        _create(repository, _scope(SourceType.FAERS))


def test_only_one_concurrent_worker_can_claim_start(engine: Engine) -> None:
    repository = ResearchJobRepository._from_engine_for_testing(engine)
    row, _ = _create(repository, _scope())
    with ThreadPoolExecutor(max_workers=2) as pool:
        claims = tuple(
            pool.map(
                lambda _: repository.transition(
                    row["run_id"], expected="submitted", target="running"
                ),
                range(2),
            )
        )
    assert sum(item is not None for item in claims) == 1
    assert repository.load(row["run_id"])["phase"] == "running"


def test_corrupt_stored_scope_fails_closed(engine: Engine) -> None:
    repository = ResearchJobRepository._from_engine_for_testing(engine)
    row, _ = _create(repository, _scope())
    with engine.begin() as connection:
        connection.execute(
            m3_research_jobs.update()
            .where(m3_research_jobs.c.run_id == row["run_id"])
            .values(scope_payload={"patient_name": "synthetic secret"})
        )
    with pytest.raises(ResearchJobIntegrityError):
        repository.load(row["run_id"])


def test_active_row_with_error_classification_fails_closed(engine: Engine) -> None:
    repository = ResearchJobRepository._from_engine_for_testing(engine)
    row, _ = _create(repository, _scope())
    with engine.begin() as connection:
        connection.execute(
            m3_research_jobs.update()
            .where(m3_research_jobs.c.run_id == row["run_id"])
            .values(error_code="execution_unavailable")
        )
    with pytest.raises(ResearchJobIntegrityError):
        repository.load(row["run_id"])
