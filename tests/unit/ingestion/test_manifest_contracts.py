"""Frozen M1A journal identity vectors and closed-schema mutations."""

# ruff: noqa: E501

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from medevidence.domain.identifiers import (
    derive_m1a_journal_identity,
    parse_m1a_json_bytes,
)
from medevidence.ingestion.artifacts import write_immutable_record
from medevidence.ingestion.contracts import (
    AcquisitionIntent,
    AcquisitionRegistrationEnvelope,
    ArtifactLink,
    JournalModel,
    RunIntent,
    RunRegistrationEnvelope,
    with_computed_identity,
)
from medevidence.ingestion.snapshots import (
    INITIAL_FREE_SPACE_FLOOR_BYTES,
    ROOT_LOCK_FILENAME,
    SnapshotStore,
)

RUN = '{"adverse_event_concept_ids":["m1a.event.gastrointestinal"],"catalog_version":"m1a-concepts-v1","code_revision":"a3fd66477046c9e026d7b2222e882cd94a84d535","created_at_utc":"2026-08-06T12:00:00.000000Z","drug_concept_ids":["m1a.drug.semaglutide"],"execution_limits":{"max_acquisitions":101,"max_attempts":2,"max_cumulative_payload_bytes_per_acquisition":5242880,"max_pages":1,"max_payload_bytes_per_response":5242880,"max_publications":100,"max_query_characters":512,"max_raw_responses_per_acquisition":4,"max_raw_responses_per_run":404,"max_redirects":1,"page_size":100,"total_deadline_ms_per_acquisition":30000},"execution_profile_id":"M1A_CONSTRAINED_V1","pubmed_query":"(\\"semaglutide\\"[Title/Abstract]) AND (\\"gastrointestinal\\"[Title/Abstract])","request_id":"request:00000000-0000-4000-8000-000000000001","run_id":"run:00000000-0000-4000-8000-000000000002","schema_version":"1.0","scope_id":"scope:sha256:6806e021895ff9d0f62b33691db00baf8e64df8fc6c879dd9705e55e640be950","source":"pubmed"}'
ACQUISITION = '{"acquisition_ordinal":0,"attempt_id":"attempt:00000000-0000-4000-8000-000000000003","created_at_utc":"2026-08-06T12:00:01.000000Z","execution_limits":{"base_backoff_ms":250,"cache_policy":"none","connect_timeout_ms":5000,"jitter_ms":100,"max_attempts":2,"max_backoff_ms":4000,"max_payload_bytes":5242880,"max_redirects":1,"max_retry_after_ms":10000,"pool_timeout_ms":5000,"read_timeout_ms":10000,"total_deadline_ms":30000,"write_timeout_ms":5000},"execution_profile_id":"M1A_CONSTRAINED_V1","operation":"search","request":{"db":"pubmed","path":"/entrez/eutils/esearch.fcgi","retmax":100,"retmode":"xml","retstart":0,"term":"(\\"semaglutide\\"[Title/Abstract]) AND (\\"gastrointestinal\\"[Title/Abstract])"},"run_id":"run:00000000-0000-4000-8000-000000000002","run_intent_id":"run-intent:sha256:9cea22d71d57ae4edfa4d4a4b3587b72b974defcd9e8421831e732ee84f032d3","schema_version":"1.0","source":"pubmed"}'
LINK_0 = '{"acquisition_intent_id":"acquisition-intent:sha256:fe9f621ba82c3a783382764171022c641e399453f6b80650380bb54a1df9cd3d","artifact_id":"sha256:6eb820e0f9762c611c2a77189f686afeca64dfb212e023017e0346e7ab826c39","artifact_kind":"pubmed_http_response","body_complete":true,"byte_size":6,"http_status":200,"media_type":"application/xml","observed_at_utc":"2026-08-06T12:00:02.000000Z","ordinal":0,"schema_version":"1.0","termination_reason":"complete_response"}'
LINK_1 = LINK_0.replace('"ordinal":0', '"ordinal":1')
ZERO_ENVELOPE = '{"acquisition_intent_id":"acquisition-intent:sha256:fe9f621ba82c3a783382764171022c641e399453f6b80650380bb54a1df9cd3d","acquisition_ordinal":0,"artifact_links":[],"attempt_id":"attempt:00000000-0000-4000-8000-000000000003","attempts_used":2,"completed_at_utc":"2026-08-06T12:00:05.000000Z","coverage_status":"unavailable","envelope_kind":"acquisition","execution_status":"failed","failure_code":"transport","manifest_id":"sha256:882cc8b218bbda8d2b09f876cf85572a34d71ae9ee5b219dc0e0172b7381384b","operation":"search","pages_completed":0,"redacted_detail":"caf\u00e9","registration_state":"ready_for_insert","result_status":"indeterminate","run_id":"run:00000000-0000-4000-8000-000000000002","schema_version":"1.0","source":"pubmed","started_at_utc":"2026-08-06T12:00:01.000000Z","truncated":false,"valid_result_count":0,"warning_codes":["source_unavailable"]}'
TWO_ENVELOPE = '{"acquisition_intent_id":"acquisition-intent:sha256:fe9f621ba82c3a783382764171022c641e399453f6b80650380bb54a1df9cd3d","acquisition_ordinal":0,"artifact_links":[{"link_id":"artifact-link:sha256:2f8434e5e24961345317bab57bac64258cc1c90bb48345b3059f15417b6cf5c5","ordinal":0},{"link_id":"artifact-link:sha256:7fa751bc6e92282f0fecb59a1448a824e39b5f0045bf7fdb365549ca5add838a","ordinal":1}],"attempt_id":"attempt:00000000-0000-4000-8000-000000000003","attempts_used":1,"completed_at_utc":"2026-08-06T12:00:04.000000Z","coverage_status":"complete","envelope_kind":"acquisition","execution_status":"succeeded","manifest_id":"sha256:b773825e8ed1ea53d961ca97debe5e1cdd622112bb983fd2cba6bdc7be0f21d4","operation":"search","pages_completed":1,"registration_state":"ready_for_insert","result_status":"matches","run_id":"run:00000000-0000-4000-8000-000000000002","schema_version":"1.0","source":"pubmed","started_at_utc":"2026-08-06T12:00:01.000000Z","truncated":false,"valid_result_count":2,"warning_codes":[]}'
RUN_ENVELOPE = '{"acquisition_registrations":[{"acquisition_registration_envelope_id":"registration-envelope:acquisition:sha256:3febdc11e8ebca14a433a7798653d7a85d3aa3385596649ff41a1911d506f4f3","run_ordinal":0}],"completed_at_utc":"2026-08-06T12:00:06.000000Z","coverage_status":"complete","envelope_kind":"run","registration_state":"ready_for_insert","report_artifact_id":"sha256:a6070e92bca201ba4b41003b1a4283631b1655e7c700a9a62b3c82ee8b0a630a","report_byte_size":1024,"report_id":"report:sha256:15d5c59556be02904a08a6b469ee4caa94df11963b39e0207acc7012c6531fa2","report_media_type":"application/json","report_status":"draft","result_status":"matches","run_id":"run:00000000-0000-4000-8000-000000000002","run_intent_id":"run-intent:sha256:9cea22d71d57ae4edfa4d4a4b3587b72b974defcd9e8421831e732ee84f032d3","run_status":"completed","schema_version":"1.0","started_at_utc":"2026-08-06T12:00:00.000000Z","warning_codes":[]}'

