"""Exact, offline-only CADEC archive admission without filesystem extraction."""

from __future__ import annotations

import hashlib
import io
import json
import os
import stat
import zipfile
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Final, Literal, cast

from medevidence.domain import (
    CADEC_APPROVED_DOCUMENT_COUNT,
    CADEC_ARCHIVE_SHA256,
    CADEC_CANONICAL_DOCUMENT_COUNT,
    CADEC_CP1252_MEMBER,
    CADEC_CP1252_MEMBER_SHA256,
    CADEC_DEVELOPMENT_MEMBERSHIP_SHA256,
    CADEC_EXCLUDED_DOCUMENT_IDS,
    CADEC_EXTERNAL_MANIFEST_BYTES,
    CADEC_EXTERNAL_MANIFEST_SHA256,
    CADEC_MALFORMED_ROW_COUNT,
    CADEC_TEST_MEMBERSHIP_SHA256,
    CADEC_TRAIN_MEMBERSHIP_SHA256,
    CadecControlledVocabularyLayer,
    CadecCorpusAnnotationV1,
    CadecCorpusDocumentV1,
    CadecLocatorV1,
    CadecProvenanceContextV1,
    CadecReleaseManifestV1,
    CadecSplit,
    ControlledVocabularyRefV1,
    canonical_json,
    derive_identity,
)

from .parsing import CadecParseError, decode_text_member, parse_annotation_member

ARCHIVE_BYTES: Final = 1_870_497
INVENTORY_ENTRY_COUNT: Final = 5_005
INVENTORY_FILE_COUNT: Final = 5_000
INVENTORY_DIRECTORY_COUNT: Final = 5
MAX_MEMBER_BYTES: Final = 3_596
MAX_ARCHIVE_INPUT_BYTES: Final = ARCHIVE_BYTES
MAX_MANIFEST_INPUT_BYTES: Final = CADEC_EXTERNAL_MANIFEST_BYTES
MAX_ZIP_ENTRIES: Final = INVENTORY_ENTRY_COUNT
MAX_AGGREGATE_COMPRESSED_BYTES: Final = ARCHIVE_BYTES
MAX_AGGREGATE_UNCOMPRESSED_BYTES: Final = INVENTORY_FILE_COUNT * MAX_MEMBER_BYTES
MAX_EXPANSION_RATIO: Final = 1_000
_LAYERS: Final = ("original", "meddra", "sct")
_MANIFEST_LAYER_NAMES: Final = {
    "original": "original_entity",
    "meddra": "meddra_normalization",
    "sct": "snomed_ct_normalization",
}
_SPLIT_DIGESTS: Final = {
    CadecSplit.TRAIN: CADEC_TRAIN_MEMBERSHIP_SHA256,
    CadecSplit.DEVELOPMENT: CADEC_DEVELOPMENT_MEMBERSHIP_SHA256,
    CadecSplit.TEST: CADEC_TEST_MEMBERSHIP_SHA256,
}


class CadecLoadErrorCode(StrEnum):
    """Stable fail-closed categories for local asset admission."""

    INPUT_PATH = "input_path"
    MANIFEST_INTEGRITY = "manifest_integrity"
    ARCHIVE_INTEGRITY = "archive_integrity"
    UNSAFE_ZIP = "unsafe_zip"
    INVENTORY_MISMATCH = "inventory_mismatch"
    MANIFEST_POLICY = "manifest_policy"
    ENCODING = "encoding"
    ANNOTATION = "annotation"
    DOMAIN_CONTRACT = "domain_contract"


class CadecLoadError(ValueError):
    """Typed local CADEC loader failure without provider payload content."""

    def __init__(self, code: CadecLoadErrorCode, message: str) -> None:
        self.code = code
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class CadecInventorySummary:
    """Content-free result of bounded ZIP inventory inspection."""

    entry_count: int
    file_count: int
    directory_count: int
    total_uncompressed_bytes: int
    inventory_sha256: str


@dataclass(frozen=True, slots=True)
class CadecVerificationSummary:
    """Safe verification evidence containing no corpus or terminology payload."""

    archive_sha256: str
    archive_bytes: int
    manifest_sha256: str
    manifest_bytes: int
    inventory_sha256: str
    inventory_entry_count: int
    inventory_file_count: int
    inventory_directory_count: int
    inventory_uncompressed_bytes: int
    canonical_document_count: int
    canonical_document_sha256: str
    approved_document_count: int
    approved_document_sha256: str
    excluded_document_count: int
    excluded_document_sha256: str
    train_count: int
    train_membership_sha256: str
    development_count: int
    development_membership_sha256: str
    test_count: int
    test_membership_sha256: str
    encoding_exception_verified: bool
    empty_document_count: int
    malformed_row_count: int
    original_reference_binding_limitation_count: int
    meddra_reference_binding_limitation_count: int
    sct_reference_binding_limitation_count: int
    raw_out_of_order_transition_count: int
    raw_out_of_order_document_count: int
    provider_gold_only: bool
    predicted_artifact_admitted: bool
    output_document_count: int
    output_annotation_count: int
    output_original_annotation_count: int
    output_meddra_annotation_count: int
    output_sct_annotation_count: int
    output_locator_count: int
    all_validation_passed: bool


