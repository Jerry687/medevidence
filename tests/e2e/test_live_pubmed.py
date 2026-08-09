"""Separately authorized, single-shot live PubMed smoke test (disabled by default)."""

from __future__ import annotations

import ast
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit
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
from medevidence.connectors.pubmed.parsing import InvalidPubMedXmlError, parse_search_page
from medevidence.connectors.pubmed.policy import PubMedConnectorConfig
from medevidence.domain import (
    CoverageStatus,
    ExecutionBounds,
    ExecutionStatus,
    ResultStatus,
    SourceOutcome,
    SourceType,
    derive_identity,
)
from medevidence.ingestion import (
    AcquisitionIntent,
    AcquisitionRegistrationEnvelope,
    ArtifactLink,
    RunIntent,
    SnapshotManifest,
    capture_acquisition,
    replay_manifest,
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
_HEX64_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_SHA256_ID_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
_LIVE_MARKER_PATTERN = re.compile(r"(?<![\w])live_api(?![\w])")
_COMPLETE_URL_PATTERN = re.compile(r"https?://", re.IGNORECASE)
_FROZEN_LIVE_REVISION = "09cc42838475a4c1bab62050fbfeac14c5dd6761"
_RECOVERY_SCHEMA_VERSION = "1.0"
_RECOVERY_WORK_ITEM = "M1A-LIVE-RUN-001-RECOVERY-AND-REDACTION-HARNESS-FIX"
_FORBIDDEN_SUMMARY_KEYS = frozenset(
    {
        "abstract",
        "abstracts",
        "authorization",
        "authorizations",
        "bodies",
        "body",
        "clientidentities",
        "clientidentity",
        "cookie",
        "cookies",
        "credential",
        "credentials",
        "email",
        "emails",
        "finalurl",
        "finalurls",
        "header",
        "headers",
        "password",
        "passwords",
        "rawbodies",
        "rawbody",
        "requesturl",
        "requesturls",
        "sourcepayload",
        "sourcepayloads",
        "token",
        "tokens",
    }
)
_REDACTION_FLAGS = {
    "contains_credentials": False,
    "contains_headers": False,
    "contains_raw_body": False,
    "contains_source_payload": False,
}
_REDACTION_FLAG_KEYS = frozenset(
    {
        "containscredentials",
        "containsheaders",
        "containsrawbody",
        "containssourcepayload",
    }
)
_HARNESS_MESSAGE = "live PubMed harness failure (redacted)"
_HARNESS_CODES = frozenset(
    {
        "LIVE_CLOSE_FAILED",
        "LIVE_EXECUTION_FAILED",
        "LIVE_FETCH_BOUNDS",
        "LIVE_INTERNAL",
        "LIVE_MARKER_CONTRACT",
        "LIVE_OUTCOME_MISSING",
        "LIVE_OWNER_EMAIL_MISSING",
        "LIVE_QUERY_MISMATCH",
        "LIVE_REDACTION_REJECTED",
        "LIVE_RESULT_INVALID",
        "LIVE_ROOT_INVALID",
        "LIVE_SEARCH_BOUNDS",
        "LIVE_STORAGE_INVALID",
        "LIVE_WRITE_INVALID",
    }
)
_SENSITIVE_FUNCTIONS = frozenset(
    {
        "_attempts_used",
        "_execute_sensitive_live_pubmed",
        "_recover_live_run_record",
        "_redacted_acceptance_payload",
        "_result_outcome",
        "_sensitive_disclosure_probe",
        "_write_acquisition_evidence",
    }
)
_LIVE_TEST_FORBIDDEN_NAMES = frozenset(
    {
        "body",
        "connector",
        "email",
        "fetch",
        "final_url",
        "headers",
        "raw_responses",
        "request_url",
        "result",
        "search",
        "summary",
    }
)
_RAW_BEARING_IDENTIFIERS = _LIVE_TEST_FORBIDDEN_NAMES - {"summary"}
_SANITIZED_RESULT_FIELDS = frozenset(
    {
        "acceptance_record_label",
        "acceptance_record_written",
        "fetch_executed",
        "fetch_manifest_id",
        "fetch_pages_completed",
        "fetch_request_count",
        "fetched_pmid_count",
        "request_count_total",
        "search_coverage_status",
        "search_execution_status",
        "search_manifest_id",
        "search_pages_completed",
        "search_request_count",
        "search_result_status",
        "selected_pmid_count",
    }
)


class _LivePubMedHarnessError(RuntimeError):
    """Test-only failure whose externally visible state is fixed and sanitized."""

    __slots__ = ()

    def __init__(self, code: object = "LIVE_INTERNAL") -> None:
        safe_code = code if isinstance(code, str) and code in _HARNESS_CODES else "LIVE_INTERNAL"
        super().__init__(safe_code)

    def __str__(self) -> str:
        return _HARNESS_MESSAGE

    def __repr__(self) -> str:
        return "_LivePubMedHarnessError(redacted)"


@dataclass(frozen=True, slots=True)
class _SanitizedLiveResult:
    acceptance_record_written: bool
    acceptance_record_label: str
    request_count_total: int
    search_request_count: int
    fetch_request_count: int
    search_pages_completed: int
    fetch_pages_completed: int
    selected_pmid_count: int
    fetched_pmid_count: int
    search_execution_status: str
    search_coverage_status: str
    search_result_status: str
    fetch_executed: bool
    search_manifest_id: str
    fetch_manifest_id: str


class _RedactedRecordError(ValueError):
    """Sanitized structural-validation failure with no payload interpolation."""


def _redacted_record_failure() -> _RedactedRecordError:
    return _RedactedRecordError("redacted record failed structural validation")


def _harness_failure(code: object = "LIVE_INTERNAL") -> _LivePubMedHarnessError:
    return _LivePubMedHarnessError(code)


def _compact_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _live_marker_selected(marker_expression: str) -> bool:
    return _LIVE_MARKER_PATTERN.search(marker_expression) is not None


def _assert_outside_git(root: Path) -> None:
    repository_root = _repository_root()
    if root == repository_root or repository_root in root.parents:
        raise _harness_failure("LIVE_STORAGE_INVALID")


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
    __tracebackhide__ = True
    return min(2, max((1, request_count, *(item.attempt_count for item in raw_responses))))


def _result_outcome(result: PubMedSearchResult | PubMedFetchResult) -> dict[str, object]:
    __tracebackhide__ = True
    if result.source_outcome is None:
        raise _harness_failure("LIVE_OUTCOME_MISSING")
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
    __tracebackhide__ = True
    if result.source_outcome is None:
        raise _harness_failure("LIVE_OUTCOME_MISSING")
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
            raise _harness_failure("LIVE_WRITE_INVALID")
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
    if not intent_path.is_relative_to(store.root) or not envelope_path.is_relative_to(store.root):
        raise _harness_failure("LIVE_WRITE_INVALID")
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
    __tracebackhide__ = True
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
        "redaction": dict(_REDACTION_FLAGS),
    }


def _write_redacted_acceptance_record(
    root: Path,
    payload: dict[str, object],
    path: Path | None = None,
) -> Path:
    _validate_redacted_summary(payload)
    path = path or root / "acceptance" / f"pubmed-live-{uuid4().hex}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    path.write_text(encoded + "\n", encoding="utf-8", newline="\n")
    return path


def _require_exact_keys(value: object, expected: set[str]) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != expected:
        raise _redacted_record_failure()
    if not all(isinstance(key, str) for key in value):
        raise _redacted_record_failure()
    return value


def _reject_prohibited_summary_content(value: object) -> None:
    __tracebackhide__ = True
    if isinstance(value, dict):
        for key, nested in value.items():
            if not isinstance(key, str):
                raise _redacted_record_failure()
            normalized = _compact_key(key)
            if normalized == "redaction":
                if key != "redaction" or nested != _REDACTION_FLAGS:
                    raise _redacted_record_failure()
                continue
            if normalized in _FORBIDDEN_SUMMARY_KEYS or normalized in _REDACTION_FLAG_KEYS:
                raise _redacted_record_failure()
            _reject_prohibited_summary_content(nested)
        return
    if isinstance(value, (list, tuple)):
        for nested in value:
            _reject_prohibited_summary_content(nested)
        return
    if isinstance(value, str) and _COMPLETE_URL_PATTERN.search(value):
        raise _redacted_record_failure()
    if not isinstance(value, (str, int, bool, type(None))):
        raise _redacted_record_failure()


