"""Strict bounded parser for official DailyMed candidate packaging metadata."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from typing import Any

from medevidence.domain import sha256_digest
from medevidence.domain.dailymed_enrichment import (
    DailyMedDiscoveryRecordV2,
    DailyMedDiscoverySummaryV2,
    DailyMedPackagingProductV2,
    DailyMedRawParentV2,
)

from .parsing import (
    DailyMedParseError,
    _list_from_keys,
    _mapping,
    _pagination,
    _required_alias,
    _versions,
)
from .policy import MAX_CANDIDATES, MAX_PAYLOAD_BYTES, validate_setid, validate_spl_version


@dataclass(frozen=True, slots=True)
class DailyMedPackagingPageV2:
    setid: str
    spl_version: str
    products: tuple[DailyMedPackagingProductV2, ...]
    page: int
    next_page: int | None


@dataclass(frozen=True, slots=True)
class DailyMedDiscoveryPageV2:
    records: tuple[DailyMedDiscoveryRecordV2, ...]
    page: int
    pagesize: int
    total: int
    next_page: int | None


_MONTHS = {
    month: number
    for number, month in enumerate(
        ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"), 1
    )
}


def _published_date(value: object) -> date | None:
    if value is None:
        return None
    if type(value) is not str or len(value) > 32:
        raise DailyMedParseError("discovery published date is invalid")
    try:
        if len(value) == 12 and value[3] == " " and value[6:8] == ", ":
            return date(int(value[8:]), _MONTHS[value[:3]], int(value[4:6]))
        return date.fromisoformat(value)
    except (KeyError, ValueError) as error:
        raise DailyMedParseError("discovery published date is invalid") from error


def parse_discovery_page_v2(
    raw: bytes, *, expected_page: int = 1, expected_pagesize: int | None = None
) -> DailyMedDiscoveryPageV2:
    """Retain exact official title/date alongside SETID and current version."""

    if type(raw) is not bytes or not raw or len(raw) > MAX_PAYLOAD_BYTES:
        raise DailyMedParseError("DailyMed V2 discovery response size is invalid")
    if raw.startswith((b"\xef\xbb\xbf", b"\xff\xfe", b"\xfe\xff")):
        raise DailyMedParseError("DailyMed V2 discovery BOM is forbidden")
    try:
        root = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=_unique,
            parse_constant=_reject_constant,
        )
        _bounded_tree(root)
    except DailyMedParseError:
        raise
    except (UnicodeError, json.JSONDecodeError, ValueError, RecursionError) as error:
        raise DailyMedParseError("DailyMed V2 discovery JSON is invalid") from error
    if type(root) is not dict:
        raise DailyMedParseError("DailyMed V2 discovery root is invalid")
    rows = _list_from_keys(root, ("data", "results", "spls"))
    if len(rows) > MAX_CANDIDATES:
        raise DailyMedParseError("discovery V2 candidate bound exceeded")
    records = []
    for raw_row in rows:
        row = _mapping(raw_row, "discovery V2 record")
        versions = _versions(row)
        title = _text(row.get("title"), "discovery title")
        records.append(
            DailyMedDiscoveryRecordV2(
                setid=validate_setid(_required_alias(row, ("setid", "set_id", "setId"), "SETID")),
                current_spl_version=max(versions, key=int),
                title=title or "",
                published_date=_published_date(row.get("published_date")),
            )
        )
    page, pagesize, total, next_page = _pagination(
        root, len(records), expected_page, expected_pagesize
    )
    return DailyMedDiscoveryPageV2(tuple(records), page, pagesize, total, next_page)


def project_discovery_summaries_v2(
    raw: bytes,
    *,
    parent: DailyMedRawParentV2,
    expected_page: int,
    expected_pagesize: int | None = None,
    first_ordinal: int = 0,
) -> tuple[DailyMedDiscoverySummaryV2, ...]:
    """Reparse exact captured discovery bytes before creating parent-bound summaries."""

    if (
        type(parent) is not DailyMedRawParentV2
        or parent.kind != "discovery_json"
        or type(raw) is not bytes
        or len(raw) != parent.byte_size
        or sha256_digest(raw) != parent.raw_content_hash
        or type(first_ordinal) is not int
        or not 0 <= first_ordinal <= 99
    ):
        raise DailyMedParseError("DailyMed discovery parent/raw binding is invalid")
    page = parse_discovery_page_v2(
        raw, expected_page=expected_page, expected_pagesize=expected_pagesize
    )
    if first_ordinal + len(page.records) > 100:
        raise DailyMedParseError("DailyMed discovery summary ordinal bound exceeded")
    return tuple(
        DailyMedDiscoverySummaryV2.create(
            setid=record.setid,
            current_spl_version=record.current_spl_version,
            title=record.title,
            published_date=record.published_date,
            candidate_ordinal=first_ordinal + index,
            parent=parent,
        )
        for index, record in enumerate(page.records)
    )


def _unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DailyMedParseError("packaging JSON contains a duplicate key")
        result[key] = value
    return result


def _reject_constant(_value: str) -> None:
    raise DailyMedParseError("packaging JSON contains a non-finite number")


def _bounded_tree(value: object, depth: int = 0) -> None:
    if depth > 32:
        raise DailyMedParseError("packaging JSON nesting exceeds its bound")
    if type(value) is str:
        if len(value) > 4096 or any(0xD800 <= ord(char) <= 0xDFFF for char in value):
            raise DailyMedParseError("packaging JSON text exceeds its bound")
    elif type(value) is list:
        if len(value) > MAX_CANDIDATES:
            raise DailyMedParseError("packaging JSON collection exceeds its bound")
        for item in value:
            _bounded_tree(item, depth + 1)
    elif type(value) is dict:
        if len(value) > 32:
            raise DailyMedParseError("packaging JSON object exceeds its bound")
        for key, item in value.items():
            _bounded_tree(key, depth + 1)
            _bounded_tree(item, depth + 1)
    elif type(value) not in (int, float, bool, type(None)):
        raise DailyMedParseError("packaging JSON value type is invalid")


def _text(value: object, name: str, *, optional: bool = False) -> str | None:
    if optional and value in (None, ""):
        return None
    if type(value) is not str or not value.strip() or len(value) > 4096:
        raise DailyMedParseError(f"packaging {name} is invalid")
    return value


def _collection(value: object, name: str) -> list[object]:
    if type(value) is not list or len(value) > MAX_CANDIDATES:
        raise DailyMedParseError(f"packaging {name} exceeds its bound")
    return value


def parse_packaging_page(
    raw: bytes,
    *,
    expected_setid: str,
    expected_spl_version: str,
    expected_page: int = 1,
) -> DailyMedPackagingPageV2:
    """Parse one exact current-version packaging page without title inference."""

    if type(raw) is not bytes or not raw or len(raw) > MAX_PAYLOAD_BYTES:
        raise DailyMedParseError("packaging response size is invalid")
    if raw.startswith((b"\xef\xbb\xbf", b"\xff\xfe", b"\xfe\xff")):
        raise DailyMedParseError("packaging response BOM is forbidden")
    try:
        root = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_unique,
            parse_constant=_reject_constant,
        )
        _bounded_tree(root)
    except (UnicodeError, json.JSONDecodeError, ValueError, RecursionError) as error:
        raise DailyMedParseError("packaging response is invalid JSON") from error
    if type(root) is not dict or set(root) != {"metadata", "data"}:
        raise DailyMedParseError("packaging response shape is invalid")
    metadata, data = root["metadata"], root["data"]
    if type(metadata) is not dict or type(data) is not dict:
        raise DailyMedParseError("packaging metadata/data shape is invalid")
    allowed_data = {"setid", "spl_version", "title", "published_date", "products"}
    if set(data) != allowed_data:
        raise DailyMedParseError("packaging data fields are invalid")
    setid = validate_setid(_text(data["setid"], "SETID") or "")
    version = validate_spl_version(_text(data["spl_version"], "SPL version") or "")
    if (setid, version) != (
        validate_setid(expected_setid),
        validate_spl_version(expected_spl_version),
    ):
        raise DailyMedParseError("packaging SETID/version differs from frozen summary")
    page_raw = metadata.get("current_page", expected_page)
    next_raw = metadata.get("next_page")
    try:
        page = int(page_raw)
        next_page = None if next_raw in (None, "null") else int(next_raw)
    except (TypeError, ValueError) as error:
        raise DailyMedParseError("packaging pagination is invalid") from error
    if (
        page != expected_page
        or not 1 <= page <= 5
        or (next_page is not None and next_page != page + 1)
    ):
        raise DailyMedParseError("packaging pagination differs from request")
    products: list[DailyMedPackagingProductV2] = []
    for raw_product in _collection(data["products"], "products"):
        if type(raw_product) is not dict or set(raw_product) - {
            "product_code",
            "product_name",
            "product_name_generic",
            "active_ingredients",
            "packaging",
            "parts",
        }:
            raise DailyMedParseError("packaging product shape is invalid")
        ingredients, strengths = [], []
        for raw_ingredient in _collection(
            raw_product.get("active_ingredients", []), "active ingredients"
        ):
            if type(raw_ingredient) is not dict or set(raw_ingredient) != {"name", "strength"}:
                raise DailyMedParseError("packaging ingredient shape is invalid")
            ingredients.append(_text(raw_ingredient["name"], "ingredient") or "")
            strength = _text(raw_ingredient["strength"], "strength", optional=True)
            if strength is not None:
                strengths.append(strength)
        ndcs = []
        for package in _collection(raw_product.get("packaging", []), "packages"):
            if type(package) is not dict or set(package) - {"ndc", "package_descriptions"}:
                raise DailyMedParseError("packaging package shape is invalid")
            ndc = _text(package.get("ndc"), "NDC", optional=True)
            if ndc is not None:
                ndcs.append(ndc)
        try:
            products.append(
                DailyMedPackagingProductV2(
                    product_code=_text(
                        raw_product.get("product_code"), "product code", optional=True
                    ),
                    product_name=_text(raw_product.get("product_name"), "product name") or "",
                    generic_name=_text(
                        raw_product.get("product_name_generic"),
                        "generic name",
                        optional=True,
                    ),
                    ingredients=tuple(sorted(set(ingredients))),
                    strengths=tuple(sorted(set(strengths))),
                    ndcs=tuple(sorted(set(ndcs))),
                )
            )
        except ValueError as error:
            raise DailyMedParseError("packaging product is incomplete") from error
    if not products:
        raise DailyMedParseError("packaging response contains no enriched product")
    return DailyMedPackagingPageV2(setid, version, tuple(products), page, next_page)
