"""Exact V2 DailyMed raw acquisition capture and replay."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from medevidence.connectors.dailymed.parsing import parse_spl_document
from medevidence.domain import (
    CoverageStatus,
    ExecutionBounds,
    ExecutionStatus,
    ResultStatus,
    SourceOutcome,
    SourceType,
    sha256_digest,
)
from medevidence.ingestion.dailymed_v2_artifacts import (
    DailyMedV2Observation,
    capture_dailymed_v2,
    replay_dailymed_v2,
)
from medevidence.ingestion.snapshots import SnapshotIntegrityError, SnapshotStore


def _store(tmp_path: Path) -> SnapshotStore:
    return SnapshotStore(
        tmp_path / "snapshots",
        free_bytes=lambda _: 20_000_000_000,
        dailymed_spl_validator=lambda body, setid, version: parse_spl_document(
            body, expected_setid=setid, expected_spl_version=version
        ),
    )


def test_v2_selected_spl_raw_and_stable_bytes_replay(tmp_path: Path) -> None:
    store = _store(tmp_path)
    raw = Path("tests/fixtures/dailymed/spl-valid.xml").read_bytes()
    now = datetime(2026, 9, 16, tzinfo=UTC)
    query_id = "dailymed-query:test"
    outcome = SourceOutcome(
        source=SourceType.DAILYMED,
        query_id=query_id,
        execution_status=ExecutionStatus.SUCCEEDED,
        coverage_status=CoverageStatus.COMPLETE,
        result_status=ResultStatus.MATCHES,
        configured_bounds=ExecutionBounds(
            max_query_characters=512,
            max_pages=5,
            max_records=100,
            max_payload_bytes=5_242_880,
            max_total_seconds=30,
        ),
        valid_result_count=1,
        pages_completed=1,
        truncated=False,
    )
    observation = DailyMedV2Observation(
        body=raw,
        status_code=200,
        observed_at_utc=now,
        request_url="https://dailymed.nlm.nih.gov/dailymed/services/v2/spls/11111111-1111-1111-1111-111111111111.xml",
        final_url="https://dailymed.nlm.nih.gov/dailymed/services/v2/spls/11111111-1111-1111-1111-111111111111.xml",
        media_type="application/xml",
        page_number=1,
        attempt_count=1,
        body_complete=True,
        termination_reason="complete_response",
    )
    with store.writer():
        captured = capture_dailymed_v2(
            store,
            operation="selected_spl",
            run_id="run:00000000-0000-4000-8000-000000000002",
            acquisition_id="acquisition:dailymed-v2-test",
            acquisition_intent_id="acquisition-intent:sha256:" + "a" * 64,
            acquisition_ordinal=2,
            attempt_id="source-task-attempt:test",
            query_id=query_id,
            snapshot_id="snapshot:dailymed-v2-test",
            request_identity=sha256_digest("synthetic current SPL request"),
            started_at_utc=now,
            completed_at_utc=now,
            source_outcome=outcome,
            requests_sent=1,
            pages_completed=1,
            observations=(observation,),
            stable_spl_bytes=raw,
            selected_setid="11111111-1111-1111-1111-111111111111",
            selected_spl_version="3",
            code_revision="a" * 40,
        )
    replayed = replay_dailymed_v2(
        store,
        manifest_id=captured.manifest.manifest_id,
        expected_operation="selected_spl",
        expected_run_id=captured.manifest.run_id,
        expected_acquisition_id=captured.manifest.acquisition_id,
        expected_intent_id=captured.manifest.acquisition_intent_id,
        expected_query_id=query_id,
        expected_request_identity=captured.manifest.request_identity,
    )
    assert replayed == captured.manifest
    assert len(replayed.members) == 2
    with pytest.raises(SnapshotIntegrityError):
        replay_dailymed_v2(
            store,
            manifest_id=captured.manifest.manifest_id,
            expected_operation="packaging",
            expected_run_id=captured.manifest.run_id,
            expected_acquisition_id=captured.manifest.acquisition_id,
            expected_intent_id=captured.manifest.acquisition_intent_id,
            expected_query_id=query_id,
            expected_request_identity=captured.manifest.request_identity,
        )
