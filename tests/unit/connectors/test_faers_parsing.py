from __future__ import annotations

import json
from pathlib import Path

import pytest

from medevidence.connectors.faers import (
    FaersParseError,
    parse_count_page,
    parse_error_envelope,
)
from medevidence.connectors.faers.parsing import MAX_PROVIDER_COUNT

FIXTURES = Path(__file__).parents[2] / "fixtures" / "faers"
RAW_FIXTURES = (
    "raw-single-latest.json",
    "raw-multi-version.json",
    "raw-repeated-pt-multi-drug.json",
    "raw-version-tie.json",
    "raw-missing-harmonization.json",
    "raw-truncated-page.json",
)


def test_count_fixtures_parse_exact_bucket_empty_and_error_envelopes() -> None:
    single = parse_count_page((FIXTURES / "count-single-bucket.json").read_bytes())
    assert [(item.reaction_pt, item.report_count) for item in single.buckets] == [("NAUSEA", 7)]
    assert single.provider_record_total == 1000
    assert single.provider_as_of_utc is not None
    empty = parse_count_page((FIXTURES / "count-empty.json").read_bytes())
    assert empty.buckets == () and empty.provider_record_total == 0
    error = parse_error_envelope((FIXTURES / "error-429.json").read_bytes())
    assert error.code == "OVER_RATE_LIMIT"
    assert error.message == "synthetic rate limit"


def test_parser_canonicalizes_count_desc_pt_asc_and_retains_ties() -> None:
    payload = json.dumps(
        {
            "results": [
                {"term": "VOMITING", "count": 3},
                {"term": "NAUSEA", "count": 7},
                {"term": "DIARRHOEA", "count": 7},
            ]
        }
    ).encode()
    page = parse_count_page(payload)
    assert [(item.reaction_pt, item.report_count) for item in page.buckets] == [
        ("DIARRHOEA", 7),
        ("NAUSEA", 7),
        ("VOMITING", 3),
    ]


@pytest.mark.parametrize("fixture_name", RAW_FIXTURES)
def test_raw_mode_fixture_is_adversarial_rejection_only(fixture_name: str) -> None:
    with pytest.raises(FaersParseError):
        parse_count_page((FIXTURES / fixture_name).read_bytes())


def test_malformed_fixture_and_invalid_utf8_reject() -> None:
    with pytest.raises(FaersParseError):
        parse_count_page((FIXTURES / "malformed.json").read_bytes())
    with pytest.raises(FaersParseError):
        parse_count_page(b"\xff")


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"results": {}},
        {"results": [{"term": "NAUSEA"}]},
        {"results": [{"term": "UNKNOWN", "count": 1}]},
        {"results": [{"term": "Nausea", "count": 1}]},
        {"results": [{"term": "NAUSEA", "count": -1}]},
        {"results": [{"term": "NAUSEA", "count": True}]},
        {"results": [{"term": "NAUSEA", "count": 1, "patient": {}}]},
        {"results": [{"term": "NAUSEA", "count": 1}], "foreign": 1},
    ],
)
def test_count_parser_rejects_open_or_non_count_shapes(payload: object) -> None:
    with pytest.raises(FaersParseError):
        parse_count_page(json.dumps(payload).encode())


def test_fixture_inventory_is_exact_synthetic_and_narrative_free() -> None:
    assert tuple(sorted(path.name for path in FIXTURES.iterdir())) == tuple(
        sorted(
            (
                "count-single-bucket.json",
                "count-empty.json",
                "error-429.json",
                "malformed.json",
                *RAW_FIXTURES,
            )
        )
    )
    forbidden = (
        "patient",
        "narrative",
        "outcome",
        "reporter",
        "geography",
        "safetyreportid",
        "drugcharacterization",
    )
    combined = b"\n".join(path.read_bytes().lower() for path in FIXTURES.iterdir())
    assert all(token.encode() not in combined for token in forbidden)


def test_payload_byte_boundary_is_enforced_before_json_decode() -> None:
    with pytest.raises(FaersParseError, match="byte bound"):
        parse_count_page(b" " * 5_242_881)


@pytest.mark.parametrize(
    "payload",
    [
        b'{"results":[],"results":[]}',
        b'{"meta":{"results":{"skip":0,"skip":0,"limit":100,"total":0}},"results":[]}',
        b'{"results":[{"term":"NAUSEA","term":"NAUSEA","count":1}]}',
        b'{"error":{"code":"X","code":"X","message":"synthetic"}}',
    ],
)
def test_parser_rejects_duplicate_json_names_at_every_nesting_level(payload: bytes) -> None:
    parser = parse_error_envelope if b'"error"' in payload else parse_count_page
    with pytest.raises(FaersParseError, match="valid UTF-8 JSON"):
        parser(payload)


def test_count_accepts_exact_signed_bigint_max_and_rejects_plus_one() -> None:
    accepted = json.dumps({"results": [{"term": "NAUSEA", "count": MAX_PROVIDER_COUNT}]}).encode()
    assert parse_count_page(accepted).buckets[0].report_count == MAX_PROVIDER_COUNT
    rejected = json.dumps(
        {"results": [{"term": "NAUSEA", "count": MAX_PROVIDER_COUNT + 1}]}
    ).encode()
    with pytest.raises(FaersParseError, match="bounded"):
        parse_count_page(rejected)


@pytest.mark.parametrize("total", [101, 1_000_000, MAX_PROVIDER_COUNT])
def test_provider_record_total_is_distinct_from_bucket_cardinality(total: int) -> None:
    payload = json.dumps(
        {
            "meta": {"results": {"skip": 0, "limit": 100, "total": total}},
            "results": [{"term": "NAUSEA", "count": 7}],
        }
    ).encode()
    page = parse_count_page(payload)
    assert page.provider_record_total == total
    assert len(page.buckets) == 1
    assert page.next_page is None


@pytest.mark.parametrize("total", [-1, True, MAX_PROVIDER_COUNT + 1])
def test_provider_record_total_rejects_invalid_or_overflow_values(total: object) -> None:
    payload = json.dumps(
        {
            "meta": {"results": {"skip": 0, "limit": 100, "total": total}},
            "results": [],
        }
    ).encode()
    with pytest.raises(FaersParseError, match="bounded JSON integer"):
        parse_count_page(payload)


def test_python_integer_digit_ceiling_translates_to_faers_parse_error() -> None:
    payload = b'{"results":[{"term":"NAUSEA","count":' + (b"9" * 10_000) + b"}]}"
    with pytest.raises(FaersParseError, match="valid UTF-8 JSON"):
        parse_count_page(payload)