VECTORS = (
    (RunIntent, RUN, 996, "9cea22d71d57ae4edfa4d4a4b3587b72b974defcd9e8421831e732ee84f032d3", 82),
    (
        AcquisitionIntent,
        ACQUISITION,
        899,
        "fe9f621ba82c3a783382764171022c641e399453f6b80650380bb54a1df9cd3d",
        90,
    ),
    (
        ArtifactLink,
        LINK_0,
        454,
        "2f8434e5e24961345317bab57bac64258cc1c90bb48345b3059f15417b6cf5c5",
        85,
    ),
    (
        ArtifactLink,
        LINK_1,
        454,
        "7fa751bc6e92282f0fecb59a1448a824e39b5f0045bf7fdb365549ca5add838a",
        85,
    ),
    (
        AcquisitionRegistrationEnvelope,
        ZERO_ENVELOPE,
        854,
        "2e112576a8189251bdada4331fd192b462263938564e0ddb68ed352fd5bceffa",
        105,
    ),
    (
        AcquisitionRegistrationEnvelope,
        TWO_ENVELOPE,
        998,
        "3febdc11e8ebca14a433a7798653d7a85d3aa3385596649ff41a1911d506f4f3",
        105,
    ),
    (
        RunRegistrationEnvelope,
        RUN_ENVELOPE,
        905,
        "fbebd711453be4be772e0eeec23dbffd788357b23bb34877cebbdad4d438cfb2",
        97,
    ),
)


