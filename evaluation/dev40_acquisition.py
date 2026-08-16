"""Exact request freeze and one-shot M2-006 Dev-40 source acquisition.

Preparation performs filesystem verification only and never constructs a
network-capable client. Live execution is separately acknowledged, requires a
hash-bound independent PASS review, and writes provider bytes outside Git.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from contextlib import suppress
from dataclasses import asdict, dataclass, is_dataclass, replace
from datetime import UTC, date, datetime
from enum import Enum
from pathlib import Path
from typing import Any, Final

import httpx
from pydantic import BaseModel

import medevidence as medevidence_package
import medevidence.connectors as connectors_package
import medevidence.connectors.faers as faers_package
import medevidence.connectors.faers.client as faers_client_module
import medevidence.connectors.faers.parsing as faers_parsing_module
import medevidence.connectors.faers.policy as faers_policy_module
import medevidence.connectors.pubmed as pubmed_package
import medevidence.connectors.pubmed.client as pubmed_client_module
import medevidence.connectors.pubmed.parsing as pubmed_parsing_module
import medevidence.connectors.pubmed.policy as pubmed_policy_module
import medevidence.domain as domain_package
import medevidence.domain.claims as domain_claims_module
import medevidence.domain.identifiers as domain_identifiers_module
import medevidence.domain.publications as domain_publications_module
import medevidence.domain.reports as domain_reports_module
import medevidence.domain.scope as domain_scope_module
import medevidence.domain.sources as domain_sources_module
from medevidence.connectors.faers import FaersConnector, FaersConnectorConfig
from medevidence.connectors.pubmed import (
    PUBMED_EFETCH_PATH,
    PUBMED_ESEARCH_PATH,
    PUBMED_ORIGIN,
    PubMedConnector,
    PubMedConnectorConfig,
    PubMedFetchResult,
    PubMedResultState,
    PubMedSearchResult,
)
from medevidence.domain import (
    GI_PT_SET_M1B_V1,
    FaersAggregateQueryV1,
    FaersAggregateRequestV1,
    FaersExecutionBoundsV1,
    FaersIdentityStrategy,
    FaersInclusiveDateRangeV1,
    derive_identity,
)

WORK_ITEM: Final = "M2-006-MEDEVIDENCE-DEV40"
SCHEMA_VERSION: Final = "medevidence.dev40.acquisition.v1"
BASELINE_COMMIT: Final = "7db1e1c497c190cd1972a05e3896ad189e658987"
EXPECTED_BRANCH: Final = "codex/m2-006-dev40-acquisition"
EVIDENCE_ROOT: Final = Path(r"D:\Projects\medevidence-external-evidence\M2-006-MEDEVIDENCE-DEV40")
FREEZE_ROOT: Final = EVIDENCE_ROOT / "acquisition-freeze"
FREEZE_V1_PATH: Final = FREEZE_ROOT / "request-freeze-001.json"
FREEZE_V1_BYTES: Final = 10_998
FREEZE_V1_SHA256: Final = "da8bfdd0071aa378b3a89551b15715095744e9942ad9397acebc369b8e4b2f25"
FREEZE_V1_SIDECAR_BYTES: Final = 90
FREEZE_V1_SIDECAR_SHA256: Final = "dadb21b4a87c64b403ffe36a9fa1df14b7b58b7e2efd1d0daab6797a1ab59297"
FREEZE_V2_PATH: Final = FREEZE_ROOT / "request-freeze-002.json"
FREEZE_V2_BYTES: Final = 15_196
FREEZE_V2_SHA256: Final = "1435e0aa48e930129b978333f1e23ead28cd1d7ae54d09f872d542a44ec5dddd"
FREEZE_V2_SIDECAR_BYTES: Final = 90
FREEZE_V2_SIDECAR_SHA256: Final = "bbe5983d9ed59d7809ca1e750150b6fd5cc763d1e567d6813f67517b1356149f"
FREEZE_V3_PATH: Final = FREEZE_ROOT / "request-freeze-003.json"
FREEZE_V3_BYTES: Final = 16_225
FREEZE_V3_SHA256: Final = "ffde50c26d0659efa2a47954b03ab94d452990ff38e50fde7dd2c9d71a5be3fb"
FREEZE_V3_SIDECAR_BYTES: Final = 90
FREEZE_V3_SIDECAR_SHA256: Final = "604272c360779248fbdb1ec603d0096a2e03bff6bc7c45d34d9c17012186564d"
FREEZE_PATH: Final = FREEZE_ROOT / "request-freeze-004.json"
LIVE_ROOT: Final = EVIDENCE_ROOT / "acquisition-001"
PUBMED_C_SUCCESSOR_ROOT: Final = EVIDENCE_ROOT / "acquisition-001-successor-001"
PUBMED_C_RAW_RELATIVE_PATH: Final = Path(
    "raw/pubmed-C-tirzepatide-gi-2020-2025-efetch-01-"
    "sha256-b02aec0b657566f31f5bc86f481e74847b8f7615a4192a12946124f49024b0f8.raw"
)
PUBMED_C_RAW_BYTES: Final = 2_892_306
PUBMED_C_RAW_SHA256: Final = "b02aec0b657566f31f5bc86f481e74847b8f7615a4192a12946124f49024b0f8"
PUBMED_C_BINDING_RELATIVE_PATH: Final = Path(
    "bindings/pubmed-C-tirzepatide-gi-2020-2025-efetch-binding.json"
)
PUBMED_C_BINDING_SHA256: Final = "4d5f926bfbc46481ad0ae09938e5f40ab8fb66edafa053b65ff01bff2bd39d48"
PUBMED_C_OPERATION_RELATIVE_PATH: Final = Path(
    "operations/pubmed-C-tirzepatide-gi-2020-2025-efetch.json"
)
PUBMED_C_OPERATION_SHA256: Final = (
    "03dc8f4a3ab40b75448afe5add68b814dab0469cf40ee8c11e3f53783579a4d8"
)
ORIGINAL_STOP_SHA256: Final = "1b49208f1daa90fea33f6a95c24f01125b4b55040d4b7805204e703d456cc8dc"
INVENTORY_PATH: Final = EVIDENCE_ROOT / "evidence-gap-inventory" / "evidence-gap-inventory-001.json"
INVENTORY_BYTES: Final = 64_448
INVENTORY_SHA256: Final = "850c4e3b7c55b2427df24dfabf33d5b4e50fd1624431cdecbb2281de2aea9389"
ACCEPTED_REVIEW_PATH: Final = (
    EVIDENCE_ROOT / "evidence-gap-inventory" / "independent-evidence-gap-review-004.json"
)
ACCEPTED_REVIEW_BYTES: Final = 10_704
ACCEPTED_REVIEW_SHA256: Final = "07f933200f079587c29ef1dafb5d5dbb9dbbdf17329df676854e72bd65f3c56d"
REVIEW_V3_PATH: Final = FREEZE_ROOT / "independent-pre-network-review-003.json"
REVIEW_V3_BYTES: Final = 2_660
REVIEW_V3_SHA256: Final = "9bf2dcb950a43156a7e576cb754c65e129800323d18888f1735a0e9a3fdb7db1"
REVIEW_V3_SIDECAR_BYTES: Final = 106
REVIEW_V3_SIDECAR_SHA256: Final = "55ead8bfd762bf0f59726e9ec87c0db74612f88fe65bf55716482e0d1defe5f2"
PRE_NETWORK_REVIEW_NAME: Final = "independent-pre-network-review-004.json"
LIVE_ACKNOWLEDGEMENT: Final = "M2-006-EXACT-SEVEN-LOGICAL-OPERATION-ACQUISITION"

PUBMED_SEARCH_CAP: Final = 262_144
PUBMED_FETCH_CAP: Final = 5_242_880
FAERS_CAP: Final = 5_242_880
PUBMED_COMBINED_CAP: Final = 16_515_072
COMBINED_RAW_CAP: Final = 21_757_952
AUTHORIZED_LOGICAL_OPERATIONS: Final = 7
MAX_HTTP_REQUESTS: Final = 26
MAX_PUBMED_HTTP_REQUESTS: Final = 24
MAX_FAERS_HTTP_REQUESTS: Final = 2
RUN_DEADLINE_SECONDS: Final = 240.0

SOURCE_STATE_PATHS: Final = (
    "src/medevidence/connectors/pubmed/client.py",
    "src/medevidence/connectors/pubmed/parsing.py",
    "tests/contract/connectors/test_pubmed_connector.py",
    "tests/unit/connectors/test_pubmed_parsing.py",
    "evaluation/dev40_acquisition.py",
    "evaluation/run_dev40_acquisition.py",
    "tests/unit/evaluation/test_dev40_acquisition.py",
    "evaluation/dev40_corpus.py",
    "evaluation/run_dev40_corpus.py",
    "tests/unit/evaluation/test_dev40_corpus.py",
)
BOOK_REMEDIATION_PATHS: Final = (
    "src/medevidence/connectors/pubmed/parsing.py",
    "src/medevidence/connectors/pubmed/client.py",
    "tests/unit/connectors/test_pubmed_parsing.py",
    "tests/contract/connectors/test_pubmed_connector.py",
    "evaluation/dev40_acquisition.py",
    "tests/unit/evaluation/test_dev40_acquisition.py",
)
RUNTIME_CLOSURE_PATHS: Final = (
    "pyproject.toml",
    "uv.lock",
    "evaluation/__init__.py",
    "src/medevidence/__init__.py",
    "src/medevidence/connectors/__init__.py",
    "src/medevidence/connectors/pubmed/__init__.py",
    "src/medevidence/connectors/pubmed/client.py",
    "src/medevidence/connectors/pubmed/parsing.py",
    "src/medevidence/connectors/pubmed/policy.py",
    "src/medevidence/connectors/faers/__init__.py",
    "src/medevidence/connectors/faers/client.py",
    "src/medevidence/connectors/faers/parsing.py",
    "src/medevidence/connectors/faers/policy.py",
    "src/medevidence/domain/__init__.py",
    "src/medevidence/domain/claims.py",
    "src/medevidence/domain/identifiers.py",
    "src/medevidence/domain/publications.py",
    "src/medevidence/domain/reports.py",
    "src/medevidence/domain/scope.py",
    "src/medevidence/domain/sources.py",
)
RUNTIME_MODULE_ORIGINS: Final = {
    "evaluation": "evaluation/__init__.py",
    "medevidence": "src/medevidence/__init__.py",
    "medevidence.connectors": "src/medevidence/connectors/__init__.py",
    "medevidence.connectors.pubmed": "src/medevidence/connectors/pubmed/__init__.py",
    "medevidence.connectors.pubmed.client": "src/medevidence/connectors/pubmed/client.py",
    "medevidence.connectors.pubmed.parsing": "src/medevidence/connectors/pubmed/parsing.py",
    "medevidence.connectors.pubmed.policy": "src/medevidence/connectors/pubmed/policy.py",
    "medevidence.connectors.faers": "src/medevidence/connectors/faers/__init__.py",
    "medevidence.connectors.faers.client": "src/medevidence/connectors/faers/client.py",
    "medevidence.connectors.faers.parsing": "src/medevidence/connectors/faers/parsing.py",
    "medevidence.connectors.faers.policy": "src/medevidence/connectors/faers/policy.py",
    "medevidence.domain": "src/medevidence/domain/__init__.py",
    "medevidence.domain.claims": "src/medevidence/domain/claims.py",
    "medevidence.domain.identifiers": "src/medevidence/domain/identifiers.py",
    "medevidence.domain.publications": "src/medevidence/domain/publications.py",
    "medevidence.domain.reports": "src/medevidence/domain/reports.py",
    "medevidence.domain.scope": "src/medevidence/domain/scope.py",
    "medevidence.domain.sources": "src/medevidence/domain/sources.py",
}

TERM_A: Final = (
    "semaglutide[Title/Abstract] AND vomiting[Title/Abstract] AND "
    '(discontinu*[Title/Abstract] OR withdrawal[Title/Abstract] OR "treatment-limiting"'
    "[Title/Abstract]) AND english[Language]"
)
TERM_B: Final = (
    "semaglutide[Title/Abstract] AND (gastrointestinal[Title/Abstract] OR "
    "nausea[Title/Abstract] OR vomiting[Title/Abstract] OR diarrhoea[Title/Abstract] OR "
    'diarrhea[Title/Abstract]) AND english[Language] AND ("2020/01/01"'
    '[Date - Publication] : "2025/12/31"[Date - Publication])'
)
TERM_C: Final = (
    "tirzepatide[Title/Abstract] AND (gastrointestinal[Title/Abstract] OR "
    "nausea[Title/Abstract] OR vomiting[Title/Abstract] OR diarrhoea[Title/Abstract] OR "
    'diarrhea[Title/Abstract]) AND english[Language] AND ("2020/01/01"'
    '[Date - Publication] : "2025/12/31"[Date - Publication])'
)


@dataclass(frozen=True, slots=True)
class PubMedPair:
    operation_id: str
    term: str
    expected_request_preimage_sha256: str
    serves_question_ids: tuple[str, ...]


PUBMED_PAIRS: Final = (
    PubMedPair(
        "pubmed-A-semaglutide-vomiting-treatment-limiting",
        TERM_A,
        "c1241b30b49af706a0ad0db29f9a4a278848fe203a7176336fb99fb03dac058a",
        ("Q13",),
    ),
    PubMedPair(
        "pubmed-B-semaglutide-gi-2020-2025",
        TERM_B,
        "35b19c4f94bf4504c05c3564778bf75fb92e6f2b8a3ea9540dd41e41d364f3ee",
        ("Q14",),
    ),
    PubMedPair(
        "pubmed-C-tirzepatide-gi-2020-2025",
        TERM_C,
        "a2d22dccea155c956c3e7840e70dfb9436217ed0e2acce5c12391690ad0506b4",
        ("Q24", "Q38"),
    ),
)

FAERS_QUERY_ID: Final = (
    "faers-query:sha256:a8a4e1086e2f9003b33edda1eb9dd4c70d0ebe54b5d1df78b031778b3e191f4c"
)


class Dev40AcquisitionError(RuntimeError):
    """Fail-closed request-freeze or acquisition error."""


@dataclass(frozen=True, slots=True)
class FreezeResult:
    path: Path
    sha256: str
    source_state_aggregate_sha256: str
    runtime_closure_aggregate_sha256: str


@dataclass(frozen=True, slots=True)
class AcquisitionResult:
    root: Path
    manifest_sha256: str
    authorized_logical_operations: int
    executed_logical_operations: int
    skipped_empty_fetches: int
    http_requests: int
    raw_bytes: int


@dataclass(frozen=True, slots=True)
class PubMedCSuccessorResult:
    """Exact identity of the append-only offline PubMed C successor evidence."""

    root: Path
    evidence_sha256: str
    publication_count: int
    book_document_count: int
    provider_record_count: int


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _jsonable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return _jsonable(value.model_dump(mode="json"))
    if is_dataclass(value) and not isinstance(value, type):
        return _jsonable(asdict(value))
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat(timespec="microseconds").replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Path):
        return value.as_posix()
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_jsonable(item) for item in value]
    return value


def _canonical_json_bytes(value: Any, *, terminal_lf: bool = True) -> bytes:
    suffix = "\n" if terminal_lf else ""
    return (
        json.dumps(
            _jsonable(value),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + suffix
    ).encode("utf-8")


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = path.with_name(f".{path.name}.pending")
    if pending.exists() or path.exists():
        raise Dev40AcquisitionError(f"evidence path is not fresh: {path.name}")
    try:
        with pending.open("xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        if pending.read_bytes() != data:
            raise Dev40AcquisitionError(f"pending evidence verification failed: {path.name}")
        pending.replace(path)
    except Exception:
        with suppress(OSError):
            pending.unlink()
        raise


def _write_with_sidecar(path: Path, data: bytes) -> str:
    digest = _sha256(data)
    _atomic_write(path, data)
    try:
        _atomic_write(
            path.with_suffix(path.suffix + ".sha256"),
            f"{digest}  {path.name}\n".encode("ascii"),
        )
    except Exception as error:
        raise Dev40AcquisitionError(
            f"evidence sidecar persistence failed after writing {path.name}"
        ) from error
    if path.read_bytes() != data or _sha256(path.read_bytes()) != digest:
        raise Dev40AcquisitionError(f"evidence rehash failed: {path.name}")
    return digest


def _write_json(path: Path, value: Any) -> str:
    return _write_with_sidecar(path, _canonical_json_bytes(value))


def _verify_exact_file(path: Path, *, expected_bytes: int, expected_sha256: str) -> None:
    try:
        data = path.read_bytes()
    except OSError as error:
        raise Dev40AcquisitionError(f"required evidence is unreadable: {path.name}") from error
    if len(data) != expected_bytes or _sha256(data) != expected_sha256:
        raise Dev40AcquisitionError(f"required evidence identity drifted: {path.name}")


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _verify_loaded_runtime_origins() -> dict[str, str]:
    evaluation_package = sys.modules.get("evaluation")
    modules: dict[str, Any] = {
        "evaluation": evaluation_package,
        "medevidence": medevidence_package,
        "medevidence.connectors": connectors_package,
        "medevidence.connectors.pubmed": pubmed_package,
        "medevidence.connectors.pubmed.client": pubmed_client_module,
        "medevidence.connectors.pubmed.parsing": pubmed_parsing_module,
        "medevidence.connectors.pubmed.policy": pubmed_policy_module,
        "medevidence.connectors.faers": faers_package,
        "medevidence.connectors.faers.client": faers_client_module,
        "medevidence.connectors.faers.parsing": faers_parsing_module,
        "medevidence.connectors.faers.policy": faers_policy_module,
        "medevidence.domain": domain_package,
        "medevidence.domain.claims": domain_claims_module,
        "medevidence.domain.identifiers": domain_identifiers_module,
        "medevidence.domain.publications": domain_publications_module,
        "medevidence.domain.reports": domain_reports_module,
        "medevidence.domain.scope": domain_scope_module,
        "medevidence.domain.sources": domain_sources_module,
    }
    if set(modules) != set(RUNTIME_MODULE_ORIGINS):
        raise Dev40AcquisitionError("loaded runtime module allowlist is internally inconsistent")
    root = _repo_root().resolve()
    origins: dict[str, str] = {}
    for module_name, relative in RUNTIME_MODULE_ORIGINS.items():
        module = modules[module_name]
        if module is None or sys.modules.get(module_name) is not module:
            raise Dev40AcquisitionError(f"loaded runtime module identity drifted: {module_name}")
        origin_value = getattr(module, "__file__", None)
        if not isinstance(origin_value, str) or not origin_value:
            raise Dev40AcquisitionError(
                f"loaded runtime module has no source origin: {module_name}"
            )
        try:
            origin = Path(origin_value).resolve(strict=True)
            expected = (root / relative).resolve(strict=True)
        except OSError as error:
            raise Dev40AcquisitionError(
                f"loaded runtime module origin cannot be resolved: {module_name}"
            ) from error
        if origin != expected or not origin.is_file():
            raise Dev40AcquisitionError(
                f"loaded runtime module origin differs from exact worktree: {module_name}"
            )
        origins[module_name] = origin.as_posix()

    critical_symbols = (
        (PubMedConnector, "medevidence.connectors.pubmed.client"),
        (PubMedFetchResult, "medevidence.connectors.pubmed.client"),
        (PubMedSearchResult, "medevidence.connectors.pubmed.client"),
        (PubMedConnectorConfig, "medevidence.connectors.pubmed.policy"),
        (PubMedResultState, "medevidence.connectors.pubmed.policy"),
        (FaersConnector, "medevidence.connectors.faers.client"),
        (FaersConnectorConfig, "medevidence.connectors.faers.policy"),
        (FaersAggregateQueryV1, "medevidence.domain.sources"),
        (FaersAggregateRequestV1, "medevidence.domain.scope"),
        (FaersExecutionBoundsV1, "medevidence.domain.scope"),
        (FaersIdentityStrategy, "medevidence.domain.scope"),
        (FaersInclusiveDateRangeV1, "medevidence.domain.scope"),
        (derive_identity, "medevidence.domain.identifiers"),
    )
    for symbol, expected_module in critical_symbols:
        if getattr(symbol, "__module__", None) != expected_module:
            raise Dev40AcquisitionError(
                f"critical runtime symbol differs from exact module: {expected_module}"
            )
    return origins


def _source_state() -> dict[str, dict[str, int | str]]:
    root = _repo_root()
    state: dict[str, dict[str, int | str]] = {}
    for relative in SOURCE_STATE_PATHS:
        path = root / relative
        try:
            raw = path.read_bytes()
        except OSError as error:
            raise Dev40AcquisitionError(f"source-state file is unreadable: {relative}") from error
        state[relative] = {"bytes": len(raw), "sha256": _sha256(raw)}
    return state


def _runtime_closure_state() -> dict[str, dict[str, int | str]]:
    root = _repo_root()
    state: dict[str, dict[str, int | str]] = {}
    for relative in RUNTIME_CLOSURE_PATHS:
        path = root / relative
        try:
            raw = path.read_bytes()
        except OSError as error:
            raise Dev40AcquisitionError(
                f"runtime-closure file is unreadable: {relative}"
            ) from error
        state[relative] = {"bytes": len(raw), "sha256": _sha256(raw)}
    return state


def _source_state_aggregate(state: Mapping[str, Mapping[str, int | str]]) -> str:
    return _sha256(_canonical_json_bytes(state, terminal_lf=False))


def _bounded_path_state(paths: Sequence[str]) -> dict[str, dict[str, int | str]]:
    root = _repo_root()
    state: dict[str, dict[str, int | str]] = {}
    for relative in paths:
        raw = (root / relative).read_bytes()
        state[relative] = {"bytes": len(raw), "sha256": _sha256(raw)}
    return state


def _evidence_tree_state(root: Path) -> dict[str, dict[str, int | str]]:
    if not root.is_dir():
        raise Dev40AcquisitionError("original stopped acquisition root is missing")
    state: dict[str, dict[str, int | str]] = {}
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        raw = path.read_bytes()
        state[path.relative_to(root).as_posix()] = {
            "bytes": len(raw),
            "sha256": _sha256(raw),
        }
    return state


def _verify_bound_evidence_file(
    root: Path,
    relative: Path,
    *,
    expected_sha256: str,
    expected_bytes: int | None = None,
) -> bytes:
    path = root / relative
    raw = path.read_bytes()
    if _sha256(raw) != expected_sha256 or (
        expected_bytes is not None and len(raw) != expected_bytes
    ):
        raise Dev40AcquisitionError(f"original evidence identity drifted: {relative.as_posix()}")
    sidecar = path.with_suffix(path.suffix + ".sha256")
    expected_sidecar = f"{expected_sha256}  {path.name}\n".encode("ascii")
    if sidecar.read_bytes() != expected_sidecar:
        raise Dev40AcquisitionError(f"original evidence sidecar drifted: {relative.as_posix()}")
    return raw


def _run_git(arguments: tuple[str, ...], *, stdout_limit: int) -> bytes:
    root = _repo_root().resolve()
    environment = {
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_OPTIONAL_LOCKS": "0",
        "LC_ALL": "C",
        "PATH": os.environ.get("PATH", ""),
        "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
    }
    try:
        completed = subprocess.run(
            ("git", *arguments),
            cwd=root,
            env=environment,
            shell=False,
            check=False,
            capture_output=True,
            timeout=5.0,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise Dev40AcquisitionError("bounded Git identity verification failed") from error
    if (
        completed.returncode != 0
        or len(completed.stdout) > stdout_limit
        or len(completed.stderr) > 2_048
    ):
        raise Dev40AcquisitionError("bounded Git identity command failed or exceeded output limits")
    return completed.stdout


def _git_output(arguments: tuple[str, ...]) -> str:
    raw = _run_git(arguments, stdout_limit=512)
    try:
        lines = raw.decode("ascii", errors="strict").splitlines()
    except UnicodeError as error:
        raise Dev40AcquisitionError("Git identity output was not exact ASCII") from error
    if len(lines) != 1 or not lines[0]:
        raise Dev40AcquisitionError("Git identity output was not one nonempty line")
    return lines[0]


def _git_candidate_status() -> dict[str, str]:
    raw = _run_git(
        ("status", "--porcelain=v1", "-z", "--untracked-files=all"),
        stdout_limit=8_192,
    )
    records = raw.split(b"\0")
    if records[-1] != b"":
        raise Dev40AcquisitionError("Git porcelain output lacks its terminal NUL")
    statuses: dict[str, str] = {}
    for record in records[:-1]:
        if len(record) < 4 or record[2:3] != b" ":
            raise Dev40AcquisitionError("Git porcelain record is malformed")
        try:
            status = record[:2].decode("ascii", errors="strict")
            relative = record[3:].decode("ascii", errors="strict").replace("\\", "/")
        except UnicodeError as error:
            raise Dev40AcquisitionError("Git candidate path/status is not exact ASCII") from error
        if (
            not relative
            or relative.startswith("/")
            or ".." in Path(relative).parts
            or relative in statuses
        ):
            raise Dev40AcquisitionError("Git candidate path is duplicate, absolute, or escaping")
        if status not in {" M", "??"}:
            raise Dev40AcquisitionError("Git candidate contains staged or unsupported changes")
        statuses[relative] = status
    expected = set(SOURCE_STATE_PATHS)
    if set(statuses) != expected:
        raise Dev40AcquisitionError("Git candidate paths differ from the exact ten-path allowlist")
    return statuses


def _verify_git_state() -> dict[str, str]:
    head = _git_output(("rev-parse", "--verify", "HEAD"))
    branch = _git_output(("branch", "--show-current"))
    top_level = Path(_git_output(("rev-parse", "--show-toplevel"))).resolve()
    if head != BASELINE_COMMIT:
        raise Dev40AcquisitionError("Git HEAD differs from the exact approved baseline")
    if branch != EXPECTED_BRANCH:
        raise Dev40AcquisitionError("Git branch differs from the exact approved branch")
    if top_level != _repo_root().resolve():
        raise Dev40AcquisitionError("Git top-level differs from the fixed acquisition worktree")
    candidate_status = _git_candidate_status()
    return {
        "head": head,
        "branch": branch,
        "top_level": top_level.as_posix(),
        "verification": "git subprocess with fixed cwd, shell false, five-second timeout",
        "candidate_path_count": str(len(candidate_status)),
        "candidate_paths_sha256": _sha256(
            _canonical_json_bytes(candidate_status, terminal_lf=False)
        ),
    }


def pubmed_search_preimage(term: str) -> dict[str, Any]:
    """Return the exact Owner-frozen ESearch request preimage."""

    return {
        "method": "GET",
        "scheme": "https",
        "host": "eutils.ncbi.nlm.nih.gov",
        "path": PUBMED_ESEARCH_PATH,
        "query_parameters_in_wire_order": [
            ["db", "pubmed"],
            ["term", term],
            ["retmode", "xml"],
            ["retstart", "0"],
            ["retmax", "100"],
            ["sort", "relevance"],
            ["tool", "medevidence"],
        ],
    }


def _request_preimage_sha256(value: Mapping[str, Any]) -> str:
    return _sha256(_canonical_json_bytes(value, terminal_lf=False))


def _request_url(preimage: Mapping[str, Any]) -> str:
    pairs = preimage["query_parameters_in_wire_order"]
    if not isinstance(pairs, list):
        raise Dev40AcquisitionError("request preimage parameter order is malformed")
    return str(httpx.URL(f"{PUBMED_ORIGIN}{preimage['path']}", params=pairs))


def _pubmed_query_id(term: str) -> str:
    return derive_identity("pubmed-query", {"query": term})


def build_faers_query() -> FaersAggregateQueryV1:
    """Build and verify the exact already-frozen tirzepatide query."""

    request = FaersAggregateRequestV1(
        drug_concept_id="drug:tirzepatide",
        identity_strategy=FaersIdentityStrategy.HARMONIZED_SUBSTANCE,
        identity_exact_value="TIRZEPATIDE",
        pt_values=GI_PT_SET_M1B_V1,
        inclusive_date_range=FaersInclusiveDateRangeV1(
            start_date=date(2025, 1, 1),
            end_date=date(2025, 1, 31),
        ),
        statistical_unit="provider_count_occurrence",
        execution_bounds=FaersExecutionBoundsV1(
            max_date_difference_days=365,
            max_inclusive_calendar_dates=366,
        ),
    )
    query = FaersAggregateQueryV1.create(request)
    if query.query_id != FAERS_QUERY_ID:
        raise Dev40AcquisitionError("frozen FAERS D query identity drifted")
    return query


def _freeze_document() -> dict[str, Any]:
    loaded_runtime_origins = _verify_loaded_runtime_origins()
    git_state = _verify_git_state()
    _verify_exact_file(
        INVENTORY_PATH,
        expected_bytes=INVENTORY_BYTES,
        expected_sha256=INVENTORY_SHA256,
    )
    _verify_exact_file(
        ACCEPTED_REVIEW_PATH,
        expected_bytes=ACCEPTED_REVIEW_BYTES,
        expected_sha256=ACCEPTED_REVIEW_SHA256,
    )
    _verify_exact_file(
        FREEZE_V1_PATH,
        expected_bytes=FREEZE_V1_BYTES,
        expected_sha256=FREEZE_V1_SHA256,
    )
    _verify_exact_file(
        FREEZE_V1_PATH.with_suffix(FREEZE_V1_PATH.suffix + ".sha256"),
        expected_bytes=FREEZE_V1_SIDECAR_BYTES,
        expected_sha256=FREEZE_V1_SIDECAR_SHA256,
    )
    _verify_exact_file(
        FREEZE_V2_PATH,
        expected_bytes=FREEZE_V2_BYTES,
        expected_sha256=FREEZE_V2_SHA256,
    )
    _verify_exact_file(
        FREEZE_V2_PATH.with_suffix(FREEZE_V2_PATH.suffix + ".sha256"),
        expected_bytes=FREEZE_V2_SIDECAR_BYTES,
        expected_sha256=FREEZE_V2_SIDECAR_SHA256,
    )
    _verify_exact_file(
        FREEZE_V3_PATH,
        expected_bytes=FREEZE_V3_BYTES,
        expected_sha256=FREEZE_V3_SHA256,
    )
    _verify_exact_file(
        FREEZE_V3_PATH.with_suffix(FREEZE_V3_PATH.suffix + ".sha256"),
        expected_bytes=FREEZE_V3_SIDECAR_BYTES,
        expected_sha256=FREEZE_V3_SIDECAR_SHA256,
    )
    _verify_exact_file(
        REVIEW_V3_PATH,
        expected_bytes=REVIEW_V3_BYTES,
        expected_sha256=REVIEW_V3_SHA256,
    )
    _verify_exact_file(
        REVIEW_V3_PATH.with_suffix(REVIEW_V3_PATH.suffix + ".sha256"),
        expected_bytes=REVIEW_V3_SIDECAR_BYTES,
        expected_sha256=REVIEW_V3_SIDECAR_SHA256,
    )
    source_state = _source_state()
    runtime_closure = _runtime_closure_state()
    pubmed: list[dict[str, Any]] = []
    for pair in PUBMED_PAIRS:
        preimage = pubmed_search_preimage(pair.term)
        digest = _request_preimage_sha256(preimage)
        if digest != pair.expected_request_preimage_sha256:
            raise Dev40AcquisitionError(f"{pair.operation_id} request preimage hash drifted")
        pubmed.append(
            {
                "operation_pair_id": pair.operation_id,
                "serves_question_ids": list(pair.serves_question_ids),
                "literal_term": pair.term,
                "search_query_id": _pubmed_query_id(pair.term),
                "search_request_preimage": preimage,
                "search_request_preimage_bytes": len(
                    _canonical_json_bytes(preimage, terminal_lf=False)
                ),
                "search_request_preimage_sha256": digest,
                "search_request_url": _request_url(preimage),
                "fetch_derivation": {
                    "pmid_input": "successful paired ESearch result only",
                    "validation": "1..100 canonical decimal PMID strings",
                    "deduplication": "exact string identity",
                    "ordering": "numeric ascending",
                    "id_serialization": "ASCII comma join",
                    "query_identity": 'derive_identity("pubmed-fetch", {"pmids": tuple})',
                    "request_preimage_profile": (
                        "canonical UTF-8 JSON without BOM or terminal LF; "
                        "exact EFetch wire-order pairs"
                    ),
                    "persistence_gate": "binding JSON plus sidecar rehashed before EFetch",
                    "zero_match": "truthful complete no-match; EFetch skipped_by_no_match",
                },
            }
        )
    faers = build_faers_query()
    return {
        "schema_version": f"{SCHEMA_VERSION}.request-freeze.v4",
        "work_item": WORK_ITEM,
        "status": "PRE_NETWORK_REVIEW_REQUIRED",
        "baseline_commit": BASELINE_COMMIT,
        "expected_branch": EXPECTED_BRANCH,
        "verified_git_state": git_state,
        "predecessor_freezes": [
            {
                "path": FREEZE_V1_PATH.as_posix(),
                "bytes": FREEZE_V1_BYTES,
                "sha256": FREEZE_V1_SHA256,
                "review_status": "FAIL — P0 0 / P1 1 / P2 0",
                "executable_status": "superseded_as_executable_gate",
                "superseded_by": FREEZE_V2_PATH.name,
                "evidence_status": "immutable_historical_evidence",
            },
            {
                "path": FREEZE_V2_PATH.as_posix(),
                "bytes": FREEZE_V2_BYTES,
                "sha256": FREEZE_V2_SHA256,
                "review_status": "FAIL — P0 0 / P1 0 / P2 1",
                "executable_status": "superseded_as_executable_gate",
                "superseded_by": FREEZE_V3_PATH.name,
                "evidence_status": "immutable_historical_evidence",
            },
            {
                "path": FREEZE_V3_PATH.as_posix(),
                "bytes": FREEZE_V3_BYTES,
                "sha256": FREEZE_V3_SHA256,
                "review_status": "PASS — P0 0 / P1 0 / P2 0",
                "terminal_audit_status": "FAIL — P0 0 / P1 1 / P2 0",
                "executable_status": "superseded_as_executable_gate",
                "superseded_by": FREEZE_PATH.name,
                "evidence_status": "immutable_historical_evidence",
            },
        ],
        "review_history": [
            {
                "review_id": "M2-006-ACQUISITION-PRE-NETWORK-REVIEW-001",
                "verdict": "FAIL",
                "finding_counts": {"P0": 0, "P1": 1, "P2": 0},
                "finding_id": "P1-001",
                "finding": (
                    "Request freeze omitted the complete executable runtime module closure "
                    "and active exact Git HEAD/branch verification before client construction."
                ),
                "remediation_status": "remediated_in_cycle_1_awaiting_review_002",
            },
            {
                "review_id": "M2-006-ACQUISITION-PRE-NETWORK-REVIEW-002",
                "verdict": "FAIL",
                "finding_counts": {"P0": 0, "P1": 0, "P2": 1},
                "finding_id": "P2-001",
                "finding": (
                    "Historical request-freeze-001 metadata ambiguously marked the failed "
                    "candidate as not superseded despite replacement by an executable successor."
                ),
                "remediation_status": "remediated_in_cycle_2_awaiting_review_003",
            },
            {
                "review_id": "M2-006-ACQUISITION-PRE-NETWORK-REVIEW-003",
                "verdict": "PASS",
                "finding_counts": {"P0": 0, "P1": 0, "P2": 0},
                "record_path": REVIEW_V3_PATH.as_posix(),
                "record_bytes": REVIEW_V3_BYTES,
                "record_sha256": REVIEW_V3_SHA256,
                "status": "closed_before_terminal_audit_001",
            },
        ],
        "terminal_audit_history": [
            {
                "audit_id": "M2-006-ACQUISITION-TERMINAL-AUDIT-001",
                "verdict": "FAIL",
                "finding_counts": {"P0": 0, "P1": 1, "P2": 0},
                "finding_id": "P1-001",
                "finding": (
                    "The CLI did not prepend the worktree src path, permitting a different "
                    "checkout's medevidence modules to satisfy freeze verification before a "
                    "live TypeError after root creation."
                ),
                "remediation_status": "remediated_in_cycle_3_awaiting_review_004",
            }
        ],
        "remediation_history": [
            {
                "cycle": 1,
                "finding_ids": ["P1-001"],
                "scope": (
                    "bind and reverify complete PubMed/FAERS runtime closure and exact Git state"
                ),
                "status": "completed_awaiting_independent_review_002",
            },
            {
                "cycle": 2,
                "finding_ids": ["P2-001"],
                "scope": (
                    "truthful explicit executable supersession metadata for immutable predecessors"
                ),
                "status": "completed_awaiting_independent_review_003",
            },
            {
                "cycle": 3,
                "finding_ids": ["TERMINAL-AUDIT-001-P1-001"],
                "scope": ("exact CLI src bootstrap and loaded runtime module-origin verification"),
                "status": "completed_awaiting_independent_review_004",
            },
        ],
        "accepted_inputs": {
            "evidence_gap_inventory": {
                "path": INVENTORY_PATH.as_posix(),
                "bytes": INVENTORY_BYTES,
                "sha256": INVENTORY_SHA256,
            },
            "independent_review_004": {
                "path": ACCEPTED_REVIEW_PATH.as_posix(),
                "bytes": ACCEPTED_REVIEW_BYTES,
                "sha256": ACCEPTED_REVIEW_SHA256,
                "verdict": "PASS — P0 0 / P1 0 / P2 0",
            },
        },
        "source_state": {
            "files": source_state,
            "aggregate_sha256": _source_state_aggregate(source_state),
        },
        "runtime_closure": {
            "definition": (
                "repository Python modules and dependency declarations transitively controlling "
                "PubMed/FAERS imports, endpoints, URL/request serialization, query identity, "
                "retry/redirect/time/payload limits, and response parsing"
            ),
            "files": runtime_closure,
            "aggregate_sha256": _source_state_aggregate(runtime_closure),
        },
        "loaded_runtime_origins": {
            "module_count": len(loaded_runtime_origins),
            "modules": loaded_runtime_origins,
            "aggregate_sha256": _sha256(
                _canonical_json_bytes(loaded_runtime_origins, terminal_lf=False)
            ),
            "verification_timing": (
                "freeze/verify and again before live-root creation and client construction"
            ),
        },
        "pubmed": pubmed,
        "faers_D": {
            "query_id": faers.query_id,
            "typed_query": faers.model_dump(mode="json"),
            "serves_question_ids": ["Q27"],
        },
        "bounds": {
            "authorized_logical_operations": AUTHORIZED_LOGICAL_OPERATIONS,
            "pubmed_operations": 6,
            "faers_operations": 1,
            "max_http_requests": MAX_HTTP_REQUESTS,
            "max_pubmed_http_requests": MAX_PUBMED_HTTP_REQUESTS,
            "max_faers_http_requests": MAX_FAERS_HTTP_REQUESTS,
            "pubmed_search_bytes_per_operation": PUBMED_SEARCH_CAP,
            "pubmed_fetch_bytes_per_operation": PUBMED_FETCH_CAP,
            "pubmed_combined_raw_bytes": PUBMED_COMBINED_CAP,
            "faers_raw_bytes": FAERS_CAP,
            "combined_raw_bytes": COMBINED_RAW_CAP,
            "logical_operation_deadline_seconds": 30,
            "whole_run_deadline_seconds": RUN_DEADLINE_SECONDS,
            "max_unique_pmids_per_pair": 100,
            "no_automatic_rerun": True,
        },
        "live_gate": {
            "canonical_root": LIVE_ROOT.as_posix(),
            "required_acknowledgement": LIVE_ACKNOWLEDGEMENT,
            "required_review_name": PRE_NETWORK_REVIEW_NAME,
            "required_review_verdict": "PASS",
            "required_findings": {"P0": 0, "P1": 0, "P2": 0},
            "review_must_bind_request_freeze_sha256": True,
            "review_must_bind_source_state_aggregate_sha256": True,
        },
        "access_declarations": {
            "medical_source_network": "not_accessed_during_freeze",
            "holdout_20": "not_accessed",
            "rankings_scores_qrels": "not_accessed",
            "corpus_or_adjudication_packet": "not_created",
        },
    }


def prepare_request_freeze(
    output_root: str | Path = FREEZE_ROOT,
    *,
    _allow_test_root: bool = False,
) -> FreezeResult:
    """Write the immutable offline request freeze without constructing clients."""

    root = Path(output_root).resolve()
    if not _allow_test_root and root != FREEZE_ROOT.resolve():
        raise Dev40AcquisitionError("request freeze requires the exact external evidence root")
    if not root.exists() or not root.is_dir():
        raise Dev40AcquisitionError("request-freeze predecessor evidence root is missing")
    path = root / FREEZE_PATH.name
    if path.exists() or path.with_suffix(path.suffix + ".sha256").exists():
        raise Dev40AcquisitionError("request-freeze successor already exists")
    document = _freeze_document()
    digest = _write_json(path, document)
    verified = verify_request_freeze(path)
    if verified.sha256 != digest:
        raise Dev40AcquisitionError("request-freeze post-write identity drifted")
    return verified


def _strict_json(path: Path) -> Any:
    def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise Dev40AcquisitionError(f"duplicate JSON key in {path.name}: {key}")
            value[key] = item
        return value

    try:
        raw = path.read_bytes()
        if raw.startswith(b"\xef\xbb\xbf"):
            raise Dev40AcquisitionError(f"UTF-8 BOM is forbidden: {path.name}")
        return json.loads(raw.decode("utf-8"), object_pairs_hook=unique_object)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise Dev40AcquisitionError(f"cannot load exact JSON evidence: {path.name}") from error


def verify_request_freeze(path: str | Path = FREEZE_PATH) -> FreezeResult:
    """Rebind a request freeze to current accepted inputs and source bytes."""

    freeze_path = Path(path).resolve()
    raw = freeze_path.read_bytes()
    value = _strict_json(freeze_path)
    expected = _freeze_document()
    if value != expected or raw != _canonical_json_bytes(expected):
        raise Dev40AcquisitionError("request-freeze content does not equal current exact contract")
    sidecar = freeze_path.with_suffix(freeze_path.suffix + ".sha256")
    expected_sidecar = f"{_sha256(raw)}  {freeze_path.name}\n".encode("ascii")
    if sidecar.read_bytes() != expected_sidecar:
        raise Dev40AcquisitionError("request-freeze sidecar is missing or malformed")
    aggregate = value["source_state"]["aggregate_sha256"]
    runtime_aggregate = value["runtime_closure"]["aggregate_sha256"]
    if not isinstance(aggregate, str) or not isinstance(runtime_aggregate, str):
        raise Dev40AcquisitionError("request-freeze source/runtime aggregate is malformed")
    return FreezeResult(freeze_path, _sha256(raw), aggregate, runtime_aggregate)


def _fetch_binding(pair: PubMedPair, pmids: Sequence[str]) -> dict[str, Any]:
    if not 1 <= len(pmids) <= 100:
        raise Dev40AcquisitionError("EFetch binding requires 1 through 100 PMIDs")
    if any(
        not isinstance(pmid, str)
        or not pmid.isascii()
        or not pmid.isdecimal()
        or pmid.startswith("0")
        or len(pmid) > 16
        for pmid in pmids
    ):
        raise Dev40AcquisitionError("EFetch binding received a noncanonical decimal PMID")
    ordered = tuple(sorted(set(pmids), key=int))
    if not 1 <= len(ordered) <= 100:
        raise Dev40AcquisitionError("EFetch canonical PMID count is outside 1 through 100")
    joined = ",".join(ordered)
    query_id = derive_identity("pubmed-fetch", {"pmids": ordered})
    preimage = {
        "method": "GET",
        "scheme": "https",
        "host": "eutils.ncbi.nlm.nih.gov",
        "path": PUBMED_EFETCH_PATH,
        "query_parameters_in_wire_order": [
            ["db", "pubmed"],
            ["id", joined],
            ["retmode", "xml"],
            ["rettype", "abstract"],
            ["tool", "medevidence"],
        ],
    }
    return {
        "schema_version": f"{SCHEMA_VERSION}.pubmed-fetch-binding.v1",
        "operation_pair_id": pair.operation_id,
        "source_search_request_preimage_sha256": pair.expected_request_preimage_sha256,
        "provider_pmids": list(pmids),
        "ordered_unique_pmids": list(ordered),
        "id_parameter": joined,
        "query_id": query_id,
        "request_preimage": preimage,
        "request_preimage_sha256": _request_preimage_sha256(preimage),
        "request_url": _request_url(preimage),
        "status": "persisted_and_rehashed_before_efetch",
    }


def _raw_records(root: Path, operation_id: str, responses: Sequence[Any]) -> tuple[list[Any], int]:
    records: list[Any] = []
    byte_count = 0
    safe_operation = operation_id.replace("/", "-")
    for ordinal, response in enumerate(responses, start=1):
        body = response.body
        if not isinstance(body, bytes):
            raise Dev40AcquisitionError("connector raw response body is not exact bytes")
        digest = _sha256(body)
        path = root / "raw" / f"{safe_operation}-{ordinal:02d}-sha256-{digest}.raw"
        _write_with_sidecar(path, body)
        byte_count += len(body)
        records.append(
            {
                "ordinal": ordinal,
                "relative_path": path.relative_to(root).as_posix(),
                "bytes": len(body),
                "sha256": digest,
                "request_url": response.request_url,
                "final_url": response.final_url,
                "status_code": response.status_code,
                "observed_at_utc": response.observed_at_utc,
                "body_complete": response.body_complete,
                "termination_reason": response.termination_reason,
                "headers": response.headers,
                "page_number": response.page_number,
                "attempt_count": response.attempt_count,
            }
        )
    return records, byte_count


def _pubmed_search_record(
    pair: PubMedPair,
    result: PubMedSearchResult,
    raw_records: Sequence[Any],
) -> dict[str, Any]:
    return {
        "schema_version": f"{SCHEMA_VERSION}.pubmed-search-operation.v1",
        "operation_id": f"{pair.operation_id}-esearch",
        "request_preimage_sha256": pair.expected_request_preimage_sha256,
        "query_id": result.query_id,
        "state": result.state,
        "pmids": result.pmids,
        "total_available": result.total_available,
        "warning_codes": result.warning_codes,
        "request_count": result.request_count,
        "retry_events": result.retry_events,
        "failure": result.failure,
        "raw_responses": raw_records,
    }


def _pubmed_fetch_record(
    pair: PubMedPair,
    result: PubMedFetchResult,
    binding_sha256: str,
    raw_records: Sequence[Any],
) -> dict[str, Any]:
    return {
        "schema_version": f"{SCHEMA_VERSION}.pubmed-fetch-operation.v1",
        "operation_id": f"{pair.operation_id}-efetch",
        "binding_sha256": binding_sha256,
        "query_id": result.query_id,
        "state": result.state,
        "requested_pmids": result.requested_pmids,
        "publication_pmids": [publication.pmid for publication in result.publications],
        "not_retrieved_pmids": result.not_retrieved_pmids,
        "malformed_record_count": len(result.malformed_records),
        "record_issue_count": len(result.record_issues),
        "warning_codes": result.warning_codes,
        "request_count": result.request_count,
        "retry_events": result.retry_events,
        "failure": result.failure,
        "raw_responses": raw_records,
    }


def _verify_pre_network_review(
    review_path: Path,
    review_sha256: str,
    freeze: FreezeResult,
    *,
    allow_test_root: bool,
) -> None:
    expected_review = (
        freeze.path.parent / PRE_NETWORK_REVIEW_NAME
        if allow_test_root
        else FREEZE_ROOT / PRE_NETWORK_REVIEW_NAME
    )
    if review_path.resolve() != expected_review.resolve():
        raise Dev40AcquisitionError("live execution requires the exact pre-network review path")
    raw = review_path.read_bytes()
    if _sha256(raw) != review_sha256:
        raise Dev40AcquisitionError("pre-network review hash differs from exact bytes")
    review = _strict_json(review_path)
    if not isinstance(review, dict):
        raise Dev40AcquisitionError("pre-network review must be a JSON object")
    expected = {
        "work_item": WORK_ITEM,
        "verdict": "PASS",
        "finding_counts": {"P0": 0, "P1": 0, "P2": 0},
        "request_freeze_sha256": freeze.sha256,
        "source_state_aggregate_sha256": freeze.source_state_aggregate_sha256,
        "runtime_closure_aggregate_sha256": freeze.runtime_closure_aggregate_sha256,
    }
    for key, value in expected.items():
        if review.get(key) != value:
            raise Dev40AcquisitionError(f"pre-network review does not bind exact {key}")


def _production_pubmed_factory(max_payload_bytes: int) -> PubMedConnector:
    config = replace(
        PubMedConnectorConfig.m1a_constrained_v1(),
        max_payload_bytes=max_payload_bytes,
    )
    return PubMedConnector(httpx.HTTPTransport(retries=0), config)


def _production_faers_factory() -> FaersConnector:
    return FaersConnector(httpx.HTTPTransport(retries=0), FaersConnectorConfig())


def _require_elapsed_within(started: float, monotonic: Callable[[], float]) -> None:
    try:
        elapsed = monotonic() - started
    except (TypeError, ValueError) as error:
        raise Dev40AcquisitionError("whole-run monotonic clock violated its contract") from error
    if elapsed < 0 or elapsed > RUN_DEADLINE_SECONDS:
        raise Dev40AcquisitionError("whole-run 240-second deadline expired or clock regressed")


def _write_stop(root: Path, message: str, operations: Sequence[Mapping[str, Any]]) -> None:
    _write_json(
        root / "stop.json",
        {
            "schema_version": f"{SCHEMA_VERSION}.stop.v1",
            "work_item": WORK_ITEM,
            "status": "STOP_SOURCE_FAILURE",
            "original_failure": message,
            "authorized_logical_operations": AUTHORIZED_LOGICAL_OPERATIONS,
            "executed_operation_records": [item["relative_path"] for item in operations],
            "success_manifest_created": False,
            "automatic_rerun_authorized": False,
        },
    )


def replay_pubmed_c_successor(
    *,
    original_root: str | Path = LIVE_ROOT,
    output_root: str | Path = PUBMED_C_SUCCESSOR_ROOT,
    _allow_test_root: bool = False,
) -> PubMedCSuccessorResult:
    """Reconcile the retained PubMed C bytes into append-only offline evidence."""

    source_root = Path(original_root).resolve()
    successor_root = Path(output_root).resolve()
    if not _allow_test_root and (
        source_root != LIVE_ROOT.resolve() or successor_root != PUBMED_C_SUCCESSOR_ROOT.resolve()
    ):
        raise Dev40AcquisitionError("PubMed C replay requires the exact external evidence roots")
    if successor_root.exists():
        raise Dev40AcquisitionError("PubMed C successor evidence root already exists")

    original_before = _evidence_tree_state(source_root)
    original_aggregate = _source_state_aggregate(original_before)
    raw = _verify_bound_evidence_file(
        source_root,
        PUBMED_C_RAW_RELATIVE_PATH,
        expected_sha256=PUBMED_C_RAW_SHA256,
        expected_bytes=PUBMED_C_RAW_BYTES,
    )
    binding_raw = _verify_bound_evidence_file(
        source_root,
        PUBMED_C_BINDING_RELATIVE_PATH,
        expected_sha256=PUBMED_C_BINDING_SHA256,
    )
    operation_raw = _verify_bound_evidence_file(
        source_root,
        PUBMED_C_OPERATION_RELATIVE_PATH,
        expected_sha256=PUBMED_C_OPERATION_SHA256,
    )
    stop_raw = _verify_bound_evidence_file(
        source_root,
        Path("stop.json"),
        expected_sha256=ORIGINAL_STOP_SHA256,
    )
    binding = json.loads(binding_raw.decode("utf-8"))
    operation = json.loads(operation_raw.decode("utf-8"))
    stop = json.loads(stop_raw.decode("utf-8"))
    if not all(isinstance(value, dict) for value in (binding, operation, stop)):
        raise Dev40AcquisitionError("original PubMed C lineage evidence is malformed")
    expected_pmids = binding.get("ordered_unique_pmids")
    raw_responses = operation.get("raw_responses")
    if (
        not isinstance(expected_pmids, list)
        or len(expected_pmids) != 100
        or any(not isinstance(pmid, str) for pmid in expected_pmids)
        or operation.get("binding_sha256") != PUBMED_C_BINDING_SHA256
        or operation.get("state") != "partial_success"
        or operation.get("not_retrieved_pmids") != ["31644235"]
        or not isinstance(raw_responses, list)
        or len(raw_responses) != 1
        or not isinstance(raw_responses[0], dict)
        or raw_responses[0].get("relative_path") != PUBMED_C_RAW_RELATIVE_PATH.as_posix()
        or raw_responses[0].get("sha256") != PUBMED_C_RAW_SHA256
        or stop.get("status") != "STOP_SOURCE_FAILURE"
        or PUBMED_C_OPERATION_RELATIVE_PATH.as_posix()
        not in stop.get("executed_operation_records", [])
    ):
        raise Dev40AcquisitionError("original PubMed C partial-success lineage is inconsistent")
    observed = raw_responses[0].get("observed_at_utc")
    query_id = binding.get("query_id")
    if not isinstance(observed, str) or not isinstance(query_id, str):
        raise Dev40AcquisitionError("original PubMed C time or query identity is malformed")
    try:
        retrieved_at = datetime.fromisoformat(observed.replace("Z", "+00:00"))
    except ValueError as error:
        raise Dev40AcquisitionError("original PubMed C observation time is malformed") from error
    if retrieved_at.tzinfo is None or retrieved_at.utcoffset() is None:
        raise Dev40AcquisitionError("original PubMed C observation time is not timezone aware")

    parsed = pubmed_parsing_module.parse_fetch_response(
        raw,
        tuple(expected_pmids),
        max_items=len(expected_pmids),
    )
    replay = pubmed_client_module.reconcile_retained_fetch_response(
        raw,
        tuple(expected_pmids),
        query_id=query_id,
        retrieved_at=retrieved_at.astimezone(UTC),
        config=replace(
            PubMedConnectorConfig.m1a_constrained_v1(),
            max_payload_bytes=PUBMED_FETCH_CAP,
        ),
    )
    if (
        parsed.article_occurrence_count != 99
        or parsed.book_document_occurrence_count != 1
        or len(parsed.records) != 99
        or len(parsed.book_documents) != 1
        or replay.state is not PubMedResultState.COMPLETE_SUCCESS
        or len(replay.publications) != 99
        or len(replay.book_documents) != 1
        or replay.book_documents[0].pmid != "31644235"
        or replay.book_document_mapping_disposition != "source_native_retained_not_coerced"
        or replay.not_retrieved_pmids
        or replay.malformed_records
        or replay.record_issues
        or replay.request_count != 0
        or replay.raw_responses
        or replay.source_outcome is None
        or replay.source_outcome.valid_result_count != 100
    ):
        raise Dev40AcquisitionError("retained PubMed C replay did not reconcile exactly 100/100")

    book = replay.book_documents[0]
    source_state = _bounded_path_state(BOOK_REMEDIATION_PATHS)
    publication_pmids = [publication.pmid for publication in replay.publications]
    document = {
        "schema_version": f"{SCHEMA_VERSION}.pubmed-c-offline-successor.v1",
        "work_item": WORK_ITEM,
        "status": "OFFLINE_SUCCESSOR_RECONCILIATION_COMPLETE",
        "original_stopped_acquisition": {
            "relative_root_name": source_root.name,
            "tree_file_count": len(original_before),
            "tree_identity_aggregate_sha256": original_aggregate,
            "stop_sha256": ORIGINAL_STOP_SHA256,
            "operation_sha256": PUBMED_C_OPERATION_SHA256,
            "binding_sha256": PUBMED_C_BINDING_SHA256,
            "raw_relative_path": PUBMED_C_RAW_RELATIVE_PATH.as_posix(),
            "raw_bytes": PUBMED_C_RAW_BYTES,
            "raw_sha256": PUBMED_C_RAW_SHA256,
            "historical_state": "partial_success_99_of_100_preserved_immutable",
        },
        "offline_replay": {
            "requested_provider_records": 100,
            "pubmed_article_occurrences": parsed.article_occurrence_count,
            "pubmed_book_article_occurrences": parsed.book_document_occurrence_count,
            "admitted_provider_records": replay.source_outcome.valid_result_count,
            "normalized_publication_records": len(replay.publications),
            "source_native_book_documents": len(replay.book_documents),
            "publication_pmids": publication_pmids,
            "publication_pmids_sha256": _sha256(
                _canonical_json_bytes(publication_pmids, terminal_lf=False)
            ),
            "not_retrieved_pmids": replay.not_retrieved_pmids,
            "malformed_record_count": len(replay.malformed_records),
            "record_issue_count": len(replay.record_issues),
            "mapping_disposition": replay.book_document_mapping_disposition,
            "book_document": {
                "pmid": book.pmid,
                "book_accession": book.book_accession,
                "title_sha256": _sha256(book.title.encode("utf-8")),
                "book_title_sha256": _sha256(book.book_title.encode("utf-8")),
                "abstract_sections_sha256": _sha256(
                    _canonical_json_bytes(book.abstract_sections, terminal_lf=False)
                ),
                "publisher_name_sha256": (
                    _sha256(book.publisher_name.encode("utf-8"))
                    if book.publisher_name is not None
                    else None
                ),
                "publisher_location_sha256": (
                    _sha256(book.publisher_location.encode("utf-8"))
                    if book.publisher_location is not None
                    else None
                ),
                "has_journal_semantics": hasattr(book, "journal"),
            },
            "query_id": query_id,
            "retained_response_observed_at_utc": observed,
            "raw_bytes_copied": False,
            "network_requests": 0,
            "faers_d_executed": False,
            "holdout_accessed": False,
        },
        "candidate_source_state": {
            "files": source_state,
            "aggregate_sha256": _source_state_aggregate(source_state),
        },
        "original_tree_unchanged": True,
    }
    successor_root.mkdir(parents=True, exist_ok=False)
    evidence_path = successor_root / "pubmed-c-offline-successor-reconciliation.json"
    evidence_sha = _write_json(evidence_path, document)
    original_after = _evidence_tree_state(source_root)
    if original_after != original_before:
        raise Dev40AcquisitionError("original stopped acquisition bytes changed during replay")
    return PubMedCSuccessorResult(
        root=successor_root,
        evidence_sha256=evidence_sha,
        publication_count=len(replay.publications),
        book_document_count=len(replay.book_documents),
        provider_record_count=replay.source_outcome.valid_result_count,
    )


def run_authorized_acquisition(
    *,
    acknowledgement: str,
    request_freeze_path: str | Path,
    request_freeze_sha256: str,
    review_record_path: str | Path,
    review_record_sha256: str,
    output_root: str | Path = LIVE_ROOT,
    _pubmed_factory: Callable[[int], PubMedConnector] | None = None,
    _faers_factory: Callable[[], FaersConnector] | None = None,
    _monotonic: Callable[[], float] = time.monotonic,
    _allow_test_root: bool = False,
) -> AcquisitionResult:
    """Consume the one-shot source authorization after the exact offline PASS gate."""

    root = Path(output_root).resolve()
    if not _allow_test_root and root != LIVE_ROOT.resolve():
        raise Dev40AcquisitionError("live acquisition requires the exact external evidence root")
    if acknowledgement != LIVE_ACKNOWLEDGEMENT:
        raise Dev40AcquisitionError("exact live authorization acknowledgement is required")
    if root.exists():
        raise Dev40AcquisitionError("live acquisition root already exists; no rerun is authorized")
    freeze_path = Path(request_freeze_path).resolve()
    if freeze_path != FREEZE_PATH.resolve() and not _allow_test_root:
        raise Dev40AcquisitionError("live acquisition requires the exact request-freeze path")
    freeze = verify_request_freeze(freeze_path)
    if freeze.sha256 != request_freeze_sha256:
        raise Dev40AcquisitionError("request-freeze argument does not match exact bytes")
    _verify_pre_network_review(
        Path(review_record_path),
        review_record_sha256,
        freeze,
        allow_test_root=_allow_test_root,
    )
    _verify_loaded_runtime_origins()
    if root.exists():
        raise Dev40AcquisitionError("live acquisition root collided during preflight")

    started = _monotonic()
    root.mkdir(parents=True, exist_ok=False)
    _write_json(
        root / "live-started.json",
        {
            "schema_version": f"{SCHEMA_VERSION}.live-started.v1",
            "work_item": WORK_ITEM,
            "status": "authorization_consumed_before_first_request",
            "request_freeze_sha256": freeze.sha256,
            "pre_network_review_sha256": review_record_sha256,
            "runtime_closure_aggregate_sha256": freeze.runtime_closure_aggregate_sha256,
            "authorized_logical_operations": AUTHORIZED_LOGICAL_OPERATIONS,
            "no_automatic_rerun": True,
        },
    )

    pubmed_factory = _pubmed_factory or _production_pubmed_factory
    faers_factory = _faers_factory or _production_faers_factory
    operations: list[dict[str, Any]] = []
    http_requests = 0
    pubmed_requests = 0
    faers_requests = 0
    pubmed_bytes = 0
    faers_bytes = 0
    executed_operations = 0
    skipped_empty_fetches = 0
    try:
        _verify_loaded_runtime_origins()
        _verify_git_state()
        for pair in PUBMED_PAIRS:
            _require_elapsed_within(started, _monotonic)
            with pubmed_factory(PUBMED_SEARCH_CAP) as connector:
                search_result = connector.search(pair.term, sort="relevance")
            executed_operations += 1
            raw_records, raw_bytes = _raw_records(
                root, f"{pair.operation_id}-esearch", search_result.raw_responses
            )
            pubmed_bytes += raw_bytes
            http_requests += search_result.request_count
            pubmed_requests += search_result.request_count
            search_path = root / "operations" / f"{pair.operation_id}-esearch.json"
            search_sha = _write_json(
                search_path,
                _pubmed_search_record(pair, search_result, raw_records),
            )
            operations.append(
                {
                    "relative_path": search_path.relative_to(root).as_posix(),
                    "sha256": search_sha,
                }
            )
            if search_result.failure is not None or search_result.request_count > 4:
                raise Dev40AcquisitionError(
                    f"{pair.operation_id} ESearch failed or exceeded bounds"
                )
            if search_result.query_id != _pubmed_query_id(pair.term):
                raise Dev40AcquisitionError(f"{pair.operation_id} ESearch query identity drifted")
            if not search_result.pmids:
                if (
                    search_result.state is not PubMedResultState.EMPTY_SUCCESS
                    or search_result.total_available != 0
                    or search_result.source_outcome is None
                ):
                    raise Dev40AcquisitionError(
                        f"{pair.operation_id} empty ESearch was not a truthful complete no-match"
                    )
                skip_path = root / "operations" / f"{pair.operation_id}-efetch-skipped.json"
                skip_sha = _write_json(
                    skip_path,
                    {
                        "schema_version": f"{SCHEMA_VERSION}.skipped-operation.v1",
                        "operation_id": f"{pair.operation_id}-efetch",
                        "status": "skipped_by_no_match",
                        "authorized_but_not_executed": True,
                        "source_search_operation_sha256": search_sha,
                    },
                )
                operations.append(
                    {
                        "relative_path": skip_path.relative_to(root).as_posix(),
                        "sha256": skip_sha,
                    }
                )
                skipped_empty_fetches += 1
                continue
            if search_result.state not in {
                PubMedResultState.COMPLETE_SUCCESS,
                PubMedResultState.BOUNDED_TRUNCATION,
            }:
                raise Dev40AcquisitionError(f"{pair.operation_id} ESearch is not usable")

            binding = _fetch_binding(pair, search_result.pmids)
            binding_path = root / "bindings" / f"{pair.operation_id}-efetch-binding.json"
            binding_sha = _write_json(binding_path, binding)
            if _sha256(binding_path.read_bytes()) != binding_sha:
                raise Dev40AcquisitionError(f"{pair.operation_id} EFetch binding rehash failed")

            _require_elapsed_within(started, _monotonic)
            with pubmed_factory(PUBMED_FETCH_CAP) as connector:
                fetch_result = connector.fetch(tuple(binding["ordered_unique_pmids"]))
            executed_operations += 1
            raw_records, raw_bytes = _raw_records(
                root, f"{pair.operation_id}-efetch", fetch_result.raw_responses
            )
            pubmed_bytes += raw_bytes
            http_requests += fetch_result.request_count
            pubmed_requests += fetch_result.request_count
            fetch_path = root / "operations" / f"{pair.operation_id}-efetch.json"
            fetch_sha = _write_json(
                fetch_path,
                _pubmed_fetch_record(pair, fetch_result, binding_sha, raw_records),
            )
            operations.append(
                {
                    "relative_path": fetch_path.relative_to(root).as_posix(),
                    "sha256": fetch_sha,
                }
            )
            if (
                fetch_result.failure is not None
                or fetch_result.state is not PubMedResultState.COMPLETE_SUCCESS
                or fetch_result.request_count > 4
                or fetch_result.query_id != binding["query_id"]
                or fetch_result.requested_pmids != tuple(binding["ordered_unique_pmids"])
                or fetch_result.not_retrieved_pmids
                or fetch_result.malformed_records
            ):
                raise Dev40AcquisitionError(f"{pair.operation_id} EFetch failed reconciliation")
            if pubmed_bytes > PUBMED_COMBINED_CAP or pubmed_requests > MAX_PUBMED_HTTP_REQUESTS:
                raise Dev40AcquisitionError("PubMed aggregate byte/request ceiling exceeded")

        _require_elapsed_within(started, _monotonic)
        faers_query = build_faers_query()
        with faers_factory() as connector:
            faers_result = connector.aggregate(faers_query)
        executed_operations += 1
        raw_records, raw_bytes = _raw_records(root, "faers-D", faers_result.raw_responses)
        faers_bytes += raw_bytes
        http_requests += faers_result.request_count
        faers_requests += faers_result.request_count
        faers_path = root / "operations" / "faers-D.json"
        faers_sha = _write_json(
            faers_path,
            {
                "schema_version": f"{SCHEMA_VERSION}.faers-operation.v1",
                "operation_id": "faers-D-tirzepatide-gi-2025-01",
                "query_id": faers_query.query_id,
                "typed_query": faers_query,
                "request_count": faers_result.request_count,
                "pages_completed": faers_result.pages_completed,
                "truncated": faers_result.truncated,
                "failure": faers_result.failure,
                "buckets": faers_result.value.buckets if faers_result.value is not None else None,
                "retry_events": faers_result.retry_events,
                "raw_responses": raw_records,
            },
        )
        operations.append(
            {"relative_path": faers_path.relative_to(root).as_posix(), "sha256": faers_sha}
        )
        if (
            faers_result.failure is not None
            or faers_result.value is None
            or faers_result.truncated
            or faers_result.request_count > MAX_FAERS_HTTP_REQUESTS
        ):
            raise Dev40AcquisitionError("FAERS D failed or exceeded its frozen bounds")
        _require_elapsed_within(started, _monotonic)
        if (
            pubmed_bytes > PUBMED_COMBINED_CAP
            or faers_bytes > FAERS_CAP
            or pubmed_bytes + faers_bytes > COMBINED_RAW_CAP
            or pubmed_requests > MAX_PUBMED_HTTP_REQUESTS
            or faers_requests > MAX_FAERS_HTTP_REQUESTS
            or http_requests > MAX_HTTP_REQUESTS
        ):
            raise Dev40AcquisitionError("combined acquisition ceiling exceeded")
        freeze_after = verify_request_freeze(freeze_path)
        if freeze_after != freeze:
            raise Dev40AcquisitionError("request/source evidence drifted during live acquisition")
        manifest_path = root / "acquisition-manifest.json"
        manifest_sha = _write_json(
            manifest_path,
            {
                "schema_version": f"{SCHEMA_VERSION}.manifest.v1",
                "work_item": WORK_ITEM,
                "status": "ACQUISITION_COMPLETE_OFFLINE_CORPUS_RECONCILIATION_ONLY",
                "request_freeze_sha256": freeze.sha256,
                "pre_network_review_sha256": review_record_sha256,
                "authorized_logical_operations": AUTHORIZED_LOGICAL_OPERATIONS,
                "executed_logical_operations": executed_operations,
                "skipped_empty_fetches": skipped_empty_fetches,
                "http_requests": http_requests,
                "raw_bytes": pubmed_bytes + faers_bytes,
                "operation_records": operations,
                "corpus_created": False,
                "adjudication_packet_created": False,
                "qrels_rankings_scores_created": False,
                "automatic_rerun_authorized": False,
            },
        )
        return AcquisitionResult(
            root,
            manifest_sha,
            AUTHORIZED_LOGICAL_OPERATIONS,
            executed_operations,
            skipped_empty_fetches,
            http_requests,
            pubmed_bytes + faers_bytes,
        )
    except Exception as error:
        message = str(error) or type(error).__name__
        try:
            _write_stop(root, message, operations)
        except Exception as stop_error:
            raise Dev40AcquisitionError(
                f"acquisition failed: {message}; STOP evidence generation also failed: {stop_error}"
            ) from error
        if isinstance(error, Dev40AcquisitionError):
            raise
        raise Dev40AcquisitionError(f"source acquisition failed: {message}") from error


__all__ = [
    "ACCEPTED_REVIEW_PATH",
    "FAERS_QUERY_ID",
    "FREEZE_PATH",
    "FREEZE_ROOT",
    "LIVE_ACKNOWLEDGEMENT",
    "LIVE_ROOT",
    "PUBMED_C_SUCCESSOR_ROOT",
    "PUBMED_PAIRS",
    "TERM_A",
    "TERM_B",
    "TERM_C",
    "AcquisitionResult",
    "Dev40AcquisitionError",
    "FreezeResult",
    "PubMedCSuccessorResult",
    "build_faers_query",
    "prepare_request_freeze",
    "pubmed_search_preimage",
    "replay_pubmed_c_successor",
    "run_authorized_acquisition",
    "verify_request_freeze",
]
