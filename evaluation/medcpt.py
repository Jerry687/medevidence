"""Offline-only MedCPT retrieval for the M2 evaluation harness."""

from __future__ import annotations

import hashlib
import importlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import numpy as np

ARTIFACT_SCHEMA = "medevidence.m2-002.medcpt-artifact-acquisition.v1r1"
ARTIFACT_MANIFEST_NAME = "medcpt-artifact-acquisition-r1.json"
ARTIFACT_MANIFEST_BYTES = 94_242
ARTIFACT_MANIFEST_SHA256 = "5943ceda5c8f3792af473a737099a6954fb30aaf62c1ec1334315305915f6755"
ARTIFACT_LEDGER_NAME = "network-ledger-r1.raw.json"
ARTIFACT_LEDGER_BYTES = 56_755
ARTIFACT_LEDGER_SHA256 = "a7b66388278e29f88b1602faffb6a195d3f1bd96f1769a2187394bb6193c97e5"
QUERY_REPO = "ncbi/MedCPT-Query-Encoder"
ARTICLE_REPO = "ncbi/MedCPT-Article-Encoder"
QUERY_REVISION = "d83a36cc6b8e3a5c5e9d9d6ba156808c1643dcbc"
ARTICLE_REVISION = "d05a736da4bb84ee4057b7f7999485be6ed85465"
AGGREGATE_ALGORITHM = (
    "SHA-256 over UTF-8 LF-terminated ordered lines: "
    "repo_id@revision TAB filename TAB bytes TAB sha256"
)
APPROVED_AGGREGATE_SHA256 = "64f7094f2b7384d17219200436990aaceb1a321e00578f5f576c6546f2d42d2a"
TOP_FIELDS = {
    "schema_version",
    "status",
    "started_at_utc",
    "completed_at_utc",
    "scope",
    "network_policy",
    "environment",
    "allowlist",
    "preserved_raw_metadata_before",
    "preserved_raw_metadata_after",
    "repositories",
    "canonical_aggregate_identity",
    "network_ledger",
    "metadata_acquisition_lineage",
}
REPOSITORY_FIELDS = {
    "role",
    "repo_id",
    "requested_revision",
    "resolved_revision",
    "immutable_full_sha_match",
    "metadata",
    "cache",
    "files",
    "config_validation",
    "tokenizer_validation",
    "documentation_validation",
    "safetensors_validation",
    "upstream_forbidden_files_visible_but_not_selected",
}
FILE_FIELDS = {
    "path",
    "cache_relative_path",
    "bytes",
    "sha256",
    "hf_blob_id",
    "hf_lfs_sha256",
    "requested_url",
    "final_url",
    "redirect_count",
    "transport_attempts",
    "etag",
}
CACHE_FIELDS = {"layout", "snapshot_path", "external_to_repository"}
FINAL_URL_FIELDS = {
    "exact_url",
    "redacted_url",
    "exact_url_sha256",
    "host",
    "path",
    "signed_query_redacted",
}


@dataclass(frozen=True)
class PinnedFile:
    """Independent trust root for one approved snapshot file."""

    path: str
    bytes: int
    sha256: str
    hf_blob_id: str
    final_url_sha256: str