def _require_nonnegative_int(value: object, *, maximum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise _redacted_record_failure()
    if maximum is not None and value > maximum:
        raise _redacted_record_failure()
    return value


def _require_sha256_ids(value: object, *, maximum: int) -> list[str]:
    if not isinstance(value, list) or len(value) > maximum:
        raise _redacted_record_failure()
    if not all(isinstance(item, str) and _SHA256_ID_PATTERN.fullmatch(item) for item in value):
        raise _redacted_record_failure()
    return value


def _validate_outcome(value: object) -> SourceOutcome:
    try:
        outcome = SourceOutcome.model_validate_json(json.dumps(value, separators=(",", ":")))
    except Exception:
        raise _redacted_record_failure() from None
    if outcome.model_dump(mode="json") != value:
        raise _redacted_record_failure()
    return outcome


def _validate_manifest_outcome(value: object) -> dict[str, object]:
    outcome = _require_exact_keys(
        value,
        {"coverage_status", "execution_status", "result_status"},
    )
    if (
        outcome["execution_status"],
        outcome["coverage_status"],
        outcome["result_status"],
    ) not in {
        ("succeeded", "complete", "matches"),
        ("succeeded", "complete", "no_match"),
        ("succeeded", "partial", "matches"),
        ("succeeded", "partial", "indeterminate"),
        ("failed", "partial", "matches"),
        ("failed", "partial", "indeterminate"),
        ("failed", "unavailable", "indeterminate"),
    }:
        raise _redacted_record_failure()
    return outcome


def _validate_executed_operation(value: object) -> int:
    operation = _require_exact_keys(
        value,
        {
            "manifest_id",
            "manifest_outcome",
            "manifest_path",
            "raw_artifact_ids",
            "request_count",
            "snapshot_id",
            "status",
            "terminal_outcome",
        },
    )
    if operation["status"] != "executed":
        raise _redacted_record_failure()
    terminal = _validate_outcome(operation["terminal_outcome"])
    persisted = _validate_manifest_outcome(operation["manifest_outcome"])
    manifest_id = operation["manifest_id"]
    if (
        not isinstance(manifest_id, str)
        or _SHA256_ID_PATTERN.fullmatch(manifest_id) is None
        or operation["snapshot_id"] != manifest_id
    ):
        raise _redacted_record_failure()
    _require_sha256_ids(operation["raw_artifact_ids"], maximum=4)
    if (
        not isinstance(operation["manifest_path"], str)
        or not Path(operation["manifest_path"]).is_absolute()
    ):
        raise _redacted_record_failure()
    request_count = _require_nonnegative_int(operation["request_count"], maximum=2)
    if terminal.execution_status.value != operation["terminal_outcome"]["execution_status"]:
        raise _redacted_record_failure()
    if persisted["execution_status"] not in {"succeeded", "failed"}:
        raise _redacted_record_failure()
    return request_count


def _validate_redacted_summary(summary: dict[str, object]) -> None:
    """Validate the closed acceptance shape without receiving sensitive material."""

    __tracebackhide__ = True
    _reject_prohibited_summary_content(summary)
    top = _require_exact_keys(
        summary,
        {
            "code_revision",
            "connector_version",
            "executed_at_utc",
            "fetch",
            "manifest_id",
            "query",
            "redaction",
            "request_count_total",
            "retained_raw_artifact_ids",
            "retention_policy_id",
            "schema_version",
            "search",
            "snapshot_id",
            "storage",
        },
    )
    if (
        top["schema_version"] != SUMMARY_SCHEMA_VERSION
        or top["retention_policy_id"] != RETENTION_POLICY_ID
        or top["connector_version"] != CONNECTOR_VERSION
        or top["query"] != EXPECTED_QUERY
        or not isinstance(top["code_revision"], str)
        or _REVISION_PATTERN.fullmatch(top["code_revision"]) is None
    ):
        raise _redacted_record_failure()
    try:
        executed_at = datetime.fromisoformat(str(top["executed_at_utc"]).replace("Z", "+00:00"))
    except ValueError:
        raise _redacted_record_failure() from None
    if executed_at.utcoffset() != UTC.utcoffset(executed_at):
        raise _redacted_record_failure()

    search = _require_exact_keys(
        top["search"],
        {
            "manifest_id",
            "manifest_outcome",
            "manifest_path",
            "raw_artifact_ids",
            "request_count",
            "snapshot_id",
            "status",
            "terminal_outcome",
        },
    )
    search_count = _validate_executed_operation(search)
    fetch = top["fetch"]
    if isinstance(fetch, dict) and fetch.get("status") == "executed":
        fetch_count = _validate_executed_operation(fetch)
    else:
        not_executed = _require_exact_keys(fetch, {"reason", "status"})
        if not_executed["status"] != "not_executed" or not_executed["reason"] not in {
            "search_outcome_not_complete",
            "search_returned_zero_pmids",
        }:
            raise _redacted_record_failure()
        fetch_count = 0

    if _require_nonnegative_int(top["request_count_total"], maximum=4) != (
        search_count + fetch_count
    ):
        raise _redacted_record_failure()
    retained_ids = _require_sha256_ids(top["retained_raw_artifact_ids"], maximum=8)
    search_ids = search["raw_artifact_ids"]
    fetch_ids = [] if fetch_count == 0 else fetch["raw_artifact_ids"]
    if retained_ids != search_ids + fetch_ids:
        raise _redacted_record_failure()
    if top["manifest_id"] != search["manifest_id"] or top["snapshot_id"] != top["manifest_id"]:
        raise _redacted_record_failure()

    storage = _require_exact_keys(
        top["storage"],
        {"acceptance_record_path", "outside_git", "snapshot_root"},
    )
    if storage["outside_git"] is not True:
        raise _redacted_record_failure()
    for key in ("acceptance_record_path", "snapshot_root"):
        if not isinstance(storage[key], str) or not Path(storage[key]).is_absolute():
            raise _redacted_record_failure()
    if top["redaction"] != _REDACTION_FLAGS:
        raise _redacted_record_failure()


def _validate_sanitized_live_result(value: _SanitizedLiveResult) -> None:
    if value.acceptance_record_written is not True:
        raise _harness_failure("LIVE_RESULT_INVALID")
    if (
        re.fullmatch(r"acceptance/pubmed-live-[0-9a-f]{32}\.json", value.acceptance_record_label)
        is None
    ):
        raise _harness_failure("LIVE_RESULT_INVALID")
    counts = (
        value.request_count_total,
        value.search_request_count,
        value.fetch_request_count,
        value.search_pages_completed,
        value.fetch_pages_completed,
        value.selected_pmid_count,
        value.fetched_pmid_count,
    )
    if any(isinstance(item, bool) or not isinstance(item, int) or item < 0 for item in counts):
        raise _harness_failure("LIVE_RESULT_INVALID")
    if (
        value.search_request_count > 2
        or value.fetch_request_count > 2
        or value.request_count_total != value.search_request_count + value.fetch_request_count
        or value.search_pages_completed > 1
        or value.fetch_pages_completed > 1
        or value.selected_pmid_count > 100
        or value.fetched_pmid_count > 1
        or value.fetch_executed != (value.fetch_request_count > 0)
    ):
        raise _harness_failure("LIVE_RESULT_INVALID")
    if (
        value.search_execution_status,
        value.search_coverage_status,
        value.search_result_status,
    ) not in {
        ("succeeded", "complete", "matches"),
        ("succeeded", "complete", "no_match"),
        ("succeeded", "partial", "matches"),
        ("succeeded", "partial", "indeterminate"),
        ("failed", "partial", "matches"),
        ("failed", "partial", "indeterminate"),
        ("failed", "unavailable", "indeterminate"),
    }:
        raise _harness_failure("LIVE_RESULT_INVALID")
    if _SHA256_ID_PATTERN.fullmatch(value.search_manifest_id) is None:
        raise _harness_failure("LIVE_RESULT_INVALID")
    if value.fetch_executed:
        if _SHA256_ID_PATTERN.fullmatch(value.fetch_manifest_id) is None:
            raise _harness_failure("LIVE_RESULT_INVALID")
    elif value.fetch_manifest_id:
        raise _harness_failure("LIVE_RESULT_INVALID")


def _first_executable_statement(node: ast.FunctionDef) -> ast.stmt | None:
    statements = node.body
    if (
        statements
        and isinstance(statements[0], ast.Expr)
        and isinstance(statements[0].value, ast.Constant)
        and isinstance(statements[0].value.value, str)
    ):
        statements = statements[1:]
    return statements[0] if statements else None


def _is_tracebackhide_assignment(node: ast.stmt | None) -> bool:
    return (
        isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id == "__tracebackhide__"
        and isinstance(node.value, ast.Constant)
        and node.value.value is True
    )


def _assigned_names(node: ast.Assign | ast.AnnAssign) -> set[str]:
    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
    return {target.id for target in targets if isinstance(target, ast.Name)}


def _is_getattr_pytest_fail(value: ast.AST, pytest_aliases: set[str]) -> bool:
    return (
        isinstance(value, ast.Call)
        and isinstance(value.func, ast.Name)
        and value.func.id == "getattr"
        and len(value.args) >= 2
        and isinstance(value.args[0], ast.Name)
        and value.args[0].id in pytest_aliases
        and isinstance(value.args[1], ast.Constant)
        and value.args[1].value == "fail"
    )


def _module_aliases(
    module: ast.Module,
    function_names: frozenset[str],
) -> tuple[frozenset[str], frozenset[str], dict[str, str]]:
    pytest_aliases = {"pytest"}
    fail_aliases: set[str] = set()
    function_aliases: dict[str, str] = {}
    for node in module.body:
        if isinstance(node, ast.Import):
            pytest_aliases.update(
                item.asname or item.name for item in node.names if item.name == "pytest"
            )
        elif isinstance(node, ast.ImportFrom) and node.module == "pytest":
            fail_aliases.update(
                item.asname or item.name for item in node.names if item.name == "fail"
            )
    changed = True
    while changed:
        changed = False
        for node in module.body:
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue
            value = node.value
            assigned = _assigned_names(node)
            if (
                isinstance(value, ast.Attribute)
                and isinstance(value.value, ast.Name)
                and value.value.id in pytest_aliases
                and value.attr == "fail"
            ) or _is_getattr_pytest_fail(value, pytest_aliases):
                before = len(fail_aliases)
                fail_aliases.update(assigned)
                changed = changed or len(fail_aliases) != before
            if isinstance(value, ast.Name):
                if value.id in pytest_aliases:
                    before = len(pytest_aliases)
                    pytest_aliases.update(assigned)
                    changed = changed or len(pytest_aliases) != before
                if value.id in fail_aliases:
                    before = len(fail_aliases)
                    fail_aliases.update(assigned)
                    changed = changed or len(fail_aliases) != before
                target = function_aliases.get(value.id, value.id)
                if target in function_names:
                    for name in assigned:
                        if function_aliases.get(name) != target:
                            function_aliases[name] = target
                            changed = True
    return frozenset(pytest_aliases), frozenset(fail_aliases), function_aliases


def _function_references_pytest(
    node: ast.FunctionDef,
    *,
    module_pytest_aliases: frozenset[str],
    module_fail_aliases: frozenset[str],
) -> bool:
    pytest_aliases = set(module_pytest_aliases)
    fail_aliases = set(module_fail_aliases)
    for child in ast.walk(node):
        if isinstance(child, ast.Import):
            pytest_aliases.update(
                item.asname or item.name for item in child.names if item.name == "pytest"
            )
        elif isinstance(child, ast.ImportFrom) and child.module == "pytest":
            fail_aliases.update(
                item.asname or item.name for item in child.names if item.name == "fail"
            )
    changed = True
    while changed:
        changed = False
        for child in ast.walk(node):
            if not isinstance(child, (ast.Assign, ast.AnnAssign)):
                continue
            value = child.value
            assigned = _assigned_names(child)
            if isinstance(value, ast.Name) and value.id in pytest_aliases:
                before = len(pytest_aliases)
                pytest_aliases.update(assigned)
                changed = changed or len(pytest_aliases) != before
            is_fail_reference = (
                (
                    isinstance(value, ast.Attribute)
                    and isinstance(value.value, ast.Name)
                    and value.value.id in pytest_aliases
                    and value.attr == "fail"
                )
                or (isinstance(value, ast.Name) and value.id in fail_aliases)
                or _is_getattr_pytest_fail(value, pytest_aliases)
            )
            if is_fail_reference:
                before = len(fail_aliases)
                fail_aliases.update(assigned)
                changed = changed or len(fail_aliases) != before
    for child in ast.walk(node):
        if (
            isinstance(child, ast.Name)
            and isinstance(child.ctx, ast.Load)
            and child.id in pytest_aliases
        ):
            return True
        if (
            isinstance(child, ast.Attribute)
            and isinstance(child.value, ast.Name)
            and child.value.id in pytest_aliases
            and child.attr == "fail"
        ):
            return True
        if (
            isinstance(child, ast.Name)
            and isinstance(child.ctx, ast.Load)
            and child.id in fail_aliases
        ):
            return True
    return False


def _local_calls(
    node: ast.FunctionDef,
    *,
    function_names: frozenset[str],
    module_function_aliases: dict[str, str],
) -> frozenset[str]:
    aliases = dict(module_function_aliases)
    changed = True
    while changed:
        changed = False
        for child in ast.walk(node):
            if not isinstance(child, (ast.Assign, ast.AnnAssign)):
                continue
            value = child.value
            if not isinstance(value, ast.Name):
                continue
            target = aliases.get(value.id, value.id)
            if target not in function_names:
                continue
            for name in _assigned_names(child):
                if aliases.get(name) != target:
                    aliases[name] = target
                    changed = True
    return frozenset(
        aliases.get(child.func.id, child.func.id)
        for child in ast.walk(node)
        if isinstance(child, ast.Call)
        and isinstance(child.func, ast.Name)
        and aliases.get(child.func.id, child.func.id) in function_names
    )


def _reachable_local_helpers(
    functions: dict[str, ast.FunctionDef],
    *,
    entrypoint_name: str,
    module_function_aliases: dict[str, str],
) -> frozenset[str]:
    if entrypoint_name not in functions:
        raise _redacted_record_failure()
    function_names = frozenset(functions)
    reachable = {entrypoint_name}
    pending = [entrypoint_name]
    while pending:
        current = pending.pop()
        for called in _local_calls(
            functions[current],
            function_names=function_names,
            module_function_aliases=module_function_aliases,
        ):
            if called not in reachable:
                reachable.add(called)
                pending.append(called)
    return frozenset(reachable)


def _handles_raw_bearing_values(node: ast.FunctionDef) -> bool:
    identifiers = {
        child.id.casefold() for child in ast.walk(node) if isinstance(child, ast.Name)
    } | {child.attr.casefold() for child in ast.walk(node) if isinstance(child, ast.Attribute)}
    return bool(identifiers & _RAW_BEARING_IDENTIFIERS)


def _enforce_sensitive_source_contract(
    source: str,
    *,
    additional_sensitive_names: frozenset[str],
    entrypoint_name: str | None,
    live_test_name: str | None,
) -> None:
    try:
        module = ast.parse(source)
    except SyntaxError:
        raise _redacted_record_failure() from None
    parsed_functions = {
        node.name: node
        for node in module.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    if any(not isinstance(node, ast.FunctionDef) for node in parsed_functions.values()):
        raise _redacted_record_failure()
    functions = {
        name: node for name, node in parsed_functions.items() if isinstance(node, ast.FunctionDef)
    }
    function_names = frozenset(functions)
    module_pytest_aliases, module_fail_aliases, module_function_aliases = _module_aliases(
        module,
        function_names,
    )
    reachable_names = (
        frozenset()
        if entrypoint_name is None
        else _reachable_local_helpers(
            functions,
            entrypoint_name=entrypoint_name,
            module_function_aliases=module_function_aliases,
        )
    )
    inspected_names = additional_sensitive_names | reachable_names
    if not inspected_names <= function_names:
        raise _redacted_record_failure()
    for name in inspected_names:
        node = functions[name]
        inferred_sensitive = name in additional_sensitive_names or _handles_raw_bearing_values(node)
        if inferred_sensitive and not _is_tracebackhide_assignment(
            _first_executable_statement(node)
        ):
            raise _redacted_record_failure()
        if inferred_sensitive and any(isinstance(child, ast.Assert) for child in ast.walk(node)):
            raise _redacted_record_failure()
        if _function_references_pytest(
            node,
            module_pytest_aliases=module_pytest_aliases,
            module_fail_aliases=module_fail_aliases,
        ):
            raise _redacted_record_failure()
    if live_test_name is None:
        return
    live_test = functions.get(live_test_name)
    if live_test is None:
        raise _redacted_record_failure()
    identifiers = {
        child.id.casefold() for child in ast.walk(live_test) if isinstance(child, ast.Name)
    } | {child.attr.casefold() for child in ast.walk(live_test) if isinstance(child, ast.Attribute)}
    if identifiers & _LIVE_TEST_FORBIDDEN_NAMES:
        raise _redacted_record_failure()
    assertions = [child for child in ast.walk(live_test) if isinstance(child, ast.Assert)]
    if not assertions:
        raise _redacted_record_failure()
    for assertion in assertions:
        assertion_names = {
            child.id for child in ast.walk(assertion.test) if isinstance(child, ast.Name)
        }
        if assertion_names != {"sanitized"}:
            raise _redacted_record_failure()
        sanitized_fields = {
            child.attr
            for child in ast.walk(assertion.test)
            if isinstance(child, ast.Attribute)
            and isinstance(child.value, ast.Name)
            and child.value.id == "sanitized"
        }
        if not sanitized_fields or not sanitized_fields <= _SANITIZED_RESULT_FIELDS:
            raise _redacted_record_failure()


def _reconstructed_invalid_xml_outcome(query_id: str) -> SourceOutcome:
    failure_id = derive_identity(
        "failure",
        {
            "source": SourceType.PUBMED,
            "query_id": query_id,
            "kind": PubMedFailureKind.INVALID_XML,
            "cause_kind": None,
            "status_code": None,
            "pages_completed": 0,
        },
    )
    config = PubMedConnectorConfig(
        page_size=100,
        max_pages=1,
        max_records=100,
        max_attempts=2,
        max_redirects=1,
    )
    return SourceOutcome(
        source=SourceType.PUBMED,
        query_id=query_id,
        execution_status=ExecutionStatus.FAILED,
        coverage_status=CoverageStatus.UNAVAILABLE,
        result_status=ResultStatus.INDETERMINATE,
        configured_bounds=ExecutionBounds(
            max_query_characters=config.max_query_characters,
            max_pages=config.max_pages,
            max_records=config.max_records,
            max_payload_bytes=config.max_payload_bytes,
            max_total_seconds=config.total_deadline_seconds,
        ),
        valid_result_count=0,
        pages_completed=0,
        truncated=False,
        warning_codes=("pubmed_source_unavailable",),
        failure_id=failure_id,
    )


def _validate_recovery_record(payload: dict[str, object]) -> None:
    _reject_prohibited_summary_content(payload)
    record = _require_exact_keys(
        payload,
        {
            "acceptance_record_originally_written",
            "canonical_manifest_ids",
            "code_revision",
            "connector_version",
            "directly_proved_request_count",
            "evidence_paths",
            "evidence_recovered_from_immutable_artifacts",
            "fetch_execution",
            "harness_failure",
            "live_command_exit_code",
            "medical_source_execution_occurred",
            "milestone_disposition",
            "persisted_manifest_outcome",
            "persisted_registration_envelope_outcome",
            "raw_artifact_ids",
            "reconstructed_terminal_connector_outcome",
            "redaction",
            "registration_envelope_ids",
            "rerun_performed",
            "retention_policy_id",
            "run_intent_id",
            "run_times_utc",
            "schema_version",
            "work_item",
        },
    )
    if (
        record["schema_version"] != _RECOVERY_SCHEMA_VERSION
        or record["work_item"] != _RECOVERY_WORK_ITEM
        or record["retention_policy_id"] != RETENTION_POLICY_ID
        or record["connector_version"] != CONNECTOR_VERSION
        or record["medical_source_execution_occurred"] is not True
        or record["live_command_exit_code"] != 1
        or record["acceptance_record_originally_written"] is not False
        or record["harness_failure"] != "redaction_header_substring_false_positive"
        or record["rerun_performed"] is not False
        or record["evidence_recovered_from_immutable_artifacts"] is not True
        or record["directly_proved_request_count"] != 1
        or record["code_revision"] != _FROZEN_LIVE_REVISION
        or record["redaction"] != _REDACTION_FLAGS
    ):
        raise _redacted_record_failure()
    outcome = _validate_outcome(record["reconstructed_terminal_connector_outcome"])
    if (
        outcome.execution_status is not ExecutionStatus.FAILED
        or outcome.coverage_status is not CoverageStatus.UNAVAILABLE
        or outcome.result_status is not ResultStatus.INDETERMINATE
        or outcome.pages_completed != 0
        or outcome.valid_result_count != 0
        or outcome.truncated
    ):
        raise _redacted_record_failure()
    for key in ("persisted_manifest_outcome", "persisted_registration_envelope_outcome"):
        if _validate_manifest_outcome(record[key]) != {
            "execution_status": "failed",
            "coverage_status": "partial",
            "result_status": "indeterminate",
        }:
            raise _redacted_record_failure()
    _require_sha256_ids(record["raw_artifact_ids"], maximum=4)
    _require_sha256_ids(record["canonical_manifest_ids"], maximum=1)
    envelope_ids = record["registration_envelope_ids"]
    if (
        not isinstance(envelope_ids, list)
        or len(envelope_ids) != 1
        or not isinstance(envelope_ids[0], str)
        or not envelope_ids[0].startswith("registration-envelope:acquisition:sha256:")
        or _SHA256_ID_PATTERN.fullmatch(envelope_ids[0].split(":", 2)[2]) is None
    ):
        raise _redacted_record_failure()
    if (
        not isinstance(record["run_intent_id"], str)
        or not record["run_intent_id"].startswith("run-intent:sha256:")
        or _HEX64_PATTERN.fullmatch(record["run_intent_id"].split(":", 2)[2]) is None
    ):
        raise _redacted_record_failure()
    times = _require_exact_keys(
        record["run_times_utc"],
        {
            "response_observed_at_utc",
            "run_intent_created_at_utc",
            "search_completed_at_utc",
            "search_started_at_utc",
        },
    )
    parsed_times: list[datetime] = []
    for key in (
        "run_intent_created_at_utc",
        "search_started_at_utc",
        "response_observed_at_utc",
        "search_completed_at_utc",
    ):
        try:
            parsed = datetime.fromisoformat(str(times[key]).replace("Z", "+00:00"))
        except ValueError:
            raise _redacted_record_failure() from None
        if parsed.utcoffset() != UTC.utcoffset(parsed):
            raise _redacted_record_failure()
        parsed_times.append(parsed)
    if parsed_times != sorted(parsed_times):
        raise _redacted_record_failure()
    fetch = _require_exact_keys(record["fetch_execution"], {"proof", "status"})
    if fetch != {
        "status": "not_executed",
        "proof": "failed_first_search_path_and_no_acquisition_0001",
    }:
        raise _redacted_record_failure()
    milestone = _require_exact_keys(
        record["milestone_disposition"],
        {
            "live_gate_acceptance_unresolved",
            "m1a_live_acceptance_pass",
            "no_rerun_authorized",
        },
    )
    if milestone != {
        "live_gate_acceptance_unresolved": True,
        "m1a_live_acceptance_pass": False,
        "no_rerun_authorized": True,
    }:
        raise _redacted_record_failure()
    paths = _require_exact_keys(
        record["evidence_paths"],
        {
            "acquisition_intent",
            "artifact_link",
            "manifest",
            "raw_artifact",
            "registration_envelope",
            "run_intent",
        },
    )
    if not all(
        isinstance(path, str) and not Path(path).is_absolute() and ".." not in Path(path).parts
        for path in paths.values()
    ):
        raise _redacted_record_failure()


def _recover_live_run_record(root: Path) -> dict[str, object]:
    """Validate one immutable failed live run and reconstruct its redacted outcome."""

    __tracebackhide__ = True
    root = root.resolve(strict=True)
    _assert_outside_git(root)
    if any(path.is_symlink() for path in root.rglob("*")):
        raise _redacted_record_failure()
    journal_root = root / "journal"
    run_directories = [path for path in journal_root.iterdir() if path.is_dir()]
    if len(run_directories) != 1:
        raise _redacted_record_failure()
    run_directory = run_directories[0]
    acquisition_directory = run_directory / "acquisition-0000"
    run_intent_path = run_directory / "run-intent.json"
    acquisition_intent_path = acquisition_directory / "acquisition-intent.json"
    artifact_link_path = acquisition_directory / "artifact-link-0000.json"
    envelope_path = acquisition_directory / "registration-envelope.json"
    try:
        run_intent = RunIntent.from_json_bytes(run_intent_path.read_bytes())
        acquisition_intent = AcquisitionIntent.from_json_bytes(acquisition_intent_path.read_bytes())
        artifact_link = ArtifactLink.from_json_bytes(artifact_link_path.read_bytes())
        envelope = AcquisitionRegistrationEnvelope.from_json_bytes(envelope_path.read_bytes())
    except Exception:
        raise _redacted_record_failure() from None

    manifest_digest = envelope.manifest_id.removeprefix("sha256:")
    manifest_path = (
        root / "pubmed" / "manifests" / "sha256" / manifest_digest[:2] / (manifest_digest + ".json")
    )
    try:
        manifest_raw = manifest_path.read_bytes()
        manifest = SnapshotManifest.from_json_bytes(manifest_raw)
    except Exception:
        raise _redacted_record_failure() from None
    if len(manifest.files) != 1:
        raise _redacted_record_failure()
    raw_path = root / manifest.files[0].relative_path

    allowed_paths = {
        ".m1a-constrained-v1.lock",
        run_intent_path.relative_to(root).as_posix(),
        acquisition_intent_path.relative_to(root).as_posix(),
        artifact_link_path.relative_to(root).as_posix(),
        envelope_path.relative_to(root).as_posix(),
        manifest_path.relative_to(root).as_posix(),
        raw_path.relative_to(root).as_posix(),
    }
    recovery_path = root / "acceptance" / "pubmed-live-run-001-recovery.json"
    if recovery_path.exists():
        allowed_paths.add(recovery_path.relative_to(root).as_posix())
    actual_paths = {path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()}
    if actual_paths != allowed_paths:
        raise _redacted_record_failure()

    request = ResearchPubMedApiRequest.model_validate_json(json.dumps(REQUEST_EXAMPLE))
    catalog = load_production_catalog()
    scope = request.to_scope(catalog)
    query = build_pubmed_query(scope, catalog.resolve_scope(scope))
    query_id = query_identity(scope, query)
    if (
        query != EXPECTED_QUERY
        or run_intent.code_revision != _FROZEN_LIVE_REVISION
        or run_intent.scope_id != scope.scope_id
        or run_intent.pubmed_query != query
        or run_intent.execution_limits != RunExecutionLimits()
        or run_intent.run_id.removeprefix("run:") != run_directory.name
        or acquisition_intent.run_id != run_intent.run_id
        or acquisition_intent.run_intent_id != run_intent.run_intent_id
        or acquisition_intent.operation != "search"
        or acquisition_intent.acquisition_ordinal != 0
        or acquisition_intent.execution_limits != AcquisitionExecutionLimits()
        or acquisition_intent.request.model_dump(mode="json")
        != {
            "db": "pubmed",
            "path": PUBMED_ESEARCH_PATH,
            "retmax": 100,
            "retmode": "xml",
            "retstart": 0,
            "term": EXPECTED_QUERY,
        }
    ):
        raise _redacted_record_failure()

    parsed_identity = urlsplit(manifest.request_identity)
    identity_query = parse_qs(parsed_identity.query, keep_blank_values=True)
    if (
        parsed_identity.scheme != "https"
        or parsed_identity.netloc != "eutils.ncbi.nlm.nih.gov"
        or parsed_identity.path != PUBMED_ESEARCH_PATH
        or parsed_identity.fragment
        or set(identity_query) != {"db", "retmax", "retmode", "retstart", "term", "tool"}
        or identity_query["db"] != ["pubmed"]
        or identity_query["retmax"] != ["100"]
        or identity_query["retmode"] != ["xml"]
        or identity_query["retstart"] != ["0"]
        or identity_query["term"] != [EXPECTED_QUERY]
        or identity_query["tool"] != ["medevidence"]
    ):
        raise _redacted_record_failure()

    if (
        manifest.manifest_id != envelope.manifest_id
        or manifest.acquisition_intent_id != acquisition_intent.acquisition_intent_id
        or manifest.code_revision != _FROZEN_LIVE_REVISION
        or manifest.started_at_utc != acquisition_intent.created_at_utc
        or manifest.execution_status is not ExecutionStatus.FAILED
        or manifest.coverage_status is not CoverageStatus.PARTIAL
        or manifest.result_status is not ResultStatus.INDETERMINATE
        or manifest.record_count != 0
        or manifest.pages_completed != 0
        or manifest.attempts_used != 1
        or manifest.truncated
        or manifest.warning_codes != ("pubmed_source_unavailable",)
        or artifact_link.acquisition_intent_id != acquisition_intent.acquisition_intent_id
        or artifact_link.ordinal != 0
        or envelope.acquisition_intent_id != acquisition_intent.acquisition_intent_id
        or envelope.run_id != run_intent.run_id
        or envelope.operation != "search"
        or envelope.acquisition_ordinal != 0
        or envelope.failure_code != "invalid_xml"
        or envelope.redacted_detail != "invalid_xml"
        or envelope.execution_status is not manifest.execution_status
        or envelope.coverage_status is not manifest.coverage_status
        or envelope.result_status is not manifest.result_status
        or envelope.valid_result_count != manifest.record_count
        or envelope.pages_completed != manifest.pages_completed
        or envelope.attempts_used != manifest.attempts_used
        or envelope.truncated != manifest.truncated
        or envelope.warning_codes != manifest.warning_codes
        or len(envelope.artifact_links) != 1
        or envelope.artifact_links[0].ordinal != artifact_link.ordinal
        or envelope.artifact_links[0].link_id != artifact_link.link_id
    ):
        raise _redacted_record_failure()
    try:
        replayed = replay_manifest(
            manifest_raw,
            SnapshotStore(root),
            expected_manifest_id=manifest.manifest_id,
            expected_links=(artifact_link,),
            expected_validated_record_count=0,
        )
        raw = raw_path.read_bytes()
    except Exception:
        raise _redacted_record_failure() from None
    if (
        replayed != manifest
        or artifact_link.artifact_id != f"sha256:{sha256(raw).hexdigest()}"
        or artifact_link.byte_size != len(raw)
        or artifact_link.http_status != 200
        or not artifact_link.body_complete
    ):
        raise _redacted_record_failure()
    try:
        parse_search_page(raw, expected_retstart=0, max_items=100)
    except InvalidPubMedXmlError:
        pass
    except Exception:
        raise _redacted_record_failure() from None
    else:
        raise _redacted_record_failure()

    reconstructed_outcome = _reconstructed_invalid_xml_outcome(query_id)
    if (run_directory / "acquisition-0001").exists():
        raise _redacted_record_failure()
    if reconstructed_outcome.pages_completed != 0 or reconstructed_outcome.result_status is not (
        ResultStatus.INDETERMINATE
    ):
        raise _redacted_record_failure()
    if not (
        run_intent.created_at_utc
        <= acquisition_intent.created_at_utc
        <= artifact_link.observed_at_utc
        <= manifest.completed_at_utc
    ):
        raise _redacted_record_failure()

    relative_paths = {
        "run_intent": run_intent_path.relative_to(root).as_posix(),
        "acquisition_intent": acquisition_intent_path.relative_to(root).as_posix(),
        "artifact_link": artifact_link_path.relative_to(root).as_posix(),
        "registration_envelope": envelope_path.relative_to(root).as_posix(),
        "manifest": manifest_path.relative_to(root).as_posix(),
        "raw_artifact": raw_path.relative_to(root).as_posix(),
    }
    payload: dict[str, object] = {
        "schema_version": _RECOVERY_SCHEMA_VERSION,
        "work_item": _RECOVERY_WORK_ITEM,
        "retention_policy_id": RETENTION_POLICY_ID,
        "connector_version": CONNECTOR_VERSION,
        "medical_source_execution_occurred": True,
        "live_command_exit_code": 1,
        "acceptance_record_originally_written": False,
        "harness_failure": "redaction_header_substring_false_positive",
        "rerun_performed": False,
        "evidence_recovered_from_immutable_artifacts": True,
        "reconstructed_terminal_connector_outcome": reconstructed_outcome.model_dump(mode="json"),
        "persisted_manifest_outcome": _manifest_outcome(manifest),
        "persisted_registration_envelope_outcome": {
            "execution_status": envelope.execution_status.value,
            "coverage_status": envelope.coverage_status.value,
            "result_status": envelope.result_status.value,
        },
        "directly_proved_request_count": 1,
        "raw_artifact_ids": [artifact_link.artifact_id],
        "canonical_manifest_ids": [manifest.manifest_id],
        "registration_envelope_ids": [envelope.registration_envelope_id],
        "run_intent_id": run_intent.run_intent_id,
        "code_revision": run_intent.code_revision,
        "run_times_utc": {
            "run_intent_created_at_utc": _utc_text(run_intent.created_at_utc),
            "search_started_at_utc": _utc_text(acquisition_intent.created_at_utc),
            "response_observed_at_utc": _utc_text(artifact_link.observed_at_utc),
            "search_completed_at_utc": _utc_text(manifest.completed_at_utc),
        },
        "fetch_execution": {
            "status": "not_executed",
            "proof": "failed_first_search_path_and_no_acquisition_0001",
        },
        "evidence_paths": relative_paths,
        "milestone_disposition": {
            "live_gate_acceptance_unresolved": True,
            "m1a_live_acceptance_pass": False,
            "no_rerun_authorized": True,
        },
        "redaction": dict(_REDACTION_FLAGS),
    }
    _validate_recovery_record(payload)
    return payload


def _write_recovery_record_no_clobber(root: Path, payload: dict[str, object]) -> tuple[Path, str]:
    _validate_recovery_record(payload)
    path = root.resolve() / "acceptance" / "pubmed-live-run-001-recovery.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    raw = (encoded + "\n").encode("utf-8")
    try:
        with path.open("xb") as handle:
            handle.write(raw)
    except FileExistsError:
        raise _redacted_record_failure() from None
    persisted = path.read_bytes()
    if persisted != raw:
        raise _redacted_record_failure()
    try:
        validated = json.loads(persisted)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise _redacted_record_failure() from None
    _validate_recovery_record(validated)
    return path, sha256(persisted).hexdigest()


def test_live_gate_is_disabled_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MEDEVIDENCE_RUN_LIVE_PUBMED", raising=False)
    assert os.environ.get("MEDEVIDENCE_RUN_LIVE_PUBMED") != "1"


def test_live_gate_requires_explicit_marker_selection() -> None:
    assert not _live_marker_selected("")
    assert _live_marker_selected("live_api")
    assert _live_marker_selected("live_api and not slow")


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


def _synthetic_redacted_summary(root: Path) -> dict[str, object]:
    manifest_id = "sha256:" + "a" * 64
    raw_artifact_id = "sha256:" + "3" * 64
    outcome = SourceOutcome(
        source=SourceType.PUBMED,
        query_id="query:sha256:" + "b" * 64,
        execution_status=ExecutionStatus.SUCCEEDED,
        coverage_status=CoverageStatus.COMPLETE,
        result_status=ResultStatus.NO_MATCH,
        configured_bounds=ExecutionBounds(
            max_query_characters=512,
            max_pages=1,
            max_records=100,
            max_payload_bytes=5_242_880,
            max_total_seconds=30,
        ),
        valid_result_count=0,
        pages_completed=1,
        truncated=False,
    )
    return {
        "schema_version": SUMMARY_SCHEMA_VERSION,
        "retention_policy_id": RETENTION_POLICY_ID,
        "query": EXPECTED_QUERY,
        "executed_at_utc": "2026-08-08T12:00:00.000000Z",
        "code_revision": "2" * 40,
        "connector_version": CONNECTOR_VERSION,
        "search": {
            "status": "executed",
            "terminal_outcome": outcome.model_dump(mode="json"),
            "request_count": 1,
            "manifest_outcome": {
                "execution_status": "succeeded",
                "coverage_status": "complete",
                "result_status": "no_match",
            },
            "manifest_id": manifest_id,
            "snapshot_id": manifest_id,
            "raw_artifact_ids": [raw_artifact_id],
            "manifest_path": str(root / "manifest.json"),
        },
        "fetch": {"status": "not_executed", "reason": "search_returned_zero_pmids"},
        "request_count_total": 1,
        "snapshot_id": manifest_id,
        "manifest_id": manifest_id,
        "retained_raw_artifact_ids": [raw_artifact_id],
        "storage": {
            "snapshot_root": str(root),
            "acceptance_record_path": str(root / "acceptance" / "summary.json"),
            "outside_git": True,
        },
        "redaction": dict(_REDACTION_FLAGS),
    }


def test_structural_redaction_allows_safe_rate_limit_value_collisions(tmp_path: Path) -> None:
    summary = _synthetic_redacted_summary(tmp_path.resolve())
    safe_rate_limit_metadata = {
        "x-ratelimit-limit": 3,
        "x-ratelimit-remaining": 2,
    }
    _reject_prohibited_summary_content(safe_rate_limit_metadata)
    _validate_redacted_summary(summary)


@pytest.mark.parametrize(
    "field",
    (
        "email",
        "E-MAILS",
        "header",
        "HEADERS",
        "authorization",
        "Authorizations",
        "cookie",
        "Cookies",
        "request_url",
        "Request-URLs",
        "final.url",
        "FINAL_URLS",
        "raw_body",
        "raw-bodies",
        "body",
        "Bodies",
        "abstract",
        "Abstracts",
        "source_payload",
        "SOURCE-PAYLOADS",
        "credential",
        "Credentials",
        "password",
        "Passwords",
        "token",
        "Tokens",
        "client_identity",
        "Client-Identities",
    ),
)
def test_structural_redaction_rejects_nested_sensitive_fields(
    tmp_path: Path,
    field: str,
) -> None:
    for depth in range(1, 4):
        candidate = json.loads(json.dumps(_synthetic_redacted_summary(tmp_path.resolve())))
        nested: dict[str, object] = candidate
        for index in range(depth):
            child: dict[str, object] = {}
            nested[f"safe_level_{index}"] = child
            nested = child
        nested[field] = "SYNTHETIC_PRIVATE_VALUE"
        with pytest.raises(_RedactedRecordError, match=r"^redacted record failed"):
            _validate_redacted_summary(candidate)


def test_structural_redaction_allows_only_exact_false_flag_schema() -> None:
    _reject_prohibited_summary_content({"redaction": dict(_REDACTION_FLAGS)})
    invalid_flags = dict(_REDACTION_FLAGS)
    invalid_flags["contains_headers"] = True
    with pytest.raises(_RedactedRecordError, match=r"^redacted record failed"):
        _reject_prohibited_summary_content({"redaction": invalid_flags})
    with pytest.raises(_RedactedRecordError, match=r"^redacted record failed"):
        _reject_prohibited_summary_content({"Redaction": dict(_REDACTION_FLAGS)})
    with pytest.raises(_RedactedRecordError, match=r"^redacted record failed"):
        _reject_prohibited_summary_content({"safe": {"contains-headers": False}})


def _sensitive_disclosure_probe() -> None:
    __tracebackhide__ = True
    synthetic_email = "DISCLOSURE_PROBE_OWNER_94731@example.invalid"
    synthetic_body = "DISCLOSURE_PROBE_RAW_BODY_6A7D9C2E"
    synthetic_header = "DISCLOSURE_PROBE_AUTHORIZATION_BEARER_0F4B8A1C"
    synthetic_complete_url = (
        "https://example.invalid/private/path?token=DISCLOSURE_PROBE_QUERY_51E2D7A9"
    )
    private_values = {
        "email": synthetic_email,
        "body": synthetic_body,
        "headers": {"authorization": synthetic_header},
        "request_url": synthetic_complete_url,
    }
    if private_values:
        raise _harness_failure("LIVE_REDACTION_REJECTED") from None


def test_redaction_failure_output_probe() -> None:
    if os.environ.get("MEDEVIDENCE_REDACTION_FAILURE_PROBE") != "1":
        pytest.skip("selected only by the offline redaction-output regression")
    _sensitive_disclosure_probe()


def test_pytest_failure_output_does_not_expose_nested_sentinels() -> None:
    sentinels = (
        "DISCLOSURE_PROBE_OWNER_94731@example.invalid",
        "DISCLOSURE_PROBE_RAW_BODY_6A7D9C2E",
        "DISCLOSURE_PROBE_AUTHORIZATION_BEARER_0F4B8A1C",
        "https://example.invalid/private/path?token=DISCLOSURE_PROBE_QUERY_51E2D7A9",
    )
    environment = os.environ.copy()
    environment["MEDEVIDENCE_REDACTION_FAILURE_PROBE"] = "1"
    for name in (
        "MEDEVIDENCE_RUN_LIVE_PUBMED",
        "MEDEVIDENCE_LIVE_SNAPSHOT_ROOT",
        "NCBI_EMAIL",
    ):
        environment.pop(name, None)
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            str(Path(__file__).resolve()),
            "-k",
            "test_redaction_failure_output_probe",
            "-vv",
            "--showlocals",
            "--disable-socket",
        ],
        cwd=_repository_root(),
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    captured = completed.stdout + completed.stderr
    assert completed.returncode == 1
    assert _HARNESS_MESSAGE in captured
    assert all(sentinel not in captured for sentinel in sentinels)
    assert "test_live_pubmed_one_page_one_record" not in captured


def test_live_harness_exception_has_only_fixed_safe_state() -> None:
    safe = _LivePubMedHarnessError("LIVE_REDACTION_REJECTED")
    collapsed = _LivePubMedHarnessError("DYNAMIC_PRIVATE_VALUE")
    assert safe.args == ("LIVE_REDACTION_REJECTED",)
    assert str(safe) == _HARNESS_MESSAGE
    assert repr(safe) == "_LivePubMedHarnessError(redacted)"
    assert safe.__dict__ == {}
    assert collapsed.args == ("LIVE_INTERNAL",)
    assert "DYNAMIC_PRIVATE_VALUE" not in repr(collapsed)


def test_sensitive_source_contract_blocks_disclosure_paths() -> None:
    source = Path(__file__).read_text(encoding="utf-8")
    assert frozenset(_SanitizedLiveResult.__dataclass_fields__) == _SANITIZED_RESULT_FIELDS
    _enforce_sensitive_source_contract(
        source,
        additional_sensitive_names=_SENSITIVE_FUNCTIONS,
        entrypoint_name="_execute_sensitive_live_pubmed",
        live_test_name="test_live_pubmed_one_page_one_record",
    )


def test_sensitive_source_checker_rejects_raw_assert_and_pytest_fail_regressions() -> None:
    direct_raw_assertion = """
def test_live_pubmed_one_page_one_record(request):
    result = connector.search("synthetic")
    assert result.raw_responses[0].body
"""
    with pytest.raises(_RedactedRecordError, match=r"^redacted record failed"):
        _enforce_sensitive_source_contract(
            direct_raw_assertion,
            additional_sensitive_names=frozenset(),
            entrypoint_name=None,
            live_test_name="test_live_pubmed_one_page_one_record",
        )
    helper_pytest_fail = """
def _probe():
    __tracebackhide__ = True
    pytest.fail(raw.body)
"""
    with pytest.raises(_RedactedRecordError, match=r"^redacted record failed"):
        _enforce_sensitive_source_contract(
            helper_pytest_fail,
            additional_sensitive_names=frozenset({"_probe"}),
            entrypoint_name=None,
            live_test_name=None,
        )


def test_sensitive_source_checker_rejects_unregistered_reachable_helper() -> None:
    unregistered_sensitive_helper = """
def _new_sensitive_helper(provider):
    return provider.body

def _execute_sensitive_live_pubmed():
    __tracebackhide__ = True
    _new_sensitive_helper(provider)
"""
    with pytest.raises(_RedactedRecordError, match=r"^redacted record failed"):
        _enforce_sensitive_source_contract(
            unregistered_sensitive_helper,
            additional_sensitive_names=frozenset(),
            entrypoint_name="_execute_sensitive_live_pubmed",
            live_test_name=None,
        )


@pytest.mark.parametrize(
    "source",
    (
        """
import pytest

def _local_module_alias_helper(provider):
    __tracebackhide__ = True
    p = pytest
    p.fail(provider.body)

def _execute_sensitive_live_pubmed():
    __tracebackhide__ = True
    _local_module_alias_helper(provider)
""",
        """
import pytest
p = pytest

def _module_alias_helper(provider):
    __tracebackhide__ = True
    p.fail(provider.body)

def _execute_sensitive_live_pubmed():
    __tracebackhide__ = True
    _module_alias_helper(provider)
""",
        """
import pytest

def _getattr_alias_helper(provider):
    __tracebackhide__ = True
    fail = getattr(pytest, "fail")
    fail(provider.body)

def _execute_sensitive_live_pubmed():
    __tracebackhide__ = True
    _getattr_alias_helper(provider)
""",
    ),
)
def test_sensitive_source_checker_rejects_all_pytest_alias_paths(source: str) -> None:
    with pytest.raises(_RedactedRecordError, match=r"^redacted record failed"):
        _enforce_sensitive_source_contract(
            source,
            additional_sensitive_names=frozenset(),
            entrypoint_name="_execute_sensitive_live_pubmed",
            live_test_name=None,
        )


def test_failed_live_evidence_recovery_is_typed_and_no_clobber(tmp_path: Path) -> None:
    now = datetime(2026, 8, 8, 23, 40, 56, tzinfo=UTC)
    root = (tmp_path / "m1a-pubmed-20260808T234054Z").resolve()
    store = SnapshotStore(root, free_bytes=lambda _: INITIAL_FREE_SPACE_FLOOR_BYTES)
    request = ResearchPubMedApiRequest.model_validate_json(json.dumps(REQUEST_EXAMPLE))
    catalog = load_production_catalog()
    scope = request.to_scope(catalog)
    query = build_pubmed_query(scope, catalog.resolve_scope(scope))
    query_id = query_identity(scope, query)
    run_id = "run:00000000-0000-4000-8000-000000000002"
    run_intent = with_computed_identity(
        RunIntent,
        {
            "schema_version": "1.0",
            "run_id": run_id,
            "request_id": "request:00000000-0000-4000-8000-000000000001",
            "created_at_utc": _utc_text(now),
            "code_revision": _FROZEN_LIVE_REVISION,
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
    invalid_body = b"<eSearchResult><Count>0</Count>"
    request_url = str(
        httpx.URL(
            PUBMED_ORIGIN + PUBMED_ESEARCH_PATH,
            params={
                "db": "pubmed",
                "term": query,
                "retmode": "xml",
                "retstart": "0",
                "retmax": "100",
                "tool": "medevidence",
            },
        )
    )
    raw_response = RawPubMedResponse(
        request_url=request_url,
        final_url=request_url,
        status_code=200,
        body=invalid_body,
        observed_at_utc=now,
        headers=(
            ("content-type", "application/xml"),
            ("x-ratelimit-limit", "3"),
            ("x-ratelimit-remaining", "2"),
        ),
    )
    outcome = _reconstructed_invalid_xml_outcome(query_id)
    failed_search = PubMedSearchResult(
        state=PubMedResultState.FAILED,
        query=query,
        query_id=query_id,
        pmids=(),
        total_available=None,
        source_outcome=outcome,
        failure=PubMedFailure(
            kind=PubMedFailureKind.INVALID_XML,
            message="synthetic malformed response",
            retryable=False,
        ),
        warning_codes=outcome.warning_codes,
        raw_responses=(raw_response,),
        retry_events=(),
        request_count=1,
    )
    with store.writer():
        write_immutable_record(
            store,
            f"journal/{run_id.removeprefix('run:')}",
            "run-intent.json",
            run_intent,
        )
        _write_acquisition_evidence(
            store,
            result=failed_search,
            operation="search",
            run_id=run_id,
            run_intent_id=run_intent.run_intent_id,
            attempt_id="attempt:00000000-0000-4000-8000-000000000003",
            acquisition_ordinal=0,
            query=query,
            pmid=None,
            started_at_utc=now,
            completed_at_utc=now,
            code_revision=_FROZEN_LIVE_REVISION,
        )
    recovery = _recover_live_run_record(root)
    _validate_recovery_record(recovery)
    written, digest = _write_recovery_record_no_clobber(root, recovery)
    assert written.is_relative_to(root)
    assert _HEX64_PATTERN.fullmatch(digest)
    with pytest.raises(_RedactedRecordError, match=r"^redacted record failed"):
        _write_recovery_record_no_clobber(root, recovery)


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
    _validate_redacted_summary(summary)
    assert path.is_relative_to(root)
    degraded_body = b"service temporarily unavailable"
    degraded_response = replace(
        response,
        status_code=503,
        body=degraded_body,
        headers=(("content-type", "text/plain"),),
    )
    degraded_failure_id = derive_identity(
        "failure",
        {
            "source": SourceType.PUBMED,
            "query_id": query_id,
            "kind": PubMedFailureKind.RETRY_EXHAUSTED,
            "cause_kind": PubMedFailureKind.RETRYABLE_SERVER_ERROR,
            "status_code": 503,
            "pages_completed": 0,
        },
    )
    degraded_search = replace(
        search,
        state=PubMedResultState.FAILED,
        source_outcome=SourceOutcome(
            source=SourceType.PUBMED,
            query_id=query_id,
            execution_status=ExecutionStatus.FAILED,
            coverage_status=CoverageStatus.UNAVAILABLE,
            result_status=ResultStatus.INDETERMINATE,
            configured_bounds=bounds,
            valid_result_count=0,
            pages_completed=0,
            truncated=False,
            warning_codes=("pubmed_source_unavailable",),
            failure_id=degraded_failure_id,
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
    _validate_redacted_summary(degraded_summary)
    assert degraded_summary["search"]["terminal_outcome"]["coverage_status"] == "unavailable"
    assert degraded_summary["search"]["manifest_outcome"]["coverage_status"] == "partial"
    assert summary["snapshot_id"] == summary["manifest_id"]
    assert summary["snapshot_id"] != summary["retained_raw_artifact_ids"][0]
    assert json.loads(path.read_text(encoding="utf-8"))["fetch"]["status"] == "not_executed"


def _execute_sensitive_live_pubmed() -> _SanitizedLiveResult:
    """Own live inputs and provider values, returning only a closed sanitized result."""

    __tracebackhide__ = True
    connector: PubMedConnector | None = None
    sanitized: _SanitizedLiveResult | None = None
    failure_code: object | None = None
    try:
        email = os.environ.get("NCBI_EMAIL")
        if email is None or not email.strip():
            raise _harness_failure("LIVE_OWNER_EMAIL_MISSING")
        root_value = os.environ.get("MEDEVIDENCE_LIVE_SNAPSHOT_ROOT")
        if root_value is None or not root_value.strip():
            raise _harness_failure("LIVE_ROOT_INVALID")
        root = Path(root_value).resolve()
        _assert_outside_git(root)

        api_request = ResearchPubMedApiRequest.model_validate_json(json.dumps(REQUEST_EXAMPLE))
        catalog = load_production_catalog()
        scope = api_request.to_scope(catalog)
        query = build_pubmed_query(scope, catalog.resolve_scope(scope))
        if query != EXPECTED_QUERY:
            raise _harness_failure("LIVE_QUERY_MISMATCH")
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
                "adverse_event_concept_ids": tuple(
                    item.concept_id for item in scope.adverse_reactions
                ),
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
            search_outcome = search.source_outcome
            if (
                search.request_count > config.max_attempts
                or search_outcome is None
                or search_outcome.pages_completed > config.max_pages
                or len(search.pmids) > config.max_records
            ):
                raise _harness_failure("LIVE_SEARCH_BOUNDS")
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
            fetch_outcome: SourceOutcome | None = None
            fetch_manifest: SnapshotManifest | None = None
            fetch_artifacts: tuple[str, ...] = ()
            fetch_manifest_path: Path | None = None
            if search.pmids:
                fetch_started = datetime.now(UTC)
                fetch = connector.fetch(search.pmids[:1], query_id=query_id)
                fetch_completed = datetime.now(UTC)
                fetch_outcome = fetch.source_outcome
                if (
                    fetch.request_count > config.max_attempts
                    or fetch_outcome is None
                    or fetch_outcome.pages_completed > config.max_pages
                    or len(fetch.requested_pmids) > 1
                ):
                    raise _harness_failure("LIVE_FETCH_BOUNDS")
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
            _validate_redacted_summary(summary)
            written = _write_redacted_acceptance_record(root, summary, acceptance_path)
            if written != acceptance_path or not written.is_relative_to(root):
                raise _harness_failure("LIVE_WRITE_INVALID")
            sanitized = _SanitizedLiveResult(
                acceptance_record_written=True,
                acceptance_record_label=written.relative_to(root).as_posix(),
                request_count_total=search.request_count + (fetch.request_count if fetch else 0),
                search_request_count=search.request_count,
                fetch_request_count=0 if fetch is None else fetch.request_count,
                search_pages_completed=search_outcome.pages_completed,
                fetch_pages_completed=0 if fetch_outcome is None else fetch_outcome.pages_completed,
                selected_pmid_count=len(search.pmids),
                fetched_pmid_count=0 if fetch is None else len(fetch.requested_pmids),
                search_execution_status=search_outcome.execution_status.value,
                search_coverage_status=search_outcome.coverage_status.value,
                search_result_status=search_outcome.result_status.value,
                fetch_executed=fetch is not None,
                search_manifest_id=search_manifest.manifest_id,
                fetch_manifest_id="" if fetch_manifest is None else fetch_manifest.manifest_id,
            )
            _validate_sanitized_live_result(sanitized)
    except _LivePubMedHarnessError as error:
        failure_code = error.args[0] if len(error.args) == 1 else "LIVE_INTERNAL"
    except Exception:
        failure_code = "LIVE_EXECUTION_FAILED"
    finally:
        if connector is not None:
            try:
                connector.close()
            except Exception:
                failure_code = "LIVE_CLOSE_FAILED"
    if failure_code is not None:
        raise _harness_failure(failure_code) from None
    if sanitized is None:
        raise _harness_failure("LIVE_INTERNAL") from None
    return sanitized


@pytest.mark.live_api
@pytest.mark.enable_socket
def test_live_pubmed_one_page_one_record(request: pytest.FixtureRequest) -> None:
    marker_expression = request.config.getoption("markexpr") or ""
    if not _live_marker_selected(marker_expression):
        pytest.skip("live PubMed requires explicit -m live_api marker selection")
    if os.environ.get("MEDEVIDENCE_RUN_LIVE_PUBMED") != "1":
        pytest.skip("live PubMed requires explicit Owner-run opt-in")
    sanitized = _execute_sensitive_live_pubmed()
    assert sanitized.acceptance_record_written is True
    assert sanitized.request_count_total <= 4
    assert sanitized.search_request_count <= 2
    assert sanitized.fetch_request_count <= 2
    assert sanitized.search_pages_completed <= 1
    assert sanitized.fetch_pages_completed <= 1
    assert sanitized.selected_pmid_count <= 100
    assert sanitized.fetched_pmid_count <= 1
    assert sanitized.search_manifest_id