@pytest.mark.parametrize(("model", "canonical", "size", "digest", "id_length"), VECTORS)
def test_frozen_identity_vectors(
    model: type,
    canonical: str,
    size: int,
    digest: str,
    id_length: int,
) -> None:
    payload = json.loads(canonical)
    record = with_computed_identity(model, payload)
    identity = getattr(record, model.identity_field)

    assert len(canonical.encode() + b"\n") == size
    assert identity == f"{model.identity_prefix}{digest}"
    assert len(identity) == id_length <= 128
    assert record.expected_identity() == identity


def test_terminal_lf_namespace_and_self_field_mutations() -> None:
    payload = json.loads(LINK_0)
    canonical = LINK_0.encode() + b"\n"
    namespace = ArtifactLink.identity_namespace.encode() + b"\0"
    record = with_computed_identity(ArtifactLink, payload)

    assert hashlib.sha256(namespace + canonical[:-1]).hexdigest() == (
        "2ceff0d4f475a27f7645b3a7ce1a0aa20788a3658b0c64be6b529224ed224d5b"
    )
    assert hashlib.sha256(namespace + canonical[:-1] + b"\r\n").hexdigest() == (
        "fe63963dc54dcef3bce1ab536e5705d4022480e813ced2a482bff463a16e5817"
    )
    assert hashlib.sha256(namespace + record.canonical_bytes()).hexdigest() == (
        "d029fe5e18602cb7cb1572c5a51d78ad0ae931dfff3fa9391629e1067549436f"
    )
    assert (
        hashlib.sha256(
            AcquisitionRegistrationEnvelope.identity_namespace.encode()
            + b"\0"
            + RUN_ENVELOPE.encode()
            + b"\n"
        ).hexdigest()
        == "8ce3a97088fa6c1521c72031f8cf66275356248272961ca1e6d292b7db0532c3"
    )


def test_unicode_is_not_normalized() -> None:
    nfd = ZERO_ENVELOPE.replace("caf\u00e9", "cafe\u0301")
    digest = hashlib.sha256(
        AcquisitionRegistrationEnvelope.identity_namespace.encode() + b"\0" + nfd.encode() + b"\n"
    ).hexdigest()
    assert digest == "7c110a1cb9c1bec65008d16ebbd9c08d29a073f87a513463b5d6dd44273147b6"


