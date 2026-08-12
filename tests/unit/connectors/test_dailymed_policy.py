from __future__ import annotations

from datetime import UTC, datetime

import pytest

from medevidence.connectors.dailymed.policy import (
    DAILYMED_ORIGIN,
    DailyMedConnectorConfig,
    DailyMedOperation,
    DailyMedRequest,
    build_dailymed_request,
    parse_retry_after,
    resolve_dailymed_redirect,
    retry_delay_seconds,
    validate_dailymed_url,
    validate_setid,
    validate_spl_version,
)

SETID = "11111111-1111-1111-1111-111111111111"


@pytest.mark.parametrize(
    ("operation", "kwargs", "path"),
    [
        (
            DailyMedOperation.DISCOVERY,
            {"query": {"setid": SETID}},
            "/dailymed/services/v2/spls.json",
        ),
        (
            DailyMedOperation.HISTORY,
            {"setid": SETID, "query": {"pagesize": 100, "page": 1}},
            f"/dailymed/services/v2/spls/{SETID}/history.json",
        ),
        (
            DailyMedOperation.NDCS,
            {"setid": SETID, "query": {"pagesize": 100, "page": 1}},
            f"/dailymed/services/v2/spls/{SETID}/ndcs.json",
        ),
        (
            DailyMedOperation.PACKAGING,
            {"setid": SETID, "query": {"pagesize": 100, "page": 1}},
            f"/dailymed/services/v2/spls/{SETID}/packaging.json",
        ),
        (
            DailyMedOperation.CURRENT_SPL,
            {"setid": SETID},
            f"/dailymed/services/v2/spls/{SETID}.xml",
        ),
        (
            DailyMedOperation.HISTORICAL_SPL,
            {"setid": SETID, "spl_version": "3"},
            "/dailymed/getFile.cfm",
        ),
    ],
)
def test_builds_exact_six_typed_paths(
    operation: DailyMedOperation, kwargs: dict[str, object], path: str
) -> None:
    request = build_dailymed_request(operation, **kwargs)  # type: ignore[arg-type]
    assert request.path == path
    assert request.url.startswith(f"{DAILYMED_ORIGIN}{path}")
    assert validate_dailymed_url(request.url, request) == request.url


def test_historical_query_is_exact_and_not_caller_editable() -> None:
    request = build_dailymed_request(DailyMedOperation.HISTORICAL_SPL, setid=SETID, spl_version="3")
    assert request.query == (("setid", SETID), ("type", "zip"), ("version", "3"))
    with pytest.raises(ValueError):
        build_dailymed_request(
            DailyMedOperation.HISTORICAL_SPL,
            setid=SETID,
            spl_version="3",
            query={"type": "xml"},
        )


@pytest.mark.parametrize(
    "value",
    [
        "00000000-0000-0000-0000-000000000000",
        "11111111-1111-1111-1111-11111111111A",
        "{11111111-1111-1111-1111-111111111111}",
        "urn:uuid:11111111-1111-1111-1111-111111111111",
        f" {SETID}",
        f"{SETID}%20",
    ],
)
def test_setid_rejects_noncanonical_and_nil_values(value: str) -> None:
    with pytest.raises(ValueError):
        validate_setid(value)


@pytest.mark.parametrize("value", ["0", "01", "+1", " 1", "1.0", "\u0661"])
def test_spl_version_rejects_noncanonical_values(value: str) -> None:
    with pytest.raises(ValueError):
        validate_spl_version(value)


def test_queries_are_closed_and_bounds_are_enforced() -> None:
    with pytest.raises(ValueError):
        build_dailymed_request(DailyMedOperation.DISCOVERY, query={"unknown": "x"})
    with pytest.raises(ValueError):
        build_dailymed_request(DailyMedOperation.DISCOVERY, query={"page": 1})
    with pytest.raises(ValueError):
        build_dailymed_request(
            DailyMedOperation.HISTORY, setid=SETID, query={"page": 6, "pagesize": 100}
        )


def test_query_character_bound_counts_complete_canonical_rendering() -> None:
    accepted = build_dailymed_request(DailyMedOperation.DISCOVERY, query={"drug_name": "a" * 502})
    assert accepted.query == (("drug_name", "a" * 502),)
    with pytest.raises(ValueError, match="512-character"):
        build_dailymed_request(DailyMedOperation.DISCOVERY, query={"drug_name": "a" * 503})


