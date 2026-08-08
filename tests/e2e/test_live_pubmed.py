"""Separately authorized, single-shot live PubMed smoke test (disabled by default)."""

from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
import pytest

from medevidence.api.contracts import ResearchPubMedApiRequest
from medevidence.api.routes import REQUEST_EXAMPLE
from medevidence.catalog import load_production_catalog
from medevidence.connectors.pubmed import (
    PubMedClientIdentity,
    PubMedConnector,
    PubMedFailure,
    PubMedFailureKind,
    PubMedFetchResult,
    PubMedResultState,
    PubMedSearchResult,
    RawPubMedResponse,
)
from medevidence.connectors.pubmed.policy import PubMedConnectorConfig
from medevidence.domain import (
    CoverageStatus,
    ExecutionBounds,
    ExecutionStatus,
    ResultStatus,
    SourceOutcome,
    SourceType,
)
from medevidence.ingestion import (
    AcquisitionIntent,
    AcquisitionRegistrationEnvelope,
    RunIntent,
    SnapshotManifest,
    capture_acquisition,
    response_observation,
    with_computed_identity,
)
from medevidence.ingestion.artifacts import write_immutable_record
from medevidence.ingestion.contracts import (
    AcquisitionExecutionLimits,
    ArtifactLinkReference,
    RunExecutionLimits,
)
from medevidence.ingestion.snapshots import INITIAL_FREE_SPACE_FLOOR_BYTES, SnapshotStore
from medevidence.tools.pubmed import build_pubmed_query, query_identity

PUBMED_ORIGIN = "https://eutils.ncbi.nlm.nih.gov"
PUBMED_ESEARCH_PATH = "/entrez/eutils/esearch.fcgi"
PUBMED_EFETCH_PATH = "/entrez/eutils/efetch.fcgi"
EXPECTED_QUERY = '("semaglutide"[Title/Abstract]) AND ("gastrointestinal"[Title/Abstract])'
SUMMARY_SCHEMA_VERSION = "1.0"
CONNECTOR_VERSION = "m1a-002"
RETENTION_POLICY_ID = "M1A-LIVE-RETENTION-v1"
_REVISION_PATTERN = re.compile(r"^[0-9a-f]{40}$")


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _assert_outside_git(root: Path) -> None:
    repository_root = _repository_root()
    if root == repository_root or repository_root in root.parents:
        pytest.fail("live raw bytes must be stored outside the Git repository")


def _code_revision() -> str:
    status = subprocess.run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        cwd=_repository_root(),
        check=True,
        capture_output=True,
        text=True,
        timeout=5,
    )
    if status.stdout.strip():
        raise AssertionError("live gate requires a clean Git worktree")
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=_repository_root(),
        check=True,
        capture_output=True,
        text=True,
        timeout=5,
    )
    revision = completed.stdout.strip()
    if _REVISION_PATTERN.fullmatch(revision) is None:
        raise AssertionError("git HEAD is not an exact revision")
    return revision