APPROVED_FILES: dict[str, tuple[PinnedFile, ...]] = {
    "query": (
        PinnedFile(
            "LICENSE",
            1239,
            "76b0009b86bfcb6dbbe5d51aa95a8103ddb2e9d582dca41c3d88e371175ce34e",
            "2a32e2a05f3d0456bebc38e31d67126a17937a9a",
            "a066c93bda965675f2fef9bab9725e36bfff481f844ef4a03a40a0989b02ce70",
        ),
        PinnedFile(
            "README.md",
            4121,
            "4451e5399fe6e8c5a4b9db86ad9ae324e2b337f0f4c7e963aaf6131b3e8dd635",
            "e5b1daeaefc9dd5976023033e0e9d40de74211d1",
            "51ac37597ec3ecb1bd297345335a58c894f06c8cfeb05fdcde1b6ab6b15828a1",
        ),
        PinnedFile(
            "added_tokens.json",
            74,
            "691a5ce0135045c12b8410af8d472ff8de864094df40ac9af418d6c644c7588d",
            "e97f8f93bfdfff48a98fde37a3cd61007272f226",
            "26ff4663dcc5edb3ac4a6c29784c51a56a51bf2fb5f48ffd00d9076da72f23c7",
        ),
        PinnedFile(
            "config.json",
            608,
            "3fea00b31d018d676d6b7e2f6cddcfe1abc69bcb88f5f09f51b848212e1671d1",
            "0fdb62e1e58c8ec1c979a498adb692476730afe8",
            "d1528cf88bf83df5a7a9a1bbed53d2188bac38e2dc03053274511d94d978929e",
        ),
        PinnedFile(
            "model.safetensors",
            437_951_328,
            "19d78c0d5eaee2f81e6c47c5425bbadcc0c6af016cbb5da4a000d64e59d6e342",
            "2bda3c3add0473d715c272e395debb63d02b532c",
            "3b48b22408a055d400da193464b4dd4c382d05ffe8d31cfe4f98d5844dd24649",
        ),
        PinnedFile(
            "special_tokens_map.json",
            125,
            "b6d346be366a7d1d48332dbc9fdf3bf8960b5d879522b7799ddba59e76237ee3",
            "a8b3208c2884c4efb86e49300fdd3dc877220cdf",
            "8d8ad247a4655a6218fa2a482c9dab5b59a7ec1004be190550f4d7d700d888f2",
        ),
        PinnedFile(
            "tokenizer.json",
            706_277,
            "6e046044df8a2fcedb10607075dca187cae61d806c0d80a96c5b81017edc90c9",
            "e68fee3b6ebe7cc02f2b5f9753071bdf2c401ecf",
            "18be23f8542fbfc534b2fbd3b2da63c9669a4acd9c99ab61c19ab9eee7735849",
        ),
        PinnedFile(
            "tokenizer_config.json",
            1488,
            "cabeefb4bbba68c42d40a56bfc1e73dd2e5dfb6e0ca90a66349519c375452d1e",
            "a2e9fe3b9f5f82565a81e85b686910b20f6ee126",
            "7309e83bf831490a315fd80b257a2ffe167f034f9eb0690304f1e4584a5ca3d9",
        ),
        PinnedFile(
            "vocab.txt",
            226_150,
            "79489a52be45e6fa033521e8ce8e4f62aedc0a742ee2aa6fc04667e5b0b1454d",
            "9d595d9c20feef7012f174efaaa5eb621910588e",
            "abe04eae89466e5cf93dad90f40cc57f57b8d63474a61ae61ca850aaa7f801db",
        ),
    ),
    "article": (
        PinnedFile(
            "LICENSE",
            1239,
            "76b0009b86bfcb6dbbe5d51aa95a8103ddb2e9d582dca41c3d88e371175ce34e",
            "2a32e2a05f3d0456bebc38e31d67126a17937a9a",
            "1762e0a5ca198d5f99090782d6f89a92a32897e3130b8ceb3eb11548a702aa02",
        ),
        PinnedFile(
            "README.md",
            4909,
            "27328ae1218fb0167e8ac00b70de513446ebae73a8640083595e24fb08deefa5",
            "832d740b90ee8f8b1fdb79748ca33f69af352d8f",
            "3c9a01484a7590af283c99904c89e925c947a2612ca3f7e17ebbb2beffb9cc30",
        ),
        PinnedFile(
            "added_tokens.json",
            74,
            "691a5ce0135045c12b8410af8d472ff8de864094df40ac9af418d6c644c7588d",
            "e97f8f93bfdfff48a98fde37a3cd61007272f226",
            "609f86ae2e8eff7c06352ec1414a6916b19f09d327b02399c8223cd6392567dd",
        ),
        PinnedFile(
            "config.json",
            608,
            "3fea00b31d018d676d6b7e2f6cddcfe1abc69bcb88f5f09f51b848212e1671d1",
            "0fdb62e1e58c8ec1c979a498adb692476730afe8",
            "f7145716de040bbdc570bf56f1a48150125bc278f81148ec7d3ebce36a06b815",
        ),
        PinnedFile(
            "model.safetensors",
            437_951_328,
            "a5d5ffe4d8666c1d0aa15f371b94fc3492ca8f927e5621abd4b3ee9fc845b0f3",
            "1e765f6b64fa883a12b280e3e434ac4e1b2115da",
            "c23f66d02262ef0931b1498e11b211efcbd61c81ed988ea0c5504e84a8a07e67",
        ),
        PinnedFile(
            "special_tokens_map.json",
            125,
            "b6d346be366a7d1d48332dbc9fdf3bf8960b5d879522b7799ddba59e76237ee3",
            "a8b3208c2884c4efb86e49300fdd3dc877220cdf",
            "5235870f24ad74a55aeb036b7399f32529169424a5f810eb81299a67925d0eed",
        ),
        PinnedFile(
            "tokenizer.json",
            706_277,
            "6e046044df8a2fcedb10607075dca187cae61d806c0d80a96c5b81017edc90c9",
            "e68fee3b6ebe7cc02f2b5f9753071bdf2c401ecf",
            "ceff1023f4a3f418287d5c2913f87388ca4a9ea817bbccda32e658b4e2cbe1d8",
        ),
        PinnedFile(
            "tokenizer_config.json",
            1488,
            "cabeefb4bbba68c42d40a56bfc1e73dd2e5dfb6e0ca90a66349519c375452d1e",
            "a2e9fe3b9f5f82565a81e85b686910b20f6ee126",
            "9ca335f9d54be4a997308f20635d1cbce71fdb8105a50e87592497f2c4818bc0",
        ),
        PinnedFile(
            "vocab.txt",
            226_150,
            "79489a52be45e6fa033521e8ce8e4f62aedc0a742ee2aa6fc04667e5b0b1454d",
            "9d595d9c20feef7012f174efaaa5eb621910588e",
            "d4f7f2f4225dbd8e24a8772bc432c07949c8db19a4b5496be789e39b858d50ab",
        ),
    ),
}
MODEL_FILES = frozenset(file.path for file in APPROVED_FILES["query"])
APPROVED_METADATA = {
    "query": (
        "query-model-metadata.raw.json",
        2943,
        "6ead632a25d705d455ab3f85cfd517a9551f5ae99191a3e1094262310a80e9cd",
    ),
    "article": (
        "article-model-metadata.raw.json",
        2855,
        "5d71f6b956e598e431eed3a7b12a913122e57c968d4b4b0ac13004b8df8ec8f0",
    ),
}
PINNED_MODEL_FINAL_PATH = {
    "query": (
        "/xet-bridge-us/65384bec5235cb10ae55f06e/"
        "22c780ede51ea32262a56b47151e5d160915883ceab61ed22a57b2708fe20fd3"
    ),
    "article": (
        "/xet-bridge-us/65384b73b81c2790a3d1190f/"
        "5679d9484dc10ead6a3503c6d28590817e287fb89c4f4154408f24a8723bae43"
    ),
}


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate artifact-manifest key {key!r}")
        result[key] = value
    return result


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _file_size(path: Path) -> int:
    return path.stat().st_size


