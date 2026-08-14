"""Offline tests for the exact MedCPT evaluation adapter."""

from __future__ import annotations

import json
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import evaluation.medcpt as medcpt
import numpy as np
import pytest
from evaluation.medcpt import (
    APPROVED_AGGREGATE_SHA256,
    APPROVED_FILES,
    APPROVED_METADATA,
    ARTICLE_REPO,
    ARTICLE_REVISION,
    ARTIFACT_LEDGER_BYTES,
    ARTIFACT_LEDGER_NAME,
    ARTIFACT_LEDGER_SHA256,
    ARTIFACT_MANIFEST_BYTES,
    ARTIFACT_MANIFEST_NAME,
    ARTIFACT_MANIFEST_SHA256,
    ARTIFACT_SCHEMA,
    MODEL_FILES,
    PINNED_MODEL_FINAL_PATH,
    QUERY_REPO,
    QUERY_REVISION,
    MedCPTIndex,
    load_medcpt_artifacts,
)


class FakeTorch:
    def __init__(self, *, intra_op_threads: int = 1, inter_op_threads: int = 1) -> None:
        self.intra_op_threads = intra_op_threads
        self.inter_op_threads = inter_op_threads

    def inference_mode(self) -> Any:
        return nullcontext()

    def get_num_threads(self) -> int:
        return self.intra_op_threads

    def get_num_interop_threads(self) -> int:
        return self.inter_op_threads


class FakeTokenizer:
    def __init__(self, values: dict[str, float]) -> None:
        self.values = values
        self.calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    def __call__(self, *args: Any, **kwargs: Any) -> dict[str, np.ndarray[Any, Any]]:
        self.calls.append((args, kwargs))
        first = args[0]
        return {"values": np.asarray([self.values[value] for value in first])}


class FakeModel:
    def __init__(self) -> None:
        self.device: str | None = None
        self.evaluating = False

    def to(self, device: str) -> FakeModel:
        self.device = device
        return self

    def eval(self) -> FakeModel:
        self.evaluating = True
        return self

    def __call__(self, *, values: np.ndarray[Any, Any]) -> SimpleNamespace:
        hidden = np.zeros((len(values), 2, 768), dtype=np.float64)
        hidden[:, 0, 0] = values
        hidden[:, 1, 0] = 10_000.0
        return SimpleNamespace(last_hidden_state=hidden)

    def parameters(self) -> list[SimpleNamespace]:
        return [SimpleNamespace(dtype="torch.float32")]


def _index(
    doc_ids: list[str],
    values: dict[str, float],
) -> tuple[MedCPTIndex, FakeTokenizer, FakeTokenizer, FakeModel, FakeModel]:
    query_tokenizer = FakeTokenizer(values)
    article_tokenizer = FakeTokenizer(values)
    query_model = FakeModel()
    article_model = FakeModel()
    index = MedCPTIndex(
        doc_ids,
        doc_ids,
        [f"body-{doc_id}" for doc_id in doc_ids],
        query_tokenizer=query_tokenizer,
        query_model=query_model,
        article_tokenizer=article_tokenizer,
        article_model=article_model,
        torch_module=FakeTorch(),
    )
    return index, query_tokenizer, article_tokenizer, query_model, article_model


def test_exact_lengths_batches_cpu_eval_cls_and_raw_inner_product() -> None:
    doc_ids = [f"d{index}" for index in range(9)]
    values = {doc_id: float(index + 1) for index, doc_id in enumerate(doc_ids)}
    values["query"] = 2.0
    index, query_tokenizer, article_tokenizer, query_model, article_model = _index(doc_ids, values)

    assert index.search("query", 2) == [("d8", 18.0), ("d7", 16.0)]
    assert [len(call[0][0]) for call in article_tokenizer.calls] == [8, 1]
    assert all(len(call[0]) == 2 for call in article_tokenizer.calls)
    assert all(call[1]["max_length"] == 512 for call in article_tokenizer.calls)
    assert len(query_tokenizer.calls) == 1
    assert query_tokenizer.calls[0][0] == (["query"],)
    assert query_tokenizer.calls[0][1]["max_length"] == 64
    assert query_model.device == article_model.device == "cpu"
    assert query_model.evaluating and article_model.evaluating


