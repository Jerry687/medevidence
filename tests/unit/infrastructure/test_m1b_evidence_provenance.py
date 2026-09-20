"""DailyMed and FAERS provenance from exact replayed synthetic source bytes."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from tests.unit.connectors.test_dailymed_parsing import SETID, VERSION
from tests.unit.orchestration import test_dailymed_faers_capability as fixtures

from medevidence.domain import SourceType, canonical_json, sha256_digest
from medevidence.infrastructure.evidence_provenance import (
    EvidenceProvenanceIntegrityError,
    VerifiedEvidenceProvenanceStore,
)
from medevidence.infrastructure.m1b_evidence_provenance import (
    VerifiedM1BEvidenceProvenanceStore,
)
from medevidence.ingestion.artifacts import (
    RawResponseObservation,
    capture_dailymed_snapshot,
    capture_faers_snapshot,
)
from medevidence.ingestion.snapshots import SnapshotStore
from medevidence.persistence.repositories import (
    DailyMedEvidenceBinding,
    FaersEvidenceBinding,
    M1BSourceParentBinding,
    PersistenceRepository,
)
from medevidence.tools.contracts import DailyMedFetchRequest
from medevidence.tools.dailymed import (
    DailyMedFetchExecutionProjection,
    DailyMedSectionEvidenceProjection,
)
from medevidence.tools.faers import (
    FaersAggregateExecutionProjection,
    FaersBucketEvidenceProjection,
)

RUN_ID = "run:12345678-1234-4234-9234-123456789abc"
TASK_ID = "source-task:12345678-1234-4234-9234-123456789abc:dailymed"
ATTEMPT_ID = "source-task-attempt:sha256:" + "a" * 64
ACQUISITION_ID = "acquisition:sha256:" + "b" * 64
INTENT_ID = "acquisition-intent:sha256:" + "c" * 64
RETRIEVED = datetime(2026, 1, 1, tzinfo=UTC)


def _repository(
    monkeypatch: pytest.MonkeyPatch,
    *,
    daily: DailyMedEvidenceBinding | None = None,
    faers: FaersEvidenceBinding | None = None,
) -> tuple[PersistenceRepository, dict[tuple[str, str], dict[str, object]]]:
    repository = object.__new__(PersistenceRepository)
    anchors: dict[tuple[str, str], dict[str, object]] = {}

    def get_daily(self: object, **values: object) -> DailyMedEvidenceBinding | None:
        if daily is None:
            return None
        return daily if values["section_id"] == daily.section_id else None

    def get_faers(self: object, **values: object) -> FaersEvidenceBinding | None:
        if faers is None:
            return None
        return faers if values["bucket_ordinal"] == faers.bucket_ordinal else None

    def insert(self: object, envelope: object) -> dict[str, object]:
        raw = envelope.canonical_bytes()
        digest = envelope.envelope_hash.removeprefix("sha256:")
        row = {
            "run_id": envelope.run_id,
            "evidence_id": envelope.evidence_id,
            "source": envelope.source.value,
            "snapshot_id": envelope.snapshot_id,
            "envelope_id": envelope.envelope_id,
            "envelope_hash": envelope.envelope_hash,
            "relative_path": f"m3/evidence-provenance/{digest[:2]}/{digest}.json",
            "byte_size": len(raw),
        }
        anchors.setdefault((envelope.run_id, envelope.evidence_id), row)
        return anchors[(envelope.run_id, envelope.evidence_id)]

    monkeypatch.setattr(PersistenceRepository, "get_dailymed_evidence_binding", get_daily)
    monkeypatch.setattr(PersistenceRepository, "get_faers_evidence_binding", get_faers)
    monkeypatch.setattr(PersistenceRepository, "insert_or_verify_evidence_provenance", insert)
    monkeypatch.setattr(
        PersistenceRepository,
        "get_evidence_provenance_anchor",
        lambda self, *, run_id, evidence_id: anchors.get((run_id, evidence_id)),
    )
    return repository, anchors


def _daily_case(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    snapshots = SnapshotStore(
        tmp_path / "snapshots",
        free_bytes=lambda _: 20_000_000_000,
        dailymed_spl_validator=lambda payload, setid, version: parse_spl_document(
            payload, expected_setid=setid, expected_spl_version=version
        ),
    )
    spl = Path("tests/fixtures/dailymed/spl-valid.xml").read_bytes()
    from medevidence.connectors.dailymed.parsing import parse_spl_document

    parsed = parse_spl_document(spl, expected_setid=SETID, expected_spl_version=VERSION)
    section = parsed.sections[0]
    request = fixtures._daily_request("query:daily")
    discovery = fixtures._discovery_bundle(request, selected=True)[0]
    fetch = DailyMedFetchRequest(
        selection_request=discovery.selection_request,
        query_id=discovery.query_id,
        decision_id=discovery.decision_id,
        selected_candidate_id=discovery.selected_candidate_id,
        selected_setid=discovery.selected_setid,
        selected_spl_version=discovery.selected_spl_version,
    )
    response = fixtures._DailyExecution({"query:daily"}, []).fetch(fetch)
    raw_bytes = spl + b"\n"
    with snapshots.writer():
        captured = capture_dailymed_snapshot(
            snapshots,
            run_id=RUN_ID,
            acquisition_id=ACQUISITION_ID,
            acquisition_intent_id=INTENT_ID,
            acquisition_ordinal=1,
            query_id=fetch.query_id,
            snapshot_id=response.fetch_snapshot_id,
            operation="fetch",
            request_identity=fetch.query_id,
            selected_setid=SETID,
            selected_spl_version=VERSION,
            started_at_utc=RETRIEVED,
            completed_at_utc=RETRIEVED,
            execution_status=response.source_outcome.execution_status,
            coverage_status=response.source_outcome.coverage_status,
            result_status=response.source_outcome.result_status,
            record_count=response.source_outcome.valid_result_count,
            pages_completed=response.source_outcome.pages_completed,
            attempts_used=1,
            truncated=response.source_outcome.truncated,
            warning_codes=response.source_outcome.warning_codes,
            observations=(
                RawResponseObservation(
                    raw_bytes,
                    RETRIEVED,
                    "application/xml",
                    None,
                    200,
                    True,
                    "complete_response",
                ),
            ),
            stable_spl_bytes=spl,
            code_revision="0" * 40,
        )
    raw_member, stable_member = captured.manifest.members
    manifest = M1BSourceParentBinding(
        captured.manifest.manifest_id,
        captured.manifest.manifest_id,
        len(captured.manifest.canonical_bytes()),
        captured.manifest_path.relative_to(snapshots.root).as_posix(),
        "dailymed_snapshot_manifest",
    )
    raw = M1BSourceParentBinding(
        raw_member.artifact_id,
        raw_member.content_hash,
        raw_member.byte_size,
        raw_member.relative_path,
        raw_member.artifact_kind,
    )
    stable = M1BSourceParentBinding(
        stable_member.artifact_id,
        stable_member.content_hash,
        stable_member.byte_size,
        stable_member.relative_path,
        stable_member.artifact_kind,
    )
    evidence_id = "evidence:sha256:" + "d" * 64
    binding = DailyMedEvidenceBinding(
        RUN_ID,
        ACQUISITION_ID,
        INTENT_ID,
        ATTEMPT_ID,
        fetch.query_id,
        response.source_outcome_id,
        response.fetch_snapshot_id,
        RETRIEVED,
        captured.manifest.connector_version,
        manifest,
        raw,
        stable,
        SETID,
        int(VERSION),
        response.label_version_id,
        response.section_ids[0],
        section.section_code,
        section.xml_path,
        section.text_start,
        section.text_end,
        sha256_digest(section.text.encode()),
    )
    projection = DailyMedFetchExecutionProjection(
        run_id=RUN_ID,
        scope_id="scope:sha256:" + "e" * 64,
        task_id=TASK_ID,
        attempt_id=ATTEMPT_ID,
        response=response,
        acquisition=fixtures.AcquisitionOutcomeRef(
            run_id=RUN_ID,
            source=SourceType.DAILYMED,
            acquisition_id=ACQUISITION_ID,
            acquisition_intent_id=INTENT_ID,
            acquisition_ordinal=1,
            operation="fetch",
            query_id=fetch.query_id,
            source_outcome_id=response.source_outcome_id,
            snapshot_id=response.fetch_snapshot_id,
        ),
        section_evidence=(
            DailyMedSectionEvidenceProjection(
                section_id=response.section_ids[0],
                evidence_id=evidence_id,
                content_hash=binding.text_hash,
                locator_ref="locator:daily",
            ),
        ),
    )
    replay = canonical_json(projection).encode()
    with snapshots.writer():
        snapshots.publish_source_replay(
            "dailymed-fetch",
            replay,
            run_id=RUN_ID,
            task_id=TASK_ID,
            attempt_id=ATTEMPT_ID,
            query_id=fetch.query_id,
            acquisition_intent_id=INTENT_ID,
        )
    repository, _ = _repository(monkeypatch, daily=binding)
    return VerifiedM1BEvidenceProvenanceStore(
        snapshots=snapshots, repository=repository
    ), projection


@pytest.mark.parametrize("parent_index", (0, 1, 2))
def test_dailymed_publish_reload_and_parent_tamper(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, parent_index: int
) -> None:
    store, projection = _daily_case(tmp_path, monkeypatch)
    envelope = store.publish_dailymed(projection)[0]
    loaded = store.load_verified_provenance(
        run_id=envelope.run_id,
        evidence_id=envelope.evidence_id,
        source=envelope.source,
        source_record_id=envelope.source_record_id,
        source_version=envelope.source_version,
        snapshot_id=envelope.snapshot_id,
        content_hash=envelope.content_hash,
    )
    assert loaded is not None and loaded.lookup_key == envelope.lookup_key
    parent = envelope.parent_artifacts[parent_index]
    (store._snapshots.root / parent.relative_path).write_bytes(b"tampered")
    with pytest.raises(EvidenceProvenanceIntegrityError):
        store.load_verified_provenance(
            run_id=envelope.run_id,
            evidence_id=envelope.evidence_id,
            source=envelope.source,
            source_record_id=envelope.source_record_id,
            source_version=envelope.source_version,
            snapshot_id=envelope.snapshot_id,
            content_hash=envelope.content_hash,
        )


def _faers_case(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    snapshots = SnapshotStore(tmp_path / "snapshots", free_bytes=lambda _: 20_000_000_000)
    raw_bytes = Path("tests/fixtures/faers/count-single-bucket.json").read_bytes()
    request = fixtures._faers_request(fixtures.FaersIdentityStrategy.HARMONIZED_SUBSTANCE)
    execution = fixtures._faers_execution(request)
    result = execution.result
    bucket = result.buckets[0]
    with snapshots.writer():
        captured = capture_faers_snapshot(
            snapshots,
            run_id=RUN_ID,
            acquisition_id=execution.acquisition_outcome_ref.acquisition_id,
            acquisition_intent_id=execution.acquisition_outcome_ref.acquisition_intent_id,
            acquisition_ordinal=execution.acquisition_outcome_ref.acquisition_ordinal,
            query=result.query,
            snapshot_id=result.snapshot_id,
            started_at_utc=RETRIEVED,
            completed_at_utc=RETRIEVED,
            source_outcome=result.source_outcome,
            retrieved_at_utc=result.retrieved_at_utc,
            provider_as_of_utc=result.provider_as_of_utc,
            attempts_used=1,
            buckets=result.buckets,
            observations=(
                RawResponseObservation(
                    raw_bytes,
                    RETRIEVED,
                    "application/json",
                    None,
                    200,
                    True,
                    "complete_response",
                ),
            ),
            code_revision="0" * 40,
        )
    member = captured.manifest.members[0]
    manifest = M1BSourceParentBinding(
        captured.manifest.manifest_id,
        captured.manifest.manifest_id,
        len(captured.manifest.canonical_bytes()),
        captured.manifest_path.relative_to(snapshots.root).as_posix(),
        "faers_aggregate_manifest",
    )
    raw = M1BSourceParentBinding(
        member.artifact_id,
        member.content_hash,
        member.byte_size,
        member.relative_path,
        member.artifact_kind,
    )
    binding = FaersEvidenceBinding(
        RUN_ID,
        execution.acquisition_outcome_ref.acquisition_id,
        execution.acquisition_outcome_ref.acquisition_intent_id,
        ATTEMPT_ID,
        result.query.query_id,
        execution.acquisition_outcome_ref.source_outcome_id,
        result.snapshot_id,
        result.retrieved_at_utc,
        captured.manifest.connector_version,
        manifest,
        raw,
        result.query.execution_profile_id,
        result.query.ast_schema_version,
        result.query.serializer_version,
        bucket.bucket_ordinal,
        bucket.reaction_pt,
        bucket.report_count,
        bucket.statistical_unit,
        bucket.identity_stratum,
        bucket.role_policy,
    )
    normalized = VerifiedM1BEvidenceProvenanceStore._faers_bucket_bytes(binding)
    projection = FaersAggregateExecutionProjection(
        run_id=RUN_ID,
        scope_id="scope:sha256:" + "e" * 64,
        task_id="source-task:12345678-1234-4234-9234-123456789abc:faers",
        attempt_id=ATTEMPT_ID,
        execution=execution,
        bucket_evidence=(
            FaersBucketEvidenceProjection(
                bucket_ordinal=bucket.bucket_ordinal,
                evidence_id="evidence:sha256:" + "f" * 64,
                content_hash=sha256_digest(normalized),
                locator_ref="locator:faers",
            ),
        ),
    )
    replay = canonical_json(projection).encode()
    with snapshots.writer():
        snapshots.publish_source_replay(
            "faers-aggregate",
            replay,
            run_id=RUN_ID,
            task_id=projection.task_id,
            attempt_id=ATTEMPT_ID,
            query_id=result.query.query_id,
            acquisition_intent_id=execution.acquisition_outcome_ref.acquisition_intent_id,
        )
    repository, _ = _repository(monkeypatch, faers=binding)
    return VerifiedM1BEvidenceProvenanceStore(
        snapshots=snapshots, repository=repository
    ), projection


def test_faers_publish_reload_and_foreign_query(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, projection = _faers_case(tmp_path, monkeypatch)
    envelope = store.publish_faers(projection)[0]
    assert (
        store.load_verified_provenance(
            run_id=envelope.run_id,
            evidence_id=envelope.evidence_id,
            source=envelope.source,
            source_record_id=envelope.source_record_id,
            source_version=envelope.source_version,
            snapshot_id=envelope.snapshot_id,
            content_hash=envelope.content_hash,
        )
        is not None
    )
    material = store.load_verified_material(
        run_id=envelope.run_id,
        evidence_id=envelope.evidence_id,
        source=envelope.source,
        source_record_id=envelope.source_record_id,
        source_version=envelope.source_version,
        snapshot_id=envelope.snapshot_id,
        content_hash=envelope.content_hash,
    )
    assert material is not None
    assert ("report_count", "7") in material.numerical_facts
    with pytest.raises(EvidenceProvenanceIntegrityError):
        store.load_verified_provenance(
            run_id=envelope.run_id,
            evidence_id=envelope.evidence_id,
            source=envelope.source,
            source_record_id=envelope.source_record_id + "x",
            source_version=envelope.source_version,
            snapshot_id=envelope.snapshot_id,
            content_hash=envelope.content_hash,
        )


def test_cadec_and_pubmed_are_not_claimed_by_m1b_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, projection = _daily_case(tmp_path, monkeypatch)
    item = projection.section_evidence[0]
    for source in (SourceType.PUBMED, SourceType.CADEC):
        assert (
            store.load_verified_provenance(
                run_id=RUN_ID,
                evidence_id=item.evidence_id,
                source=source,
                source_record_id="record",
                source_version="version",
                snapshot_id=projection.response.fetch_snapshot_id,
                content_hash=item.content_hash,
            )
            is None
        )


def test_generic_reader_dispatches_m1b_without_changing_pubmed_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    m1b, projection = _daily_case(tmp_path, monkeypatch)
    envelope = m1b.publish_dailymed(projection)[0]
    outer = VerifiedEvidenceProvenanceStore(
        snapshots=m1b._snapshots,
        repository=m1b._repository,
        m1b=m1b,
    )
    loaded = outer.load_verified_provenance(
        run_id=envelope.run_id,
        evidence_id=envelope.evidence_id,
        source=SourceType.DAILYMED,
        source_record_id=envelope.source_record_id,
        source_version=envelope.source_version,
        snapshot_id=envelope.snapshot_id,
        content_hash=envelope.content_hash,
    )
    assert loaded is not None and loaded.source is SourceType.DAILYMED
    material = m1b.load_verified_material(
        run_id=envelope.run_id,
        evidence_id=envelope.evidence_id,
        source=envelope.source,
        source_record_id=envelope.source_record_id,
        source_version=envelope.source_version,
        snapshot_id=envelope.snapshot_id,
        content_hash=envelope.content_hash,
    )
    assert material is not None
    assert material.locator_ref == projection.section_evidence[0].locator_ref
    assert sha256_digest(material.normalized_text.encode()) == envelope.content_hash


def test_missing_source_replay_is_rejected_on_every_reload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, projection = _daily_case(tmp_path, monkeypatch)
    envelope = store.publish_dailymed(projection)[0]
    capture_path = store._snapshots.root / envelope.parent_artifacts[0].relative_path
    capture = json.loads(capture_path.read_bytes())
    replay_path = store._snapshots.root / capture["source_replay"]["relative_path"]
    replay_path.unlink()
    with pytest.raises(EvidenceProvenanceIntegrityError, match="source parent"):
        store.load_verified_provenance(
            run_id=envelope.run_id,
            evidence_id=envelope.evidence_id,
            source=envelope.source,
            source_record_id=envelope.source_record_id,
            source_version=envelope.source_version,
            snapshot_id=envelope.snapshot_id,
            content_hash=envelope.content_hash,
        )


def test_unrelated_valid_raw_and_stable_pair_cannot_replace_capture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, projection = _daily_case(tmp_path, monkeypatch)
    envelope = store.publish_dailymed(projection)[0]
    original = store._repository.get_dailymed_evidence_binding(
        run_id=projection.run_id,
        acquisition_id=projection.acquisition.acquisition_id,
        query_id=projection.response.request.query_id,
        source_outcome_id=projection.response.source_outcome_id,
        snapshot_id=projection.response.fetch_snapshot_id,
        label_version_id=projection.response.label_version_id,
        section_id=projection.section_evidence[0].section_id,
    )
    assert original is not None
    altered = (
        Path("tests/fixtures/dailymed/spl-valid.xml")
        .read_bytes()
        .replace(b"Nausea", b"Other symptom")
    )
    altered_hash = sha256_digest(altered)
    altered_path = (
        f"dailymed/raw/sha256/{altered_hash.removeprefix('sha256:')[:2]}/"
        f"{altered_hash.removeprefix('sha256:')}.bin"
    )
    with store._snapshots.writer():
        store._snapshots.publish_bytes(altered_path, altered, artifact_class="raw")
    foreign = replace(
        original,
        raw=M1BSourceParentBinding(
            altered_hash,
            altered_hash,
            len(altered),
            altered_path,
            "dailymed_http_response",
        ),
    )
    monkeypatch.setattr(
        PersistenceRepository,
        "get_dailymed_evidence_binding",
        lambda self, **values: foreign,
    )
    with pytest.raises(EvidenceProvenanceIntegrityError, match="source graph"):
        store.load_verified_provenance(
            run_id=envelope.run_id,
            evidence_id=envelope.evidence_id,
            source=envelope.source,
            source_record_id=envelope.source_record_id,
            source_version=envelope.source_version,
            snapshot_id=envelope.snapshot_id,
            content_hash=envelope.content_hash,
        )


@pytest.mark.parametrize("parent_name", ("raw", "stable_spl"))
def test_dailymed_valid_nonmember_parent_is_rejected_before_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, parent_name: str
) -> None:
    store, projection = _daily_case(tmp_path, monkeypatch)
    original = store._repository.get_dailymed_evidence_binding(
        run_id=projection.run_id,
        acquisition_id=projection.acquisition.acquisition_id,
        query_id=projection.response.request.query_id,
        source_outcome_id=projection.response.source_outcome_id,
        snapshot_id=projection.response.fetch_snapshot_id,
        label_version_id=projection.response.label_version_id,
        section_id=projection.section_evidence[0].section_id,
    )
    assert original is not None
    alternate = Path("tests/fixtures/dailymed/spl-valid.xml").read_bytes() + b"\n\n"
    digest = sha256_digest(alternate)
    value = digest.removeprefix("sha256:")
    relative = (
        f"dailymed/raw/sha256/{value[:2]}/{value}.bin"
        if parent_name == "raw"
        else f"dailymed/sha256/{value}.xml"
    )
    with store._snapshots.writer():
        store._snapshots.publish_bytes(
            relative, alternate, artifact_class="raw" if parent_name == "raw" else "journal"
        )
    parent = M1BSourceParentBinding(
        digest,
        digest,
        len(alternate),
        relative,
        "dailymed_http_response" if parent_name == "raw" else "dailymed_spl_xml",
    )
    foreign = replace(original, **{parent_name: parent})
    monkeypatch.setattr(
        PersistenceRepository,
        "get_dailymed_evidence_binding",
        lambda self, **values: foreign,
    )
    with pytest.raises(EvidenceProvenanceIntegrityError, match="not in manifest"):
        store.publish_dailymed(projection)


def test_faers_valid_nonmember_raw_is_rejected_before_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, projection = _faers_case(tmp_path, monkeypatch)
    result = projection.execution.result
    original = store._repository.get_faers_evidence_binding(
        run_id=projection.run_id,
        acquisition_id=projection.execution.acquisition_outcome_ref.acquisition_id,
        query_id=result.query.query_id,
        source_outcome_id=projection.execution.acquisition_outcome_ref.source_outcome_id,
        snapshot_id=result.snapshot_id,
        bucket_ordinal=projection.bucket_evidence[0].bucket_ordinal,
    )
    assert original is not None
    alternate = Path("tests/fixtures/faers/count-single-bucket.json").read_bytes() + b"\n"
    digest = sha256_digest(alternate)
    value = digest.removeprefix("sha256:")
    relative = f"faers/raw/sha256/{value[:2]}/{value}.bin"
    with store._snapshots.writer():
        store._snapshots.publish_bytes(relative, alternate, artifact_class="raw")
    foreign = replace(
        original,
        raw=M1BSourceParentBinding(
            digest,
            digest,
            len(alternate),
            relative,
            "faers_http_response",
        ),
    )
    monkeypatch.setattr(
        PersistenceRepository,
        "get_faers_evidence_binding",
        lambda self, **values: foreign,
    )
    with pytest.raises(EvidenceProvenanceIntegrityError, match="not in manifest"):
        store.publish_faers(projection)


@pytest.mark.parametrize("source", (SourceType.DAILYMED, SourceType.FAERS))
def test_persisted_retrieval_time_drift_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, source: SourceType
) -> None:
    if source is SourceType.DAILYMED:
        store, projection = _daily_case(tmp_path, monkeypatch)
        envelope = store.publish_dailymed(projection)[0]
        original = store._repository.get_dailymed_evidence_binding(
            run_id=projection.run_id,
            acquisition_id=projection.acquisition.acquisition_id,
            query_id=projection.response.request.query_id,
            source_outcome_id=projection.response.source_outcome_id,
            snapshot_id=projection.response.fetch_snapshot_id,
            label_version_id=projection.response.label_version_id,
            section_id=projection.section_evidence[0].section_id,
        )
        assert original is not None
        monkeypatch.setattr(
            PersistenceRepository,
            "get_dailymed_evidence_binding",
            lambda self, **values: replace(
                original, retrieved_at_utc=original.retrieved_at_utc + timedelta(days=1)
            ),
        )
    else:
        store, projection = _faers_case(tmp_path, monkeypatch)
        envelope = store.publish_faers(projection)[0]
        result = projection.execution.result
        original = store._repository.get_faers_evidence_binding(
            run_id=projection.run_id,
            acquisition_id=projection.execution.acquisition_outcome_ref.acquisition_id,
            query_id=result.query.query_id,
            source_outcome_id=projection.execution.acquisition_outcome_ref.source_outcome_id,
            snapshot_id=result.snapshot_id,
            bucket_ordinal=projection.bucket_evidence[0].bucket_ordinal,
        )
        assert original is not None
        monkeypatch.setattr(
            PersistenceRepository,
            "get_faers_evidence_binding",
            lambda self, **values: replace(
                original, retrieved_at_utc=original.retrieved_at_utc + timedelta(days=1)
            ),
        )
    with pytest.raises(EvidenceProvenanceIntegrityError):
        store.load_verified_provenance(
            run_id=envelope.run_id,
            evidence_id=envelope.evidence_id,
            source=envelope.source,
            source_record_id=envelope.source_record_id,
            source_version=envelope.source_version,
            snapshot_id=envelope.snapshot_id,
            content_hash=envelope.content_hash,
        )
