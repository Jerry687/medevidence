"""Unit tests for source-neutral provenance and failure alignment."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from medevidence.domain import (
    CADEC_CORPUS_ID,
    CADEC_CORPUS_VERSION,
    CADEC_CP1252_MEMBER,
    CADEC_CP1252_MEMBER_SHA256,
    CADEC_EXTERNAL_MANIFEST_BYTES,
    CADEC_EXTERNAL_MANIFEST_SHA256,
    CADEC_LICENCE_DEED_SHA256,
    CADEC_LICENCE_RECORD_SHA256,
    CADEC_TERMINAL_FREEZE_AUDIT_BYTES,
    CADEC_TERMINAL_FREEZE_AUDIT_SHA256,
    DAILYMED_CONNECTOR_TRUST_ALLOWLIST,
    DAILYMED_HISTORICAL_ZIP_POLICY,
    DAILYMED_LOINC_SECTION_ALLOWLIST,
    DAILYMED_LOINC_SECTION_ORACLE,
    DAILYMED_XML_SECURITY_POLICY,
    FAERS_CONNECTOR_POLICY,
    FAERS_FRESHNESS_ORACLE,
    MEDICAL_SOURCE_NETWORK_EXECUTION_AUTHORIZED,
    ORDINARY_VALIDATION_HOSTS,
    CadecControlledVocabularyLayer,
    CadecCorpusAnnotationV1,
    CadecCorpusDocumentV1,
    CadecEncodingExceptionV1,
    CadecLicencePolicyV1,
    CadecProvenanceContextV1,
    CadecReferenceBindingLimitationSummaryV1,
    CadecReleaseManifestV1,
    CadecSplit,
    ControlledVocabularyRefV1,
    CoverageStatus,
    DailyMedConnectorTrustAllowlist,
    DailyMedHistoricalZipPolicy,
    DailyMedLoincSectionOracle,
    DailyMedRedirectPolicy,
    DailyMedTransportPolicy,
    DailyMedTrustPath,
    DailyMedXmlSecurityPolicy,
    DomainWarning,
    ExecutionBounds,
    ExecutionStatus,
    FaersFreshnessOracleV1,
    FaersTransportPolicyV1,
    FailureCode,
    LoincSectionDefinition,
    Provenance,
    ResultStatus,
    SourceFailure,
    SourceOutcome,
    SourceType,
    TextSpanSegmentV1,
    sha256_digest,
)


def cadec_document() -> CadecCorpusDocumentV1:
    provenance = CadecProvenanceContextV1.create(
        corpus_id=CADEC_CORPUS_ID,
        corpus_version=CADEC_CORPUS_VERSION,
        split=CadecSplit.TRAIN,
        artifact_id="artifact:synthetic-document",
        artifact_sha256=sha256_digest(b"synthetic document bytes"),
    )
    return CadecCorpusDocumentV1.create(
        corpus_id=provenance.corpus_id,
        corpus_version=provenance.corpus_version,
        split=provenance.split,
        artifact_id=provenance.artifact_id,
        artifact_sha256=provenance.artifact_sha256,
        document_id="SYNTHETIC.1",
        member_path="cadec/text/SYNTHETIC.1.txt",
        text_length=20,
        text_sha256=sha256_digest(b"synthetic text value"),
        provenance=provenance,
    )


def cadec_annotation() -> CadecCorpusAnnotationV1:
    document = cadec_document()
    provenance = CadecProvenanceContextV1.create(
        corpus_id=document.corpus_id,
        corpus_version=document.corpus_version,
        split=document.split,
        artifact_id="artifact:synthetic-annotation",
        artifact_sha256=sha256_digest(b"synthetic annotation bytes"),
        lineage_artifact_ids=(document.artifact_id,),
    )
    return CadecCorpusAnnotationV1.create(
        corpus_id=provenance.corpus_id,
        corpus_version=provenance.corpus_version,
        split=provenance.split,
        artifact_id=provenance.artifact_id,
        artifact_sha256=provenance.artifact_sha256,
        annotation_id="SYNTHETIC.1.ann.1",
        layer="original",
        member_path="cadec/original/SYNTHETIC.1.ann",
        document_id=document.document_id,
        document_artifact_id=document.artifact_id,
        document_text_sha256=document.text_sha256,
        spans=(TextSpanSegmentV1(ordinal=0, start_offset=2, end_offset=8),),
        surface_text_sha256=sha256_digest(b"span-value"),
        provenance=provenance,
    )


def test_cadec_external_evidence_encoding_and_reference_limitations_are_exact() -> None:
    manifest = CadecReleaseManifestV1.create()
    exception = CadecEncodingExceptionV1()
    summary = CadecReferenceBindingLimitationSummaryV1()

    assert (manifest.external_manifest_bytes, manifest.external_manifest_sha256) == (
        CADEC_EXTERNAL_MANIFEST_BYTES,
        CADEC_EXTERNAL_MANIFEST_SHA256,
    )
    assert (manifest.terminal_freeze_audit_bytes, manifest.terminal_freeze_audit_sha256) == (
        CADEC_TERMINAL_FREEZE_AUDIT_BYTES,
        CADEC_TERMINAL_FREEZE_AUDIT_SHA256,
    )
    assert (exception.member_path, exception.encoding, exception.sha256) == (
        CADEC_CP1252_MEMBER,
        "cp1252",
        CADEC_CP1252_MEMBER_SHA256,
    )
    assert (summary.original_term_count, summary.meddra_count, summary.sct_count) == (2, 44, 45)
    assert summary.total_count == 91
    assert "not_malformed" in summary.disposition


def test_cadec_release_and_licence_are_exact_closed_external_evidence() -> None:
    manifest = CadecReleaseManifestV1.create()
    licence = manifest.licence

    assert (manifest.corpus_id, manifest.corpus_version) == (
        CADEC_CORPUS_ID,
        CADEC_CORPUS_VERSION,
    )
    assert licence == CadecLicencePolicyV1()
    assert (licence.licence_name, licence.licence_id) == ("CSIRO Data Licence", 1061)
    assert licence.attribution_required is True
    assert licence.non_commercial_internal_research_only is True
    assert licence.intellectual_property_assertion_over_data_allowed is False
    assert licence.provider_accuracy_or_endorsement_may_be_implied is False
    assert licence.raw_archive_or_corpus_redistribution_allowed is False
    assert (licence.licence_record_sha256, licence.licence_deed_sha256) == (
        CADEC_LICENCE_RECORD_SHA256,
        CADEC_LICENCE_DEED_SHA256,
    )

    for field, value in (
        ("licence_id", 1062),
        ("attribution_required", False),
        ("non_commercial_internal_research_only", False),
        ("intellectual_property_assertion_over_data_allowed", True),
        ("provider_accuracy_or_endorsement_may_be_implied", True),
        ("raw_archive_or_corpus_redistribution_allowed", True),
    ):
        with pytest.raises(ValidationError):
            CadecLicencePolicyV1.model_validate({**licence.model_dump(mode="python"), field: value})


def test_controlled_vocabulary_contract_cannot_carry_restricted_payload() -> None:
    reference = ControlledVocabularyRefV1(
        reference=CadecControlledVocabularyLayer.MEDDRA,
    )
    assert reference.version == "not stated in retained provider/archive metadata"
    assert reference.legal_status == "reference-only"
    assert CadecReleaseManifestV1.create().controlled_vocabulary_refs == (
        reference,
        ControlledVocabularyRefV1(reference=CadecControlledVocabularyLayer.SNOMED_CT),
    )
    for forbidden in ("identifier", "term", "hierarchy", "payload"):
        with pytest.raises(ValidationError):
            ControlledVocabularyRefV1.model_validate(
                {**reference.model_dump(mode="python"), forbidden: "restricted"}
            )
    for field, value in (
        ("reference", "RxNorm"),
        ("version", "2026"),
        ("legal_status", "redistributable"),
        ("identifiers_emitted", True),
        ("terms_emitted", True),
        ("hierarchy_emitted", True),
        ("payload_emitted", True),
    ):
        with pytest.raises(ValidationError):
            ControlledVocabularyRefV1.model_validate(
                {**reference.model_dump(mode="python"), field: value}
            )


def _cadec_annotation_for_layer(
    layer: str,
    controlled_vocabulary_refs: tuple[ControlledVocabularyRefV1, ...],
) -> CadecCorpusAnnotationV1:
    original_annotation = cadec_annotation()
    annotation_data = original_annotation.model_dump(
        mode="python", exclude={"annotation_record_id"}
    )
    annotation_data.update(
        layer=layer,
        member_path=f"cadec/{layer}/{original_annotation.document_id}.ann",
        spans=original_annotation.spans,
        controlled_vocabulary_refs=controlled_vocabulary_refs,
        provenance=original_annotation.provenance,
    )
    return CadecCorpusAnnotationV1.create(**annotation_data)


def test_cadec_annotation_vocabulary_refs_are_exact_function_of_layer() -> None:
    meddra = ControlledVocabularyRefV1(reference=CadecControlledVocabularyLayer.MEDDRA)
    sct = ControlledVocabularyRefV1(reference=CadecControlledVocabularyLayer.SNOMED_CT)

    for layer, expected_refs in (
        ("original", ()),
        ("meddra", (meddra,)),
        ("sct", (sct,)),
    ):
        annotation = _cadec_annotation_for_layer(layer, expected_refs)
        assert annotation.layer == layer
        assert annotation.controlled_vocabulary_refs == expected_refs


def test_cadec_annotation_rejects_wrong_empty_extra_or_cross_layer_vocabulary_refs() -> None:
    meddra = ControlledVocabularyRefV1(reference=CadecControlledVocabularyLayer.MEDDRA)
    sct = ControlledVocabularyRefV1(reference=CadecControlledVocabularyLayer.SNOMED_CT)

    for layer, invalid_refs in (
        ("original", (meddra,)),
        ("meddra", ()),
        ("meddra", (sct,)),
        ("meddra", (meddra, sct)),
        ("sct", ()),
        ("sct", (meddra,)),
        ("sct", (sct, meddra)),
    ):
        with pytest.raises(
            ValidationError,
            match="controlled vocabulary references must exactly match the annotation layer",
        ):
            _cadec_annotation_for_layer(layer, invalid_refs)


def test_cadec_option_a_composites_spans_and_identities_round_trip() -> None:
    document = cadec_document()
    annotation = cadec_annotation()

    annotation.validate_against(document, CadecReleaseManifestV1.create())
    assert CadecCorpusDocumentV1.model_validate_json(document.model_dump_json()) == document
    assert CadecCorpusAnnotationV1.model_validate_json(annotation.model_dump_json()) == annotation
    assert annotation.origin.value == "provider_gold"
    assert annotation.spans[0].start_offset == 2
    assert annotation.spans[0].end_offset == 8


def test_cadec_document_allows_zero_text_length() -> None:
    document = cadec_document()
    zero = CadecCorpusDocumentV1.create(
        **{
            **document.model_dump(
                mode="python", exclude={"document_record_id", "text_length", "provenance"}
            ),
            "text_length": 0,
            "provenance": document.provenance,
        }
    )

    assert zero.text_length == 0
    assert zero.schema_version == "m1b.cadec.document.v1"


def test_cadec_document_rejects_negative_text_length() -> None:
    document = cadec_document()
    with pytest.raises(ValidationError):
        CadecCorpusDocumentV1.model_validate(
            {**document.model_dump(mode="python"), "text_length": -1}
        )


def test_cadec_positive_text_length_contract_is_unchanged() -> None:
    document = cadec_document()

    assert document.text_length == 20
    document.validate_against(CadecReleaseManifestV1.create())


def test_cadec_zero_length_document_identity_remains_content_derived() -> None:
    document = cadec_document()
    data = document.model_dump(
        mode="python", exclude={"document_record_id", "text_length", "provenance"}
    )
    data["provenance"] = document.provenance
    first = CadecCorpusDocumentV1.create(**data, text_length=0)
    second = CadecCorpusDocumentV1.create(**data, text_length=0)

    assert first.document_record_id == second.document_record_id
    assert first.document_record_id != document.document_record_id


def test_cadec_zero_length_document_binds_exact_release_split_and_provenance() -> None:
    document = cadec_document()
    zero = CadecCorpusDocumentV1.create(
        **{
            **document.model_dump(
                mode="python", exclude={"document_record_id", "text_length", "provenance"}
            ),
            "text_length": 0,
            "provenance": document.provenance,
        }
    )

    zero.validate_against(CadecReleaseManifestV1.create())
    assert zero.split is CadecSplit.TRAIN
    assert zero.provenance.artifact_id == zero.artifact_id
    assert zero.provenance.lineage_artifact_ids == ()


def test_cadec_mismatch_is_distinct_from_frozen_malformed_row_rejection() -> None:
    document = cadec_document()
    original_annotation = cadec_annotation()
    annotation_data = original_annotation.model_dump(
        mode="python", exclude={"annotation_record_id"}
    )
    annotation_data.update(
        document_id="SYNTHETIC.2",
        member_path="cadec/original/SYNTHETIC.2.ann",
        spans=original_annotation.spans,
        controlled_vocabulary_refs=original_annotation.controlled_vocabulary_refs,
        provenance=original_annotation.provenance,
    )
    annotation = CadecCorpusAnnotationV1.create(**annotation_data)
    with pytest.raises(ValueError, match="does not match its exact document composite"):
        annotation.validate_against(document, CadecReleaseManifestV1.create())

    assert (
        CadecReleaseManifestV1.create().malformed_row_policy == "reject_never_repair_or_reinterpret"
    )


def test_cadec_rejects_nfc_span_order_and_existing_instance_bypasses() -> None:
    with pytest.raises(ValidationError):
        CadecProvenanceContextV1.create(
            corpus_id=CADEC_CORPUS_ID,
            corpus_version="e\u0301",
            split=CadecSplit.TRAIN,
            artifact_id="artifact:synthetic",
            artifact_sha256=sha256_digest(b"synthetic"),
        )
    with pytest.raises(ValidationError):
        TextSpanSegmentV1(ordinal=0, start_offset=3, end_offset=3)

    annotation = cadec_annotation()
    forged_span = annotation.spans[0].model_copy(update={"end_offset": 0})
    forged = annotation.model_copy(update={"spans": (forged_span,)})
    with pytest.raises(ValidationError):
        CadecCorpusAnnotationV1.model_validate(forged)


def test_cadec_release_admission_member_labels_and_lineage_fail_closed() -> None:
    release = CadecReleaseManifestV1.create()
    document = cadec_document()
    annotation = cadec_annotation()

    document.validate_against(release)
    annotation.validate_against(document, release)

    for change in (
        {"document_id": "DICLOFENAC-SODIUM.7", "member_path": "cadec/text/DICLOFENAC-SODIUM.7.txt"},
        {"document_id": "../SYNTHETIC.1", "member_path": "cadec/text/../SYNTHETIC.1.txt"},
        {"member_path": "../cadec/text/SYNTHETIC.1.txt"},
    ):
        with pytest.raises(ValidationError):
            CadecCorpusDocumentV1.model_validate(
                document.model_copy(update=change).model_dump(mode="python")
            )

    foreign_release = release.model_copy(update={"external_manifest_sha256": "0" * 64})
    with pytest.raises(ValidationError):
        document.validate_against(foreign_release)

    missing_lineage = annotation.model_copy(
        update={"provenance": annotation.provenance.model_copy(update={"lineage_artifact_ids": ()})}
    )
    with pytest.raises(ValidationError):
        missing_lineage.validate_against(document, release)

    cross_split = annotation.model_copy(update={"split": CadecSplit.DEVELOPMENT})
    with pytest.raises(ValidationError):
        cross_split.validate_against(document, release)


def test_cadec_annotation_validate_against_rejects_forged_self_fields() -> None:
    release = CadecReleaseManifestV1.create()
    document = cadec_document()
    annotation = cadec_annotation()
    forged_values = (
        {"annotation_record_id": "annotation:forged"},
        {"reference_binding_limited": True},
        {"spans": (annotation.spans[0].model_copy(update={"end_offset": 0}),)},
        {"provenance": annotation.provenance.model_copy(update={"artifact_id": "artifact:forged"})},
    )
    for changes in forged_values:
        with pytest.raises(ValidationError):
            annotation.model_copy(update=changes).validate_against(document, release)


def test_faers_transport_and_freshness_are_exact_non_authorizing_metadata() -> None:
    policy = FAERS_CONNECTOR_POLICY
    assert policy.host == "api.fda.gov"
    assert policy.path == "/drug/event.json"
    assert policy.max_redirects == 0
    assert policy.acquisition_deadline_ms == 30_000
    assert policy.ordinary_validation_hosts == ()
    assert policy.medical_source_network_execution_authorized is False
    assert FAERS_FRESHNESS_ORACLE.authorizes_network_io is False
    assert FAERS_FRESHNESS_ORACLE.result_cache == "none"
    assert FAERS_FRESHNESS_ORACLE.stale_fallback is False

    for field, value in (
        ("host", "example.org"),
        ("path", "/other"),
        ("max_redirects", 1),
        ("max_attempts", 3),
        ("acquisition_deadline_ms", 60_000),
        ("max_response_bytes", 5_242_881),
        ("ordinary_validation_hosts", ("api.fda.gov",)),
        ("medical_source_network_execution_authorized", True),
    ):
        with pytest.raises(ValidationError):
            FaersTransportPolicyV1(**{**policy.model_dump(mode="python"), field: value})

    for field, value in (
        ("result_cache", "memory"),
        ("stale_fallback", True),
        ("authorizes_network_io", True),
    ):
        with pytest.raises(ValidationError):
            FaersFreshnessOracleV1(
                **{**FAERS_FRESHNESS_ORACLE.model_dump(mode="python"), field: value}
            )


def bounds() -> ExecutionBounds:
    return ExecutionBounds(
        max_query_characters=512,
        max_pages=5,
        max_records=100,
        max_payload_bytes=5_242_880,
        max_total_seconds=60,
    )


def complete_outcome() -> SourceOutcome:
    return SourceOutcome(
        source=SourceType.PUBMED,
        query_id="query:one",
        execution_status=ExecutionStatus.SUCCEEDED,
        coverage_status=CoverageStatus.COMPLETE,
        result_status=ResultStatus.MATCHES,
        configured_bounds=bounds(),
        valid_result_count=1,
        pages_completed=1,
        truncated=False,
    )


def successful_provenance() -> Provenance:
    return Provenance(
        source=SourceType.PUBMED,
        source_record_id="12345",
        query_id="query:one",
        source_lookup_key="pubmed:12345",
        retrieved_at=datetime(2026, 7, 27, 12, 0, tzinfo=UTC),
        connector_version="fixture-1.0",
        content_hash=sha256_digest(b"raw publication bytes"),
        snapshot_id=None,
        artifact_ids=(),
        transformation_lineage=(),
        warnings=(),
        failure=None,
        source_outcome=complete_outcome(),
        configured_bounds=bounds(),
    )


def test_provenance_serializes_utc_with_z_and_round_trips() -> None:
    provenance = successful_provenance()
    serialized = provenance.model_dump_json()

    assert '"retrieved_at":"2026-07-27T12:00:00Z"' in serialized
    assert Provenance.model_validate_json(serialized) == provenance


@pytest.mark.parametrize(
    "timestamp",
    [
        datetime(2026, 7, 27, 12, 0),
        datetime(2026, 7, 27, 12, 0, tzinfo=timezone(timedelta(hours=1))),
    ],
)
def test_provenance_rejects_naive_and_non_utc_timestamps(
    timestamp: datetime,
) -> None:
    data = successful_provenance().model_dump(mode="python")
    data["retrieved_at"] = timestamp
    with pytest.raises(ValidationError):
        Provenance(**data)


def test_failed_unavailable_provenance_preserves_typed_failure_without_record() -> None:
    outcome = SourceOutcome(
        source=SourceType.PUBMED,
        query_id="query:failed",
        execution_status=ExecutionStatus.FAILED,
        coverage_status=CoverageStatus.UNAVAILABLE,
        result_status=ResultStatus.INDETERMINATE,
        configured_bounds=bounds(),
        valid_result_count=0,
        pages_completed=0,
        truncated=False,
        warning_codes=("source_unavailable",),
        failure_id="failure:timeout",
    )
    provenance = Provenance(
        source=SourceType.PUBMED,
        source_record_id=None,
        query_id="query:failed",
        source_lookup_key="pubmed:bounded-query",
        retrieved_at=datetime(2026, 7, 27, 12, 0, tzinfo=UTC),
        connector_version="fixture-1.0",
        content_hash=sha256_digest(b""),
        warnings=(
            DomainWarning(
                code="source_unavailable",
                message="No usable source response was obtained.",
            ),
        ),
        failure=SourceFailure(
            failure_id="failure:timeout",
            failure_code=FailureCode.TIMEOUT,
            retryable=True,
        ),
        source_outcome=outcome,
        configured_bounds=bounds(),
    )

    assert provenance.source_record_id is None
    assert provenance.failure is not None
    assert provenance.failure.failure_code is FailureCode.TIMEOUT


@pytest.mark.parametrize(
    "changes",
    [
        {"source": SourceType.CADEC},
        {"query_id": "query:other"},
        {
            "configured_bounds": ExecutionBounds(
                max_query_characters=100,
                max_pages=1,
                max_records=1,
                max_payload_bytes=100,
                max_total_seconds=1,
            )
        },
        {
            "warnings": (
                DomainWarning(code="z_warning", message="z"),
                DomainWarning(code="a_warning", message="a"),
            )
        },
    ],
)
def test_provenance_rejects_source_query_bounds_and_warning_drift(
    changes: dict[str, object],
) -> None:
    data = successful_provenance().model_dump(mode="python")
    data.update(changes)
    with pytest.raises(ValidationError):
        Provenance(**data)


def test_provenance_is_strict_frozen_and_forbids_extras() -> None:
    provenance = successful_provenance()
    with pytest.raises(ValidationError):
        provenance.query_id = "query:mutated"
    with pytest.raises(ValidationError):
        Provenance(
            **{
                **provenance.model_dump(mode="python"),
                "provider_response": object(),
            }
        )


def test_dailymed_connector_trust_metadata_is_closed_and_non_authorizing() -> None:
    trust = DAILYMED_CONNECTOR_TRUST_ALLOWLIST
    assert trust.authorizes_network_io is False
    assert trust.ordinary_validation_hosts == ORDINARY_VALIDATION_HOSTS == ()
    assert MEDICAL_SOURCE_NETWORK_EXECUTION_AUTHORIZED is False
    assert (trust.scheme, trust.host, trust.port, trust.methods) == (
        "https",
        "dailymed.nlm.nih.gov",
        443,
        ("GET",),
    )
    assert trust.redirect.model_dump(mode="python") == {
        "maximum": 1,
        "scheme": "https",
        "host": "dailymed.nlm.nih.gov",
        "port": 443,
        "cross_host_allowed": False,
    }
    assert tuple(path.path_template for path in trust.paths) == (
        "/dailymed/services/v2/spls.json",
        "/dailymed/services/v2/spls/{SETID}/history.json",
        "/dailymed/services/v2/spls/{SETID}/ndcs.json",
        "/dailymed/services/v2/spls/{SETID}/packaging.json",
        "/dailymed/services/v2/spls/{SETID}.xml",
        "/dailymed/getFile.cfm",
    )
    assert trust.paths[-1].exact_query == (
        ("type", "zip"),
        ("setid", "{SETID}"),
        ("version", "{SPL_VERSION}"),
    )
    assert trust.denied == (
        "http",
        "alternate_hosts",
        "v1_services",
        "arbitrary_resource_paths",
        "media_endpoints",
        "pdf_endpoints",
        "bulk_downloads",
        "mapping_file_downloads",
        "caller_supplied_urls",
        "arbitrary_query_keys",
        "fragments",
        "userinfo",
        "cross_host_redirects",
    )
    assert trust.transport.model_dump(mode="python") == {
        "connect_seconds": 5,
        "read_seconds": 10,
        "write_seconds": 5,
        "pool_seconds": 5,
        "total_seconds": 30,
        "max_attempts": 2,
        "backoff_base_ms": 250,
        "backoff_cap_seconds": 4,
        "jitter_max_ms": 100,
        "retry_after_cap_seconds": 10,
        "retryable": ("connect_timeout", "read_timeout", "408", "429", "5xx"),
        "permanent": (
            "other_4xx",
            "parse_failure",
            "identity_drift",
            "integrity_failure",
        ),
        "discovery_max_pages": 5,
        "discovery_max_candidates": 100,
        "cumulative_payload_bytes": 5_242_880,
        "response_bytes": 5_242_880,
        "fixed_version_cache": "immutable",
        "latest_discovery_cache": "none",
        "stale_fallback": False,
    }
    with pytest.raises(ValidationError):
        DailyMedConnectorTrustAllowlist.model_validate(
            {
                **trust.model_dump(mode="python"),
                "paths": tuple(reversed(trust.paths)),
            }
        )


def test_each_standalone_dailymed_trust_path_is_exactly_one_frozen_row() -> None:
    for path in DAILYMED_CONNECTOR_TRUST_ALLOWLIST.paths:
        assert DailyMedTrustPath.model_validate(path.model_dump(mode="python")) == path
        assert DailyMedTrustPath.model_validate_json(path.model_dump_json()) == path


def test_standalone_dailymed_trust_path_rejects_every_row_drift() -> None:
    discovery = DAILYMED_CONNECTOR_TRUST_ALLOWLIST.paths[0]
    historical = DAILYMED_CONNECTOR_TRUST_ALLOWLIST.paths[-1]
    discovery_payload = discovery.model_dump(mode="python")
    historical_payload = historical.model_dump(mode="python")

    for payload in (
        {**discovery_payload, "path_template": "/dailymed/services/v2/foreign.json"},
        {**discovery_payload, "purpose": "foreign_purpose"},
        {
            **discovery_payload,
            "allowed_query_keys": (*discovery.allowed_query_keys, "unauthorized"),
        },
        {
            **historical_payload,
            "exact_query": (("type", "xml"), *historical.exact_query[1:]),
        },
    ):
        with pytest.raises(ValidationError, match="exact frozen row"):
            DailyMedTrustPath.model_validate(payload)

    for field, values in (
        ("allowed_query_keys", discovery.allowed_query_keys),
        ("exact_query", historical.exact_query),
    ):
        base = discovery_payload if field == "allowed_query_keys" else historical_payload
        for drifted in (
            values[:-1],
            (*values, values[-1]),
            tuple(reversed(values)),
        ):
            with pytest.raises(ValidationError):
                DailyMedTrustPath.model_validate({**base, field: drifted})


def weakened_policy_value(value: object) -> object:
    if isinstance(value, bool):
        return not value
    if isinstance(value, int):
        return value + 1
    if isinstance(value, str):
        return f"{value}-drift"
    if isinstance(value, tuple):
        return (*value, value[-1]) if value else ("unexpected",)
    raise AssertionError(f"unsupported frozen policy value: {value!r}")


@pytest.mark.parametrize(
    "canonical",
    (
        DAILYMED_CONNECTOR_TRUST_ALLOWLIST.paths[0],
        DailyMedRedirectPolicy(),
        DailyMedTransportPolicy(),
        DAILYMED_XML_SECURITY_POLICY,
        DAILYMED_HISTORICAL_ZIP_POLICY,
    ),
)
def test_dailymed_policy_instances_revalidate_every_security_field(canonical: object) -> None:
    model_type = type(canonical)
    for field in model_type.model_fields:
        drifted = canonical.model_copy(
            update={field: weakened_policy_value(getattr(canonical, field))}
        )
        with pytest.raises(ValidationError):
            model_type.model_validate(drifted)


def test_connector_revalidates_drifted_nested_policy_instances() -> None:
    trust = DAILYMED_CONNECTOR_TRUST_ALLOWLIST
    nested_drifts = (
        {"redirect": trust.redirect.model_copy(update={"maximum": 0})},
        {"transport": trust.transport.model_copy(update={"connect_seconds": 6})},
        {
            "paths": (
                trust.paths[0].model_copy(update={"purpose": "foreign_purpose"}),
                *trust.paths[1:],
            )
        },
    )
    for change in nested_drifts:
        with pytest.raises(ValidationError):
            DailyMedConnectorTrustAllowlist.model_validate(trust.model_copy(update=change))

    nested_fields = {field for change in nested_drifts for field in change}
    for field in type(trust).model_fields.keys() - nested_fields:
        drifted = trust.model_copy(update={field: weakened_policy_value(getattr(trust, field))})
        with pytest.raises(ValidationError):
            DailyMedConnectorTrustAllowlist.model_validate(drifted)


def tuple_drifts(values: tuple[object, ...]) -> tuple[tuple[object, ...], ...]:
    candidates = (
        (),
        values[:-1],
        tuple(reversed(values)),
        (*values, values[-1]),
    )
    return tuple(candidate for candidate in candidates if candidate != values)


@pytest.mark.parametrize("field", ["retryable", "permanent"])
def test_dailymed_transport_rejects_every_closed_tuple_weakening(field: str) -> None:
    canonical = DailyMedTransportPolicy()
    values = getattr(canonical, field)
    for drifted in tuple_drifts(values):
        with pytest.raises(ValidationError):
            DailyMedTransportPolicy.model_validate(
                {**canonical.model_dump(mode="python"), field: drifted}
            )


def test_dailymed_connector_rejects_tuple_nested_and_scalar_drift() -> None:
    trust = DAILYMED_CONNECTOR_TRUST_ALLOWLIST
    payload = trust.model_dump(mode="python")
    for field in ("methods", "denied", "paths"):
        values = getattr(trust, field)
        for drifted in tuple_drifts(values):
            with pytest.raises(ValidationError):
                DailyMedConnectorTrustAllowlist.model_validate({**payload, field: drifted})

    weakened_transport = {
        **trust.transport.model_dump(mode="python"),
        "retryable": ("429",),
    }
    with pytest.raises(ValidationError):
        DailyMedConnectorTrustAllowlist.model_validate({**payload, "transport": weakened_transport})
    with pytest.raises(ValidationError):
        DailyMedConnectorTrustAllowlist.model_validate(
            {**payload, "transport": {**payload["transport"], "connect_seconds": 6}}
        )
    with pytest.raises(ValidationError):
        DailyMedConnectorTrustAllowlist.model_validate(
            {**payload, "redirect": {**payload["redirect"], "maximum": 0}}
        )
    assert DailyMedConnectorTrustAllowlist.model_validate_json(trust.model_dump_json()) == trust
    assert DailyMedRedirectPolicy.model_validate_json(trust.redirect.model_dump_json()) == (
        trust.redirect
    )
    assert DailyMedTransportPolicy.model_validate_json(trust.transport.model_dump_json()) == (
        trust.transport
    )


def test_dailymed_zip_and_xml_security_metadata_freezes_all_exact_bounds() -> None:
    zip_policy = DAILYMED_HISTORICAL_ZIP_POLICY
    assert zip_policy.filesystem_extraction is False
    assert zip_policy.max_http_or_compressed_bytes == 5_242_880
    assert zip_policy.max_total_uncompressed_bytes == 5_242_880
    assert zip_policy.max_member_uncompressed_bytes == 5_242_880
    assert zip_policy.max_entries == 128
    assert zip_policy.rejected_ascii_codepoints == (*tuple(range(32)), 127)
    assert all(ord(character) in zip_policy.rejected_ascii_codepoints for character in "\n\r\t")
    assert 0 in zip_policy.rejected_ascii_codepoints
    assert 31 in zip_policy.rejected_ascii_codepoints
    assert 127 in zip_policy.rejected_ascii_codepoints

    xml_policy = DAILYMED_XML_SECURITY_POLICY
    assert xml_policy.candidate_root == "{urn:hl7-org:v3}document"
    assert xml_policy.maximum_depth == 64
    assert xml_policy.maximum_elements == 50_000
    assert xml_policy.maximum_attributes_per_element == 64
    assert xml_policy.maximum_decoded_characters == 5_000_000
    assert xml_policy.maximum_text_node_characters == 262_144
    assert xml_policy.maximum_label_sections == 128
    assert xml_policy.additional_safe_attributes == "permitted_semantically_inert"
    assert xml_policy.setid_element_count == xml_policy.version_element_count == 1
    assert xml_policy.setid_identity_attribute == "unqualified root"
    assert xml_policy.version_identity_attribute == "unqualified value"
    assert xml_policy.namespaced_or_local_name_attribute_lookalikes_count is False
    assert xml_policy.nested_selector_elements_count is False
    assert xml_policy.dtd_allowed is False
    assert xml_policy.entity_declarations_allowed is False
    assert xml_policy.xinclude_allowed is False
    assert xml_policy.schema_resolution_allowed is False
    assert xml_policy.xslt_allowed is False
    assert xml_policy.recovery_mode_allowed is False
    assert xml_policy.external_io_allowed is False
    assert zip_policy.directories == "allowed_non_evidence"
    assert zip_policy.unsafe_name_never_normalized_into_acceptance is True
    assert zip_policy.ascii_control_rejection_count == 33
    assert zip_policy.xml_member_suffix_match == "case_insensitive_.xml"
    assert zip_policy.xml_classification_parser == "frozen_defusedxml_fail_closed"
    assert zip_policy.exact_candidate_count == 1
    assert zip_policy.multiple_candidates == (
        "reject_even_if_exactly_one_matches_selected_identity"
    )
    assert zip_policy.member_or_filename_identity_evidence is False
    assert zip_policy.safe_non_xml_attachments == (
        "permitted_but_nonauthoritative_and_not_retained_as_label_evidence"
    )
    with pytest.raises(ValidationError):
        DailyMedXmlSecurityPolicy.model_validate(
            {**xml_policy.model_dump(mode="python"), "setid_element_count": 2}
        )
    with pytest.raises(ValidationError):
        DailyMedHistoricalZipPolicy.model_validate(
            {**zip_policy.model_dump(mode="python"), "max_entries": 129}
        )


def test_dailymed_xml_policy_rejects_tuple_and_representative_scalar_drift() -> None:
    policy = DAILYMED_XML_SECURITY_POLICY
    payload = policy.model_dump(mode="python")
    values = policy.additional_safe_attributes_never_affect
    for drifted in tuple_drifts(values):
        with pytest.raises(ValidationError):
            DailyMedXmlSecurityPolicy.model_validate(
                {**payload, "additional_safe_attributes_never_affect": drifted}
            )
    for changes in (
        {"dtd_allowed": True},
        {"maximum_depth": 63},
        {"external_io_allowed": True},
    ):
        with pytest.raises(ValidationError):
            DailyMedXmlSecurityPolicy.model_validate({**payload, **changes})
    assert DailyMedXmlSecurityPolicy.model_validate_json(policy.model_dump_json()) == policy


@pytest.mark.parametrize(
    "field",
    ["rejected_ascii_codepoints", "member_name_reject", "rejected_path_classes"],
)
def test_dailymed_zip_policy_rejects_every_closed_tuple_weakening(field: str) -> None:
    policy = DAILYMED_HISTORICAL_ZIP_POLICY
    payload = policy.model_dump(mode="python")
    values = getattr(policy, field)
    for drifted in tuple_drifts(values):
        with pytest.raises(ValidationError):
            DailyMedHistoricalZipPolicy.model_validate({**payload, field: drifted})


def test_dailymed_zip_policy_rejects_representative_scalar_drift_and_round_trips() -> None:
    policy = DAILYMED_HISTORICAL_ZIP_POLICY
    payload = policy.model_dump(mode="python")
    for changes in (
        {"max_entries": 127},
        {"filesystem_extraction": True},
        {"xml_member_suffix_match": "case_sensitive_.xml"},
    ):
        with pytest.raises(ValidationError):
            DailyMedHistoricalZipPolicy.model_validate({**payload, **changes})
    assert DailyMedHistoricalZipPolicy.model_validate_json(policy.model_dump_json()) == policy


def test_loinc_282_registry_is_the_exact_four_code_title_oracle() -> None:
    assert DAILYMED_LOINC_SECTION_ORACLE.model_dump(mode="python", exclude={"entries"}) == {
        "schema_version": "m1b.dailymed.loinc-section-allowlist.v1",
        "authority": "LOINC",
        "steward": "Regenstrief Institute, Inc.",
        "code_system": "http://loinc.org",
        "release": "2.82",
        "mapping_mode": "exact_code_title_pair_not_fuzzy_alias",
        "expansion_requires_new_owner_decision": True,
    }
    assert tuple(
        (entry.code, entry.title, entry.status, entry.evidence_url)
        for entry in DAILYMED_LOINC_SECTION_ALLOWLIST
    ) == (
        (
            "34084-4",
            "FDA package insert Adverse reactions section",
            "Active",
            "https://loinc.org/34084-4",
        ),
        (
            "43685-7",
            "FDA package insert Warnings and precautions section",
            "Active",
            "https://loinc.org/43685-7",
        ),
        (
            "34066-1",
            "FDA package insert Boxed warning section",
            "Active",
            "https://loinc.org/34066-1",
        ),
        (
            "34067-9",
            "FDA package insert Indications and usage section",
            "Active",
            "https://loinc.org/34067-9",
        ),
    )
    with pytest.raises(ValidationError):
        DailyMedLoincSectionOracle.model_validate(
            {
                **DAILYMED_LOINC_SECTION_ORACLE.model_dump(mode="python"),
                "entries": tuple(reversed(DAILYMED_LOINC_SECTION_ALLOWLIST)),
            }
        )


def test_standalone_loinc_rows_are_exact_one_of_four_and_revalidated() -> None:
    rows = DAILYMED_LOINC_SECTION_ALLOWLIST
    for row in rows:
        assert LoincSectionDefinition.model_validate(row) == row
        assert LoincSectionDefinition.model_validate_json(row.model_dump_json()) == row

        for field in type(row).model_fields:
            drifted = row.model_copy(update={field: weakened_policy_value(getattr(row, field))})
            with pytest.raises(ValidationError):
                LoincSectionDefinition.model_validate(drifted)

    mixed = rows[0].model_copy(update={"title": rows[1].title})
    with pytest.raises(ValidationError, match="exact frozen row"):
        LoincSectionDefinition.model_validate(mixed)


def test_loinc_oracle_revalidates_every_field_and_nested_row_instance() -> None:
    oracle = DAILYMED_LOINC_SECTION_ORACLE
    for field in type(oracle).model_fields:
        if field == "entries":
            drifted_value: object = (
                oracle.entries[0].model_copy(
                    update={"evidence_url": oracle.entries[1].evidence_url}
                ),
                *oracle.entries[1:],
            )
        else:
            drifted_value = weakened_policy_value(getattr(oracle, field))
        with pytest.raises(ValidationError):
            DailyMedLoincSectionOracle.model_validate(
                oracle.model_copy(update={field: drifted_value})
            )