@dataclass(frozen=True, slots=True)
class CadecLoadResult:
    """Frozen domain objects plus a separately safe verification summary."""

    release_manifest: CadecReleaseManifestV1
    documents: tuple[CadecCorpusDocumentV1, ...]
    annotations: tuple[CadecCorpusAnnotationV1, ...]
    locators: tuple[CadecLocatorV1, ...]
    verification: CadecVerificationSummary


@dataclass(frozen=True, slots=True)
class _ManifestPolicy:
    inventory: tuple[Mapping[str, object], ...]
    canonical_ids: tuple[str, ...]
    approved_ids: tuple[str, ...]
    exclusions: tuple[str, ...]
    split_by_document: Mapping[str, CadecSplit]
    limited_rows: Mapping[str, frozenset[tuple[str, int, str, str]]]
    malformed_rows: frozenset[tuple[str, int, str, str]]
    annotation_count_by_layer: Mapping[str, int]
    canonical_sha256: str
    approved_sha256: str
    exclusion_sha256: str


def load_cadec_archive(archive_path: str | Path, manifest_path: str | Path) -> CadecLoadResult:
    """Admit only the exact frozen production archive and authoritative manifest."""

    archive_bytes = _read_regular_input_bytes(archive_path, "archive", MAX_ARCHIVE_INPUT_BYTES)
    manifest_bytes = _read_regular_input_bytes(manifest_path, "manifest", MAX_MANIFEST_INPUT_BYTES)
    manifest_size, manifest_hash = _bytes_identity(manifest_bytes)
    if (manifest_size, manifest_hash) != (
        CADEC_EXTERNAL_MANIFEST_BYTES,
        CADEC_EXTERNAL_MANIFEST_SHA256,
    ):
        raise CadecLoadError(
            CadecLoadErrorCode.MANIFEST_INTEGRITY,
            "external manifest size or SHA-256 differs from the exact freeze",
        )
    archive_size, archive_hash = _bytes_identity(archive_bytes)
    if (archive_size, archive_hash) != (ARCHIVE_BYTES, CADEC_ARCHIVE_SHA256):
        raise CadecLoadError(
            CadecLoadErrorCode.ARCHIVE_INTEGRITY,
            "archive size or SHA-256 differs from the exact freeze",
        )
    policy = _read_and_validate_manifest(manifest_bytes)
    release = CadecReleaseManifestV1.create()
    return _admit_archive(
        archive_bytes,
        policy=policy,
        release=release,
        archive_size=archive_size,
        archive_hash=archive_hash,
        manifest_size=manifest_size,
        manifest_hash=manifest_hash,
    )


def inspect_zip_inventory(archive_path: str | Path) -> CadecInventorySummary:
    """Inspect a synthetic ZIP safely without claiming production admission."""

    archive_bytes = _read_regular_input_bytes(archive_path, "archive", MAX_ARCHIVE_INPUT_BYTES)
    try:
        with zipfile.ZipFile(io.BytesIO(archive_bytes)) as handle:
            records, total = _inspect_and_read_inventory(handle, expected=None)
    except (zipfile.BadZipFile, OSError, RuntimeError) as error:
        raise CadecLoadError(CadecLoadErrorCode.UNSAFE_ZIP, "invalid or truncated ZIP") from error
    return CadecInventorySummary(
        entry_count=len(records),
        file_count=sum(record["entry_kind"] == "file" for record in records),
        directory_count=sum(record["entry_kind"] == "directory" for record in records),
        total_uncompressed_bytes=total,
        inventory_sha256=_inventory_digest(records),
    )


def _read_regular_input_bytes(value: str | Path, label: str, maximum_bytes: int) -> bytes:
    """Open once, revalidate the handle, and retain bounded immutable bytes."""

    if not isinstance(value, (str, Path)):
        raise TypeError(f"{label}_path must be an explicit str or Path")
    path = Path(value)
    if not path.is_absolute():
        raise CadecLoadError(CadecLoadErrorCode.INPUT_PATH, f"{label}_path must be absolute")
    try:
        path_item = path.lstat()
    except OSError as error:
        raise CadecLoadError(
            CadecLoadErrorCode.INPUT_PATH, f"{label}_path is unavailable"
        ) from error
    if not stat.S_ISREG(path_item.st_mode) or path.is_symlink():
        raise CadecLoadError(CadecLoadErrorCode.INPUT_PATH, f"{label}_path must be a regular file")
    attributes = getattr(path_item, "st_file_attributes", 0)
    if attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0):
        raise CadecLoadError(
            CadecLoadErrorCode.INPUT_PATH, f"{label}_path must not be a reparse point"
        )
    try:
        with path.open("rb") as stream:
            opened = os.fstat(stream.fileno())
            if not stat.S_ISREG(opened.st_mode):
                raise CadecLoadError(
                    CadecLoadErrorCode.INPUT_PATH,
                    f"opened {label} must remain a regular file",
                )
            opened_attributes = getattr(opened, "st_file_attributes", 0)
            if opened_attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0):
                raise CadecLoadError(
                    CadecLoadErrorCode.INPUT_PATH,
                    f"opened {label} must not be a reparse point",
                )
            if (
                path_item.st_ino
                and opened.st_ino
                and (path_item.st_dev, path_item.st_ino) != (opened.st_dev, opened.st_ino)
            ):
                raise CadecLoadError(
                    CadecLoadErrorCode.INPUT_PATH,
                    f"{label}_path changed between inspection and open",
                )
            payload = stream.read(maximum_bytes + 1)
    except OSError as error:
        raise CadecLoadError(
            CadecLoadErrorCode.INPUT_PATH, "input changed or became unreadable"
        ) from error
    if len(payload) > maximum_bytes:
        raise CadecLoadError(
            CadecLoadErrorCode.INPUT_PATH,
            f"{label} exceeds the finite input byte bound",
        )
    return bytes(payload)