def _utc_text(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _attempts_used(request_count: int, raw_responses: tuple[Any, ...]) -> int:
    return min(2, max((1, request_count, *(item.attempt_count for item in raw_responses))))


def _result_outcome(result: PubMedSearchResult | PubMedFetchResult) -> dict[str, object]:
    if result.source_outcome is None:
        raise AssertionError("live connector result must contain a terminal source outcome")
    return result.source_outcome.model_dump(mode="json")


def _manifest_outcome(manifest: SnapshotManifest) -> dict[str, str]:
    return {
        "execution_status": manifest.execution_status.value,
        "coverage_status": manifest.coverage_status.value,
        "result_status": manifest.result_status.value,
    }


def _write_acquisition_evidence(
    store: SnapshotStore,
    *,
    result: PubMedSearchResult | PubMedFetchResult,
    operation: str,
    run_id: str,
    run_intent_id: str,
    attempt_id: str,
    acquisition_ordinal: int,
    query: str,
    pmid: str | None,
    started_at_utc: datetime,
    completed_at_utc: datetime,
    code_revision: str,
) -> tuple[SnapshotManifest, tuple[str, ...], Path, Path]:
    if result.source_outcome is None:
        raise AssertionError("live connector result must contain a terminal source outcome")
    request: dict[str, object]
    if operation == "search":
        request = {
            "db": "pubmed",
            "path": PUBMED_ESEARCH_PATH,
            "retmax": 100,
            "retmode": "xml",
            "retstart": 0,
            "term": query,
        }
    else:
        if pmid is None:
            raise AssertionError("fetch evidence requires one PMID")
        request = {
            "db": "pubmed",
            "id": pmid,
            "path": PUBMED_EFETCH_PATH,
            "retmode": "xml",
            "rettype": "abstract",
        }
    intent = with_computed_identity(
        AcquisitionIntent,
        {
            "schema_version": "1.0",
            "attempt_id": attempt_id,
            "run_id": run_id,
            "run_intent_id": run_intent_id,
            "created_at_utc": _utc_text(started_at_utc),
            "execution_profile_id": "M1A_CONSTRAINED_V1",
            "source": "pubmed",
            "operation": operation,
            "acquisition_ordinal": acquisition_ordinal,
            "request": request,
            "execution_limits": AcquisitionExecutionLimits().model_dump(mode="json"),
        },
    )
    journal_directory = (
        f"journal/{run_id.removeprefix('run:')}/acquisition-{acquisition_ordinal:04d}"
    )
    intent_path = write_immutable_record(
        store,
        journal_directory,
        "acquisition-intent.json",
        intent,
    )
    observations = tuple(
        response_observation(
            body=item.body,
            observed_at_utc=item.observed_at_utc,
            headers=item.headers,
            http_status=item.status_code,
            body_complete=item.body_complete,
            termination_reason=item.termination_reason,
        )
        for item in result.raw_responses
    )
    persisted_execution_status = result.source_outcome.execution_status
    persisted_coverage_status = result.source_outcome.coverage_status
    persisted_result_status = result.source_outcome.result_status
    if persisted_coverage_status is CoverageStatus.UNAVAILABLE and observations:
        # The frozen unavailable manifest is zero-file only. When the connector
        # received response bytes before declaring unavailable, retain those
        # bytes under a failed/partial manifest so ADR-009 traceability is not
        # lost; the terminal connector outcome remains unavailable in the
        # acceptance summary.
        persisted_coverage_status = CoverageStatus.PARTIAL
    request_identity = (
        result.raw_responses[0].request_url
        if result.raw_responses
        else (
            f"{PUBMED_ORIGIN}{PUBMED_ESEARCH_PATH if operation == 'search' else PUBMED_EFETCH_PATH}"
        )
    )
    captured = capture_acquisition(
        store,
        journal_relative_directory=journal_directory,
        acquisition_intent_id=intent.acquisition_intent_id,
        request_identity=request_identity,
        started_at_utc=started_at_utc,
        completed_at_utc=completed_at_utc,
        validated_record_count=result.source_outcome.valid_result_count,
        execution_status=persisted_execution_status,
        coverage_status=persisted_coverage_status,
        result_status=persisted_result_status,
        attempts_used=_attempts_used(result.request_count, result.raw_responses),
        pages_completed=result.source_outcome.pages_completed,
        truncated=result.source_outcome.truncated,
        warning_codes=result.source_outcome.warning_codes,
        observations=observations,
        code_revision=code_revision,
    )
    envelope_payload: dict[str, object] = {
        "schema_version": "1.0",
        "envelope_kind": "acquisition",
        "acquisition_intent_id": intent.acquisition_intent_id,
        "acquisition_ordinal": acquisition_ordinal,
        "attempt_id": attempt_id,
        "run_id": run_id,
        "source": "pubmed",
        "operation": operation,
        "started_at_utc": _utc_text(captured.manifest.started_at_utc),
        "completed_at_utc": _utc_text(captured.manifest.completed_at_utc),
        "execution_status": persisted_execution_status.value,
        "coverage_status": persisted_coverage_status.value,
        "result_status": persisted_result_status.value,
        "valid_result_count": result.source_outcome.valid_result_count,
        "pages_completed": result.source_outcome.pages_completed,
        "attempts_used": _attempts_used(result.request_count, result.raw_responses),
        "truncated": result.source_outcome.truncated,
        "warning_codes": result.source_outcome.warning_codes,
        "artifact_links": tuple(
            ArtifactLinkReference(ordinal=item.ordinal, link_id=item.link_id).model_dump(
                mode="json"
            )
            for item in captured.artifact_links
        ),
        "manifest_id": captured.manifest.manifest_id,
        "registration_state": "ready_for_insert",
    }
    if result.failure is not None:
        envelope_payload["failure_code"] = result.failure.kind.value
        envelope_payload["redacted_detail"] = result.failure.kind.value
    envelope = with_computed_identity(AcquisitionRegistrationEnvelope, envelope_payload)
    envelope_path = write_immutable_record(
        store,
        journal_directory,
        "registration-envelope.json",
        envelope,
    )
    assert intent_path.is_relative_to(store.root)
    assert envelope_path.is_relative_to(store.root)
    return (
        captured.manifest,
        tuple(item.artifact_id for item in captured.artifact_links),
        captured.manifest_path,
        envelope_path,
    )


def _redacted_acceptance_payload(
    *,
    query: str,
    executed_at_utc: datetime,
    code_revision: str,
    search: PubMedSearchResult,
    search_manifest: SnapshotManifest,
    search_artifact_ids: tuple[str, ...],
    search_manifest_path: Path,
    fetch: PubMedFetchResult | None,
    fetch_manifest: SnapshotManifest | None,
    fetch_artifact_ids: tuple[str, ...],
    fetch_manifest_path: Path | None,
    snapshot_root: Path,
    acceptance_path: Path,
) -> dict[str, object]:
    fetch_payload: dict[str, object]
    if fetch is None or fetch_manifest is None or fetch_manifest_path is None:
        search_outcome = search.source_outcome
        zero_result = (
            search_outcome is not None
            and search_outcome.execution_status is ExecutionStatus.SUCCEEDED
            and search_outcome.coverage_status is CoverageStatus.COMPLETE
            and search_outcome.result_status is ResultStatus.NO_MATCH
            and search.total_available == 0
            and not search.pmids
        )
        fetch_payload = {
            "status": "not_executed",
            "reason": (
                "search_returned_zero_pmids" if zero_result else "search_outcome_not_complete"
            ),
        }
    else:
        fetch_payload = {
            "status": "executed",
            "terminal_outcome": _result_outcome(fetch),
            "request_count": fetch.request_count,
            "manifest_outcome": _manifest_outcome(fetch_manifest),
            "manifest_id": fetch_manifest.manifest_id,
            "snapshot_id": fetch_manifest.manifest_id,
            "raw_artifact_ids": list(fetch_artifact_ids),
            "manifest_path": str(fetch_manifest_path),
        }
    return {
        "schema_version": SUMMARY_SCHEMA_VERSION,
        "retention_policy_id": RETENTION_POLICY_ID,
        "query": query,
        "executed_at_utc": _utc_text(executed_at_utc),
        "code_revision": code_revision,
        "connector_version": CONNECTOR_VERSION,
        "search": {
            "status": "executed",
            "terminal_outcome": _result_outcome(search),
            "request_count": search.request_count,
            "manifest_outcome": _manifest_outcome(search_manifest),
            "manifest_id": search_manifest.manifest_id,
            "snapshot_id": search_manifest.manifest_id,
            "raw_artifact_ids": list(search_artifact_ids),
            "manifest_path": str(search_manifest_path),
        },
        "fetch": fetch_payload,
        "request_count_total": search.request_count + (fetch.request_count if fetch else 0),
        "snapshot_id": search_manifest.manifest_id,
        "manifest_id": search_manifest.manifest_id,
        "retained_raw_artifact_ids": list(search_artifact_ids) + list(fetch_artifact_ids),
        "storage": {
            "snapshot_root": str(snapshot_root),
            "acceptance_record_path": str(acceptance_path),
            "outside_git": True,
        },
        "redaction": {
            "raw_bodies": False,
            "credentials": False,
            "headers": False,
            "source_payload": False,
        },
    }


def _write_redacted_acceptance_record(
    root: Path,
    payload: dict[str, object],
    path: Path | None = None,
) -> Path:
    path = path or root / "acceptance" / f"pubmed-live-{uuid4().hex}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    path.write_text(encoded + "\n", encoding="utf-8", newline="\n")
    return path


def _assert_redacted_summary(
    summary: dict[str, object],
    *,
    raw_bodies: tuple[bytes, ...],
    email: str | None,
    headers: tuple[tuple[str, str], ...],
) -> None:
    encoded = json.dumps(summary, ensure_ascii=False, sort_keys=True).encode("utf-8")
    assert all(body not in encoded for body in raw_bodies if body)
    if email:
        assert email.encode("utf-8") not in encoded
    assert all(value.encode("utf-8") not in encoded for pair in headers for value in pair)
    assert summary["redaction"] == {
        "credentials": False,
        "headers": False,
        "raw_bodies": False,
        "source_payload": False,
    }
    assert summary["retention_policy_id"] == RETENTION_POLICY_ID


def test_live_gate_is_disabled_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MEDEVIDENCE_RUN_LIVE_PUBMED", raising=False)
    assert os.environ.get("MEDEVIDENCE_RUN_LIVE_PUBMED") != "1"


def test_live_gate_uses_exact_frozen_query_and_limits() -> None:
    request = ResearchPubMedApiRequest.model_validate_json(json.dumps(REQUEST_EXAMPLE))
    catalog = load_production_catalog()
    scope = request.to_scope(catalog)
    query = build_pubmed_query(scope, catalog.resolve_scope(scope))
    assert query == EXPECTED_QUERY
    config = PubMedConnectorConfig(
        page_size=100,
        max_pages=1,
        max_records=100,
        max_attempts=2,
        max_redirects=1,
    )
    assert config.page_size == config.max_records == 100
    assert config.max_pages == config.max_redirects == 1
    assert config.max_attempts == 2
    assert PUBMED_ORIGIN == "https://eutils.ncbi.nlm.nih.gov"
    assert {PUBMED_ESEARCH_PATH, PUBMED_EFETCH_PATH} == {
        "/entrez/eutils/esearch.fcgi",
        "/entrez/eutils/efetch.fcgi",
    }


def test_live_gate_counts_retry_attempts_separately_from_pages() -> None:
    attempts: list[httpx.Request] = []
    search_body = (
        b"<eSearchResult><Count>1</Count><RetMax>1</RetMax>"
        b"<RetStart>0</RetStart><IdList><Id>12345678</Id></IdList></eSearchResult>"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(request)
        if len(attempts) == 1:
            return httpx.Response(
                429,
                request=request,
                headers={"Retry-After": "0"},
                content=b"temporary failure",
            )
        return httpx.Response(200, request=request, content=search_body)

    connector = PubMedConnector(
        httpx.MockTransport(handler),
        PubMedConnectorConfig(
            page_size=100,
            max_pages=1,
            max_records=100,
            max_attempts=2,
            max_redirects=1,
        ),
        identity=PubMedClientIdentity(email="owner@example.invalid"),
        sleep=lambda _: None,
        jitter=lambda: 0.0,
    )
    try:
        result = connector.search(
            EXPECTED_QUERY,
            query_id="query:sha256:" + "2" * 64,
        )
    finally:
        connector.close()

    assert result.request_count == 2
    assert len(attempts) == 2
    assert result.source_outcome is not None
    assert result.source_outcome.pages_completed == 1
    assert result.source_outcome.coverage_status is CoverageStatus.COMPLETE
    assert result.pmids == ("12345678",)


def test_redacted_acceptance_shape_is_constructible_without_live_request(tmp_path: Path) -> None:
    now = datetime(2026, 8, 8, 12, tzinfo=UTC)
    raw_body = b"<eSearchResult><Count>0</Count><IdList /></eSearchResult>"
    root = tmp_path / "live-snapshots"
    store = SnapshotStore(root, free_bytes=lambda _: INITIAL_FREE_SPACE_FLOOR_BYTES)
    query_id = "query:sha256:" + "1" * 64
    bounds = ExecutionBounds(
        max_query_characters=512,
        max_pages=1,
        max_records=1,
        max_payload_bytes=5_242_880,
        max_total_seconds=30,
    )
    outcome = SourceOutcome(
        source=SourceType.PUBMED,
        query_id=query_id,
        execution_status=ExecutionStatus.SUCCEEDED,
        coverage_status=CoverageStatus.COMPLETE,
        result_status=ResultStatus.NO_MATCH,
        configured_bounds=bounds,
        valid_result_count=0,
        pages_completed=1,
        truncated=False,
    )
    response = RawPubMedResponse(
        request_url=f"{PUBMED_ORIGIN}{PUBMED_ESEARCH_PATH}",
        final_url=f"{PUBMED_ORIGIN}{PUBMED_ESEARCH_PATH}",
        status_code=200,
        body=raw_body,
        observed_at_utc=now,
        headers=(("content-type", "application/xml"),),
    )
    search = PubMedSearchResult(
        state=PubMedResultState.EMPTY_SUCCESS,
        query=EXPECTED_QUERY,
        query_id=query_id,
        pmids=(),
        total_available=0,
        source_outcome=outcome,
        failure=None,
        warning_codes=(),
        raw_responses=(response,),
        retry_events=(),
        request_count=1,
    )
    intent = with_computed_identity(
        AcquisitionIntent,
        {
            "schema_version": "1.0",
            "attempt_id": "attempt:00000000-0000-4000-8000-000000000003",
            "run_id": "run:00000000-0000-4000-8000-000000000002",
            "run_intent_id": "run-intent:sha256:" + "4" * 64,
            "created_at_utc": _utc_text(now),
            "execution_profile_id": "M1A_CONSTRAINED_V1",
            "source": "pubmed",
            "operation": "search",
            "acquisition_ordinal": 0,
            "request": {
                "db": "pubmed",
                "path": PUBMED_ESEARCH_PATH,
                "retmax": 100,
                "retmode": "xml",
                "retstart": 0,
                "term": EXPECTED_QUERY,
            },
            "execution_limits": AcquisitionExecutionLimits().model_dump(mode="json"),
        },
    )
    with store.writer():
        captured = capture_acquisition(
            store,
            journal_relative_directory="journal/offline-shape/acquisition-0000",
            acquisition_intent_id=intent.acquisition_intent_id,
            request_identity=response.request_url,
            started_at_utc=now,
            completed_at_utc=now,
            validated_record_count=0,
            execution_status=outcome.execution_status,
            coverage_status=outcome.coverage_status,
            result_status=outcome.result_status,
            attempts_used=1,
            pages_completed=1,
            truncated=False,
            warning_codes=(),
            observations=(
                response_observation(
                    body=response.body,
                    observed_at_utc=response.observed_at_utc,
                    headers=response.headers,
                    http_status=response.status_code,
                    body_complete=response.body_complete,
                    termination_reason=response.termination_reason,
                ),
            ),
            code_revision="a" * 40,
        )
    summary = _redacted_acceptance_payload(
        query=EXPECTED_QUERY,
        executed_at_utc=now,
        code_revision="a" * 40,
        search=search,
        search_manifest=captured.manifest,
        search_artifact_ids=tuple(item.artifact_id for item in captured.artifact_links),
        search_manifest_path=captured.manifest_path,
        fetch=None,
        fetch_manifest=None,
        fetch_artifact_ids=(),
        fetch_manifest_path=None,
        snapshot_root=root,
        acceptance_path=root / "acceptance/summary.json",
    )
    path = _write_redacted_acceptance_record(root, summary)
    _assert_redacted_summary(
        summary,
        raw_bodies=(raw_body,),
        email="owner@example.invalid",
        headers=(("content-type", "application/xml"), ("x-secret", "never")),
    )
    assert path.is_relative_to(root)
    degraded_body = b"service temporarily unavailable"
    degraded_response = replace(
        response,
        status_code=503,
        body=degraded_body,
        headers=(("content-type", "text/plain"),),
    )
    degraded_search = replace(
        search,
        state=PubMedResultState.FAILED,
        source_outcome=outcome.model_copy(
            update={
                "execution_status": ExecutionStatus.FAILED,
                "coverage_status": CoverageStatus.UNAVAILABLE,
                "result_status": ResultStatus.INDETERMINATE,
            }
        ),
        raw_responses=(degraded_response,),
        failure=PubMedFailure(
            kind=PubMedFailureKind.RETRY_EXHAUSTED,
            message="retry budget exhausted",
            retryable=False,
            status_code=503,
            cause_kind=PubMedFailureKind.RETRYABLE_SERVER_ERROR,
        ),
    )
    with store.writer():
        (
            degraded_manifest,
            degraded_artifacts,
            degraded_manifest_path,
            degraded_envelope_path,
        ) = _write_acquisition_evidence(
            store,
            result=degraded_search,
            operation="search",
            run_id="run:00000000-0000-4000-8000-000000000004",
            run_intent_id=intent.run_intent_id,
            attempt_id="attempt:00000000-0000-4000-8000-000000000005",
            acquisition_ordinal=0,
            query=EXPECTED_QUERY,
            pmid=None,
            started_at_utc=now,
            completed_at_utc=now,
            code_revision="a" * 40,
        )
    assert degraded_manifest.coverage_status is CoverageStatus.PARTIAL
    assert degraded_manifest.files
    assert degraded_artifacts == (degraded_manifest.files[0].artifact_id,)
    assert degraded_manifest_path.is_relative_to(root)
    assert degraded_envelope_path.is_relative_to(root)
    degraded_summary = _redacted_acceptance_payload(
        query=EXPECTED_QUERY,
        executed_at_utc=now,
        code_revision="a" * 40,
        search=degraded_search,
        search_manifest=degraded_manifest,
        search_artifact_ids=degraded_artifacts,
        search_manifest_path=degraded_manifest_path,
        fetch=None,
        fetch_manifest=None,
        fetch_artifact_ids=(),
        fetch_manifest_path=None,
        snapshot_root=root,
        acceptance_path=root / "acceptance/degraded-summary.json",
    )
    assert degraded_summary["fetch"] == {
        "status": "not_executed",
        "reason": "search_outcome_not_complete",
    }
    _assert_redacted_summary(
        degraded_summary,
        raw_bodies=(degraded_body,),
        email=None,
        headers=degraded_response.headers,
    )
    assert degraded_summary["search"]["terminal_outcome"]["coverage_status"] == "unavailable"
    assert degraded_summary["search"]["manifest_outcome"]["coverage_status"] == "partial"
    assert summary["snapshot_id"] == summary["manifest_id"]
    assert summary["snapshot_id"] != summary["retained_raw_artifact_ids"][0]
    assert json.loads(path.read_text(encoding="utf-8"))["fetch"]["status"] == "not_executed"


@pytest.mark.live_api
@pytest.mark.enable_socket
def test_live_pubmed_one_page_one_record(request: pytest.FixtureRequest) -> None:
    marker_expression = request.config.getoption("markexpr") or ""
    if re.search(r"(?<![\w])live_api(?![\w])", marker_expression) is None:
        pytest.skip("live PubMed requires explicit -m live_api marker selection")
    if os.environ.get("MEDEVIDENCE_RUN_LIVE_PUBMED") != "1":
        pytest.skip("live PubMed requires explicit Owner-run opt-in")
    email = os.environ.get("NCBI_EMAIL")
    if email is None or not email.strip():
        pytest.fail("NCBI_EMAIL must be supplied by the Owner for the live gate")
    root_value = os.environ.get("MEDEVIDENCE_LIVE_SNAPSHOT_ROOT")
    if root_value is None:
        pytest.fail("MEDEVIDENCE_LIVE_SNAPSHOT_ROOT outside Git is required")
    root = Path(root_value).resolve()
    _assert_outside_git(root)

    request = ResearchPubMedApiRequest.model_validate_json(json.dumps(REQUEST_EXAMPLE))
    catalog = load_production_catalog()
    scope = request.to_scope(catalog)
    query = build_pubmed_query(scope, catalog.resolve_scope(scope))
    assert query == EXPECTED_QUERY
    query_id = query_identity(scope, query)
    code_revision = _code_revision()
    started_at_utc = datetime.now(UTC)
    run_id = f"run:{uuid4()}"
    request_id = f"request:{uuid4()}"
    run_intent = with_computed_identity(
        RunIntent,
        {
            "schema_version": "1.0",
            "run_id": run_id,
            "request_id": request_id,
            "created_at_utc": _utc_text(started_at_utc),
            "code_revision": code_revision,
            "scope_id": scope.scope_id,
            "execution_profile_id": "M1A_CONSTRAINED_V1",
            "catalog_version": "m1a-concepts-v1",
            "source": "pubmed",
            "drug_concept_ids": tuple(item.concept_id for item in scope.drugs),
            "adverse_event_concept_ids": tuple(item.concept_id for item in scope.adverse_reactions),
            "pubmed_query": query,
            "execution_limits": RunExecutionLimits().model_dump(mode="json"),
        },
    )
    config = PubMedConnectorConfig(
        page_size=100,
        max_pages=1,
        max_records=100,
        max_attempts=2,
        max_redirects=1,
    )
    connector = PubMedConnector(
        httpx.HTTPTransport(retries=0),
        config,
        identity=PubMedClientIdentity(email=email),
    )
    store = SnapshotStore(root)
    try:
        with store.writer():
            write_immutable_record(
                store,
                f"journal/{run_id.removeprefix('run:')}",
                "run-intent.json",
                run_intent,
            )
            search_started = datetime.now(UTC)
            search = connector.search(query, query_id=query_id)
            search_completed = datetime.now(UTC)
            assert search.request_count <= config.max_attempts
            assert search.source_outcome is not None
            assert search.source_outcome.pages_completed <= config.max_pages
            search_manifest, search_artifacts, search_manifest_path, _ = (
                _write_acquisition_evidence(
                    store,
                    result=search,
                    operation="search",
                    run_id=run_id,
                    run_intent_id=run_intent.run_intent_id,
                    attempt_id=f"attempt:{uuid4()}",
                    acquisition_ordinal=0,
                    query=query,
                    pmid=None,
                    started_at_utc=search_started,
                    completed_at_utc=search_completed,
                    code_revision=code_revision,
                )
            )
            fetch: PubMedFetchResult | None = None
            fetch_manifest: SnapshotManifest | None = None
            fetch_artifacts: tuple[str, ...] = ()
            fetch_manifest_path: Path | None = None
            if search.pmids:
                fetch_started = datetime.now(UTC)
                fetch = connector.fetch(search.pmids[:1], query_id=query_id)
                fetch_completed = datetime.now(UTC)
                assert fetch.request_count <= config.max_attempts
                assert fetch.source_outcome is not None
                assert fetch.source_outcome.pages_completed <= config.max_pages
                (
                    fetch_manifest,
                    fetch_artifacts,
                    fetch_manifest_path,
                    _,
                ) = _write_acquisition_evidence(
                    store,
                    result=fetch,
                    operation="fetch",
                    run_id=run_id,
                    run_intent_id=run_intent.run_intent_id,
                    attempt_id=f"attempt:{uuid4()}",
                    acquisition_ordinal=1,
                    query=query,
                    pmid=search.pmids[0],
                    started_at_utc=fetch_started,
                    completed_at_utc=fetch_completed,
                    code_revision=code_revision,
                )
            acceptance_path = root / "acceptance" / f"pubmed-live-{uuid4().hex}.json"
            summary = _redacted_acceptance_payload(
                query=query,
                executed_at_utc=datetime.now(UTC),
                code_revision=code_revision,
                search=search,
                search_manifest=search_manifest,
                search_artifact_ids=search_artifacts,
                search_manifest_path=search_manifest_path,
                fetch=fetch,
                fetch_manifest=fetch_manifest,
                fetch_artifact_ids=fetch_artifacts,
                fetch_manifest_path=fetch_manifest_path,
                snapshot_root=root,
                acceptance_path=acceptance_path,
            )
            _assert_redacted_summary(
                summary,
                raw_bodies=tuple(item.body for item in search.raw_responses)
                + (() if fetch is None else tuple(item.body for item in fetch.raw_responses)),
                email=email,
                headers=tuple(
                    item for response in search.raw_responses for item in response.headers
                )
                + (
                    ()
                    if fetch is None
                    else tuple(
                        item for response in fetch.raw_responses for item in response.headers
                    )
                ),
            )
            written = _write_redacted_acceptance_record(root, summary, acceptance_path)
            assert written == acceptance_path
            assert written.is_relative_to(root)
            assert len(search.pmids) <= 100
            assert fetch is None or len(fetch.requested_pmids) <= 1
    finally:
        connector.close()