def test_equal_inner_products_use_document_id_tie_break() -> None:
    index, *_ = _index(
        ["z-document", "a-document"],
        {"z-document": 3.0, "a-document": 3.0, "q": 2.0},
    )

    assert index.search("q", 2) == [("a-document", 6.0), ("z-document", 6.0)]


def test_runtime_provenance_is_observed_from_models_embeddings_and_index() -> None:
    index, *_ = _index(["d1", "d2"], {"d1": 1.0, "d2": 2.0, "query": 3.0})

    with pytest.raises(ValueError, match="query embedding dtype has not been observed"):
        index.runtime_provenance()

    index.search("query", 1)

    assert index.runtime_provenance() == {
        "pytorch_intra_op_threads_observed": 1,
        "pytorch_inter_op_threads_observed": 1,
        "model_parameter_dtype_observed": {
            "query_encoder": "torch.float32",
            "article_encoder": "torch.float32",
        },
        "query_embedding_dtype_observed": "float32",
        "document_embedding_index_dtype_observed": "float32",
        "dense_index_memory_bytes": index._document_embeddings.nbytes,
        "dense_index_memory_measurement": "numpy.ndarray.nbytes",
        "dense_index_memory_limitation": (
            "Document embedding matrix only; not Python process RSS, allocator overhead, "
            "model memory, or total application memory."
        ),
    }


def test_model_parameter_dtype_evidence_fails_closed() -> None:
    class MixedDtypeModel(FakeModel):
        def parameters(self) -> list[SimpleNamespace]:
            return [
                SimpleNamespace(dtype="torch.float16"),
                SimpleNamespace(dtype="torch.float32"),
            ]

    with pytest.raises(ValueError, match="query model parameter dtype must be singular"):
        MedCPTIndex(
            ["d1"],
            ["d1"],
            ["body"],
            query_tokenizer=FakeTokenizer({"d1": 1.0}),
            query_model=MixedDtypeModel(),
            article_tokenizer=FakeTokenizer({"d1": 1.0}),
            article_model=FakeModel(),
            torch_module=FakeTorch(),
        )


def test_thread_counts_are_observed_from_loaded_torch_runtime() -> None:
    values = {"d1": 1.0, "query": 2.0}
    index = MedCPTIndex(
        ["d1"],
        ["d1"],
        ["body"],
        query_tokenizer=FakeTokenizer(values),
        query_model=FakeModel(),
        article_tokenizer=FakeTokenizer(values),
        article_model=FakeModel(),
        torch_module=FakeTorch(intra_op_threads=3, inter_op_threads=5),
    )

    index.search("query", 1)

    provenance = index.runtime_provenance()
    assert provenance["pytorch_intra_op_threads_observed"] == 3
    assert provenance["pytorch_inter_op_threads_observed"] == 5