def _bytes_identity(payload: bytes) -> tuple[int, str]:
    return len(payload), hashlib.sha256(payload).hexdigest()


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise CadecLoadError(
                CadecLoadErrorCode.MANIFEST_INTEGRITY, "manifest contains duplicate object names"
            )
        result[key] = value
    return result


def _read_and_validate_manifest(payload: bytes) -> _ManifestPolicy:
    try:
        root = json.loads(
            payload.decode("utf-8", errors="strict"), object_pairs_hook=_unique_object
        )
    except (UnicodeError, json.JSONDecodeError, RecursionError) as error:
        raise CadecLoadError(
            CadecLoadErrorCode.MANIFEST_INTEGRITY, "manifest must be exact UTF-8 JSON"
        ) from error
    manifest = _mapping(root, "manifest")
    archive = _mapping(manifest.get("archive"), "archive")
    _require(archive, "bytes", ARCHIVE_BYTES)
    _require(archive, "sha256", CADEC_ARCHIVE_SHA256)
    inventory = _mapping(manifest.get("inventory"), "inventory")
    _require(inventory, "entry_count", INVENTORY_ENTRY_COUNT)
    _require(inventory, "file_count", INVENTORY_FILE_COUNT)
    _require(inventory, "directory_count", INVENTORY_DIRECTORY_COUNT)
    raw_inventory = _sequence(inventory.get("members"), "inventory members")
    entries = tuple(_mapping(item, "inventory member") for item in raw_inventory)
    if len(entries) != INVENTORY_ENTRY_COUNT:
        _policy_error("manifest inventory length differs from the freeze")
    paths = tuple(_string(item.get("path"), "inventory path") for item in entries)
    if paths != tuple(sorted(paths)) or len(set(paths)) != len(paths):
        _policy_error("manifest inventory paths are not sorted and unique")

    canonical = _mapping(manifest.get("canonical_document_inventory"), "canonical inventory")
    approved = _mapping(manifest.get("approved_subset"), "approved subset")
    canonical_ids = _canonical_id_list(canonical, CADEC_CANONICAL_DOCUMENT_COUNT, "canonical")
    approved_ids = _canonical_id_list(approved, CADEC_APPROVED_DOCUMENT_COUNT, "approved")
    exclusions_root = _mapping(manifest.get("exclusion_ledger"), "exclusion ledger")
    exclusions = tuple(
        _string(item, "excluded document")
        for item in _sequence(exclusions_root.get("complete_document_ids"), "exclusions")
    )
    if exclusions != CADEC_EXCLUDED_DOCUMENT_IDS:
        _policy_error("exclusion ledger differs from the exact freeze")
    if tuple(item for item in canonical_ids if item not in exclusions) != approved_ids:
        _policy_error("approved subset is not canonical inventory minus exact exclusions")
    exclusion_files = _sequence(exclusions_root.get("excluded_archive_files"), "excluded files")
    expected_excluded_paths = tuple(
        sorted(
            f"cadec/{layer}/{document_id}{'.txt' if layer == 'text' else '.ann'}"
            for document_id in exclusions
            for layer in ("text", *_LAYERS)
        )
    )
    observed_excluded_paths = tuple(
        sorted(
            _string(_mapping(item, "excluded file").get("path"), "excluded file path")
            for item in exclusion_files
        )
    )
    if observed_excluded_paths != expected_excluded_paths:
        _policy_error("excluded-file ledger differs from the exact complete-document policy")

    split_by_document = _validate_splits(manifest, approved_ids)
    limited_rows = _validate_reference_ledger(manifest)
    malformed_rows = _validate_malformed_ledger(manifest)
    annotation_count_by_layer = _validate_annotation_aggregates(manifest)
    _validate_encoding_and_gold(manifest)
    _validate_layer_pairing(manifest, canonical_ids)
    return _ManifestPolicy(
        inventory=entries,
        canonical_ids=canonical_ids,
        approved_ids=approved_ids,
        exclusions=exclusions,
        split_by_document=split_by_document,
        limited_rows=limited_rows,
        malformed_rows=malformed_rows,
        annotation_count_by_layer=annotation_count_by_layer,
        canonical_sha256=_string(canonical.get("sha256"), "canonical digest"),
        approved_sha256=_string(approved.get("sha256"), "approved digest"),
        exclusion_sha256=_membership_digest(exclusions),
    )