def test_duplicate_unknown_float_null_and_invalid_order_reject_before_hash() -> None:
    with pytest.raises(ValueError, match="duplicate"):
        parse_m1a_json_bytes(b'{"a":1,"a":2}')
    for raw in (b'{"a":1.0}', b'{"a":NaN}', b'{"a":null}'):
        with pytest.raises(ValueError):
            parse_m1a_json_bytes(raw)

    unknown = json.loads(LINK_0)
    unknown["unexpected"] = "forbidden"
    with pytest.raises(ValidationError):
        with_computed_identity(ArtifactLink, unknown)

    reordered = json.loads(TWO_ENVELOPE)
    reordered["artifact_links"].reverse()
    with pytest.raises(ValidationError, match="contiguous"):
        with_computed_identity(AcquisitionRegistrationEnvelope, reordered)

    duplicate = json.loads(TWO_ENVELOPE)
    duplicate["artifact_links"][1]["ordinal"] = 0
    with pytest.raises(ValidationError, match="contiguous"):
        with_computed_identity(AcquisitionRegistrationEnvelope, duplicate)


def test_same_raw_artifact_at_different_ordinal_has_distinct_link_identity() -> None:
    first = with_computed_identity(ArtifactLink, json.loads(LINK_0))
    second = with_computed_identity(ArtifactLink, json.loads(LINK_1))
    assert first.artifact_id == second.artifact_id
    assert first.link_id != second.link_id


def test_json_boundary_rejects_noncanonical_or_wrong_identity() -> None:
    record = with_computed_identity(ArtifactLink, json.loads(LINK_0))
    with pytest.raises(ValidationError, match="does not match"):
        ArtifactLink.from_json_bytes(
            record.canonical_bytes().replace(
                record.link_id.encode(),
                f"artifact-link:sha256:{'0' * 64}".encode(),
            )
        )
    with pytest.raises(ValueError, match="canonical"):
        ArtifactLink.from_json_bytes(record.canonical_bytes().replace(b"\n", b"\r\n"))
    with pytest.raises(ValueError, match="canonical"):
        ArtifactLink.from_json_bytes(b" " + record.canonical_bytes())
    assert (
        derive_m1a_journal_identity(
            namespace=record.identity_namespace,
            prefix=record.identity_prefix,
            self_field=record.identity_field,
            value=record,
        )
        == record.link_id
    )


def test_envelopes_require_positive_complete_evidence_and_failure_detail() -> None:
    complete = json.loads(TWO_ENVELOPE)
    complete["artifact_links"] = []
    with pytest.raises(ValidationError, match="retained artifact links"):
        with_computed_identity(AcquisitionRegistrationEnvelope, complete)

    complete = json.loads(TWO_ENVELOPE)
    complete["pages_completed"] = 0
    with pytest.raises(ValidationError, match="completed page"):
        with_computed_identity(AcquisitionRegistrationEnvelope, complete)

    failed = json.loads(ZERO_ENVELOPE)
    del failed["redacted_detail"]
    with pytest.raises(ValidationError, match="redacted_detail"):
        with_computed_identity(AcquisitionRegistrationEnvelope, failed)


def test_partial_match_envelope_requires_but_accepts_retained_links() -> None:
    partial = json.loads(TWO_ENVELOPE)
    partial["coverage_status"] = "partial"
    partial["pages_completed"] = 0

    envelope = with_computed_identity(AcquisitionRegistrationEnvelope, partial)
    assert envelope.result_status.value == "matches"
    assert envelope.pages_completed == 0
    assert len(envelope.artifact_links) == 2

    partial["artifact_links"] = []
    with pytest.raises(ValidationError, match="retained artifact links"):
        with_computed_identity(AcquisitionRegistrationEnvelope, partial)


