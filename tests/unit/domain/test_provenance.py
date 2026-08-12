"""Unit tests for source-neutral provenance and failure alignment."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from medevidence.domain import (
    DAILYMED_CONNECTOR_TRUST_ALLOWLIST,
    DAILYMED_HISTORICAL_ZIP_POLICY,
    DAILYMED_LOINC_SECTION_ALLOWLIST,
    DAILYMED_LOINC_SECTION_ORACLE,
    DAILYMED_XML_SECURITY_POLICY,
    MEDICAL_SOURCE_NETWORK_EXECUTION_AUTHORIZED,
    ORDINARY_VALIDATION_HOSTS,
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
    FailureCode,
    LoincSectionDefinition,
    Provenance,
    ResultStatus,
    SourceFailure,
    SourceOutcome,
    SourceType,
    sha256_digest,
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