def _validate_splits(
    manifest: Mapping[str, object], approved_ids: tuple[str, ...]
) -> Mapping[str, CadecSplit]:
    policy = _mapping(manifest.get("split_policy"), "split policy")
    _require(policy, "algorithm", "MEDEVIDENCE_CADEC_SPLIT_V1")
    memberships = _mapping(policy.get("memberships"), "split memberships")
    result: dict[str, CadecSplit] = {}
    expected_counts = {CadecSplit.TRAIN: 992, CadecSplit.DEVELOPMENT: 119, CadecSplit.TEST: 137}
    for split in CadecSplit:
        row = _mapping(memberships.get(split.value), f"{split.value} membership")
        members = tuple(
            _string(item, "split document")
            for item in _sequence(row.get("members"), "split members")
        )
        if members != tuple(sorted(members)) or len(members) != expected_counts[split]:
            _policy_error("split membership count, order, or uniqueness differs from the freeze")
        _require(row, "count", expected_counts[split])
        _require(row, "sha256", _SPLIT_DIGESTS[split])
        if _membership_digest(members) != _SPLIT_DIGESTS[split]:
            _policy_error("split membership digest does not reproduce")
        for document_id in members:
            if document_id in result:
                _policy_error("split memberships overlap")
            expected_bucket = (
                int.from_bytes(hashlib.sha256(document_id.encode("utf-8")).digest()[:8], "big")
                % 100
            )
            computed = (
                CadecSplit.TRAIN
                if expected_bucket <= 79
                else CadecSplit.DEVELOPMENT
                if expected_bucket <= 89
                else CadecSplit.TEST
            )
            if computed is not split:
                _policy_error("manifest split differs from the independently computed algorithm")
            result[document_id] = split
    if tuple(sorted(result)) != approved_ids:
        _policy_error("split union differs from the approved subset")
    return result


def _validate_reference_ledger(
    manifest: Mapping[str, object],
) -> Mapping[str, frozenset[tuple[str, int, str, str]]]:
    contract = _mapping(manifest.get("annotation_contract"), "annotation contract")
    binding = _mapping(contract.get("reference_binding"), "reference binding")
    layers = _mapping(binding.get("layers"), "reference-binding layers")
    expected_counts = {"original": 2, "meddra": 44, "sct": 45}
    result: dict[str, frozenset[tuple[str, int, str, str]]] = {}
    for layer, manifest_name in _MANIFEST_LAYER_NAMES.items():
        row = _mapping(layers.get(manifest_name), f"{layer} reference binding")
        ledger = _mapping(row.get("mismatch_ledger"), f"{layer} mismatch ledger")
        _require(row, "mismatch_count", expected_counts[layer])
        _require(ledger, "count", expected_counts[layer])
        items: set[tuple[str, int, str, str]] = set()
        for value in _sequence(ledger.get("items"), "mismatch items"):
            item = _mapping(value, "mismatch item")
            identity = (
                _string(item.get("member_path"), "limitation member path"),
                _integer(item.get("physical_line"), "limitation line"),
                _string(item.get("member_sha256"), "limitation member hash"),
                _string(item.get("raw_row_sha256"), "limitation row hash"),
            )
            if identity in items:
                _policy_error("reference-binding limitation ledger contains duplicates")
            items.add(identity)
        if len(items) != expected_counts[layer]:
            _policy_error("reference-binding limitation ledger differs from the freeze")
        result[layer] = frozenset(items)
    return result


def _validate_malformed_ledger(
    manifest: Mapping[str, object],
) -> frozenset[tuple[str, int, str, str]]:
    scan = _mapping(manifest.get("full_invalid_row_scan"), "invalid-row scan")
    _require(scan, "invalid_row_count", CADEC_MALFORMED_ROW_COUNT)
    result: set[tuple[str, int, str, str]] = set()
    for value in _sequence(scan.get("invalid_rows"), "invalid rows"):
        item = _mapping(value, "invalid row")
        result.add(
            (
                _string(item.get("member_path"), "invalid member path"),
                _integer(item.get("physical_line"), "invalid line"),
                _string(item.get("member_sha256"), "invalid member hash"),
                _string(item.get("raw_row_sha256"), "invalid row hash"),
            )
        )
    if len(result) != CADEC_MALFORMED_ROW_COUNT:
        _policy_error("malformed-row ledger differs from the exact five identities")
    return frozenset(result)


def _validate_annotation_aggregates(manifest: Mapping[str, object]) -> Mapping[str, int]:
    contract = _mapping(manifest.get("annotation_contract"), "annotation contract")
    facts = _mapping(
        contract.get("approved_subset_aggregate_facts"), "approved annotation aggregates"
    )
    expected = {"original": 9_089, "meddra": 6_300, "sct": 9_089}
    row_field = {
        "original": "entity_t_rows",
        "meddra": "normalization_tt_rows",
        "sct": "normalization_tt_rows",
    }
    for layer, manifest_name in _MANIFEST_LAYER_NAMES.items():
        row = _mapping(facts.get(manifest_name), f"{layer} annotation aggregate")
        _require(row, "files", CADEC_APPROVED_DOCUMENT_COUNT)
        _require(row, "invalid_rows", 0)
        _require(row, "out_of_bounds_segments", 0)
        _require(row, row_field[layer], expected[layer])
        _require(row, "span_rows", expected[layer])
    return expected


def _validate_encoding_and_gold(manifest: Mapping[str, object]) -> None:
    encoding = _mapping(manifest.get("encoding_policy"), "encoding policy")
    exception = _mapping(encoding.get("exact_exception"), "encoding exception")
    _require(exception, "member_path", CADEC_CP1252_MEMBER)
    _require(exception, "member_sha256", CADEC_CP1252_MEMBER_SHA256)
    _require(exception, "encoding", "Windows-1252")
    _require(encoding, "strict_utf8_successful_file_members", 4_999)
    _require(encoding, "unexpected_strict_utf8_failures", 0)
    gold = _mapping(manifest.get("gold_predicted_provenance"), "gold provenance")
    _require(gold, "archive_predicted_layer_or_artifact_observed", False)
    _require(gold, "predicted_outputs_admitted", "none")
    vocab = _mapping(manifest.get("controlled_vocabulary_boundary"), "vocabulary boundary")
    for field in ("identifiers_emitted", "terms_emitted", "hierarchy_emitted", "payload_emitted"):
        _require(vocab, field, False)