def test_query_character_bound_is_cumulative_across_canonical_fields() -> None:
    # 10 for `drug_name=`, 1 for `&`, 8 for `labeler=`, plus 493 values.
    accepted = build_dailymed_request(
        DailyMedOperation.DISCOVERY,
        query={"drug_name": "a" * 250, "labeler": "b" * 243},
    )
    assert sum(len(key) + 1 + len(value) for key, value in accepted.query) + 1 == 512
    with pytest.raises(ValueError, match="512-character"):
        build_dailymed_request(
            DailyMedOperation.DISCOVERY,
            query={"drug_name": "a" * 250, "labeler": "b" * 244},
        )


def test_query_character_bound_counts_unicode_codepoints_before_encoding() -> None:
    accepted = build_dailymed_request(DailyMedOperation.DISCOVERY, query={"drug_name": "药" * 502})
    assert len(accepted.url.split("?", 1)[1]) > 512
    with pytest.raises(ValueError, match="512-character"):
        build_dailymed_request(DailyMedOperation.DISCOVERY, query={"drug_name": "药" * 503})


def test_mutated_request_cannot_bypass_query_character_bound_on_revalidation() -> None:
    request = build_dailymed_request(DailyMedOperation.DISCOVERY, query={"drug_name": "safe"})
    object.__setattr__(request, "query", (("drug_name", "a" * 503),))
    with pytest.raises(ValueError, match="512-character"):
        validate_dailymed_url(request.url, request)


def test_redirect_requires_exact_same_origin_path_and_query() -> None:
    request = build_dailymed_request(DailyMedOperation.DISCOVERY, query={"setid": SETID})
    assert resolve_dailymed_redirect(request.url, request.url, request) == request.url
    for location in (
        request.url.replace("https://", "http://"),
        request.url.replace("dailymed.nlm.nih.gov", "example.invalid"),
        request.url.replace("spls.json", "media.cfm"),
        request.url + "&page=2",
    ):
        with pytest.raises(ValueError):
            resolve_dailymed_redirect(request.url, location, request)


def test_frozen_transport_configuration_is_not_weakenable() -> None:
    assert DailyMedConnectorConfig().max_payload_bytes == 5_242_880
    with pytest.raises(ValueError):
        DailyMedConnectorConfig(max_attempts=3)
    with pytest.raises(ValueError):
        DailyMedConnectorConfig(stale_fallback=True)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("connect_timeout_seconds", 6.0),
        ("read_timeout_seconds", 11.0),
        ("write_timeout_seconds", 6.0),
        ("pool_timeout_seconds", 6.0),
        ("total_deadline_seconds", 31.0),
        ("max_attempts", 99),
        ("base_backoff_seconds", 0.5),
        ("max_backoff_seconds", 5.0),
        ("jitter_seconds", 0.2),
        ("max_retry_after_seconds", 11.0),
        ("max_redirects", 2),
        ("max_pages", 6),
        ("max_candidates", 101),
        ("max_payload_bytes", 5_242_881),
        ("fixed_version_cache", "mutable"),
        ("discovery_cache", "memory"),
        ("stale_fallback", True),
    ],
)
def test_existing_config_one_field_drift_rejects_at_connector_entry(
    field: str, value: object
) -> None:
    import httpx

    from medevidence.connectors.dailymed import DailyMedConnector

    config = DailyMedConnectorConfig()
    object.__setattr__(config, field, value)
    with pytest.raises((TypeError, ValueError)):
        DailyMedConnector(httpx.MockTransport(lambda _: httpx.Response(200)), config=config)


def test_public_request_cannot_serve_as_its_own_weakened_policy_oracle() -> None:
    canonical = build_dailymed_request(DailyMedOperation.DISCOVERY, query={"setid": SETID})
    drifts = (
        DailyMedRequest(canonical.operation, "/unfrozen.json", canonical.query),
        DailyMedRequest(canonical.operation, canonical.path, (("url", "https://evil.invalid"),)),
        DailyMedRequest(DailyMedOperation.HISTORY, canonical.path, canonical.query, SETID),
        DailyMedRequest(canonical.operation, canonical.path, canonical.query, SETID),
    )
    for drift in drifts:
        with pytest.raises((TypeError, ValueError)):
            validate_dailymed_url(drift.url, drift)


def test_retry_timing_is_capped_and_requires_injected_bounded_jitter() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    assert parse_retry_after("99", now=now) == 10
    assert parse_retry_after("invalid", now=now) is None
    assert retry_delay_seconds(1, jitter=0.1) == pytest.approx(0.35)
    with pytest.raises(ValueError):
        retry_delay_seconds(1, jitter=0.101)