RECORD_SPECS: dict[str, tuple[type[JournalModel], str]] = {
    "run_intent": (RunIntent, RUN),
    "acquisition_intent": (AcquisitionIntent, ACQUISITION),
    "artifact_link": (ArtifactLink, LINK_0),
    "acquisition_envelope": (AcquisitionRegistrationEnvelope, TWO_ENVELOPE),
    "run_envelope": (RunRegistrationEnvelope, RUN_ENVELOPE),
}
FILENAME_ALLOWED_RECORDS = {
    "run-intent.json": {"run_intent"},
    "acquisition-intent.json": {"acquisition_intent"},
    "artifact-link-0000.json": {"artifact_link"},
    "registration-envelope.json": {"acquisition_envelope", "run_envelope"},
}
FILENAME_CORRECT_RECORD = {
    "run-intent.json": "run_intent",
    "acquisition-intent.json": "acquisition_intent",
    "artifact-link-0000.json": "artifact_link",
    "registration-envelope.json": "acquisition_envelope",
}
WRONG_FILENAME_TYPE_CASES = tuple(
    (record_name, filename)
    for filename, allowed in FILENAME_ALLOWED_RECORDS.items()
    for record_name in RECORD_SPECS
    if record_name not in allowed
)


def journal_record(name: str) -> JournalModel:
    model, canonical = RECORD_SPECS[name]
    return with_computed_identity(model, json.loads(canonical))


def snapshot_store(root: Path) -> SnapshotStore:
    return SnapshotStore(
        root,
        free_bytes=lambda _: INITIAL_FREE_SPACE_FLOOR_BYTES,
    )


def committed_journal_files(store: SnapshotStore) -> tuple[Path, ...]:
    return tuple(
        path for path in store.root.rglob("*") if path.is_file() and path.name != ROOT_LOCK_FILENAME
    )


@pytest.mark.parametrize(
    ("record_name", "filename"),
    WRONG_FILENAME_TYPE_CASES,
)
def test_wrong_concrete_journal_type_cannot_poison_immutable_filename(
    tmp_path: Path,
    record_name: str,
    filename: str,
) -> None:
    store = snapshot_store(tmp_path / f"{record_name}-{filename}")
    correct_name = FILENAME_CORRECT_RECORD[filename]
    correct = journal_record(correct_name)

    with store.writer():
        with pytest.raises(ValueError, match="concrete record type"):
            write_immutable_record(
                store,
                "preallocated",
                filename,
                journal_record(record_name),
            )
        assert committed_journal_files(store) == ()
        path = write_immutable_record(
            store,
            "preallocated",
            filename,
            correct,
        )

    assert path.read_bytes() == correct.canonical_bytes()


@pytest.mark.parametrize(
    ("record_name", "filename"),
    [
        ("run_intent", "run-intent.json"),
        ("acquisition_intent", "acquisition-intent.json"),
        ("artifact_link", "artifact-link-0000.json"),
        ("acquisition_envelope", "registration-envelope.json"),
        ("run_envelope", "registration-envelope.json"),
    ],
)
def test_every_allowed_journal_filename_type_mapping_publishes(
    tmp_path: Path,
    record_name: str,
    filename: str,
) -> None:
    store = snapshot_store(tmp_path / record_name)
    record = journal_record(record_name)

    with store.writer():
        path = write_immutable_record(store, "preallocated", filename, record)

    assert path.read_bytes() == record.canonical_bytes()


def test_artifact_link_filename_must_match_ordinal_before_publication(
    tmp_path: Path,
) -> None:
    store = snapshot_store(tmp_path / "snapshots")
    ordinal_one = with_computed_identity(ArtifactLink, json.loads(LINK_1))
    ordinal_zero = journal_record("artifact_link")

    with store.writer():
        with pytest.raises(ValueError, match="ordinal"):
            write_immutable_record(
                store,
                "preallocated",
                "artifact-link-0000.json",
                ordinal_one,
            )
        assert committed_journal_files(store) == ()
        path = write_immutable_record(
            store,
            "preallocated",
            "artifact-link-0000.json",
            ordinal_zero,
        )

    assert path.read_bytes() == ordinal_zero.canonical_bytes()


def test_run_envelope_rejects_complete_indeterminate_state() -> None:
    payload = json.loads(RUN_ENVELOPE)
    payload["result_status"] = "indeterminate"
    with pytest.raises(ValidationError, match="indeterminate"):
        with_computed_identity(RunRegistrationEnvelope, payload)
