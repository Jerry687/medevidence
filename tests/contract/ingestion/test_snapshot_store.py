"""Offline contract checks for exact-byte snapshot publication and replay."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import httpx

from medevidence.connectors.pubmed import PubMedConnector, PubMedResultState
from medevidence.domain import CoverageStatus, ExecutionStatus, ResultStatus
from medevidence.ingestion.artifacts import (
    capture_acquisition,
    replay_manifest,
    response_observation,
)
from medevidence.ingestion.snapshots import (
    INITIAL_FREE_SPACE_FLOOR_BYTES,
    SnapshotStore,
)


def test_snapshot_store_has_no_transport_and_replays_exact_bytes(tmp_path: Path) -> None:
    store = SnapshotStore(
        tmp_path / "snapshots",
        free_bytes=lambda _: INITIAL_FREE_SPACE_FLOOR_BYTES,
    )
    body = b"\x00synthetic\r\nbody\xff"

    with store.writer():
        written = store.store_raw_body(body)
        verified = store.verify(written.artifact_id)

    assert verified.read_bytes() == body
    assert verified == written.path


def test_mock_transport_result_captures_and_replays_bound_manifest(tmp_path: Path) -> None:
    body = (
        b"<eSearchResult><Count>1</Count><RetMax>1</RetMax><RetStart>0</RetStart>"
        b"<IdList><Id>1</Id></IdList></eSearchResult>"
    )
    now = datetime(2026, 8, 6, 12, 0, tzinfo=UTC)

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=body,
            headers={
                "content-type": "application/xml; charset=utf-8",
                "content-encoding": "identity",
            },
        )

    with PubMedConnector(
        httpx.MockTransport(handler),
        monotonic=lambda: 0.0,
        utc_now=lambda: now,
        sleep=lambda _: None,
        jitter=lambda: 0.0,
    ) as connector:
        result = connector.search("synthetic[Title/Abstract]")

    assert result.state is PubMedResultState.COMPLETE_SUCCESS
    assert result.pmids == ("1",)
    assert result.source_outcome is not None
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
    store = SnapshotStore(
        tmp_path / "snapshots",
        free_bytes=lambda _: INITIAL_FREE_SPACE_FLOOR_BYTES,
    )
    with store.writer():
        captured = capture_acquisition(
            store,
            journal_relative_directory="journal/acquisition-0000",
            acquisition_intent_id=(
                "acquisition-intent:sha256:"
                "fe9f621ba82c3a783382764171022c641e399453f6b80650380bb54a1df9cd3d"
            ),
            request_identity=result.raw_responses[0].request_url,
            started_at_utc=now,
            completed_at_utc=now,
            validated_record_count=len(result.pmids),
            execution_status=ExecutionStatus.SUCCEEDED,
            coverage_status=CoverageStatus.COMPLETE,
            result_status=ResultStatus.MATCHES,
            attempts_used=1,
            pages_completed=1,
            truncated=False,
            warning_codes=(),
            observations=observations,
            code_revision="a3fd66477046c9e026d7b2222e882cd94a84d535",
        )

    replayed = replay_manifest(
        captured.manifest_path.read_bytes(),
        store,
        expected_manifest_id=captured.manifest.manifest_id,
        expected_links=captured.artifact_links,
        expected_validated_record_count=len(result.pmids),
    )

    assert replayed == captured.manifest
    assert captured.manifest.request_identity == result.raw_responses[0].request_url
    assert len(captured.artifact_links) == 1
    assert captured.artifact_links[0].artifact_id.removeprefix("sha256:") in str(
        store.verify(captured.artifact_links[0].artifact_id)
    )
    assert captured.artifact_links[0].media_type == "application/xml"
    assert captured.artifact_links[0].content_encoding == "identity"
    assert captured.artifact_links[0].http_status == 200
    assert captured.artifact_links[0].byte_size == len(body)
    assert captured.artifact_links[0].observed_at_utc == now
    assert captured.artifact_links[0].body_complete
    assert captured.artifact_link_paths[0].read_bytes() == (
        captured.artifact_links[0].canonical_bytes()
    )