def _validate_layer_pairing(manifest: Mapping[str, object], canonical_ids: tuple[str, ...]) -> None:
    layers = _mapping(manifest.get("layer_inventory_and_pair_proof"), "layer pairing")
    for name in ("text", *_MANIFEST_LAYER_NAMES.values()):
        row = _mapping(layers.get(name), f"{name} layer")
        _require(row, "file_count", CADEC_CANONICAL_DOCUMENT_COUNT)
        _require(row, "paired_exactly_with_text_identity_set", True)
        identity_set = _mapping(row.get("identity_set"), f"{name} identity set")
        _require(identity_set, "count", len(canonical_ids))
        _require(identity_set, "sha256", _membership_digest(canonical_ids))


def _admit_archive(
    archive_bytes: bytes,
    *,
    policy: _ManifestPolicy,
    release: CadecReleaseManifestV1,
    archive_size: int,
    archive_hash: str,
    manifest_size: int,
    manifest_hash: str,
) -> CadecLoadResult:
    documents: list[CadecCorpusDocumentV1] = []
    annotations: list[CadecCorpusAnnotationV1] = []
    locators: list[CadecLocatorV1] = []
    malformed_seen: set[tuple[str, int, str, str]] = set()
    limitation_counts: Counter[str] = Counter()
    annotation_counts: Counter[str] = Counter()
    raw_out_of_order_transitions = 0
    raw_out_of_order_documents: set[str] = set()
    empty_document_count = 0
    try:
        with zipfile.ZipFile(io.BytesIO(archive_bytes)) as handle:
            records, total_uncompressed = _inspect_and_read_inventory(
                handle, expected=policy.inventory
            )
            by_path = {info.filename: info for info in handle.infolist()}
            for document_id in policy.canonical_ids:
                for layer in _LAYERS:
                    member_path = f"cadec/{layer}/{document_id}.ann"
                    info = by_path[member_path]
                    payload = _read_member(handle, info)
                    member_hash = hashlib.sha256(payload).hexdigest()
                    if document_id in policy.exclusions:
                        for physical_line, raw_row in enumerate(payload.splitlines(), 1):
                            if len(raw_row.split(b"\t")) != 3:
                                malformed_seen.add(
                                    (
                                        member_path,
                                        physical_line,
                                        member_hash,
                                        hashlib.sha256(raw_row).hexdigest(),
                                    )
                                )
            if malformed_seen != policy.malformed_rows:
                raise CadecLoadError(
                    CadecLoadErrorCode.ANNOTATION,
                    "observed malformed-row identities differ from the exact ledger",
                )
            for document_id in policy.approved_ids:
                split = policy.split_by_document[document_id]
                text_path = f"cadec/text/{document_id}.txt"
                text_payload = _read_member(handle, by_path[text_path])
                text_hash = hashlib.sha256(text_payload).hexdigest()
                try:
                    document_text = decode_text_member(
                        text_payload, member_path=text_path, member_sha256=text_hash
                    )
                except CadecParseError as error:
                    raise CadecLoadError(CadecLoadErrorCode.ENCODING, str(error)) from error
                if not document_text:
                    empty_document_count += 1
                    empty_members = {
                        layer: (
                            _read_member(handle, by_path[f"cadec/{layer}/{document_id}.ann"]),
                            f"cadec/{layer}/{document_id}.ann",
                        )
                        for layer in _LAYERS
                    }
                    _validate_empty_document_layers(empty_members)
                document_artifact_id = _member_artifact_id(text_path, text_hash)
                document_provenance = CadecProvenanceContextV1.create(
                    split=split,
                    artifact_id=document_artifact_id,
                    artifact_sha256=f"sha256:{text_hash}",
                    lineage_artifact_ids=(),
                )
                document = CadecCorpusDocumentV1.create(
                    split=split,
                    artifact_id=document_artifact_id,
                    artifact_sha256=f"sha256:{text_hash}",
                    document_id=document_id,
                    member_path=text_path,
                    text_length=len(document_text),
                    text_sha256=f"sha256:{text_hash}",
                    provenance=document_provenance,
                )
                document.validate_against(release)
                documents.append(document)
                for layer in _LAYERS:
                    member_path = f"cadec/{layer}/{document_id}.ann"
                    payload = _read_member(handle, by_path[member_path])
                    member_hash = hashlib.sha256(payload).hexdigest()
                    try:
                        parsed = parse_annotation_member(
                            payload,
                            document_text=document_text,
                            document_id=document_id,
                            layer=cast(Literal["original", "meddra", "sct"], layer),
                            member_path=member_path,
                            member_sha256=member_hash,
                            limited_row_identities=policy.limited_rows[layer],
                        )
                    except CadecParseError as error:
                        raise CadecLoadError(CadecLoadErrorCode.ANNOTATION, str(error)) from error
                    limitation_counts[layer] += parsed.reference_binding_limitation_count
                    annotation_counts[layer] += len(parsed.annotations)
                    raw_out_of_order_transitions += parsed.raw_out_of_order_transition_count
                    if parsed.has_raw_out_of_order_transition:
                        raw_out_of_order_documents.add(document_id)
                    annotation_artifact_id = _member_artifact_id(member_path, member_hash)
                    annotation_provenance = CadecProvenanceContextV1.create(
                        split=split,
                        artifact_id=annotation_artifact_id,
                        artifact_sha256=f"sha256:{member_hash}",
                        lineage_artifact_ids=(document_artifact_id,),
                    )
                    refs = _vocabulary_refs(layer)
                    for parsed_row in parsed.annotations:
                        annotation = CadecCorpusAnnotationV1.create(
                            split=split,
                            artifact_id=annotation_artifact_id,
                            artifact_sha256=f"sha256:{member_hash}",
                            annotation_id=parsed_row.annotation_id,
                            layer=layer,
                            member_path=member_path,
                            document_id=document_id,
                            document_artifact_id=document_artifact_id,
                            document_text_sha256=f"sha256:{text_hash}",
                            spans=parsed_row.spans,
                            surface_text_sha256=parsed_row.surface_text_sha256,
                            controlled_vocabulary_refs=refs,
                            provenance=annotation_provenance,
                            reference_binding_limited=parsed_row.reference_binding_limited,
                        )
                        annotation.validate_against(document, release)
                        locator = CadecLocatorV1.create(
                            corpus_id=annotation.corpus_id,
                            corpus_version=annotation.corpus_version,
                            release_manifest_sha256=annotation.release_manifest_sha256,
                            terminal_freeze_audit_sha256=annotation.terminal_freeze_audit_sha256,
                            split=annotation.split,
                            split_membership_sha256=annotation.split_membership_sha256,
                            artifact_id=annotation.artifact_id,
                            artifact_sha256=annotation.artifact_sha256,
                            document_id=annotation.document_id,
                            document_artifact_id=annotation.document_artifact_id,
                            document_text_sha256=annotation.document_text_sha256,
                            annotation_id=annotation.annotation_id,
                            annotation_record_id=annotation.annotation_record_id,
                            annotation_layer=annotation.layer,
                            annotation_member_path=annotation.member_path,
                            parent_artifact_lineage=(annotation.artifact_id,),
                            spans=annotation.spans,
                        )
                        locator.validate_against(
                            document=document, annotation=annotation, release_manifest=release
                        )
                        annotations.append(annotation)
                        locators.append(locator)
    except CadecLoadError:
        raise
    except (zipfile.BadZipFile, OSError, RuntimeError, ValueError, KeyError) as error:
        raise CadecLoadError(
            CadecLoadErrorCode.DOMAIN_CONTRACT,
            "CADEC admission failed closed during ZIP or domain validation",
        ) from error
    if limitation_counts != Counter({"original": 2, "meddra": 44, "sct": 45}):
        raise CadecLoadError(
            CadecLoadErrorCode.ANNOTATION,
            "observed reference-binding limitations differ from the exact 2/44/45 ledger",
        )
    if annotation_counts != Counter(policy.annotation_count_by_layer):
        raise CadecLoadError(
            CadecLoadErrorCode.ANNOTATION,
            "admitted provider-row counts differ from the exact layer aggregates",
        )
    if raw_out_of_order_transitions != 43 or len(raw_out_of_order_documents) != 26:
        raise CadecLoadError(
            CadecLoadErrorCode.ANNOTATION,
            "raw out-of-order span diagnostics differ from the exact 43/26 freeze",
        )
    if empty_document_count != 2:
        raise CadecLoadError(
            CadecLoadErrorCode.ANNOTATION,
            "empty-document count differs from the exact production archive observation",
        )
    summary = CadecVerificationSummary(
        archive_sha256=archive_hash,
        archive_bytes=archive_size,
        manifest_sha256=manifest_hash,
        manifest_bytes=manifest_size,
        inventory_sha256=_inventory_digest(records),
        inventory_entry_count=len(records),
        inventory_file_count=INVENTORY_FILE_COUNT,
        inventory_directory_count=INVENTORY_DIRECTORY_COUNT,
        inventory_uncompressed_bytes=total_uncompressed,
        canonical_document_count=len(policy.canonical_ids),
        canonical_document_sha256=policy.canonical_sha256,
        approved_document_count=len(policy.approved_ids),
        approved_document_sha256=policy.approved_sha256,
        excluded_document_count=len(policy.exclusions),
        excluded_document_sha256=policy.exclusion_sha256,
        train_count=sum(split is CadecSplit.TRAIN for split in policy.split_by_document.values()),
        train_membership_sha256=CADEC_TRAIN_MEMBERSHIP_SHA256,
        development_count=sum(
            split is CadecSplit.DEVELOPMENT for split in policy.split_by_document.values()
        ),
        development_membership_sha256=CADEC_DEVELOPMENT_MEMBERSHIP_SHA256,
        test_count=sum(split is CadecSplit.TEST for split in policy.split_by_document.values()),
        test_membership_sha256=CADEC_TEST_MEMBERSHIP_SHA256,
        encoding_exception_verified=True,
        empty_document_count=empty_document_count,
        malformed_row_count=len(malformed_seen),
        original_reference_binding_limitation_count=limitation_counts["original"],
        meddra_reference_binding_limitation_count=limitation_counts["meddra"],
        sct_reference_binding_limitation_count=limitation_counts["sct"],
        raw_out_of_order_transition_count=raw_out_of_order_transitions,
        raw_out_of_order_document_count=len(raw_out_of_order_documents),
        provider_gold_only=True,
        predicted_artifact_admitted=False,
        output_document_count=len(documents),
        output_annotation_count=len(annotations),
        output_original_annotation_count=annotation_counts["original"],
        output_meddra_annotation_count=annotation_counts["meddra"],
        output_sct_annotation_count=annotation_counts["sct"],
        output_locator_count=len(locators),
        all_validation_passed=True,
    )
    return CadecLoadResult(release, tuple(documents), tuple(annotations), tuple(locators), summary)


