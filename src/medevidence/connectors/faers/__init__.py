"""Bounded, offline-testable FAERS count connector and parser."""

from .client import FaersConnector, FaersConnectorResult, RawFaersResponse
from .parsing import (
    FaersCountBucket,
    FaersCountPage,
    FaersParseError,
    FaersProviderError,
    parse_count_page,
    parse_error_envelope,
)
from .policy import (
    FAERS_COUNT_FIELD,
    FAERS_EXECUTION_PROFILE_ID,
    FAERS_HOST,
    FAERS_PATH,
    FaersConnectorConfig,
    FaersFailure,
    FaersFailureKind,
    FaersRequest,
    FaersRetryEvent,
    build_faers_request,
    serialize_faers_query,
    validate_connector_config,
    validate_faers_request,
    validate_faers_url,
)

__all__ = [
    "FAERS_COUNT_FIELD",
    "FAERS_EXECUTION_PROFILE_ID",
    "FAERS_HOST",
    "FAERS_PATH",
    "FaersConnector",
    "FaersConnectorConfig",
    "FaersConnectorResult",
    "FaersCountBucket",
    "FaersCountPage",
    "FaersFailure",
    "FaersFailureKind",
    "FaersParseError",
    "FaersProviderError",
    "FaersRequest",
    "FaersRetryEvent",
    "RawFaersResponse",
    "build_faers_request",
    "parse_count_page",
    "parse_error_envelope",
    "serialize_faers_query",
    "validate_connector_config",
    "validate_faers_request",
    "validate_faers_url",
]
