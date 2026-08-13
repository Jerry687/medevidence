"""Unit tests for safe synthetic ZIP inspection and production locking."""

from __future__ import annotations

import hashlib
import json
import stat
import zipfile
from dataclasses import asdict, fields
from pathlib import Path
from typing import IO, Any, cast

import pytest

import medevidence.connectors.cadec.loader as loader_module
from medevidence.connectors.cadec import (
    CadecLoadError,
    CadecLoadErrorCode,
    CadecVerificationSummary,
    inspect_zip_inventory,
    load_cadec_archive,
)
from medevidence.connectors.cadec.loader import (
    _member_artifact_id,
    _read_regular_input_bytes,
    _validate_empty_document_layers,
)
from medevidence.domain import derive_identity

FIXTURES = Path("tests/fixtures/cadec")


def _zip(path: Path, members: list[tuple[str, bytes]]) -> Path:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, payload in members:
            archive.writestr(name, payload)
    return path


def test_synthetic_inventory_is_read_in_memory_without_production_admission(
    tmp_path: Path,
) -> None:
    archive = _zip(
        tmp_path / "synthetic.zip",
        [("cadec/", b""), ("cadec/text/", b""), ("cadec/text/SYNTHETIC.1.txt", b"Alpha")],
    )

    summary = inspect_zip_inventory(archive.resolve())

    assert (summary.entry_count, summary.file_count, summary.directory_count) == (3, 1, 2)
    assert summary.total_uncompressed_bytes == 5
    assert len(summary.inventory_sha256) == 64
    assert (
        json.loads((FIXTURES / "synthetic-asset-manifest.json").read_text())[
            "production_admission_authorized"
        ]
        is False
    )


@pytest.mark.parametrize(
    "name,payload,message",
    [
        ("../escape.txt", b"x", "noncanonical"),
        ("cadec/text/SYNTHETIC.1.bin", b"x", "extension"),
        ("cadec/text/SYNTHETIC.1.txt", b"x" * 3597, "oversized"),
    ],
)
def test_synthetic_inventory_rejects_unsafe_members(
    tmp_path: Path, name: str, payload: bytes, message: str
) -> None:
    archive = _zip(tmp_path / "unsafe.zip", [(name, payload)])
    with pytest.raises(CadecLoadError, match=message):
        inspect_zip_inventory(archive.resolve())


def test_synthetic_inventory_rejects_symlink_member(tmp_path: Path) -> None:
    archive_path = tmp_path / "symlink.zip"
    info = zipfile.ZipInfo("cadec/text/SYNTHETIC.1.txt")
    info.create_system = 3
    info.external_attr = (stat.S_IFLNK | 0o777) << 16
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr(info, b"target")

    with pytest.raises(CadecLoadError, match="special ZIP member"):
        inspect_zip_inventory(archive_path.resolve())


def test_public_loader_rejects_synthetic_manifest_before_archive_admission(
    tmp_path: Path,
) -> None:
    archive = _zip(tmp_path / "synthetic.zip", [("cadec/", b"")])
    manifest = (FIXTURES / "synthetic-asset-manifest.json").resolve()

    with pytest.raises(CadecLoadError) as raised:
        load_cadec_archive(archive.resolve(), manifest)

    assert raised.value.code is CadecLoadErrorCode.MANIFEST_INTEGRITY


def test_public_loader_uses_each_opened_input_bytes_once_despite_path_replacement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive_path = (tmp_path / "archive.zip").resolve()
    manifest_path = (tmp_path / "manifest.json").resolve()
    archive_original = b"original archive bytes"
    manifest_original = b'{"original":true}'
    archive_path.write_bytes(archive_original)
    manifest_path.write_bytes(manifest_original)
    original_open = Path.open
    untyped_open: Any = original_open
    open_counts = {archive_path: 0, manifest_path: 0}

    class ReplaceOnClose:
        def __init__(self, stream: IO[bytes], path: Path) -> None:
            self.stream = stream
            self.path = path

        def __enter__(self) -> ReplaceOnClose:
            return self

        def __exit__(self, *args: object) -> None:
            self.stream.close()
            with original_open(self.path, "wb") as replacement:
                replacement.write(b"replacement bytes")

        def fileno(self) -> int:
            return self.stream.fileno()

        def read(self, size: int = -1) -> bytes:
            return self.stream.read(size)

    def replacing_open(path: Path, *args: object, **kwargs: object) -> ReplaceOnClose:
        resolved = path.resolve()
        open_counts[resolved] += 1
        return ReplaceOnClose(untyped_open(path, *args, **kwargs), resolved)

    captured: dict[str, object] = {}
    monkeypatch.setattr(Path, "open", replacing_open)
    monkeypatch.setattr(loader_module, "ARCHIVE_BYTES", len(archive_original))
    monkeypatch.setattr(
        loader_module, "CADEC_ARCHIVE_SHA256", hashlib.sha256(archive_original).hexdigest()
    )
    monkeypatch.setattr(loader_module, "CADEC_EXTERNAL_MANIFEST_BYTES", len(manifest_original))
    monkeypatch.setattr(
        loader_module,
        "CADEC_EXTERNAL_MANIFEST_SHA256",
        hashlib.sha256(manifest_original).hexdigest(),
    )
    monkeypatch.setattr(
        loader_module,
        "_read_and_validate_manifest",
        lambda payload: captured.setdefault("manifest", payload),
    )

    def admit(payload: bytes, **kwargs: object) -> object:
        captured["archive"] = payload
        captured["policy"] = kwargs["policy"]
        return captured

    monkeypatch.setattr(loader_module, "_admit_archive", admit)

    result = load_cadec_archive(archive_path, manifest_path)

    assert cast(object, result) is captured
    assert captured["archive"] == archive_original
    assert captured["manifest"] == manifest_original
    assert open_counts == {archive_path: 1, manifest_path: 1}
    with original_open(archive_path, "rb") as stream:
        assert stream.read() == b"replacement bytes"
    with original_open(manifest_path, "rb") as stream:
        assert stream.read() == b"replacement bytes"


