"""Strict narrative-free parser for synthetic/openFDA count envelopes."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final

from medevidence.domain import GI_PT_SET_M1B_V1

from .policy import MAX_BUCKETS, MAX_PAYLOAD_BYTES, PAGE_SIZE

_ROOT_KEYS: Final = frozenset({"meta", "results"})
_META_KEYS: Final = frozenset({"last_updated", "results"})
_META_RESULTS_KEYS: Final = frozenset({"skip", "limit", "total"})
MAX_PROVIDER_COUNT: Final = 9_223_372_036_854_775_807


class FaersParseError(ValueError):
    """A provider envelope violated the closed count-only parser contract."""


@dataclass(frozen=True, slots=True)
class FaersCountBucket:
    """One exact provider-supplied PT occurrence bucket."""

    reaction_pt: str
    report_count: int

    def __post_init__(self) -> None:
        if self.reaction_pt not in GI_PT_SET_M1B_V1:
            raise ValueError("reaction_pt must be an exact frozen GI PT literal")
        if (
            isinstance(self.report_count, bool)
            or not isinstance(self.report_count, int)
            or not 0 <= self.report_count <= MAX_PROVIDER_COUNT
        ):
            raise ValueError("report_count must be a bounded nonnegative integer")


@dataclass(frozen=True, slots=True)
class FaersCountPage:
    """One bounded, canonically ordered count page with optional freshness."""

    buckets: tuple[FaersCountBucket, ...]
    page_number: int
    page_size: int
    provider_record_total: int
    next_page: int | None
    provider_as_of_utc: datetime | None = None

    def __post_init__(self) -> None:
        if not 1 <= self.page_number <= 5:
            raise ValueError("page_number is outside the frozen bound")
        if self.page_size != PAGE_SIZE:
            raise ValueError("page_size must equal the frozen value 100")
        if (
            isinstance(self.provider_record_total, bool)
            or not isinstance(self.provider_record_total, int)
            or not 0 <= self.provider_record_total <= MAX_PROVIDER_COUNT
        ):
            raise ValueError("provider_record_total is outside the signed-bigint bound")
        if len(self.buckets) > MAX_BUCKETS:
            raise ValueError("bucket collection exceeds the frozen bound")
        if self.provider_as_of_utc is not None and (
            self.provider_as_of_utc.tzinfo is None
            or self.provider_as_of_utc.utcoffset() != timedelta(0)
        ):
            raise ValueError("provider_as_of_utc must be timezone-aware UTC")
        expected = tuple(
            sorted(self.buckets, key=lambda item: (-item.report_count, item.reaction_pt))
        )
        if self.buckets != expected:
            raise ValueError("count buckets must use count DESC then PT ASC")
        pts = tuple(item.reaction_pt for item in self.buckets)
        if len(set(pts)) != len(pts):
            raise ValueError("count buckets must use unique PT literals")
        if self.page_number != 1 or self.next_page is not None:
            raise ValueError("count-page continuation metadata is inconsistent")


@dataclass(frozen=True, slots=True)
class FaersProviderError:
    """Bounded error-envelope metadata; never an evidence result."""

    code: str
    message: str

    def __post_init__(self) -> None:
        for name, value in (("code", self.code), ("message", self.message)):
            if (
                not isinstance(value, str)
                or not value
                or value != value.strip()
                or len(value) > 256
                or any(ord(character) < 32 or ord(character) == 127 for character in value)
            ):
                raise ValueError(f"provider error {name} must be bounded canonical text")


def parse_count_page(
    payload: bytes, *, expected_page: int = 1, expected_page_size: int = PAGE_SIZE
) -> FaersCountPage:
    """Parse only the exact count-envelope shape and canonicalize its buckets."""

    root = _json_object(payload)
    _exact_keys(root, required={"results"}, allowed=_ROOT_KEYS, label="count root")
    raw_results = root["results"]
    if not isinstance(raw_results, list):
        raise FaersParseError("count results must be an array")
    if len(raw_results) > MAX_BUCKETS:
        raise FaersParseError("count results exceed the 100-bucket bound")
    buckets: list[FaersCountBucket] = []
    for value in raw_results:
        row = _mapping(value, "count bucket")
        _exact_keys(row, required={"term", "count"}, allowed={"term", "count"}, label="bucket")
        term = row["term"]
        count = row["count"]
        if not isinstance(term, str) or term not in GI_PT_SET_M1B_V1:
            raise FaersParseError("count term is not an exact frozen GI PT literal")
        if (
            isinstance(count, bool)
            or not isinstance(count, int)
            or not 0 <= count <= MAX_PROVIDER_COUNT
        ):
            raise FaersParseError("count must be a bounded nonnegative JSON integer")
        buckets.append(FaersCountBucket(term, count))
    if len({item.reaction_pt for item in buckets}) != len(buckets):
        raise FaersParseError("count results contain a duplicate PT bucket")
    buckets.sort(key=lambda item: (-item.report_count, item.reaction_pt))

    provider_as_of: datetime | None = None
    total = len(buckets)
    next_page: int | None = None
    if "meta" in root:
        meta = _mapping(root["meta"], "count metadata")
        _exact_keys(meta, required=set(), allowed=_META_KEYS, label="count metadata")
        if "last_updated" in meta:
            provider_as_of = _utc_datetime(meta["last_updated"])
        if "results" in meta:
            paging = _mapping(meta["results"], "count pagination metadata")
            _exact_keys(
                paging,
                required={"skip", "limit", "total"},
                allowed=_META_RESULTS_KEYS,
                label="count pagination metadata",
            )
            skip = _bounded_int(paging["skip"], 0, 400, "skip")
            limit = _bounded_int(paging["limit"], PAGE_SIZE, PAGE_SIZE, "limit")
            total = _bounded_int(paging["total"], 0, MAX_PROVIDER_COUNT, "total")
            expected_skip = (expected_page - 1) * expected_page_size
            if skip != expected_skip or limit != expected_page_size:
                raise FaersParseError("count pagination differs from the typed request")

    try:
        return FaersCountPage(
            buckets=tuple(buckets),
            page_number=expected_page,
            page_size=expected_page_size,
            provider_record_total=total,
            next_page=next_page,
            provider_as_of_utc=provider_as_of,
        )
    except ValueError as error:
        raise FaersParseError("count envelope has inconsistent bounded metadata") from error


def parse_error_envelope(payload: bytes) -> FaersProviderError:
    """Parse a bounded provider error envelope without treating it as evidence."""

    root = _json_object(payload)
    _exact_keys(root, required={"error"}, allowed={"error"}, label="error root")
    error = _mapping(root["error"], "error")
    _exact_keys(error, required={"code", "message"}, allowed={"code", "message"}, label="error")
    try:
        return FaersProviderError(
            code=_canonical_text(error["code"], "error code"),
            message=_canonical_text(error["message"], "error message"),
        )
    except ValueError as exc:
        raise FaersParseError("error envelope contains invalid text") from exc


def _json_object(payload: bytes) -> Mapping[str, object]:
    if not isinstance(payload, bytes):
        raise TypeError("FAERS payload must be exact bytes")
    if len(payload) > MAX_PAYLOAD_BYTES:
        raise FaersParseError("JSON payload exceeds the frozen byte bound")
    try:
        value = json.loads(
            payload.decode("utf-8", errors="strict"),
            object_pairs_hook=_unique_json_object,
        )
    except (UnicodeError, ValueError, OverflowError, RecursionError) as error:
        raise FaersParseError("FAERS payload must be valid UTF-8 JSON") from error
    return _mapping(value, "JSON root")


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """Reject duplicate JSON names at every object nesting depth."""

    result: dict[str, object] = {}
    for name, value in pairs:
        if name in result:
            raise FaersParseError("FAERS JSON contains a duplicate object name")
        result[name] = value
    return result


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise FaersParseError(f"{label} must be an object with string keys")
    return value


def _exact_keys(
    value: Mapping[str, object],
    *,
    required: set[str],
    allowed: set[str] | frozenset[str],
    label: str,
) -> None:
    missing = required - value.keys()
    extra = value.keys() - allowed
    if missing or extra:
        raise FaersParseError(f"{label} violates the closed field set")


def _bounded_int(value: object, minimum: int, maximum: int, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise FaersParseError(f"{label} must be a bounded JSON integer")
    return value


def _canonical_text(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > 256
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise FaersParseError(f"{label} must be bounded canonical text")
    return value


def _utc_datetime(value: object) -> datetime:
    text = _canonical_text(value, "last_updated")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as error:
        raise FaersParseError("last_updated must be an ISO datetime") from error
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise FaersParseError("last_updated must be timezone-aware UTC")
    return parsed.astimezone(UTC)


__all__ = [
    "MAX_PROVIDER_COUNT",
    "FaersCountBucket",
    "FaersCountPage",
    "FaersParseError",
    "FaersProviderError",
    "parse_count_page",
    "parse_error_envelope",
]