def _write_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> SimpleNamespace:
    actual_sha256 = medcpt._sha256_file
    actual_size = medcpt._file_size
    synthetic_identities: dict[Path, tuple[int, str]] = {}

    def fake_sha256(path: Path) -> str:
        identity = synthetic_identities.get(path.resolve())
        return identity[1] if identity is not None else actual_sha256(path)

    def fake_size(path: Path) -> int:
        identity = synthetic_identities.get(path.resolve())
        return identity[0] if identity is not None else actual_size(path)

    monkeypatch.setattr(medcpt, "_sha256_file", fake_sha256)
    monkeypatch.setattr(medcpt, "_file_size", fake_size)

    cache_root = tmp_path / "cache"
    old_manifest = tmp_path / "medcpt-artifact-acquisition.json"
    old_manifest.write_text("{}", encoding="utf-8")
    synthetic_identities[old_manifest.resolve()] = (
        87_888,
        "1f461bd28727cb4a7b1e52c962bf1d0bbb83ca96267e09c0fbf0f199d2b1f180",
    )
    preserved_before = [
        {"path": name, "bytes": size, "sha256": sha256}
        for name, size, sha256 in APPROVED_METADATA.values()
    ]
    raw_metadata: dict[str, Path] = {}
    for role, (name, size, sha256) in APPROVED_METADATA.items():
        raw_path = tmp_path / name
        raw_path.write_bytes(f"synthetic-{role}-metadata".encode())
        synthetic_identities[raw_path.resolve()] = (size, sha256)
        raw_metadata[role] = raw_path.resolve()

    repositories: list[dict[str, Any]] = []
    for role, repo_id, revision in (
        ("query", QUERY_REPO, QUERY_REVISION),
        ("article", ARTICLE_REPO, ARTICLE_REVISION),
    ):
        snapshot = (
            cache_root
            / f"models--ncbi--{repo_id.split('/', maxsplit=1)[1]}"
            / "snapshots"
            / revision
        )
        snapshot.mkdir(parents=True)
        files: list[dict[str, Any]] = []
        for pinned in APPROVED_FILES[role]:
            path = snapshot / pinned.path
            path.write_bytes(f"synthetic-{role}-{pinned.path}".encode())
            synthetic_identities[path.resolve()] = (pinned.bytes, pinned.sha256)
            requested_url = f"https://huggingface.co/{repo_id}/resolve/{revision}/{pinned.path}"
            if pinned.path == "model.safetensors":
                final_host = "us.aws.cdn.hf.co"
                final_path = PINNED_MODEL_FINAL_PATH[role]
                lfs_sha256: str | None = pinned.sha256
                etag = final_path.rsplit("/", maxsplit=1)[-1]
            else:
                final_host = "huggingface.co"
                final_path = f"/api/resolve-cache/models/{repo_id}/{revision}/{pinned.path}"
                lfs_sha256 = None
                etag = pinned.hf_blob_id
            files.append(
                {
                    "path": pinned.path,
                    "cache_relative_path": path.relative_to(cache_root).as_posix(),
                    "bytes": pinned.bytes,
                    "sha256": pinned.sha256,
                    "hf_blob_id": pinned.hf_blob_id,
                    "hf_lfs_sha256": lfs_sha256,
                    "requested_url": requested_url,
                    "final_url": {
                        "exact_url": None,
                        "redacted_url": f"https://{final_host}{final_path}?<redacted>",
                        "exact_url_sha256": pinned.final_url_sha256,
                        "host": final_host,
                        "path": final_path,
                        "signed_query_redacted": True,
                    },
                    "redirect_count": 1,
                    "transport_attempts": 1,
                    "etag": etag,
                }
            )
        _metadata_name, metadata_bytes, metadata_sha256 = APPROVED_METADATA[role]
        repositories.append(
            {
                "role": role,
                "repo_id": repo_id,
                "requested_revision": revision,
                "resolved_revision": revision,
                "immutable_full_sha_match": True,
                "metadata": {
                    "preserved_raw_path": str(raw_metadata[role]),
                    "bytes": metadata_bytes,
                    "sha256": metadata_sha256,
                    "private": False,
                    "gated": False,
                    "disabled": False,
                    "library_name": "transformers",
                    "license": "other",
                    "license_name": "public-domain",
                    "license_link": "LICENSE",
                },
                "cache": {
                    "layout": "models--owner--repo/snapshots/full_commit_sha/files",
                    "snapshot_path": str(snapshot),
                    "external_to_repository": True,
                },
                "files": files,
                "config_validation": {},
                "tokenizer_validation": {},
                "documentation_validation": {},
                "safetensors_validation": {},
                "upstream_forbidden_files_visible_but_not_selected": [],
            }
        )
    probe = {
        "event_kind": "huggingface_model_revision_metadata_get",
        "authority": "non_authoritative_failed_probe",
        "role": "query",
        "repo_id": QUERY_REPO,
        "requested_revision": QUERY_REVISION,
        "lookup": f"api/models/{QUERY_REPO}/revision/{QUERY_REVISION}",
        "method": "GET",
        "attempt": 1,
        "request_url": f"https://huggingface.co/api/models/{QUERY_REPO}/revision/{QUERY_REVISION}",
        "started_at_utc": None,
        "completed_at_utc": None,
        "timestamps_not_durably_recorded": True,
        "status_code": 200,
        "response_bytes": 1991,
        "response_sha256": "3e7f355e4c3b7e1a524d343080ce934ebd53584b81e70efb717d99f8851b9e7c",
        "final_url": f"https://huggingface.co/api/models/{QUERY_REPO}/revision/{QUERY_REVISION}",
        "final_host": "huggingface.co",
        "redirect_count": 0,
        "preserved_raw_metadata_bytes": APPROVED_METADATA["query"][1],
        "preserved_raw_metadata_sha256": APPROVED_METADATA["query"][2],
        "response_bytes_equal_preserved_raw": False,
        "response_sha256_equal_preserved_raw": False,
        "outcome": "parameterless_probe_metadata_mismatch",
        "successor_ledger_entry_index": 38,
    }
    authoritative_entries: list[dict[str, Any]] = []
    for role, repo_id, revision, ledger_index in (
        ("query", QUERY_REPO, QUERY_REVISION, 39),
        ("article", ARTICLE_REPO, ARTICLE_REVISION, 40),
    ):
        _name, size, sha256 = APPROVED_METADATA[role]
        request_url = f"https://huggingface.co/api/models/{repo_id}/revision/{revision}?blobs=true"
        authoritative_entries.append(
            {
                "event_kind": "huggingface_model_revision_metadata_get",
                "authority": "authoritative",
                "role": role,
                "repo_id": repo_id,
                "requested_revision": revision,
                "lookup": request_url.removeprefix("https://huggingface.co/"),
                "method": "GET",
                "attempt": 1,
                "request_url": request_url,
                "started_at_utc": f"2026-08-14T01:42:5{ledger_index - 39}.0000000-05:00",
                "completed_at_utc": f"2026-08-14T01:42:5{ledger_index - 39}.1000000-05:00",
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
        )
    ledger_entries: list[dict[str, Any]] = [{} for _ in range(41)]
    for entry in [probe, *authoritative_entries]:
        ledger_entry = dict(entry)
        ledger_index = ledger_entry.pop("successor_ledger_entry_index")
        ledger_entries[ledger_index] = ledger_entry
    ledger = tmp_path / ARTIFACT_LEDGER_NAME
    ledger.write_text(
        json.dumps(
            {
                "schema_version": "medevidence.m2-002.raw-network-ledger.v1r1",
                "updated_at_utc": "2026-08-14T06:43:00Z",
                "supersedes": {},
                "entries": ledger_entries,
            }
        ),
        encoding="utf-8",
    )
    synthetic_identities[ledger.resolve()] = (
        ARTIFACT_LEDGER_BYTES,
        ARTIFACT_LEDGER_SHA256,
    )
    aggregate = medcpt._canonical_aggregate_identity()
    manifest = {
        "schema_version": ARTIFACT_SCHEMA,
        "status": "PASS",
        "started_at_utc": "2026-08-14T00:00:00Z",
        "completed_at_utc": "2026-08-14T00:00:01Z",
        "scope": {},
        "network_policy": {},
        "environment": {},
        "allowlist": {},
        "preserved_raw_metadata_before": preserved_before,
        "preserved_raw_metadata_after": [
            dict(record, unchanged=True) for record in preserved_before
        ],
        "repositories": repositories,
        "canonical_aggregate_identity": aggregate,
        "network_ledger": [],
        "metadata_acquisition_lineage": {
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
            "supersedes_manifest": {
                "path": str(old_manifest.resolve()),
                "bytes": 87_888,
                "sha256": "1f461bd28727cb4a7b1e52c962bf1d0bbb83ca96267e09c0fbf0f199d2b1f180",
                "schema_version": "medevidence.m2-002.medcpt-artifact-acquisition.v1",
            },
            "successor_ledger": {
                "path": str(ledger.resolve()),
                "bytes": ARTIFACT_LEDGER_BYTES,
                "sha256": ARTIFACT_LEDGER_SHA256,
                "schema_version": "medevidence.m2-002.raw-network-ledger.v1r1",
            },
            "cache_rebind": {
                "canonical_aggregate_sha256": APPROVED_AGGREGATE_SHA256,
                "repository_count": 2,
                "file_count": 18,
                "total_bytes": 877_783_608,
                "cache_entries_reused_without_write": True,
            },
            "prior_non_authoritative_events": [probe],
            "entries": authoritative_entries,
        },
    }
    manifest_path = tmp_path / ARTIFACT_MANIFEST_NAME
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    synthetic_identities[manifest_path.resolve()] = (
        ARTIFACT_MANIFEST_BYTES,
        ARTIFACT_MANIFEST_SHA256,
    )
    return SimpleNamespace(
        manifest=manifest_path,
        cache=cache_root,
        old_manifest=old_manifest,
        ledger=ledger,
        identities=synthetic_identities,
    )


def test_exact_external_artifact_manifest_and_cache_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _write_manifest(tmp_path, monkeypatch)

    artifacts = load_medcpt_artifacts(fixture.manifest, fixture.cache)

    assert artifacts.query.repo_id == QUERY_REPO
    assert artifacts.article.repo_id == ARTICLE_REPO
    assert len(artifacts.query.files) == len(MODEL_FILES)
    assert artifacts.aggregate_identity["sha256"] == APPROVED_AGGREGATE_SHA256
    assert artifacts.manifest_sha256 == ARTIFACT_MANIFEST_SHA256


@pytest.mark.parametrize("name", ["config.json", "tokenizer.json", "README.md"])
def test_pinned_non_weight_cache_drift_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    name: str,
) -> None:
    fixture = _write_manifest(tmp_path, monkeypatch)
    payload = json.loads(fixture.manifest.read_text(encoding="utf-8"))
    path = Path(payload["repositories"][0]["cache"]["snapshot_path"]) / name
    fixture.identities.pop(path.resolve())
    path.write_bytes(b"drift")

    with pytest.raises(ValueError, match="cached file identity drifted"):
        load_medcpt_artifacts(fixture.manifest, fixture.cache)