def test_regular_input_byte_bound_accepts_at_limit_and_rejects_one_over(
    tmp_path: Path,
) -> None:
    exact = (tmp_path / "exact.bin").resolve()
    over = (tmp_path / "over.bin").resolve()
    exact.write_bytes(b"1234")
    over.write_bytes(b"12345")

    assert _read_regular_input_bytes(exact, "archive", 4) == b"1234"
    with pytest.raises(CadecLoadError, match="finite input byte bound"):
        _read_regular_input_bytes(over, "archive", 4)


def test_inventory_entry_bound_accepts_exact_limit_and_rejects_10001(
    tmp_path: Path,
) -> None:
    exact = _zip(
        tmp_path / "exact-entries.zip",
        [(f"cadec/text/{index}.txt", b"") for index in range(loader_module.MAX_ZIP_ENTRIES)],
    )
    excessive = _zip(
        tmp_path / "excessive-entries.zip",
        [(f"cadec/text/{index}.txt", b"") for index in range(10_001)],
    )

    assert inspect_zip_inventory(exact.resolve()).entry_count == loader_module.MAX_ZIP_ENTRIES
    with pytest.raises(CadecLoadError, match="entry-count bound"):
        inspect_zip_inventory(excessive.resolve())


def test_inventory_aggregate_compressed_and_uncompressed_bounds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    exact = _zip(
        tmp_path / "aggregate-exact.zip",
        [("cadec/text/1.txt", b"12345"), ("cadec/text/2.txt", b"67890")],
    )
    over = _zip(
        tmp_path / "aggregate-over.zip",
        [("cadec/text/1.txt", b"12345"), ("cadec/text/2.txt", b"678901")],
    )
    monkeypatch.setattr(loader_module, "MAX_AGGREGATE_UNCOMPRESSED_BYTES", 10)
    monkeypatch.setattr(loader_module, "MAX_EXPANSION_RATIO", 10_000)

    assert inspect_zip_inventory(exact.resolve()).total_uncompressed_bytes == 10
    with pytest.raises(CadecLoadError, match="aggregate uncompressed-byte bound"):
        inspect_zip_inventory(over.resolve())

    monkeypatch.setattr(loader_module, "MAX_AGGREGATE_UNCOMPRESSED_BYTES", 100)
    with zipfile.ZipFile(exact) as archive:
        compressed_total = sum(info.compress_size for info in archive.infolist())
    monkeypatch.setattr(loader_module, "MAX_AGGREGATE_COMPRESSED_BYTES", compressed_total)
    assert inspect_zip_inventory(exact.resolve()).entry_count == 2
    monkeypatch.setattr(loader_module, "MAX_AGGREGATE_COMPRESSED_BYTES", compressed_total - 1)
    with pytest.raises(CadecLoadError, match="aggregate compressed-byte bound"):
        inspect_zip_inventory(exact.resolve())


def test_inventory_expansion_ratio_bound_is_finite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stored = tmp_path / "stored.zip"
    with zipfile.ZipFile(stored, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr("cadec/text/1.txt", b"1234567890")
    compressed = _zip(tmp_path / "compressed.zip", [("cadec/text/1.txt", b"0" * 3_596)])
    monkeypatch.setattr(loader_module, "MAX_EXPANSION_RATIO", 1)

    assert inspect_zip_inventory(stored.resolve()).total_uncompressed_bytes == 10
    with pytest.raises(CadecLoadError, match="expansion-ratio bound"):
        inspect_zip_inventory(compressed.resolve())


def test_empty_document_accepts_exactly_three_empty_annotation_layers() -> None:
    _validate_empty_document_layers(
        {
            "original": (b"", "cadec/original/SYNTHETIC.1.ann"),
            "meddra": (b"", "cadec/meddra/SYNTHETIC.1.ann"),
            "sct": (b"", "cadec/sct/SYNTHETIC.1.ann"),
        }
    )


def test_empty_document_rejects_a_nonempty_annotation_layer() -> None:
    with pytest.raises(CadecLoadError, match="zero annotation rows"):
        _validate_empty_document_layers(
            {
                "original": (b"T1\tADR 0 1\tx\n", "cadec/original/SYNTHETIC.1.ann"),
                "meddra": (b"", "cadec/meddra/SYNTHETIC.1.ann"),
                "sct": (b"", "cadec/sct/SYNTHETIC.1.ann"),
            }
        )


def test_member_identity_keeps_empty_members_distinct_by_canonical_path() -> None:
    digest = "0" * 64
    first = _member_artifact_id("cadec/original/SYNTHETIC.1.ann", digest)
    second = _member_artifact_id("cadec/meddra/SYNTHETIC.1.ann", digest)

    assert first != second
    assert first == derive_identity(
        "cadec-member-artifact",
        {
            "member_path": "cadec/original/SYNTHETIC.1.ann",
            "sha256": f"sha256:{digest}",
        },
    )


def test_verification_summary_schema_is_right_safe() -> None:
    field_names = {field.name for field in fields(CadecVerificationSummary)}
    serialized_names = set(asdict) if False else field_names

    assert serialized_names.isdisjoint(
        {"text", "term", "raw_row", "spans", "offsets", "identifiers", "payload"}
    )
    assert {
        "archive_sha256",
        "manifest_sha256",
        "raw_out_of_order_transition_count",
        "raw_out_of_order_document_count",
        "empty_document_count",
        "all_validation_passed",
    } <= field_names
