"""Offline concrete composition with optional disposable PostgreSQL."""

from __future__ import annotations

import os
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient

from medevidence.api import create_app
from medevidence.api.routes import REQUEST_EXAMPLE
from medevidence.composition import create_api_dependencies
from medevidence.persistence import (
    DATABASE_URL_ENV,
    PersistenceRepository,
    PersistenceSettings,
)

pytestmark = pytest.mark.enable_socket

NOW = datetime(2026, 8, 8, 12, tzinfo=UTC)
FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "pubmed"
VALID_FETCH = (FIXTURES / "valid_fetch.xml").read_bytes()
VALID_SEARCH = (FIXTURES / "valid_search.xml").read_bytes()
COMPLETE_SEARCH = VALID_SEARCH.replace(b"<Count>3</Count>", b"<Count>2</Count>")
EMPTY_SEARCH = b"""<?xml version="1.0" encoding="UTF-8"?>
<eSearchResult><Count>0</Count><RetMax>0</RetMax><RetStart>0</RetStart><IdList/></eSearchResult>
"""


def _transport(mode: str) -> httpx.BaseTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/esearch.fcgi"):
            body = EMPTY_SEARCH if mode == "no_match" else COMPLETE_SEARCH
            return httpx.Response(
                200,
                content=body,
                headers={"content-type": "application/xml"},
                request=request,
            )
        if request.url.path.endswith("/efetch.fcgi"):
            pmid = request.url.params["id"]
            if mode == "partial" and pmid == "222":
                body = b"<not-valid-pubmed-xml>"
            else:
                body = VALID_FETCH.replace(b"111", pmid.encode("ascii"))
            return httpx.Response(
                200,
                content=body,
                headers={"content-type": "application/xml"},
                request=request,
            )
        raise AssertionError("composition attempted an unapproved PubMed path")

    return httpx.MockTransport(handler)


def _ids(seed: int) -> tuple[Callable[[], str], Callable[[], str], Callable[[], str]]:
    attempt = 0

    def request_id() -> str:
        return f"request:00000000-0000-4000-8000-{seed:012d}"

    def run_id() -> str:
        return f"run:00000000-0000-4000-8000-{seed + 100:012d}"

    def attempt_id() -> str:
        nonlocal attempt
        attempt += 1
        return f"attempt:00000000-0000-4000-8000-{seed * 100 + attempt:012d}"

    return request_id, run_id, attempt_id


def _dependencies(
    tmp_path: Path,
    *,
    database_url: str,
    mode: str,
    seed: int,
) -> object:
    request_id, run_id, attempt_id = _ids(seed)
    return create_api_dependencies(
        snapshot_root=tmp_path / "snapshots",
        persistence_settings=PersistenceSettings(database_url=database_url),
        code_revision="0" * 40,
        request_id_factory=request_id,
        run_id_factory=run_id,
        attempt_id_factory=attempt_id,
        utc_now=lambda: NOW,
        transport_factory=lambda: _transport(mode),
    )


@pytest.fixture
def database_url() -> str:
    value = os.environ.get(DATABASE_URL_ENV)
    if value is None:
        pytest.skip(f"{DATABASE_URL_ENV} is required for disposable PostgreSQL integration")
    config = Config("alembic.ini")
    command.downgrade(config, "base")
    command.upgrade(config, "head")
    return value


def test_app_creation_performs_no_adapter_io(tmp_path: Path) -> None:
    dependencies = _dependencies(
        tmp_path,
        database_url="postgresql+psycopg://test:test@127.0.0.1:1/never-contact",
        mode="complete",
        seed=1,
    )

    app = create_app(dependencies)

    assert not (tmp_path / "snapshots").exists()
    assert tuple(app.openapi()["paths"]) == ("/v1/research/pubmed",)


def test_postgresql_complete_matches_persist_search_and_fetch_separately(
    tmp_path: Path,
    database_url: str,
) -> None:
    response = TestClient(
        create_app(
            _dependencies(
                tmp_path,
                database_url=database_url,
                mode="complete",
                seed=2,
            )
        )
    ).post("/v1/research/pubmed", json=REQUEST_EXAMPLE)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["source_outcomes"][0]["result_status"] == "matches"
    assert len(body["publications"]) == 2
    assert len(body["acquisition_snapshot_ids"]) == 3
    repository = PersistenceRepository(PersistenceSettings(database_url=database_url))
    try:
        snapshots = tuple(
            repository.get_snapshot(snapshot_id) for snapshot_id in body["acquisition_snapshot_ids"]
        )
        assert all(item is not None for item in snapshots)
        search = snapshots[0]
        fetches = snapshots[1:]
        assert search is not None
        assert search.attempt is not None and search.attempt["operation"] == "search"
        assert search.snapshot["record_count"] == 2
        assert search.publications == search.publication_memberships == ()
        assert all(item is not None for item in fetches)
        assert all(
            item is not None
            and item.attempt is not None
            and item.attempt["operation"] == "fetch"
            and item.snapshot["record_count"] == 1
            and len(item.publications) == len(item.publication_memberships) == 1
            for item in fetches
        )
        assert sum(len(item.publications) for item in snapshots if item is not None) == 2
        assert repository.get_report(body["report_id"]) is not None
    finally:
        repository.close()
    root = tmp_path / "snapshots"
    assert all(
        (root / file["relative_storage_path"]).is_file()
        for item in snapshots
        if item is not None
        for file in item.files
    )


def test_postgresql_complete_no_match_persists_search_only(
    tmp_path: Path,
    database_url: str,
) -> None:
    response = TestClient(
        create_app(
            _dependencies(
                tmp_path,
                database_url=database_url,
                mode="no_match",
                seed=3,
            )
        )
    ).post("/v1/research/pubmed", json=REQUEST_EXAMPLE)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["source_outcomes"][0]["result_status"] == "no_match"
    assert body["publications"] == body["claims"] == body["citations"] == []
    assert len(body["acquisition_snapshot_ids"]) == 1


def test_postgresql_partial_match_retains_only_persisted_fetch(
    tmp_path: Path,
    database_url: str,
) -> None:
    response = TestClient(
        create_app(
            _dependencies(
                tmp_path,
                database_url=database_url,
                mode="partial",
                seed=4,
            )
        )
    ).post("/v1/research/pubmed", json=REQUEST_EXAMPLE)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["source_outcomes"][0]["coverage_status"] == "partial"
    assert body["source_outcomes"][0]["result_status"] == "matches"
    assert len(body["publications"]) == 1
    assert len(body["acquisition_snapshot_ids"]) == 3
    repository = PersistenceRepository(PersistenceSettings(database_url=database_url))
    try:
        failed_fetch = repository.get_snapshot(body["acquisition_snapshot_ids"][-1])
        assert failed_fetch is not None
        assert failed_fetch.attempt is not None
        assert failed_fetch.attempt["operation"] == "fetch"
        assert failed_fetch.snapshot["coverage_status"] == "unavailable"
        assert failed_fetch.snapshot["record_count"] == 0
        assert failed_fetch.files == failed_fetch.publications == ()
    finally:
        repository.close()