def _inspect_and_read_inventory(
    handle: zipfile.ZipFile, *, expected: tuple[Mapping[str, object], ...] | None
) -> tuple[tuple[dict[str, object], ...], int]:
    infos = handle.infolist()
    if len(infos) > MAX_ZIP_ENTRIES:
        raise CadecLoadError(
            CadecLoadErrorCode.UNSAFE_ZIP, "ZIP exceeds the finite entry-count bound"
        )
    if expected is not None and len(infos) != INVENTORY_ENTRY_COUNT:
        raise CadecLoadError(CadecLoadErrorCode.INVENTORY_MISMATCH, "ZIP entry count differs")
    aggregate_compressed = sum(info.compress_size for info in infos)
    aggregate_uncompressed = sum(info.file_size for info in infos)
    if aggregate_compressed > MAX_AGGREGATE_COMPRESSED_BYTES:
        raise CadecLoadError(
            CadecLoadErrorCode.UNSAFE_ZIP,
            "ZIP exceeds the aggregate compressed-byte bound",
        )
    if aggregate_uncompressed > MAX_AGGREGATE_UNCOMPRESSED_BYTES:
        raise CadecLoadError(
            CadecLoadErrorCode.UNSAFE_ZIP,
            "ZIP exceeds the aggregate uncompressed-byte bound",
        )
    if aggregate_uncompressed > max(1, aggregate_compressed) * MAX_EXPANSION_RATIO:
        raise CadecLoadError(
            CadecLoadErrorCode.UNSAFE_ZIP, "ZIP exceeds the finite expansion-ratio bound"
        )
    names: set[str] = set()
    folded: set[str] = set()
    records: list[dict[str, object]] = []
    total = 0
    expected_by_path = (
        {_string(item.get("path"), "inventory path"): item for item in expected}
        if expected is not None
        else None
    )
    for info in infos:
        name = _safe_zip_name(info.filename, info.is_dir())
        key = name.removesuffix("/")
        if key in names or key.casefold() in folded:
            raise CadecLoadError(CadecLoadErrorCode.UNSAFE_ZIP, "ZIP contains duplicate paths")
        names.add(key)
        folded.add(key.casefold())
        if info.flag_bits & 0x1:
            raise CadecLoadError(
                CadecLoadErrorCode.UNSAFE_ZIP, "encrypted ZIP entries are forbidden"
            )
        if info.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}:
            raise CadecLoadError(CadecLoadErrorCode.UNSAFE_ZIP, "unsupported ZIP compression")
        if info.extract_version > 45 or info.file_size > MAX_MEMBER_BYTES:
            raise CadecLoadError(
                CadecLoadErrorCode.UNSAFE_ZIP, "ZIP64 or oversized member forbidden"
            )
        mode = (info.external_attr >> 16) & 0xFFFF
        kind = stat.S_IFMT(mode)
        if kind and not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)):
            raise CadecLoadError(CadecLoadErrorCode.UNSAFE_ZIP, "special ZIP member forbidden")
        body = b"" if info.is_dir() else _read_member(handle, info)
        if len(body) != info.file_size:
            raise CadecLoadError(CadecLoadErrorCode.UNSAFE_ZIP, "ZIP member read was truncated")
        total += len(body)
        record: dict[str, object] = {
            "compressed_bytes": info.compress_size,
            "entry_kind": "directory" if info.is_dir() else "file",
            "media_type": _media_type(name, info.is_dir()),
            "path": name,
            "sha256_uncompressed_bytes": hashlib.sha256(body).hexdigest(),
            "uncompressed_bytes": len(body),
        }
        if expected_by_path is not None and expected_by_path.get(name) != record:
            raise CadecLoadError(
                CadecLoadErrorCode.INVENTORY_MISMATCH,
                "ZIP member metadata or exact bytes differ from the manifest",
            )
        records.append(record)
    if expected_by_path is not None and set(expected_by_path) != {
        str(row["path"]) for row in records
    }:
        raise CadecLoadError(
            CadecLoadErrorCode.INVENTORY_MISMATCH, "ZIP inventory path set differs"
        )
    records.sort(key=lambda row: str(row["path"]))
    return tuple(records), total