def _load_strict_json(path: Path, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_strict_object,
        )
    except json.JSONDecodeError as error:
        raise ValueError(f"{label} is not valid JSON") from error
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must be a JSON object")
    return payload


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _canonical_aggregate_identity() -> dict[str, Any]:
    lines: list[str] = []
    total_bytes = 0
    for role, repo_id, revision in (
        ("query", QUERY_REPO, QUERY_REVISION),
        ("article", ARTICLE_REPO, ARTICLE_REVISION),
    ):
        for file in APPROVED_FILES[role]:
            lines.append(f"{repo_id}@{revision}\t{file.path}\t{file.bytes}\t{file.sha256}")
            total_bytes += file.bytes
    digest = hashlib.sha256("".join(f"{line}\n" for line in lines).encode("utf-8")).hexdigest()
    if digest != APPROVED_AGGREGATE_SHA256:
        raise ValueError("internal MedCPT aggregate trust root is inconsistent")
    return {
        "algorithm": AGGREGATE_ALGORITHM,
        "ordered_lines": lines,
        "sha256": digest,
        "repository_count": 2,
        "file_count": len(lines),
        "total_bytes": total_bytes,
    }


def _validate_file_acquisition(
    record: dict[str, Any],
    pinned: PinnedFile,
    *,
    role: str,
    repo_id: str,
    revision: str,
) -> None:
    requested_url = f"https://huggingface.co/{repo_id}/resolve/{revision}/{pinned.path}"
    if pinned.path == "model.safetensors":
        final_host = "us.aws.cdn.hf.co"
        final_path = PINNED_MODEL_FINAL_PATH[role]
        expected_lfs: str | None = pinned.sha256
        expected_etag = final_path.rsplit("/", maxsplit=1)[-1]
    else:
        final_host = "huggingface.co"
        final_path = f"/api/resolve-cache/models/{repo_id}/{revision}/{pinned.path}"
        expected_lfs = None
        expected_etag = pinned.hf_blob_id
    final_url = record["final_url"]
    expected_final_url = {
        "exact_url": None,
        "redacted_url": f"https://{final_host}{final_path}?<redacted>",
        "exact_url_sha256": pinned.final_url_sha256,
        "host": final_host,
        "path": final_path,
        "signed_query_redacted": True,
    }
    if not isinstance(final_url, dict) or set(final_url) != FINAL_URL_FIELDS:
        raise ValueError("MedCPT final URL evidence has an unexpected schema")
    if (
        record["hf_blob_id"] != pinned.hf_blob_id
        or record["hf_lfs_sha256"] != expected_lfs
        or record["requested_url"] != requested_url
        or final_url != expected_final_url
        or record["redirect_count"] != 1
        or record["transport_attempts"] != 1
        or record["etag"] != expected_etag
    ):
        raise ValueError(f"MedCPT acquisition identity drifted: {pinned.path}")


