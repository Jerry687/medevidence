"""Offline-only, exact-asset CADEC loader and strict annotation parser."""

from .loader import (
    ARCHIVE_BYTES,
    INVENTORY_DIRECTORY_COUNT,
    INVENTORY_ENTRY_COUNT,
    INVENTORY_FILE_COUNT,
    MAX_MEMBER_BYTES,
    CadecInventorySummary,
    CadecLoadError,
    CadecLoadErrorCode,
    CadecLoadResult,
    CadecVerificationSummary,
    inspect_zip_inventory,
    load_cadec_archive,
)
from .parsing import (
    MAX_ANNOTATION_LINES,
    MAX_ANNOTATION_ROW_BYTES,
    CadecParseError,
    ParsedCadecAnnotation,
    ParsedCadecMember,
    decode_text_member,
    parse_annotation_member,
)

__all__ = [
    "ARCHIVE_BYTES",
    "INVENTORY_DIRECTORY_COUNT",
    "INVENTORY_ENTRY_COUNT",
    "INVENTORY_FILE_COUNT",
    "MAX_ANNOTATION_LINES",
    "MAX_ANNOTATION_ROW_BYTES",
    "MAX_MEMBER_BYTES",
    "CadecInventorySummary",
    "CadecLoadError",
    "CadecLoadErrorCode",
    "CadecLoadResult",
    "CadecParseError",
    "CadecVerificationSummary",
    "ParsedCadecAnnotation",
    "ParsedCadecMember",
    "decode_text_member",
    "inspect_zip_inventory",
    "load_cadec_archive",
    "parse_annotation_member",
]