def _read_member(handle: zipfile.ZipFile, info: zipfile.ZipInfo) -> bytes:
    try:
        with handle.open(info, "r") as stream:
            body = stream.read(MAX_MEMBER_BYTES + 1)
            if len(body) > MAX_MEMBER_BYTES or stream.read(1):
                raise CadecLoadError(CadecLoadErrorCode.UNSAFE_ZIP, "ZIP member exceeds bound")
            return body
    except (zipfile.BadZipFile, OSError, RuntimeError) as error:
        raise CadecLoadError(
            CadecLoadErrorCode.UNSAFE_ZIP, "ZIP CRC or member read failed"
        ) from error


def _safe_zip_name(name: str, is_directory: bool) -> str:
    if not name or "\\" in name or "\x00" in name or not name.isascii():
        raise CadecLoadError(CadecLoadErrorCode.UNSAFE_ZIP, "ZIP member name is unsafe")
    path = PurePosixPath(name)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise CadecLoadError(CadecLoadErrorCode.UNSAFE_ZIP, "ZIP member path is noncanonical")
    expected = f"{path.as_posix().removesuffix('/')}" + ("/" if is_directory else "")
    if expected != name:
        raise CadecLoadError(CadecLoadErrorCode.UNSAFE_ZIP, "ZIP directory marker is inconsistent")
    return name