def _validate_metadata_file(
    manifest_parent: Path,
    role: str,
    repository_metadata: Any,
) -> Path:
    name, size, sha256 = APPROVED_METADATA[role]
    raw_path = manifest_parent / name
    if raw_path.is_symlink() or not raw_path.is_file():
        raise ValueError("MedCPT preserved metadata must be a regular file")
    raw_resolved = raw_path.resolve(strict=True)
    expected = {
        "preserved_raw_path": str(raw_resolved),
        "bytes": size,
        "sha256": sha256,
        "private": False,
        "gated": False,
        "disabled": False,
        "library_name": "transformers",
        "license": "other",
        "license_name": "public-domain",
        "license_link": "LICENSE",
    }
    if (
        repository_metadata != expected
        or _file_size(raw_resolved) != size
        or _sha256_file(raw_resolved) != sha256
    ):
        raise ValueError(f"MedCPT {role} preserved metadata identity drifted")
    return raw_resolved


def _validate_metadata_lineage(
    payload: dict[str, Any],
    manifest_parent: Path,
    raw_metadata: Mapping[str, Path],
) -> None:
    lineage = payload["metadata_acquisition_lineage"]
    lineage_fields = {
        "schema_version",
        "acquisition_kind",
        "source_host",
        "files_metadata_parameter",
        "timeout_seconds",
        "automatic_redirects",
        "maximum_attempts_per_model",
        "retry_count",
        "authoritative_metadata_get_count",
        "all_authoritative_responses_exact_match_preserved_raw",
        "supersedes_manifest",
        "successor_ledger",
        "cache_rebind",
        "prior_non_authoritative_events",
        "entries",
    }
    if not isinstance(lineage, dict) or set(lineage) != lineage_fields:
        raise ValueError("MedCPT metadata lineage has an unexpected schema")
    exact_policy = {
        "schema_version": "medevidence.m2-002.medcpt-metadata-acquisition-lineage.v1",
        "acquisition_kind": "huggingface_model_revision_metadata",
        "source_host": "huggingface.co",
        "files_metadata_parameter": {
            "name": "blobs",
            "value": True,
            "request_query": "blobs=true",
            "official_client_semantics": "huggingface_hub HfApi files_metadata=True",
        },
        "timeout_seconds": 30,
        "automatic_redirects": False,
        "maximum_attempts_per_model": 1,
        "retry_count": 0,
        "authoritative_metadata_get_count": 2,
        "all_authoritative_responses_exact_match_preserved_raw": True,
    }
    if any(lineage[key] != value for key, value in exact_policy.items()):
        raise ValueError("MedCPT metadata acquisition policy drifted")

    superseded = manifest_parent / "medcpt-artifact-acquisition.json"
    expected_superseded = {
        "path": str(superseded.resolve(strict=True)),
        "bytes": 87_888,
        "sha256": "1f461bd28727cb4a7b1e52c962bf1d0bbb83ca96267e09c0fbf0f199d2b1f180",
        "schema_version": "medevidence.m2-002.medcpt-artifact-acquisition.v1",
    }
    if (
        lineage["supersedes_manifest"] != expected_superseded
        or superseded.is_symlink()
        or not superseded.is_file()
        or _file_size(superseded) != expected_superseded["bytes"]
        or _sha256_file(superseded) != expected_superseded["sha256"]
    ):
        raise ValueError("MedCPT superseded manifest identity drifted")

    ledger_path = manifest_parent / ARTIFACT_LEDGER_NAME
    expected_ledger = {
        "path": str(ledger_path.resolve(strict=True)),
        "bytes": ARTIFACT_LEDGER_BYTES,
        "sha256": ARTIFACT_LEDGER_SHA256,
        "schema_version": "medevidence.m2-002.raw-network-ledger.v1r1",
    }
    if (
        lineage["successor_ledger"] != expected_ledger
        or ledger_path.is_symlink()
        or not ledger_path.is_file()
        or _file_size(ledger_path) != ARTIFACT_LEDGER_BYTES
        or _sha256_file(ledger_path) != ARTIFACT_LEDGER_SHA256
    ):
        raise ValueError("MedCPT successor ledger identity drifted")
    ledger = _load_strict_json(ledger_path, "MedCPT successor ledger")
    if set(ledger) != {"schema_version", "updated_at_utc", "supersedes", "entries"}:
        raise ValueError("MedCPT successor ledger has an unexpected schema")
    ledger_entries = ledger["entries"]
    if (
        ledger["schema_version"] != expected_ledger["schema_version"]
        or not isinstance(ledger_entries, list)
        or len(ledger_entries) != 41
    ):
        raise ValueError("MedCPT successor ledger is incomplete")

    aggregate = _canonical_aggregate_identity()
    if lineage["cache_rebind"] != {
        "canonical_aggregate_sha256": aggregate["sha256"],
        "repository_count": 2,
        "file_count": 18,
        "total_bytes": 877_783_608,
        "cache_entries_reused_without_write": True,
    }:
        raise ValueError("MedCPT metadata lineage cache binding drifted")

    probes = lineage["prior_non_authoritative_events"]
    if not isinstance(probes, list) or len(probes) != 1:
        raise ValueError("MedCPT metadata lineage must retain the failed probe")
    probe = probes[0]
    if not isinstance(probe, dict) or probe.get("successor_ledger_entry_index") != 38:
        raise ValueError("MedCPT failed-probe lineage binding drifted")
    probe_without_index = dict(probe)
    probe_without_index.pop("successor_ledger_entry_index")
    if (
        probe_without_index != ledger_entries[38]
        or probe.get("authority") != "non_authoritative_failed_probe"
        or probe.get("response_bytes") != 1991
        or probe.get("response_sha256")
        != "3e7f355e4c3b7e1a524d343080ce934ebd53584b81e70efb717d99f8851b9e7c"
        or probe.get("response_bytes_equal_preserved_raw") is not False
        or probe.get("response_sha256_equal_preserved_raw") is not False
        or probe.get("outcome") != "parameterless_probe_metadata_mismatch"
    ):
        raise ValueError("MedCPT failed-probe evidence drifted")

    entries = lineage["entries"]
    if not isinstance(entries, list) or len(entries) != 2:
        raise ValueError("MedCPT metadata lineage must have two authoritative entries")
    expected_roles = {
        "query": (QUERY_REPO, QUERY_REVISION, 39),
        "article": (ARTICLE_REPO, ARTICLE_REVISION, 40),
    }
    seen: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("MedCPT metadata lineage entry must be an object")
        role = entry.get("role")
        if role not in expected_roles or role in seen:
            raise ValueError("MedCPT metadata lineage roles must be exact and unique")
        seen.add(role)
        repo_id, revision, ledger_index = expected_roles[role]
        _name, size, sha256 = APPROVED_METADATA[role]
        request_url = f"https://huggingface.co/api/models/{repo_id}/revision/{revision}?blobs=true"
        exact_entry = {
            "event_kind": "huggingface_model_revision_metadata_get",
            "authority": "authoritative",
            "role": role,
            "repo_id": repo_id,
            "requested_revision": revision,
            "lookup": request_url.removeprefix("https://huggingface.co/"),
            "method": "GET",
            "attempt": 1,
            "request_url": request_url,
            "status_code": 200,
            "response_bytes": size,
            "response_sha256": sha256,
            "response_content_type": "application/json; charset=utf-8",
            "final_url": request_url,
            "final_host": "huggingface.co",
            "redirect_count": 0,
            "preserved_raw_metadata_path": str(raw_metadata[role]),
            "preserved_raw_metadata_bytes": size,
            "preserved_raw_metadata_sha256": sha256,
            "response_bytes_equal_preserved_raw": True,
            "response_sha256_equal_preserved_raw": True,
            "outcome": "exact_match",
            "successor_ledger_entry_index": ledger_index,
        }
        if set(entry) != set(exact_entry) | {"started_at_utc", "completed_at_utc"}:
            raise ValueError("MedCPT authoritative metadata lineage schema drifted")
        if any(entry[key] != value for key, value in exact_entry.items()):
            raise ValueError(f"MedCPT {role} authoritative metadata lineage drifted")
        if not isinstance(entry["started_at_utc"], str) or not isinstance(
            entry["completed_at_utc"], str
        ):
            raise ValueError("MedCPT authoritative metadata timestamps are missing")
        ledger_entry = dict(entry)
        ledger_entry.pop("successor_ledger_entry_index")
        if ledger_entry != ledger_entries[ledger_index]:
            raise ValueError("MedCPT authoritative metadata ledger binding drifted")


