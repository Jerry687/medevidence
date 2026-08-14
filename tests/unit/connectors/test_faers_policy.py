from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime
from urllib.parse import parse_qs, urlsplit

import pytest
from pydantic import ValidationError

from medevidence.connectors.faers import (
    FAERS_COUNT_FIELD,
    FaersConnectorConfig,
    build_faers_request,
    serialize_faers_query,
    validate_connector_config,
    validate_faers_request,
    validate_faers_url,
)
from medevidence.connectors.faers.policy import parse_retry_after, retry_delay_seconds
from medevidence.domain import (
    FaersAggregateQueryV1,
    FaersAggregateRequestV1,
    FaersExecutionBoundsV1,
    FaersIdentityStrategy,
    FaersInclusiveDateRangeV1,
)


def _query(
    *,
    identity: str = "TEST DRUG",
    strategy: FaersIdentityStrategy = FaersIdentityStrategy.HARMONIZED_SUBSTANCE,
) -> FaersAggregateQueryV1:
    return FaersAggregateQueryV1.create(
        FaersAggregateRequestV1(
            drug_concept_id="drug:test",
            identity_strategy=strategy,
            identity_exact_value=identity,
            pt_values=("DIARRHOEA", "NAUSEA", "VOMITING"),
            inclusive_date_range=FaersInclusiveDateRangeV1(
                start_date=date(2025, 1, 1), end_date=date(2025, 12, 31)
            ),
            execution_bounds=FaersExecutionBoundsV1(
                max_date_difference_days=365,
                max_inclusive_calendar_dates=366,
            ),
            statistical_unit="provider_count_occurrence",
        )
    )


def test_serializer_emits_exact_closed_ast_order_and_no_role_clause() -> None:
    query = _query()
    expression = serialize_faers_query(query)
    assert expression == (
        'patient.drug.openfda.substance_name.exact:"TEST DRUG"+AND+'
        '(patient.reaction.reactionmeddrapt.exact:"DIARRHOEA"+OR+'
        'patient.reaction.reactionmeddrapt.exact:"NAUSEA"+OR+'
        'patient.reaction.reactionmeddrapt.exact:"VOMITING")+AND+'
        "receivedate:[20250101 TO 20251231]"
    )
    assert "+TO+" not in expression
    assert "role" not in expression.casefold()
    assert "receiptdate" not in expression
    assert expression.index(query.identity_field) < expression.index(query.group_field)
    assert expression.index(query.group_field) < expression.index("receivedate")


def test_native_identity_uses_only_its_exact_provider_field() -> None:
    expression = serialize_faers_query(
        _query(strategy=FaersIdentityStrategy.NATIVE_MEDICINAL_PRODUCT)
    )
    assert expression.startswith('patient.drug.medicinalproduct.exact:"TEST DRUG"')
    assert "openfda.substance_name" not in expression


def test_request_performs_once_only_utf8_percent_encoding_with_percent20_spaces() -> None:
    request = build_faers_request(_query(identity='CAFÉ \\ "TEST"'))
    parts = urlsplit(request.url)
    assert parts.scheme == "https"
    assert parts.netloc == "api.fda.gov"
    assert parts.path == "/drug/event.json"
    assert "+" not in parts.query
    assert "%20" in parts.query
    assert "%20TO%20" in parts.query
    assert "%2BTO%2B" not in parts.query
    assert "%2BAND%2B" in parts.query
    assert "%C3%89" in parts.query
    assert "%5C%5C" in parts.query
    assert "%5C%22TEST%5C%22" in parts.query
    assert "%25" not in parts.query
    assert "receivedate:[20250101 TO 20251231]" in request.provider_expression
    decoded = parse_qs(parts.query, strict_parsing=True)
    assert decoded == {
        "search": [request.provider_expression],
        "count": [FAERS_COUNT_FIELD],
        "limit": ["100"],
        "skip": ["0"],
    }


def test_request_rejects_preencoding_non_nfc_and_query_instance_drift() -> None:
    for identity in ("TEST%20DRUG", "CAFE\N{COMBINING ACUTE ACCENT}"):
        with pytest.raises(ValidationError):
            _query(identity=identity)

    query = _query()
    for field, value in (
        ("endpoint_path", "/foreign"),
        ("role_policy", "filtered"),
        ("group_field", "foreign"),
        ("pt_values", ("NAUSEA",)),
        ("effective_total_deadline_ms", 30_001),
    ):
        with pytest.raises((TypeError, ValueError, ValidationError)):
            build_faers_request(query.model_copy(update={field: value}))


def test_serialized_query_exact_512_boundary_and_plus_one() -> None:
    base_length = len(serialize_faers_query(_query(identity="A"))) - 1
    exact = "A" * (512 - base_length)
    assert len(serialize_faers_query(_query(identity=exact))) == 512
    with pytest.raises(ValueError, match="512"):
        serialize_faers_query(_query(identity=exact + "A"))


def test_request_page_and_url_are_derived_and_revalidated() -> None:
    query = _query()
    request = build_faers_request(query, page_number=5)
    assert request.skip == 400
    assert request.limit == 100
    assert validate_faers_request(request) == request
    assert validate_faers_url(request.url, request) == request.url
    for page in (0, 6, True, 1.0):
        with pytest.raises((TypeError, ValueError)):
            build_faers_request(query, page_number=page)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        validate_faers_url(request.url.replace("api.fda.gov", "example.invalid"), request)
    with pytest.raises(ValueError):
        validate_faers_url(request.url.replace("%2B", "+"), request)


def test_named_connector_profile_is_exact_and_non_weakenable() -> None:
    config = FaersConnectorConfig()
    assert validate_connector_config(config) == config
    assert config.total_deadline_seconds == 30.0
    assert config.max_attempts == 2
    assert config.max_redirects == 0
    assert config.max_response_bytes == config.max_cumulative_bytes == 5_242_880
    assert config.result_cache == "none" and config.stale_fallback is False
    for field, value in (
        ("total_deadline_seconds", 30.001),
        ("total_deadline_seconds", 60.0),
        ("max_attempts", 3),
        ("max_redirects", 1),
        ("max_payload_bytes", 5_242_881),
    ):
        actual_field = "max_response_bytes" if field == "max_payload_bytes" else field
        with pytest.raises(ValueError):
            replace(config, **{actual_field: value})


def test_retry_timing_is_bounded_and_canonical() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    assert parse_retry_after(None, now=now) is None
    assert parse_retry_after("99", now=now) == 10.0
    assert parse_retry_after("Thu, 01 Jan 2026 00:00:05 GMT", now=now) == 5.0
    assert parse_retry_after("invalid", now=now) is None
    assert retry_delay_seconds(1, jitter=0.0) == 0.25
    assert retry_delay_seconds(2, jitter=0.1) == 0.6
    with pytest.raises(ValueError):
        retry_delay_seconds(3, jitter=0.0)
    with pytest.raises(ValueError):
        retry_delay_seconds(1, jitter=0.101)