def _media_type(path: str, directory: bool) -> str:
    if directory:
        return "application/x-directory"
    if path.endswith(".txt"):
        return "text/plain"
    if path.endswith(".ann"):
        return "text/annotation"
    raise CadecLoadError(CadecLoadErrorCode.UNSAFE_ZIP, "unexpected ZIP member extension")


def _member_artifact_id(member_path: str, member_hash: str) -> str:
    return derive_identity(
        "cadec-member-artifact",
        {"member_path": member_path, "sha256": f"sha256:{member_hash}"},
    )


def _validate_empty_document_layers(
    members: Mapping[str, tuple[bytes, str]],
) -> None:
    """Require all three annotation members to have zero rows for empty text."""

    if tuple(sorted(members)) != tuple(sorted(_LAYERS)):
        raise CadecLoadError(
            CadecLoadErrorCode.ANNOTATION,
            "empty document must bind exactly the original, MedDRA, and SCT layers",
        )
    for layer in _LAYERS:
        payload, member_path = members[layer]
        member_hash = hashlib.sha256(payload).hexdigest()
        try:
            decoded = decode_text_member(
                payload, member_path=member_path, member_sha256=member_hash
            )
        except CadecParseError as error:
            raise CadecLoadError(CadecLoadErrorCode.ENCODING, str(error)) from error
        if decoded.splitlines():
            raise CadecLoadError(
                CadecLoadErrorCode.ANNOTATION,
                "empty document requires zero annotation rows in every layer",
            )


def _vocabulary_refs(layer: str) -> tuple[ControlledVocabularyRefV1, ...]:
    if layer == "original":
        return ()
    reference = (
        CadecControlledVocabularyLayer.MEDDRA
        if layer == "meddra"
        else CadecControlledVocabularyLayer.SNOMED_CT
    )
    return (ControlledVocabularyRefV1(reference=reference),)


def _inventory_digest(records: Sequence[Mapping[str, object]]) -> str:
    return hashlib.sha256(canonical_json(tuple(records)).encode("utf-8")).hexdigest()


def _membership_digest(members: Sequence[str]) -> str:
    return hashlib.sha256(("".join(f"{item}\n" for item in members)).encode("utf-8")).hexdigest()


def _canonical_id_list(
    row: Mapping[str, object], expected_count: int, label: str
) -> tuple[str, ...]:
    _require(row, "count", expected_count)
    members = tuple(
        _string(item, f"{label} document")
        for item in _sequence(row.get("members"), f"{label} members")
    )
    if members != tuple(sorted(set(members))) or len(members) != expected_count:
        _policy_error(f"{label} document membership is not exact, unique, and sorted")
    digest = _membership_digest(members)
    _require(row, "sha256", digest)
    return members


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        _policy_error(f"{label} must be a JSON object")
    return cast(Mapping[str, object], value)


def _sequence(value: object, label: str) -> Sequence[object]:
    if not isinstance(value, list):
        _policy_error(f"{label} must be a JSON array")
    return cast(Sequence[object], value)


def _string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        _policy_error(f"{label} must be exact nonblank text")
    return cast(str, value)


def _integer(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        _policy_error(f"{label} must be a nonnegative JSON integer")
    return cast(int, value)


def _require(row: Mapping[str, object], field: str, expected: object) -> None:
    if row.get(field) != expected or field not in row:
        _policy_error(f"manifest field {field!r} differs from the exact freeze")


def _policy_error(message: str) -> None:
    raise CadecLoadError(CadecLoadErrorCode.MANIFEST_POLICY, message)


__all__ = [
    "ARCHIVE_BYTES",
    "INVENTORY_DIRECTORY_COUNT",
    "INVENTORY_ENTRY_COUNT",
    "INVENTORY_FILE_COUNT",
    "MAX_AGGREGATE_COMPRESSED_BYTES",
    "MAX_AGGREGATE_UNCOMPRESSED_BYTES",
    "MAX_ARCHIVE_INPUT_BYTES",
    "MAX_EXPANSION_RATIO",
    "MAX_MANIFEST_INPUT_BYTES",
    "MAX_MEMBER_BYTES",
    "MAX_ZIP_ENTRIES",
    "CadecInventorySummary",
    "CadecLoadError",
    "CadecLoadErrorCode",
    "CadecLoadResult",
    "CadecVerificationSummary",
    "inspect_zip_inventory",
    "load_cadec_archive",
]