@dataclass(frozen=True)
class ArtifactSnapshot:
    """One exact, verified external Hugging Face snapshot."""

    role: str
    repo_id: str
    revision: str
    path: Path
    files: tuple[dict[str, str | int], ...]


@dataclass(frozen=True)
class MedCPTArtifacts:
    """Verified query/article snapshots and their acquisition evidence."""

    manifest_path: Path
    manifest_sha256: str
    aggregate_identity: Any
    query: ArtifactSnapshot
    article: ArtifactSnapshot

    def provenance(self) -> dict[str, Any]:
        return {
            "schema_version": ARTIFACT_SCHEMA,
            "manifest": {
                "path": str(self.manifest_path),
                "bytes": self.manifest_path.stat().st_size,
                "sha256": self.manifest_sha256,
            },
            "canonical_aggregate_identity": self.aggregate_identity,
            "repositories": [
                {
                    "role": snapshot.role,
                    "repo_id": snapshot.repo_id,
                    "revision": snapshot.revision,
                    "snapshot_path": str(snapshot.path),
                    "files": list(snapshot.files),
                }
                for snapshot in (self.query, self.article)
            ],
        }


def load_medcpt_artifacts(
    manifest_path: str | Path,
    cache_root: str | Path,
) -> MedCPTArtifacts:
    """Validate exact external acquisition evidence and cache bytes."""

    repository_root = Path(__file__).resolve().parents[1]
    manifest = Path(manifest_path)
    root = Path(cache_root)
    if manifest.is_symlink() or not manifest.is_file():
        raise ValueError("MedCPT artifact manifest must be a regular file")
    if root.is_symlink() or not root.is_dir():
        raise ValueError("MedCPT cache root must be a regular directory")
    manifest_resolved = manifest.resolve(strict=True)
    root_resolved = root.resolve(strict=True)
    if _is_within(manifest_resolved, repository_root) or _is_within(root_resolved, repository_root):
        raise ValueError("MedCPT manifest and cache must remain outside the repository")
    if (
        manifest_resolved.name != ARTIFACT_MANIFEST_NAME
        or _file_size(manifest_resolved) != ARTIFACT_MANIFEST_BYTES
        or _sha256_file(manifest_resolved) != ARTIFACT_MANIFEST_SHA256
    ):
        raise ValueError("MedCPT artifact manifest identity drifted")
    payload = _load_strict_json(manifest_resolved, "MedCPT artifact manifest")
    if set(payload) != TOP_FIELDS:
        raise ValueError("MedCPT artifact manifest has an unexpected top-level schema")
    if payload["schema_version"] != ARTIFACT_SCHEMA or payload["status"] != "PASS":
        raise ValueError("MedCPT artifact acquisition did not pass the exact schema")
    aggregate_identity = _canonical_aggregate_identity()
    if payload["canonical_aggregate_identity"] != aggregate_identity:
        raise ValueError("MedCPT canonical aggregate identity drifted")
    preserved_before = [
        {"path": name, "bytes": size, "sha256": sha256}
        for name, size, sha256 in APPROVED_METADATA.values()
    ]
    preserved_after = [dict(record, unchanged=True) for record in preserved_before]
    if (
        payload["preserved_raw_metadata_before"] != preserved_before
        or payload["preserved_raw_metadata_after"] != preserved_after
    ):
        raise ValueError("MedCPT preserved metadata inventory drifted")
    repositories = payload["repositories"]
    if not isinstance(repositories, list) or len(repositories) != 2:
        raise ValueError("MedCPT manifest must contain exactly two repositories")
    if [record.get("role") for record in repositories if isinstance(record, dict)] != [
        "query",
        "article",
    ]:
        raise ValueError("MedCPT repository ordering must be query then article")
    expected = {
        "query": (QUERY_REPO, QUERY_REVISION),
        "article": (ARTICLE_REPO, ARTICLE_REVISION),
    }
    snapshots: dict[str, ArtifactSnapshot] = {}
    raw_metadata: dict[str, Path] = {}
    for record in repositories:
        if not isinstance(record, dict) or set(record) != REPOSITORY_FIELDS:
            raise ValueError("MedCPT repository record has an unexpected schema")
        role = record["role"]
        if role not in expected or role in snapshots:
            raise ValueError("MedCPT repository roles must be exact and unique")
        repo_id, revision = expected[role]
        if (
            record["repo_id"] != repo_id
            or record["requested_revision"] != revision
            or record["resolved_revision"] != revision
            or record["immutable_full_sha_match"] is not True
        ):
            raise ValueError(f"MedCPT {role} identity or revision drifted")
        raw_metadata[role] = _validate_metadata_file(
            manifest_resolved.parent,
            role,
            record["metadata"],
        )
        cache = record["cache"]
        if not isinstance(cache, dict) or set(cache) != CACHE_FIELDS:
            raise ValueError("MedCPT cache record has an unexpected schema")
        if (
            cache["layout"] != "models--owner--repo/snapshots/full_commit_sha/files"
            or cache["external_to_repository"] is not True
        ):
            raise ValueError("MedCPT cache policy is not exact")
        snapshot = Path(cache["snapshot_path"])
        if snapshot.is_symlink() or not snapshot.is_dir():
            raise ValueError("MedCPT snapshot must be a regular directory")
        snapshot_resolved = snapshot.resolve(strict=True)
        expected_snapshot = (
            root_resolved
            / f"models--ncbi--{repo_id.split('/', maxsplit=1)[1]}"
            / "snapshots"
            / revision
        )
        if snapshot_resolved != expected_snapshot or not _is_within(
            snapshot_resolved, root_resolved
        ):
            raise ValueError("MedCPT snapshot path does not match the approved cache root")
        files = record["files"]
        pinned_files = {file.path: file for file in APPROVED_FILES[role]}
        if not isinstance(files, list) or len(files) != len(pinned_files):
            raise ValueError("MedCPT snapshot file inventory is incomplete")
        file_evidence: list[dict[str, str | int]] = []
        seen: set[str] = set()
        prefix = snapshot_resolved.relative_to(root_resolved).as_posix()
        for file_record in files:
            if not isinstance(file_record, dict) or set(file_record) != FILE_FIELDS:
                raise ValueError("MedCPT file record has an unexpected schema")
            name = file_record["path"]
            if name not in pinned_files or name in seen or Path(name).name != name:
                raise ValueError("MedCPT manifest contains an unlisted or duplicate file")
            seen.add(name)
            if file_record["cache_relative_path"] != f"{prefix}/{name}":
                raise ValueError("MedCPT file cache path does not match its snapshot")
            path = snapshot_resolved / name
            if path.is_symlink() or not path.is_file():
                raise ValueError("MedCPT snapshot member must be a regular file")
            pinned = pinned_files[name]
            size = file_record["bytes"]
            sha256 = file_record["sha256"]
            if (
                size != pinned.bytes
                or sha256 != pinned.sha256
                or _file_size(path) != pinned.bytes
                or _sha256_file(path) != pinned.sha256
            ):
                raise ValueError(f"MedCPT cached file identity drifted: {name}")
            _validate_file_acquisition(
                file_record,
                pinned,
                role=role,
                repo_id=repo_id,
                revision=revision,
            )
            file_evidence.append({"path": name, "bytes": pinned.bytes, "sha256": pinned.sha256})
        actual_files = {
            path.relative_to(snapshot_resolved).as_posix()
            for path in snapshot_resolved.rglob("*")
            if path.is_file()
        }
        if actual_files != MODEL_FILES or any(name.endswith(".bin") for name in actual_files):
            raise ValueError("MedCPT snapshot contains unlisted or prohibited files")
        snapshots[role] = ArtifactSnapshot(
            role=role,
            repo_id=repo_id,
            revision=revision,
            path=snapshot_resolved,
            files=tuple(sorted(file_evidence, key=lambda item: str(item["path"]))),
        )
    _validate_metadata_lineage(payload, manifest_resolved.parent, raw_metadata)
    return MedCPTArtifacts(
        manifest_path=manifest_resolved,
        manifest_sha256=_sha256_file(manifest_resolved),
        aggregate_identity=aggregate_identity,
        query=snapshots["query"],
        article=snapshots["article"],
    )