@pytest.mark.parametrize("defect", ["bin_file", "unlisted_file"])
def test_artifact_cache_drift_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    defect: str,
) -> None:
    fixture = _write_manifest(tmp_path, monkeypatch)
    payload = json.loads(fixture.manifest.read_text(encoding="utf-8"))
    snapshot = Path(payload["repositories"][0]["cache"]["snapshot_path"])
    if defect == "bin_file":
        (snapshot / "pytorch_model.bin").write_bytes(b"prohibited")
    else:
        (snapshot / "extra.json").write_bytes(b"unlisted")

    with pytest.raises(ValueError):
        load_medcpt_artifacts(fixture.manifest, fixture.cache)


@pytest.mark.parametrize(
    "defect",
    ["aggregate", "blob", "requested_url", "final_url", "repository_metadata", "lineage"],
)
def test_self_declared_manifest_drift_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    defect: str,
) -> None:
    fixture = _write_manifest(tmp_path, monkeypatch)
    payload = json.loads(fixture.manifest.read_text(encoding="utf-8"))
    file_record = payload["repositories"][0]["files"][3]
    if defect == "aggregate":
        payload["canonical_aggregate_identity"]["sha256"] = "0" * 64
    elif defect == "blob":
        file_record["hf_blob_id"] = "0" * 40
    elif defect == "requested_url":
        file_record["requested_url"] += "?drift=true"
    elif defect == "final_url":
        file_record["final_url"]["exact_url_sha256"] = "0" * 64
    elif defect == "repository_metadata":
        payload["repositories"][0]["metadata"]["sha256"] = "0" * 64
    else:
        payload["metadata_acquisition_lineage"]["entries"][0]["response_sha256"] = "0" * 64
    fixture.manifest.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError):
        load_medcpt_artifacts(fixture.manifest, fixture.cache)


def test_successor_ledger_drift_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _write_manifest(tmp_path, monkeypatch)
    ledger = json.loads(fixture.ledger.read_text(encoding="utf-8"))
    ledger["entries"][39]["response_sha256"] = "0" * 64
    fixture.ledger.write_text(json.dumps(ledger), encoding="utf-8")

    with pytest.raises(ValueError, match="ledger binding drifted"):
        load_medcpt_artifacts(fixture.manifest, fixture.cache)


def test_superseded_v1_manifest_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _write_manifest(tmp_path, monkeypatch)

    with pytest.raises(ValueError, match="manifest identity drifted"):
        load_medcpt_artifacts(fixture.old_manifest, fixture.cache)


def test_repository_contained_cache_is_rejected(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text("{}", encoding="utf-8")

    with pytest.raises(ValueError, match="outside the repository"):
        load_medcpt_artifacts(manifest, Path("evaluation"))
