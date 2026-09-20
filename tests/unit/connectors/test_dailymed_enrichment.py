"""Strict packaging parsing and transport-injected connector enrichment."""

from __future__ import annotations

import json
from dataclasses import replace

import httpx
import pytest
from tests.unit.tools.test_dailymed_enrichment import parent

from medevidence.connectors.dailymed.client import DailyMedConnector
from medevidence.connectors.dailymed.enrichment import (
    parse_discovery_page_v2,
    parse_packaging_page,
    project_discovery_summaries_v2,
)
from medevidence.connectors.dailymed.parsing import DailyMedParseError
from medevidence.domain import sha256_digest

SETID = "11111111-1111-4111-8111-111111111111"


def discovery_payload() -> bytes:
    return json.dumps(
        {
            "metadata": {"current_page": "1", "elements_per_page": "1", "total_elements": "1"},
            "data": [
                {
                    "setid": SETID,
                    "spl_version": "2",
                    "title": "EXACT PRODUCT (INGREDIENT) TABLET [LABELER]",
                    "published_date": "Nov 01, 2013",
                }
            ],
        },
        separators=(",", ":"),
    ).encode()


def test_v2_discovery_retains_title_date_and_exact_raw_parent() -> None:
    raw = discovery_payload()
    parsed = parse_discovery_page_v2(raw, expected_pagesize=1)
    assert parsed.records[0].title.startswith("EXACT PRODUCT")
    assert parsed.records[0].published_date.isoformat() == "2013-11-01"
    source_parent = parent("discovery_json", 0, "query:discovery").model_copy(
        update={
            "raw_artifact_id": sha256_digest(raw),
            "raw_content_hash": sha256_digest(raw),
            "byte_size": len(raw),
        }
    )
    projected = project_discovery_summaries_v2(
        raw, parent=source_parent, expected_page=1, expected_pagesize=1
    )
    assert projected[0].title == parsed.records[0].title
    assert projected[0].parent.raw_content_hash == sha256_digest(raw)
    with pytest.raises(DailyMedParseError, match="parent/raw"):
        project_discovery_summaries_v2(
            raw + b" ", parent=source_parent, expected_page=1, expected_pagesize=1
        )

    sent: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(200, content=raw, headers={"Content-Type": "application/json"})

    with DailyMedConnector(httpx.MockTransport(handler)) as connector:
        result = connector.discover_v2(setid=SETID, pagesize=1)
    assert result.failure is None and result.value == (parsed,)
    assert result.raw_responses[0].body == raw and len(sent) == 1


def test_v2_discovery_rejects_duplicate_identity_and_nonfinite_json() -> None:
    raw = discovery_payload()
    duplicate = raw.replace(
        b'"setid":"' + SETID.encode() + b'",',
        b'"setid":"22222222-2222-4222-8222-222222222222","setid":"' + SETID.encode() + b'",',
        1,
    )
    with pytest.raises(DailyMedParseError, match="duplicate"):
        parse_discovery_page_v2(duplicate, expected_pagesize=1)
    with pytest.raises(DailyMedParseError, match="non-finite"):
        parse_discovery_page_v2(raw[:-1] + b',"ignored":NaN}', expected_pagesize=1)


def payload(*, version: str = "2") -> bytes:
    return json.dumps(
        {
            "metadata": {"current_page": "1", "next_page": "null"},
            "data": {
                "setid": SETID,
                "spl_version": version,
                "title": "EXACT TITLE",
                "published_date": "Jan 01, 2026",
                "products": [
                    {
                        "product_code": "0001",
                        "product_name": "EXACT PRODUCT",
                        "product_name_generic": "exact generic",
                        "active_ingredients": [{"name": "Ingredient", "strength": "1 mg"}],
                        "packaging": [{"ndc": "0001-0001", "package_descriptions": []}],
                        "parts": {},
                    }
                ],
            },
        },
        separators=(",", ":"),
    ).encode()


def test_packaging_parser_and_mock_transport_bind_setid_version() -> None:
    page = parse_packaging_page(payload(), expected_setid=SETID, expected_spl_version="2")
    assert page.products[0].ingredients == ("Ingredient",)
    sent = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(200, content=payload(), headers={"Content-Type": "application/json"})

    with DailyMedConnector(httpx.MockTransport(handler)) as connector:
        result = connector.packaging(SETID, "2")
    assert result.failure is None and result.value == (page,)
    assert len(sent) == 1 and sent[0].url.path.endswith(f"/{SETID}/packaging.json")
    assert result.raw_responses[0].body == payload()
    bound_parent = parent("packaging_json", 1, "query:packaging").model_copy(
        update={
            "raw_artifact_id": sha256_digest(payload()),
            "raw_content_hash": sha256_digest(payload()),
            "byte_size": len(payload()),
        }
    )
    captured = DailyMedConnector.captured_packaging_v2(
        result, parent=bound_parent, expected_setid=SETID, expected_spl_version="2"
    )
    assert captured.products == page.products
    with pytest.raises(ValueError, match="partial"):
        DailyMedConnector.captured_packaging_v2(
            replace(result, truncated=True),
            parent=bound_parent,
            expected_setid=SETID,
            expected_spl_version="2",
        )


@pytest.mark.parametrize(
    "change", ("version", "duplicate", "missing_ingredient", "bom", "nonfinite")
)
def test_packaging_parser_fails_closed(change: str) -> None:
    raw = payload(version="3" if change == "version" else "2")
    if change == "duplicate":
        raw = raw[:-1] + b',"data":{}}'
    elif change == "missing_ingredient":
        document = json.loads(raw)
        document["data"]["products"][0]["active_ingredients"] = []
        raw = json.dumps(document, separators=(",", ":")).encode()
    elif change == "bom":
        raw = b"\xef\xbb\xbf" + raw
    elif change == "nonfinite":
        raw = raw[:-1] + b',"ignored":NaN}'
    with pytest.raises(DailyMedParseError):
        parse_packaging_page(raw, expected_setid=SETID, expected_spl_version="2")