class MedCPTIndex:
    """CPU-only MedCPT index using raw CLS embeddings and inner product."""

    dimensions = 768
    query_max_length = 64
    article_max_length = 512
    query_batch_size = 1
    document_batch_size = 8

    def __init__(
        self,
        doc_ids: Sequence[str],
        titles: Sequence[str],
        texts: Sequence[str],
        *,
        query_tokenizer: Any,
        query_model: Any,
        article_tokenizer: Any,
        article_model: Any,
        torch_module: Any,
        artifacts: MedCPTArtifacts | None = None,
    ) -> None:
        if not doc_ids or len(doc_ids) != len(titles) or len(doc_ids) != len(texts):
            raise ValueError("MedCPT documents, titles, and ids must be non-empty and aligned")
        if len(set(doc_ids)) != len(doc_ids):
            raise ValueError("MedCPT document ids must be unique")
        self.doc_ids = list(doc_ids)
        self._query_tokenizer = query_tokenizer
        self._query_model = query_model
        self._article_tokenizer = article_tokenizer
        self._article_model = article_model
        self._torch = torch_module
        self.artifacts = artifacts
        self._query_model.to("cpu")
        self._article_model.to("cpu")
        self._query_model.eval()
        self._article_model.eval()
        self._torch_intra_op_threads_observed = int(self._torch.get_num_threads())
        self._torch_inter_op_threads_observed = int(self._torch.get_num_interop_threads())
        self._query_model_parameter_dtype_observed = self._model_parameter_dtype(
            self._query_model,
            role="query",
        )
        self._article_model_parameter_dtype_observed = self._model_parameter_dtype(
            self._article_model,
            role="article",
        )
        self._query_embedding_dtype_observed: str | None = None
        with self._torch.inference_mode():
            batches = [
                self._encode_articles(
                    titles[start : start + self.document_batch_size],
                    texts[start : start + self.document_batch_size],
                )
                for start in range(0, len(self.doc_ids), self.document_batch_size)
            ]
        self._document_embeddings = np.concatenate(batches, axis=0)
        self._document_embedding_index_dtype_observed = str(self._document_embeddings.dtype)
        self._dense_index_memory_bytes = int(self._document_embeddings.nbytes)

    @staticmethod
    def _model_parameter_dtype(model: Any, *, role: str) -> str:
        parameters = getattr(model, "parameters", None)
        if not callable(parameters):
            raise ValueError(f"MedCPT {role} model does not expose parameter dtype evidence")
        dtypes = {str(parameter.dtype) for parameter in parameters()}
        if len(dtypes) != 1:
            raise ValueError(f"MedCPT {role} model parameter dtype must be singular")
        return dtypes.pop()

    @classmethod
    def from_local_artifacts(
        cls,
        doc_ids: Sequence[str],
        titles: Sequence[str],
        texts: Sequence[str],
        *,
        manifest_path: str | Path,
        cache_root: str | Path,
    ) -> MedCPTIndex:
        artifacts = load_medcpt_artifacts(manifest_path, cache_root)
        torch = importlib.import_module("torch")
        transformers = importlib.import_module("transformers")
        torch.set_num_threads(1)
        torch.set_num_interop_threads(1)
        query_tokenizer = transformers.AutoTokenizer.from_pretrained(
            artifacts.query.path,
            local_files_only=True,
            trust_remote_code=False,
        )
        article_tokenizer = transformers.AutoTokenizer.from_pretrained(
            artifacts.article.path,
            local_files_only=True,
            trust_remote_code=False,
        )
        query_model = transformers.AutoModel.from_pretrained(
            artifacts.query.path,
            local_files_only=True,
            trust_remote_code=False,
            use_safetensors=True,
        )
        article_model = transformers.AutoModel.from_pretrained(
            artifacts.article.path,
            local_files_only=True,
            trust_remote_code=False,
            use_safetensors=True,
        )
        return cls(
            doc_ids,
            titles,
            texts,
            query_tokenizer=query_tokenizer,
            query_model=query_model,
            article_tokenizer=article_tokenizer,
            article_model=article_model,
            torch_module=torch,
            artifacts=artifacts,
        )

    @staticmethod
    def _numpy(value: Any) -> np.ndarray[Any, np.dtype[np.float32]]:
        if hasattr(value, "detach"):
            value = value.detach().cpu().numpy()
        return cast(
            np.ndarray[Any, np.dtype[np.float32]],
            np.asarray(value, dtype=np.float32),
        )

    def _encode_articles(self, titles: Sequence[str], texts: Sequence[str]) -> np.ndarray[Any, Any]:
        tokens = self._article_tokenizer(
            list(titles),
            list(texts),
            truncation=True,
            max_length=self.article_max_length,
            padding=True,
            return_tensors="pt",
        )
        output = self._article_model(**dict(tokens))
        embeddings = self._numpy(output.last_hidden_state[:, 0, :])
        if embeddings.shape != (len(titles), self.dimensions):
            raise ValueError("MedCPT article CLS embeddings must be exactly 768-dimensional")
        return embeddings

    def _encode_query(self, query: str) -> np.ndarray[Any, Any]:
        tokens = self._query_tokenizer(
            [query],
            truncation=True,
            max_length=self.query_max_length,
            padding=True,
            return_tensors="pt",
        )
        output = self._query_model(**dict(tokens))
        embeddings = self._numpy(output.last_hidden_state[:, 0, :])
        if embeddings.shape != (self.query_batch_size, self.dimensions):
            raise ValueError("MedCPT query CLS embedding must be exactly 768-dimensional")
        self._query_embedding_dtype_observed = str(embeddings.dtype)
        return cast(np.ndarray[Any, Any], embeddings[0])

    def search(self, query: str, limit: int) -> list[tuple[str, float]]:
        """Rank by raw inner product, breaking equal scores by document id."""

        if limit < 1:
            raise ValueError("limit must be positive")
        with self._torch.inference_mode():
            query_embedding = self._encode_query(query)
        scores = self._document_embeddings @ query_embedding
        ranking = sorted(
            zip(self.doc_ids, scores, strict=True),
            key=lambda item: (-float(item[1]), item[0]),
        )
        selected = [(doc_id, float(score)) for doc_id, score in ranking[:limit]]
        if any(not math.isfinite(score) for _doc_id, score in selected):
            raise ValueError("MedCPT produced a non-finite score")
        return selected

    def provenance(self) -> Mapping[str, Any] | None:
        return self.artifacts.provenance() if self.artifacts is not None else None

    def runtime_provenance(self) -> Mapping[str, Any]:
        """Return observations from the loaded models and completed dense index."""

        if self._query_embedding_dtype_observed is None:
            raise ValueError("MedCPT query embedding dtype has not been observed")
        return {
            "pytorch_intra_op_threads_observed": self._torch_intra_op_threads_observed,
            "pytorch_inter_op_threads_observed": self._torch_inter_op_threads_observed,
            "model_parameter_dtype_observed": {
                "query_encoder": self._query_model_parameter_dtype_observed,
                "article_encoder": self._article_model_parameter_dtype_observed,
            },
            "query_embedding_dtype_observed": self._query_embedding_dtype_observed,
            "document_embedding_index_dtype_observed": (
                self._document_embedding_index_dtype_observed
            ),
            "dense_index_memory_bytes": self._dense_index_memory_bytes,
            "dense_index_memory_measurement": "numpy.ndarray.nbytes",
            "dense_index_memory_limitation": (
                "Document embedding matrix only; not Python process RSS, allocator overhead, "
                "model memory, or total application memory."
            ),
        }
