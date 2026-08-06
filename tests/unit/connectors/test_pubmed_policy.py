"""Unit tests for the network-free PubMed transport policy."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime

import pytest

from medevidence.connectors.pubmed.policy import (
    MAX_ATTEMPTS,
    MAX_PAGES,
    MAX_PAYLOAD_BYTES,
    MAX_QUERY_CHARACTERS,
    MAX_RECORDS,
    MAX_TOTAL_DEADLINE_SECONDS,
    PUBMED_EFETCH_PATH,
    PUBMED_ESEARCH_PATH,
    PUBMED_ORIGIN,
    RETRYABLE_STATUS_CODES,
    PubMedConnectorConfig,
    PubMedFailure,
    PubMedFailureKind,
    PubMedResultState,
    parse_retry_after,
    resolve_pubmed_redirect,
    retry_delay_seconds,
    validate_pubmed_url,
)

NOW = datetime(2026, 8, 5, 12, 0, tzinfo=UTC)
SEARCH_URL = f"{PUBMED_ORIGIN}{PUBMED_ESEARCH_PATH}?db=pubmed&term=aspirin"


def test_constants_and_connector_local_classifications_are_exact() -> None:
    assert PUBMED_ORIGIN == "https://eutils.ncbi.nlm.nih.gov"
    assert PUBMED_ESEARCH_PATH == "/entrez/eutils/esearch.fcgi"
    assert PUBMED_EFETCH_PATH == "/entrez/eutils/efetch.fcgi"
    assert {429, 500, 502, 503, 504} == RETRYABLE_STATUS_CODES
    assert {state.value for state in PubMedResultState} == {
        "complete_success",
        "empty_success",
        "bounded_truncation",
        "partial_success",
        "partial_failure",
        "failed",
    }


def test_config_defaults_are_finite_bounded_immutable_and_no_cache() -> None:
    config = PubMedConnectorConfig()

    assert config.max_query_characters == MAX_QUERY_CHARACTERS
    assert config.max_pages == MAX_PAGES
    assert config.max_records == MAX_RECORDS
    assert config.max_payload_bytes == MAX_PAYLOAD_BYTES
    assert config.max_cumulative_payload_bytes == MAX_PAYLOAD_BYTES
    assert config.total_deadline_seconds <= MAX_TOTAL_DEADLINE_SECONDS
    assert config.max_attempts <= MAX_ATTEMPTS
    assert config.cache_policy == "none"
    with pytest.raises(FrozenInstanceError):
        config.max_pages = 1


@pytest.mark.parametrize(
    "changes",
    [
        {"max_query_characters": 0},
        {"max_query_characters": MAX_QUERY_CHARACTERS + 1},
        {"page_size": 0},
        {"page_size": 101},
        {"max_pages": 0},
        {"max_pages": MAX_PAGES + 1},
        {"max_records": 0},
        {"max_records": MAX_RECORDS + 1},
        {"max_payload_bytes": 0},
        {"max_payload_bytes": MAX_PAYLOAD_BYTES + 1},
        {"connect_timeout_seconds": 0.0},
        {"read_timeout_seconds": float("inf")},
        {"write_timeout_seconds": float("nan")},
        {"pool_timeout_seconds": -1.0},
        {"total_deadline_seconds": 0.5},
        {"total_deadline_seconds": 1.5},
        {"total_deadline_seconds": MAX_TOTAL_DEADLINE_SECONDS + 0.1},
        {"max_attempts": 0},
        {"max_attempts": MAX_ATTEMPTS + 1},
        {"max_redirects": -1},
        {"max_redirects": 6},
        {"cache_policy": "memory"},
    ],
)
def test_config_rejects_out_of_policy_values(changes: dict[str, object]) -> None:
    with pytest.raises((TypeError, ValueError)):
        PubMedConnectorConfig(**changes)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "changes",
    [
        {"base_backoff_seconds": 3.0, "max_backoff_seconds": 2.0},
        {"jitter_seconds": 3.0, "max_backoff_seconds": 2.0},
    ],
)
def test_config_rejects_inconsistent_delay_bounds(changes: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        PubMedConnectorConfig(**changes)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("url", "path"),
    [
        (SEARCH_URL, PUBMED_ESEARCH_PATH),
        (
            f"https://EUTILS.NCBI.NLM.NIH.GOV:443{PUBMED_EFETCH_PATH}?db=pubmed&id=1",
            PUBMED_EFETCH_PATH,
        ),
    ],
)
def test_exact_approved_urls_are_accepted_and_canonicalized(url: str, path: str) -> None:
    canonical = validate_pubmed_url(url, path)

    assert canonical.startswith(PUBMED_ORIGIN)
    assert path in canonical


@pytest.mark.parametrize(
    "url",
    [
        f"http://eutils.ncbi.nlm.nih.gov{PUBMED_ESEARCH_PATH}",
        f"https://eutils.ncbi.nlm.nih.gov.evil.example{PUBMED_ESEARCH_PATH}",
        f"https://evil-eutils.ncbi.nlm.nih.gov{PUBMED_ESEARCH_PATH}",
        f"https://eutils.ncbi.nlm.nih.gov.evil{PUBMED_ESEARCH_PATH}",
        f"https://eutils.ncbi.nlm.nih.gov.{PUBMED_ESEARCH_PATH}",
        f"https://*.ncbi.nlm.nih.gov{PUBMED_ESEARCH_PATH}",
        f"https://user@eutils.ncbi.nlm.nih.gov{PUBMED_ESEARCH_PATH}",
        f"https://eutils.ncbi.nlm.nih.gov:444{PUBMED_ESEARCH_PATH}",
        f"https://eutils.ncbi.nlm.nih.gov{PUBMED_EFETCH_PATH}",
        f"https://eutils.ncbi.nlm.nih.gov{PUBMED_ESEARCH_PATH}/extra",
        f"https://eutils.ncbi.nlm.nih.gov{PUBMED_ESEARCH_PATH}#fragment",
        f"https://eutils.ncbi.nlm.nih.gov{PUBMED_ESEARCH_PATH}\n",
    ],
)
def test_url_validation_rejects_downgrade_lookalike_authority_and_path(url: str) -> None:
    with pytest.raises(ValueError):
        validate_pubmed_url(url, PUBMED_ESEARCH_PATH)


def test_url_validation_rejects_unapproved_expected_path() -> None:
    with pytest.raises(ValueError):
        validate_pubmed_url(
            f"{PUBMED_ORIGIN}/entrez/eutils/einfo.fcgi",
            "/entrez/eutils/einfo.fcgi",
        )


@pytest.mark.parametrize(
    "location",
    [
        PUBMED_ESEARCH_PATH + "?db=pubmed&term=aspirin",
        f"{PUBMED_ORIGIN}{PUBMED_ESEARCH_PATH}?db=pubmed&term=aspirin",
        f"https://eutils.ncbi.nlm.nih.gov:443{PUBMED_ESEARCH_PATH}?term=aspirin&db=pubmed",
        "?term=aspirin&db=pubmed",
    ],
)
def test_redirect_allows_only_same_origin_same_endpoint(location: str) -> None:
    resolved = resolve_pubmed_redirect(SEARCH_URL, location, PUBMED_ESEARCH_PATH)

    assert validate_pubmed_url(resolved, PUBMED_ESEARCH_PATH) == resolved


@pytest.mark.parametrize(
    "location",
    [
        f"http://eutils.ncbi.nlm.nih.gov{PUBMED_ESEARCH_PATH}",
        f"https://eutils.ncbi.nlm.nih.gov.evil.example{PUBMED_ESEARCH_PATH}",
        f"//evil.example{PUBMED_ESEARCH_PATH}",
        PUBMED_EFETCH_PATH,
        PUBMED_ESEARCH_PATH + "?db=pubmed&term=ibuprofen",
        f"{PUBMED_ORIGIN}{PUBMED_ESEARCH_PATH}#fragment",
        "",
    ],
)
def test_redirect_rejects_other_origin_downgrade_path_and_blank(location: str) -> None:
    with pytest.raises(ValueError):
        resolve_pubmed_redirect(SEARCH_URL, location, PUBMED_ESEARCH_PATH)


def test_redirect_rejects_invalid_utf8_that_would_replacement_decode_equal() -> None:
    current = f"{PUBMED_ORIGIN}{PUBMED_ESEARCH_PATH}?db=pubmed&term=%EF%BF%BD&retmode=xml"
    location = f"{PUBMED_ESEARCH_PATH}?db=pubmed&term=%FF&retmode=xml"

    with pytest.raises(ValueError, match="not valid UTF-8"):
        resolve_pubmed_redirect(current, location, PUBMED_ESEARCH_PATH)


@pytest.mark.parametrize(
    ("value", "cap", "expected"),
    [
        ("5", 10.0, 5.0),
        (" 5 ", 10.0, 5.0),
        ("999", 10.0, 10.0),
        ("Wed, 05 Aug 2026 12:00:06 GMT", 10.0, 6.0),
        ("Wed, 05 Aug 2026 11:59:00 GMT", 10.0, 0.0),
        ("Wed, 05 Aug 2026 12:01:00 GMT", 10.0, 10.0),
        (None, 10.0, None),
        ("", 10.0, None),
        ("1.5", 10.0, None),
        ("-1", 10.0, None),
        ("not-a-date", 10.0, None),
    ],
)
def test_retry_after_parses_delta_and_http_date_with_cap(
    value: str | None,
    cap: float,
    expected: float | None,
) -> None:
    assert parse_retry_after(value, now=NOW, cap_seconds=cap) == expected


def test_retry_after_requires_aware_now_and_finite_cap() -> None:
    with pytest.raises(ValueError):
        parse_retry_after("1", now=datetime(2026, 8, 5), cap_seconds=10.0)
    with pytest.raises(ValueError):
        parse_retry_after("1", now=NOW, cap_seconds=float("inf"))


def test_retry_after_huge_delta_is_capped_without_integer_conversion_failure() -> None:
    delay = parse_retry_after("9" * 10_000, now=NOW, cap_seconds=10.0)

    assert delay == 10.0


def test_exponential_backoff_uses_injected_jitter_and_caps_total_delay() -> None:
    config = PubMedConnectorConfig(
        max_attempts=4,
        base_backoff_seconds=1.0,
        jitter_seconds=0.5,
        max_backoff_seconds=3.0,
    )

    assert retry_delay_seconds(1, config=config, jitter=0.25) == 1.25
    assert retry_delay_seconds(2, config=config, jitter=0.5) == 2.5
    assert retry_delay_seconds(3, config=config, jitter=0.5) == 3.0


@pytest.mark.parametrize("jitter", [-0.01, 0.51, float("inf"), float("nan")])
def test_backoff_rejects_out_of_range_or_non_finite_jitter(jitter: float) -> None:
    config = PubMedConnectorConfig(jitter_seconds=0.5)
    with pytest.raises(ValueError):
        retry_delay_seconds(1, config=config, jitter=jitter)


def test_retry_exhaustion_requires_a_typed_non_recursive_cause() -> None:
    with pytest.raises(ValueError):
        PubMedFailure(
            kind=PubMedFailureKind.RETRY_EXHAUSTED,
            message="attempt budget exhausted",
            retryable=False,
        )
    failure = PubMedFailure(
        kind=PubMedFailureKind.RETRY_EXHAUSTED,
        message="attempt budget exhausted",
        retryable=False,
        status_code=503,
        cause_kind=PubMedFailureKind.RETRYABLE_SERVER_ERROR,
    )

    assert failure.cause_kind is PubMedFailureKind.RETRYABLE_SERVER_ERROR
