"""Import and dependency-boundary checks for source-neutral domain contracts."""

from __future__ import annotations

import ast
import copy
import hashlib
import json
import sys
import textwrap
import tomllib
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

DOMAIN_ROOT = Path("src/medevidence/domain")
CONNECTOR_ROOT = Path("src/medevidence/connectors")
INGESTION_ROOT = Path("src/medevidence/ingestion")
PERSISTENCE_ROOT = Path("src/medevidence/persistence")
TOOLS_ROOT = Path("src/medevidence/tools")
API_ROOT = Path("src/medevidence/api")
PROHIBITED_TOKENS = {
    "alembic",
    "fastapi",
    "httpx",
    "langgraph",
    "mcp",
    "psycopg",
    "qdrant",
    "sqlalchemy",
    "streamlit",
    "tenacity",
    "uvicorn",
}
APPROVED_CONNECTOR_THIRD_PARTY_ROOTS = {"defusedxml", "httpx"}
APPROVED_PERSISTENCE_THIRD_PARTY_ROOTS = {"sqlalchemy"}


def _load_dependency_helper() -> dict[str, object]:
    script_path = Path("scripts/dependency-audit.ps1")
    dependency_audit = script_path.read_text(encoding="utf-8")
    start_marker = "$helperScript = @'"
    end_marker = "\n'@\n"
    _, start_separator, helper_remainder = dependency_audit.partition(start_marker)
    assert start_separator == start_marker
    helper_source, end_separator, _ = helper_remainder.lstrip("\r\n").partition(end_marker)
    assert end_separator == end_marker

    namespace: dict[str, object] = {"__name__": "dependency_evidence_helper"}
    exec(compile(helper_source, str(script_path), "exec"), namespace)
    return namespace


def _load_ci_advisory_preflight() -> dict[str, object]:
    workflow_path = Path(".github/workflows/dependency-audit.yml")
    workflow = workflow_path.read_text(encoding="utf-8")
    start_marker = "$preflightSource = @'\n"
    end_marker = "\n          '@\n"
    _, start_separator, remainder = workflow.partition(start_marker)
    assert start_separator == start_marker
    source, end_separator, _ = remainder.partition(end_marker)
    assert end_separator == end_marker

    namespace: dict[str, object] = {"__name__": "ci_advisory_preflight_test"}
    exec(compile(textwrap.dedent(source), str(workflow_path), "exec"), namespace)
    return namespace


DEPENDENCY_HELPER = _load_dependency_helper()
CI_ADVISORY_PREFLIGHT = _load_ci_advisory_preflight()
LICENSE_VALIDATOR = cast(
    Callable[[object], str | None], DEPENDENCY_HELPER["validate_license_expression"]
)
LICENSE_METADATA_RESOLVER = cast(
    Callable[..., tuple[str | None, tuple[str, ...]]],
    DEPENDENCY_HELPER["resolve_license_metadata"],
)
SNIFFIO_LICENSE_EVIDENCE_SHA256 = cast(
    dict[str, str], DEPENDENCY_HELPER["SNIFFIO_1_3_1_LICENSE_EVIDENCE_SHA256"]
)
RAW_AUDIT_NORMALIZER = cast(
    Callable[[Path], dict[str, Any]], DEPENDENCY_HELPER["normalize_raw_audit"]
)
OSV_FALLBACK_VALIDATOR = cast(
    Callable[[Path, Path, dict[str, str]], dict[str, Any]],
    DEPENDENCY_HELPER["validate_osv_torch_fallback"],
)
PACKAGE_SETS_FROM_LOCK = cast(
    Callable[[Path], tuple[Any, Any, Any, dict[str, str]]],
    DEPENDENCY_HELPER["package_sets_from_lock"],
)
PACKAGES_FROM_AUDIT = cast(
    Callable[
        [Path, str, Path, Path, dict[str, str]],
        tuple[Any | None, int, int, list[dict[str, str]], dict[str, Any] | None],
    ],
    DEPENDENCY_HELPER["packages_from_audit"],
)
PACKAGES_FROM_LICENSES = cast(
    Callable[[Path], tuple[Any, dict[str, int]]],
    DEPENDENCY_HELPER["packages_from_licenses"],
)
FINALIZE_ADVISORY_DISPOSITIONS = cast(
    Callable[
        [Any, Any, Any, list[dict[str, str]], dict[str, Any] | None],
        tuple[list[dict[str, str]], dict[str, int]],
    ],
    DEPENDENCY_HELPER["finalize_advisory_dispositions"],
)
CI_RUN_PREFLIGHT = cast(
    Callable[..., tuple[Path, Path, Path]], CI_ADVISORY_PREFLIGHT["run_preflight"]
)
CI_ACQUIRE_OSV = cast(Callable[..., None], CI_ADVISORY_PREFLIGHT["acquire_osv"])
CI_VALIDATE_INSTALLED_TORCH = cast(
    Callable[[Path], None], CI_ADVISORY_PREFLIGHT["validate_installed_torch"]
)

TORCH_BINDING = {
    "architecture": "amd64",
    "name": "torch",
    "version": "2.13.0+cpu",
    "registry": "https://download.pytorch.org/whl/cpu",
    "wheel_url": (
        "https://download-r2.pytorch.org/whl/cpu/torch-2.13.0%2Bcpu-cp312-cp312-win_amd64.whl"
    ),
    "wheel_sha256": ("sha256:a8b450c1e58e5800e5b4691dac412f8d2d65a1dc3298166f91596603a3531e6f"),
}
OSV_REQUEST_BODY = '{"package":{"ecosystem":"PyPI","name":"torch"},"version":"2.13.0"}'


def _write_osv_evidence(
    tmp_path: Path,
    *,
    response_bytes: bytes = b'{"vulns":[]}',
    record_mutation: Callable[[dict[str, Any]], None] | None = None,
) -> tuple[Path, Path]:
    response_path = tmp_path / "osv-response.json"
    response_path.write_bytes(response_bytes)
    record: dict[str, Any] = {
        "schema_version": "1.0",
        "acquisition_method": "direct_osv_post",
        "vulnerability_service": "osv",
        "service_url": "https://api.osv.dev/v1/query",
        "http_method": "POST",
        "request_content_type": "application/json",
        "request_body_utf8": OSV_REQUEST_BODY,
        "request_body_byte_count": len(OSV_REQUEST_BODY.encode()),
        "request_body_sha256": hashlib.sha256(OSV_REQUEST_BODY.encode()).hexdigest(),
        "request_started_at_utc": "2026-08-14T05:00:00.000Z",
        "response_received_at_utc": "2026-08-14T05:00:00.250Z",
        "acquired_at_utc": "2026-08-14T05:00:00.250Z",
        "elapsed_milliseconds": 250,
        "http_status": 200,
        "attempt_count": 1,
        "retry_count": 0,
        "connect_timeout_seconds": 10,
        "read_timeout_seconds": 30,
        "maximum_response_bytes": 1_048_576,
        "response_body_byte_count": len(response_bytes),
        "response_body_sha256": hashlib.sha256(response_bytes).hexdigest(),
        "osv_coordinate": {
            "ecosystem": "PyPI",
            "name": "torch",
            "version": "2.13.0",
        },
        "installed_artifact": {
            "name": "torch",
            "version": "2.13.0+cpu",
            "source_registry": TORCH_BINDING["registry"],
            "wheel_url": TORCH_BINDING["wheel_url"],
            "wheel_sha256": TORCH_BINDING["wheel_sha256"],
        },
    }
    if record_mutation is not None:
        record_mutation(record)
    acquisition_path = tmp_path / "osv-acquisition.json"
    acquisition_path.write_text(json.dumps(record), encoding="utf-8")
    return response_path, acquisition_path


def _is_approved_connector_import(module: str) -> bool:
    root = module.split(".", maxsplit=1)[0]
    return (
        root in sys.stdlib_module_names
        or root in APPROVED_CONNECTOR_THIRD_PARTY_ROOTS
        or module == "medevidence.domain"
        or module.startswith("medevidence.domain.")
    )


def test_domain_imports_only_stdlib_pydantic_and_intra_domain_modules() -> None:
    violations: list[str] = []
    for path in sorted(DOMAIN_ROOT.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                roots = {alias.name.split(".", maxsplit=1)[0] for alias in node.names}
            elif isinstance(node, ast.ImportFrom):
                if node.level > 0:
                    continue
                roots = {(node.module or "").split(".", maxsplit=1)[0]}
            else:
                continue
            for root in roots:
                if root not in sys.stdlib_module_names and root != "pydantic":
                    violations.append(f"{path}:{node.lineno}:{root}")

    assert violations == []


def test_domain_source_contains_no_prohibited_outer_layer_capability() -> None:
    violations: list[str] = []
    for path in sorted(DOMAIN_ROOT.glob("*.py")):
        source = path.read_text(encoding="utf-8").casefold()
        for token in PROHIBITED_TOKENS:
            if token in source:
                violations.append(f"{path}:{token}")

    assert violations == []


def test_connectors_import_only_approved_layers_and_dependencies() -> None:
    violations: list[str] = []
    for path in sorted(CONNECTOR_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules = {alias.name.casefold() for alias in node.names}
            elif isinstance(node, ast.ImportFrom):
                if node.level == 1:
                    continue
                if node.level > 1:
                    violations.append(f"{path}:{node.lineno}:{'.' * node.level}{node.module or ''}")
                    continue
                modules = {(node.module or "").casefold()}
            else:
                continue
            for module in modules:
                if not _is_approved_connector_import(module):
                    violations.append(f"{path}:{node.lineno}:{module}")

    assert violations == []


def test_ingestion_imports_only_domain_and_standard_library() -> None:
    violations: list[str] = []
    for path in sorted(INGESTION_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules = {alias.name for alias in node.names}
            elif isinstance(node, ast.ImportFrom):
                if node.level > 0:
                    continue
                modules = {node.module or ""}
            else:
                continue
            for module in modules:
                root = module.split(".", maxsplit=1)[0]
                if (
                    root not in sys.stdlib_module_names
                    and root != "pydantic"
                    and module != "medevidence.domain"
                    and not module.startswith("medevidence.domain.")
                ):
                    violations.append(f"{path}:{node.lineno}:{module}")

    assert violations == []


def test_persistence_imports_only_approved_inward_layers_and_sqlalchemy() -> None:
    violations: list[str] = []
    for path in sorted(PERSISTENCE_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules = {alias.name for alias in node.names}
            elif isinstance(node, ast.ImportFrom):
                if node.level > 0:
                    continue
                modules = {node.module or ""}
            else:
                continue
            for module in modules:
                root = module.split(".", maxsplit=1)[0]
                if (
                    root not in sys.stdlib_module_names
                    and root not in APPROVED_PERSISTENCE_THIRD_PARTY_ROOTS
                    and module != "medevidence.domain"
                    and not module.startswith("medevidence.domain.")
                ):
                    violations.append(f"{path}:{node.lineno}:{module}")

    assert violations == []


def test_tools_import_only_domain_and_consumer_owned_tool_modules() -> None:
    violations: list[str] = []
    for path in sorted(TOOLS_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules = {alias.name for alias in node.names}
            elif isinstance(node, ast.ImportFrom):
                if node.level > 0:
                    continue
                modules = {node.module or ""}
            else:
                continue
            for module in modules:
                root = module.split(".", maxsplit=1)[0]
                if (
                    root not in sys.stdlib_module_names
                    and root != "pydantic"
                    and module != "medevidence.domain"
                    and not module.startswith("medevidence.domain.")
                ):
                    violations.append(f"{path}:{node.lineno}:{module}")

    assert violations == []


def test_api_imports_no_concrete_connector_storage_or_persistence_adapter() -> None:
    forbidden = {
        "medevidence.connectors",
        "medevidence.ingestion",
        "medevidence.persistence",
        "sqlalchemy",
        "psycopg",
    }
    violations: list[str] = []
    for path in sorted(API_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules = {alias.name for alias in node.names}
            elif isinstance(node, ast.ImportFrom):
                if node.level > 0:
                    continue
                modules = {node.module or ""}
            else:
                continue
            for module in modules:
                if any(module == item or module.startswith(f"{item}.") for item in forbidden):
                    violations.append(f"{path}:{node.lineno}:{module}")

    assert violations == []


@pytest.mark.parametrize(
    "module",
    [
        "medevidence.api",
        "medevidence.orchestration",
        "medevidence.retrieval",
    ],
)
def test_connector_import_policy_rejects_outer_medevidence_layers(module: str) -> None:
    assert not _is_approved_connector_import(module)


def test_only_owner_approved_direct_dependencies_are_present() -> None:
    project = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    assert project["project"]["dependencies"] == [
        "alembic==1.18.5",
        "defusedxml==0.7.1",
        "fastapi==0.141.1",
        "httpx==0.28.1",
        "langgraph==1.2.11",
        "langgraph-checkpoint-postgres==3.1.2",
        "psycopg[binary]==3.3.4",
        "pydantic==2.13.4",
        "SQLAlchemy==2.0.51",
    ]
    assert set(project["dependency-groups"]["dev"]) == {
        "coverage==7.15.2",
        "mypy==2.3.0",
        "pip-audit==2.10.1",
        "pytest==9.1.1",
        "pytest-cov==7.1.0",
        "pytest-socket==0.8.0",
        "ruff==0.15.22",
    }
    assert project["dependency-groups"]["retrieval"] == [
        "numpy==2.5.1",
        "scikit-learn==1.9.0",
        "torch==2.13.0",
        "transformers==5.15.0",
    ]
    assert not any(
        dependency.casefold().startswith(("numpy", "scikit-learn", "torch", "transformers"))
        for dependency in project["project"]["dependencies"]
    )
    production_names = {
        dependency.partition("==")[0].casefold()
        for dependency in project["project"]["dependencies"]
    }
    assert {"langgraph", "langgraph-checkpoint-postgres"} <= production_names
    assert production_names.isdisjoint({"langchain", "langchain-core", "openai", "redis"})
    assert project["tool"]["uv"]["sources"] == {"torch": {"index": "pytorch-cpu"}}
    assert project["tool"]["uv"]["index"] == [
        {
            "name": "pytorch-cpu",
            "url": "https://download.pytorch.org/whl/cpu",
            "explicit": True,
        }
    ]
    lock_text = Path("uv.lock").read_text(encoding="utf-8").casefold()
    assert 'name = "uvicorn"' not in lock_text
    assert not any(item.startswith("fastapi[") for item in project["project"]["dependencies"])


def test_retrieval_group_is_explicit_in_bootstrap_ci_and_dependency_evidence() -> None:
    bootstrap = Path("scripts/bootstrap.ps1").read_text(encoding="utf-8")
    workflow = Path(".github/workflows/quality.yml").read_text(encoding="utf-8")
    dependency_audit = Path("scripts/dependency-audit.ps1").read_text(encoding="utf-8")

    assert "sync --locked --group dev --group retrieval" in bootstrap
    assert "scripts\\bootstrap.ps1" in workflow
    assert 'groups.get("retrieval")' in dependency_audit
    assert '"torch==2.13.0"' in dependency_audit
    assert '"transformers==5.15.0"' in dependency_audit
    assert '"retrieval": sorted(retrieval' in dependency_audit
    assert '"export", "--locked", "--all-groups"' in dependency_audit


def test_lock_binds_exact_windows_cpu_torch_and_has_no_accelerator_closure() -> None:
    lock = tomllib.loads(Path("uv.lock").read_text(encoding="utf-8"))
    packages = lock["package"]
    torch_records = [record for record in packages if record["name"] == "torch"]

    assert {
        (record["version"], tuple(record["resolution-markers"])) for record in torch_records
    } == {
        ("2.13.0", ("sys_platform == 'darwin'",)),
        ("2.13.0+cpu", ("sys_platform != 'darwin'",)),
    }
    active = next(record for record in torch_records if record["version"] == "2.13.0+cpu")
    assert active["source"] == {"registry": "https://download.pytorch.org/whl/cpu"}
    assert {
        (wheel["url"], wheel["hash"]) for wheel in active["wheels"] if "-win_" in wheel["url"]
    } == {
        (
            "https://download-r2.pytorch.org/whl/cpu/torch-2.13.0%2Bcpu-cp312-cp312-win_amd64.whl",
            "sha256:a8b450c1e58e5800e5b4691dac412f8d2d65a1dc3298166f91596603a3531e6f",
        ),
        (
            "https://download-r2.pytorch.org/whl/cpu/torch-2.13.0%2Bcpu-cp312-cp312-win_arm64.whl",
            "sha256:fa0762705b933624d59f6823db9ce7ec2e35b3e1e9c319c9db51fbeecfc3e319",
        ),
    }
    assert all(
        record["source"] == {"registry": "https://pypi.org/simple"}
        for record in packages
        if record["name"] not in {"medevidence", "torch"}
    )
    normalized_names = {record["name"].replace("_", "-").casefold() for record in packages}
    assert "triton" not in normalized_names
    assert not any(name.startswith(("nvidia-", "cuda-")) for name in normalized_names)


def test_numpy_2_5_1_spdx_expression_is_accepted_exactly() -> None:
    expression = "BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0"

    assert LICENSE_VALIDATOR(expression) == expression


@pytest.mark.parametrize(
    "expression",
    [
        "MPL-2.0 AND (Apache-2.0 OR MIT)",
        "(MPL-2.0 AND (Apache-2.0 WITH LLVM-exception OR MIT)) OR BSD-3-Clause",
    ],
)
def test_bounded_parenthesized_spdx_expression_is_accepted_exactly(expression: str) -> None:
    assert LICENSE_VALIDATOR(expression) == expression


@pytest.mark.parametrize(
    "expression",
    [
        "MPL-2.0 AND (Apache-2.0 OR MIT",
        "MPL-2.0 AND (Apache-2.0 OR MIT))",
        "MPL-2.0 AND ()",
        "MPL-2.0 AND (OR MIT)",
        "MPL-2.0 AND (MIT OR)",
        "MPL-2.0 AND (MIT Apache-2.0)",
        "MPL-2.0 AND (MIT; import os)",
        "MPL-2.0 AND (__import__)",
        "MPL-2.0 WITH LLVM-exception",
        "MPL-2.0  AND MIT",
        "MPL-2.0 AND ( MIT)",
        "MPL-2.0\nOR MIT",
    ],
)
def test_malformed_or_injection_like_parenthesized_spdx_is_rejected(expression: str) -> None:
    with pytest.raises(ValueError, match="approved SPDX-expression grammar"):
        LICENSE_VALIDATOR(expression)


def test_spdx_parentheses_nesting_is_bounded() -> None:
    exact_maximum = "MIT"
    for _ in range(16):
        exact_maximum = f"({exact_maximum} OR MIT)"

    assert LICENSE_VALIDATOR(exact_maximum) == exact_maximum

    max_plus_one = f"({exact_maximum} OR MIT)"

    with pytest.raises(ValueError, match="approved SPDX-expression grammar"):
        LICENSE_VALIDATOR(max_plus_one)


def test_spdx_token_count_is_bounded() -> None:
    exact_maximum = " OR ".join(["MIT"] * 64)

    assert LICENSE_VALIDATOR(exact_maximum) == exact_maximum

    max_plus_one = f"{exact_maximum} OR MIT"

    with pytest.raises(ValueError, match="approved SPDX-expression grammar"):
        LICENSE_VALIDATOR(max_plus_one)


@pytest.mark.parametrize(
    "expression",
    ["0BSD", "Zlib", "CC0-1.0", "BSL-1.0", "CNRI-Python", "ISC"],
)
def test_newly_approved_spdx_identifiers_are_accepted_exactly(expression: str) -> None:
    assert LICENSE_VALIDATOR(expression) == expression


def test_only_owner_approved_with_exception_is_accepted() -> None:
    assert LICENSE_VALIDATOR("Apache-2.0 WITH LLVM-exception") == "Apache-2.0 WITH LLVM-exception"
    with pytest.raises(ValueError):
        LICENSE_VALIDATOR("GPL-3.0-only WITH GCC-exception-3.1")


@pytest.mark.parametrize("value", ["LicenseRef-Proprietary", "MIT OR LicenseRef-local"])
def test_licenseref_is_globally_rejected(value: str) -> None:
    with pytest.raises(ValueError, match="LicenseRef"):
        LICENSE_VALIDATOR(value)


def test_exact_legacy_and_iscl_classifier_mappings() -> None:
    assert LICENSE_METADATA_RESOLVER(None, "ISC License", []) == ("ISC", ())
    assert LICENSE_METADATA_RESOLVER(None, "Apache 2.0 License", []) == (
        "Apache-2.0",
        (),
    )
    classifier = "License :: OSI Approved :: ISC License (ISCL)"
    assert LICENSE_METADATA_RESOLVER(None, None, [classifier]) == ("ISC", (classifier,))


def test_orjson_expression_exactly_reconciles_multiple_classifiers() -> None:
    expression = "MPL-2.0 AND (Apache-2.0 OR MIT)"
    classifiers = [
        "License :: OSI Approved :: Apache Software License",
        "License :: OSI Approved :: MIT License",
        "License :: OSI Approved :: Mozilla Public License 2.0 (MPL 2.0)",
    ]

    assert LICENSE_METADATA_RESOLVER(expression, None, classifiers) == (
        expression,
        tuple(classifiers),
    )


@pytest.mark.parametrize(
    ("expression", "classifiers"),
    [
        (
            "MPL-2.0 AND (Apache-2.0 OR MIT)",
            [
                "License :: OSI Approved :: Apache Software License",
                "License :: OSI Approved :: Mozilla Public License 2.0 (MPL 2.0)",
            ],
        ),
        (
            "MPL-2.0 AND Apache-2.0",
            [
                "License :: OSI Approved :: Apache Software License",
                "License :: OSI Approved :: MIT License",
                "License :: OSI Approved :: Mozilla Public License 2.0 (MPL 2.0)",
            ],
        ),
        (
            "MPL-2.0 AND Apache-2.0",
            [
                "License :: OSI Approved :: Apache Software License",
                "License :: OSI Approved :: BSD License",
                "License :: OSI Approved :: Mozilla Public License 2.0 (MPL 2.0)",
            ],
        ),
        (
            None,
            [
                "License :: OSI Approved :: Apache Software License",
                "License :: OSI Approved :: MIT License",
            ],
        ),
    ],
)
def test_multiple_classifiers_fail_when_expression_does_not_exactly_cover_them(
    expression: str | None,
    classifiers: list[str],
) -> None:
    with pytest.raises(ValueError, match="exact license classifiers conflict"):
        LICENSE_METADATA_RESOLVER(expression, None, classifiers)


def test_single_classifier_reconciliation_behavior_is_preserved() -> None:
    classifier = "License :: OSI Approved :: MIT License"

    assert LICENSE_METADATA_RESOLVER("MIT", None, [classifier]) == (
        "MIT",
        (classifier,),
    )
    with pytest.raises(ValueError, match="standardized license metadata sources conflict"):
        LICENSE_METADATA_RESOLVER("MPL-2.0 AND MIT", None, [classifier])


def test_sniffio_1_3_1_exact_legacy_license_evidence_is_accepted() -> None:
    classifiers = [
        "License :: OSI Approved :: Apache Software License",
        "License :: OSI Approved :: MIT License",
    ]

    assert LICENSE_METADATA_RESOLVER(
        None,
        "MIT OR Apache-2.0",
        classifiers,
        "sniffio",
        "1.3.1",
        dict(SNIFFIO_LICENSE_EVIDENCE_SHA256),
    ) == ("MIT OR Apache-2.0", tuple(classifiers))


@pytest.mark.parametrize(
    ("package_name", "package_version", "classifiers", "evidence_mutation"),
    [
        ("sniffio-fork", "1.3.1", None, None),
        ("sniffio", "1.3.2", None, None),
        (
            "sniffio",
            "1.3.1",
            [
                "License :: OSI Approved :: Apache Software License",
                "License :: OSI Approved :: Mozilla Public License 2.0 (MPL 2.0)",
            ],
            None,
        ),
        ("sniffio", "1.3.1", None, "missing"),
        ("sniffio", "1.3.1", None, "content"),
    ],
)
def test_sniffio_legacy_license_exception_rejects_any_binding_drift(
    package_name: str,
    package_version: str,
    classifiers: list[str] | None,
    evidence_mutation: str | None,
) -> None:
    exact_classifiers = [
        "License :: OSI Approved :: Apache Software License",
        "License :: OSI Approved :: MIT License",
    ]
    evidence = dict(SNIFFIO_LICENSE_EVIDENCE_SHA256)
    if evidence_mutation == "missing":
        evidence.pop("LICENSE")
    elif evidence_mutation == "content":
        evidence["LICENSE"] = "0" * 64

    with pytest.raises(ValueError, match="license evidence"):
        LICENSE_METADATA_RESOLVER(
            None,
            "MIT OR Apache-2.0",
            classifiers or exact_classifiers,
            package_name,
            package_version,
            evidence,
        )


def _sniffio_normalized_license_record() -> dict[str, Any]:
    return {
        "license_classifiers": [
            "License :: OSI Approved :: Apache Software License",
            "License :: OSI Approved :: MIT License",
        ],
        "license_evidence_sha256": dict(SNIFFIO_LICENSE_EVIDENCE_SHA256),
        "license_expression": "MIT OR Apache-2.0",
        "metadata_source": "installed_distribution",
        "name": "sniffio",
        "reachability": "windows_active",
        "review_status": "declared",
        "source_registry": "https://pypi.org/simple",
        "source_wheel_sha256": None,
        "source_wheel_url": None,
        "version": "1.3.1",
    }


def _write_license_inventory(tmp_path: Path, record: dict[str, Any]) -> Path:
    path = tmp_path / "licenses.json"
    path.write_text(json.dumps({"packages": [record]}), encoding="utf-8")
    return path


def test_authoritative_reconciliation_accepts_exact_normalized_sniffio_evidence(
    tmp_path: Path,
) -> None:
    packages, counts = PACKAGES_FROM_LICENSES(
        _write_license_inventory(tmp_path, _sniffio_normalized_license_record())
    )

    assert packages.items == ("sniffio==1.3.1",)
    assert counts == {"declared": 1, "needs_review": 0, "missing_metadata": 0}


@pytest.mark.parametrize(
    "mutation",
    ["missing_hashes", "changed_hash", "foreign_name", "wrong_version", "foreign_field"],
)
def test_authoritative_reconciliation_rejects_forged_normalized_sniffio_evidence(
    tmp_path: Path,
    mutation: str,
) -> None:
    record = _sniffio_normalized_license_record()
    if mutation == "missing_hashes":
        record.pop("license_evidence_sha256")
    elif mutation == "changed_hash":
        cast(dict[str, str], record["license_evidence_sha256"])["LICENSE"] = "0" * 64
    elif mutation == "foreign_name":
        record["name"] = "sniffio-fork"
    elif mutation == "wrong_version":
        record["version"] = "1.3.2"
    else:
        record["foreign_evidence"] = "forged"

    with pytest.raises(ValueError):
        PACKAGES_FROM_LICENSES(_write_license_inventory(tmp_path, record))


def test_standardized_license_conflict_fails_closed() -> None:
    with pytest.raises(ValueError, match="conflict"):
        LICENSE_METADATA_RESOLVER("MIT", "Apache-2.0", [])


def test_pip_audit_optional_arrays_are_strict(tmp_path: Path) -> None:
    valid_path = tmp_path / "valid.json"
    valid_path.write_text(
        '{"dependencies":[{"name":"example","version":"1.0"}]}',
        encoding="utf-8",
    )
    normalized = RAW_AUDIT_NORMALIZER(valid_path)
    assert normalized["dependencies"][0]["vulns"] == []
    assert normalized["fixes"] == []

    for field, value in (("vulns", "null"), ("vulns", "{}"), ("fixes", "null")):
        malformed_path = tmp_path / f"malformed-{field}-{len(value)}.json"
        if field == "vulns":
            payload = f'{{"dependencies":[{{"name":"x","version":"1","vulns":{value}}}]}}'
        else:
            payload = f'{{"dependencies":[{{"name":"x","version":"1"}}],"fixes":{value}}}'
        malformed_path.write_text(payload, encoding="utf-8")
        with pytest.raises(ValueError, match=field):
            RAW_AUDIT_NORMALIZER(malformed_path)


def _set_nested(record: dict[str, Any], path: tuple[str, ...], value: Any) -> None:
    target = record
    for part in path[:-1]:
        target = cast(dict[str, Any], target[part])
    target[path[-1]] = value


def test_exact_torch_osv_fallback_accepts_bound_empty_response(tmp_path: Path) -> None:
    response_path, acquisition_path = _write_osv_evidence(tmp_path)

    normalized = OSV_FALLBACK_VALIDATOR(response_path, acquisition_path, TORCH_BINDING)

    assert normalized["disposition"] == "audited_via_exact_public_version_fallback"
    assert normalized["osv_coordinate"] == {
        "ecosystem": "PyPI",
        "name": "torch",
        "version": "2.13.0",
    }
    assert normalized["installed_artifact"]["version"] == "2.13.0+cpu"
    assert normalized["vulnerability_count"] == 0
    assert normalized["attempt_count"] == 1
    assert normalized["retry_count"] == 0
    assert "does not establish PyPI wheel byte identity" in normalized["limitation"]


def test_exact_two_byte_empty_osv_object_is_a_bound_zero_result(tmp_path: Path) -> None:
    response_path, acquisition_path = _write_osv_evidence(tmp_path, response_bytes=b"{}")

    normalized = OSV_FALLBACK_VALIDATOR(response_path, acquisition_path, TORCH_BINDING)

    assert normalized["vulnerability_count"] == 0
    assert normalized["raw_response_byte_count"] == 2
    assert normalized["raw_response_sha256"] == (
        "44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a"
    )


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("installed_artifact", "name"), "torchvision"),
        (("installed_artifact", "version"), "2.13.0"),
        (("installed_artifact", "source_registry"), "https://pypi.org/simple"),
        (("installed_artifact", "wheel_url"), "https://example.test/torch.whl"),
        (("installed_artifact", "wheel_sha256"), "sha256:" + "0" * 64),
        (("osv_coordinate", "ecosystem"), "OSS-Fuzz"),
        (("osv_coordinate", "name"), "torchvision"),
        (("osv_coordinate", "version"), "2.13.0+cpu"),
        (("request_body_utf8",), "{}"),
        (("request_body_sha256",), "0" * 64),
        (("response_body_sha256",), "0" * 64),
        (("http_status",), 201),
        (("attempt_count",), 2),
        (("retry_count",), 1),
        (("service_url",), "https://api.osv.dev/v1/querybatch"),
        (("acquired_at_utc",), "2026-08-14T05:00:00.251Z"),
    ],
)
def test_torch_osv_fallback_rejects_any_acquisition_binding_drift(
    tmp_path: Path,
    path: tuple[str, ...],
    value: Any,
) -> None:
    response_path, acquisition_path = _write_osv_evidence(
        tmp_path,
        record_mutation=lambda record: _set_nested(record, path, value),
    )

    with pytest.raises(ValueError):
        OSV_FALLBACK_VALIDATOR(response_path, acquisition_path, TORCH_BINDING)


@pytest.mark.parametrize(
    "response_bytes",
    [
        b'{"vulns":null}',
        b'{"vulns":{}}',
        b'{"vulns":[],"vulns":[]}',
        b'{"nextPageToken":"page-2"}',
        b'{"vulns":[],"nextPageToken":""}',
        b'{"vulns":[],"nextPageToken":null}',
        b'{"vulns":[],"unknown":null}',
        b"[]",
        b'{"vulns":NaN}',
        b"not-json",
    ],
)
def test_torch_osv_fallback_rejects_malformed_or_ambiguous_response(
    tmp_path: Path,
    response_bytes: bytes,
) -> None:
    response_path, acquisition_path = _write_osv_evidence(tmp_path, response_bytes=response_bytes)

    with pytest.raises(ValueError):
        OSV_FALLBACK_VALIDATOR(response_path, acquisition_path, TORCH_BINDING)


def test_torch_osv_fallback_rejects_nonempty_vulnerabilities(tmp_path: Path) -> None:
    response_path, acquisition_path = _write_osv_evidence(
        tmp_path, response_bytes=b'{"vulns":[{"id":"OSV-TEST"}]}'
    )

    with pytest.raises(ValueError, match="one or more vulnerabilities"):
        OSV_FALLBACK_VALIDATOR(response_path, acquisition_path, TORCH_BINDING)


def _write_synthetic_pip_audit(
    tmp_path: Path,
    records: list[dict[str, Any]],
) -> Path:
    path = tmp_path / "vulnerability-audit.json"
    path.write_text(
        json.dumps(
            {
                "audit_status": "completed",
                "vulnerability_service": "pypi",
                "skipped_package_count": sum("skip_reason" in item for item in records),
                "vulnerability_count": sum(len(item["vulns"]) for item in records),
                "dependencies": records,
                "fixes": [],
            }
        ),
        encoding="utf-8",
    )
    return path


def _active_pip_records() -> tuple[Any, Any, Any, dict[str, str], list[dict[str, Any]]]:
    lock, active, inactive, binding = PACKAGE_SETS_FROM_LOCK(Path("uv.lock"))
    records = [
        {"name": identity.split("==", 1)[0], "version": identity.split("==", 1)[1], "vulns": []}
        for identity in active.items
        if identity != "torch==2.13.0+cpu"
    ]
    records.append(
        {
            "name": "torch",
            "skip_reason": (
                "Dependency not found on PyPI and could not be audited: torch (2.13.0+cpu)"
            ),
            "vulns": [],
        }
    )
    return lock, active, inactive, binding, records


def test_audit_reconciliation_accounts_for_exact_105_plus_1_plus_1(
    tmp_path: Path,
) -> None:
    lock, active, inactive, binding, records = _active_pip_records()
    audit_path = _write_synthetic_pip_audit(tmp_path, records)
    response_path, acquisition_path = _write_osv_evidence(tmp_path)

    audit, vulnerability_count, skipped_count, dispositions, fallback = PACKAGES_FROM_AUDIT(
        audit_path, "Audit", response_path, acquisition_path, binding
    )
    finalized, counts = FINALIZE_ADVISORY_DISPOSITIONS(
        lock, active, inactive, dispositions, fallback
    )

    assert audit is not None and audit.items == active.items
    assert vulnerability_count == 0
    assert skipped_count == 0
    assert counts == {
        "pip_audit_pass": 105,
        "audited_via_exact_public_version_fallback": 1,
        "marker_inactive_target_not_executable": 1,
    }
    assert len(finalized) == 107
    assert {
        (item["version"], item["disposition"]) for item in finalized if item["name"] == "torch"
    } == {
        ("2.13.0+cpu", "audited_via_exact_public_version_fallback"),
        ("2.13.0", "marker_inactive_target_not_executable"),
    }


def test_audit_reconciliation_without_fallback_accounts_for_exact_106_plus_1(
    tmp_path: Path,
) -> None:
    lock, active, inactive, binding = PACKAGE_SETS_FROM_LOCK(Path("uv.lock"))
    records = [
        {"name": identity.split("==", 1)[0], "version": identity.split("==", 1)[1], "vulns": []}
        for identity in active.items
    ]
    audit_path = _write_synthetic_pip_audit(tmp_path, records)

    audit, vulnerability_count, skipped_count, dispositions, fallback = PACKAGES_FROM_AUDIT(
        audit_path,
        "Audit",
        tmp_path / "unused-osv-response.json",
        tmp_path / "unused-osv-acquisition.json",
        binding,
    )
    finalized, counts = FINALIZE_ADVISORY_DISPOSITIONS(
        lock, active, inactive, dispositions, fallback
    )

    assert audit is not None and audit.items == active.items
    assert vulnerability_count == 0
    assert skipped_count == 0
    assert fallback is None
    assert counts == {
        "pip_audit_pass": 106,
        "marker_inactive_target_not_executable": 1,
    }
    assert len(finalized) == 107


@pytest.mark.parametrize("second_skip_name", ["torch", "alembic"])
def test_torch_osv_fallback_rejects_a_second_or_non_torch_skip(
    tmp_path: Path,
    second_skip_name: str,
) -> None:
    _, _, _, binding, records = _active_pip_records()
    if second_skip_name == "torch":
        records.append(copy.deepcopy(records[-1]))
    else:
        records[0] = {
            "name": second_skip_name,
            "skip_reason": "not audited",
            "vulns": [],
        }
    audit_path = _write_synthetic_pip_audit(tmp_path, records)
    response_path, acquisition_path = _write_osv_evidence(tmp_path)

    with pytest.raises(ValueError, match="sole exact torch"):
        PACKAGES_FROM_AUDIT(audit_path, "Audit", response_path, acquisition_path, binding)


def test_non_torch_pip_identity_remains_authoritative(tmp_path: Path) -> None:
    lock, active, inactive, binding, records = _active_pip_records()
    records[0]["version"] = "999"
    audit_path = _write_synthetic_pip_audit(tmp_path, records)
    response_path, acquisition_path = _write_osv_evidence(tmp_path)

    _, _, _, dispositions, fallback = PACKAGES_FROM_AUDIT(
        audit_path, "Audit", response_path, acquisition_path, binding
    )
    with pytest.raises(ValueError, match="exactly account"):
        FINALIZE_ADVISORY_DISPOSITIONS(lock, active, inactive, dispositions, fallback)


def test_osv_fallback_has_no_network_call_or_retry_loop() -> None:
    source = Path("scripts/dependency-audit.ps1").read_text(encoding="utf-8")

    assert "Invoke-WebRequest" not in source
    assert "Invoke-RestMethod" not in source
    assert "api.osv.dev/v1/query" in source
    assert 'acquisition["attempt_count"] != 1' in source
    assert 'acquisition["retry_count"] != 0' in source
    preserved_branch = source.index(
        "if ($usingPreservedAuditEvidence) {", source.index("$advisoryStatus")
    )
    pip_invocation = source.index('"run", "--locked", "--no-sync", "pip-audit"', preserved_branch)
    assert preserved_branch < pip_invocation


class _FakeSocket:
    def __init__(self) -> None:
        self.timeout: int | None = None

    def settimeout(self, timeout: int) -> None:
        self.timeout = timeout


class _FakeHttpResponse:
    def __init__(self, status: int, body: bytes) -> None:
        self.status = status
        self._body = body

    def read(self, maximum_bytes: int) -> bytes:
        return self._body[:maximum_bytes]


class _FakeHttpsConnection:
    def __init__(self, status: int = 200, body: bytes = b"{}") -> None:
        self.status = status
        self.body = body
        self.sock = _FakeSocket()
        self.connect_count = 0
        self.close_count = 0
        self.requests: list[tuple[str, str, bytes, dict[str, str]]] = []

    def connect(self) -> None:
        self.connect_count += 1

    def request(
        self,
        method: str,
        path: str,
        *,
        body: bytes,
        headers: dict[str, str],
    ) -> None:
        self.requests.append((method, path, body, headers))

    def getresponse(self) -> _FakeHttpResponse:
        return _FakeHttpResponse(self.status, self.body)

    def close(self) -> None:
        self.close_count += 1


def _ci_runner_with_raw_audit(
    raw_payload: object,
    commands: list[list[str]],
) -> Callable[..., SimpleNamespace]:
    def runner(command: list[str], **_: object) -> SimpleNamespace:
        commands.append(command)
        if "export" in command:
            output_path = Path(command[command.index("--output-file") + 1])
            output_path.write_text("example==1 --hash=sha256:" + "0" * 64, encoding="utf-8")
        if "pip-audit" in command:
            output_path = Path(command[command.index("--output") + 1])
            output_path.write_text(json.dumps(raw_payload), encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    return runner


def _clock_pair() -> Callable[[], datetime]:
    moments = iter(
        [
            datetime(2026, 8, 14, 5, 0, 0, tzinfo=UTC),
            datetime(2026, 8, 14, 5, 0, 0, tzinfo=UTC) + timedelta(milliseconds=250),
        ]
    )
    return lambda: next(moments)


def test_hosted_ci_runs_one_exact_pip_audit_and_one_exact_osv_post(tmp_path: Path) -> None:
    commands: list[list[str]] = []
    connection = _FakeHttpsConnection()
    raw_payload = {
        "dependencies": [
            {"name": "example", "version": "1", "vulns": []},
            {"name": "torch", "skip_reason": _active_pip_records()[-1][-1]["skip_reason"]},
        ],
        "fixes": [],
    }

    normalized_path, response_path, acquisition_path = CI_RUN_PREFLIGHT(
        Path.cwd(),
        tmp_path,
        runner=_ci_runner_with_raw_audit(raw_payload, commands),
        torch_validator=lambda _: None,
        connection_factory=lambda *args, **kwargs: connection,
        clock=_clock_pair(),
    )

    assert sum("pip-audit" in command for command in commands) == 1
    assert connection.connect_count == 1
    assert connection.close_count == 1
    assert connection.sock.timeout == 30
    assert len(connection.requests) == 1
    method, path, body, headers = connection.requests[0]
    assert (method, path, body) == ("POST", "/v1/query", OSV_REQUEST_BODY.encode())
    assert headers["Content-Type"] == "application/json"
    assert headers["Content-Length"] == "66"
    assert normalized_path.is_file()
    assert response_path.read_bytes() == b"{}"
    validated = OSV_FALLBACK_VALIDATOR(response_path, acquisition_path, TORCH_BINDING)
    assert validated["disposition"] == "audited_via_exact_public_version_fallback"


def test_hosted_ci_preflight_proves_current_installed_cpu_torch_binding() -> None:
    CI_VALIDATE_INSTALLED_TORCH(Path.cwd())


@pytest.mark.parametrize(
    "raw_payload",
    [
        [],
        {
            "dependencies": [
                {"name": "example", "version": "1", "vulns": [{"id": "TEST-1"}]},
                {"name": "torch", "skip_reason": _active_pip_records()[-1][-1]["skip_reason"]},
            ],
            "fixes": [],
        },
        {
            "dependencies": [
                {"name": "example", "version": "1", "vulns": []},
                {"name": "other", "skip_reason": "not audited"},
            ],
            "fixes": [],
        },
        {
            "dependencies": [
                {"name": "example", "vulns": []},
                {"name": "torch", "skip_reason": _active_pip_records()[-1][-1]["skip_reason"]},
            ],
            "fixes": [],
        },
    ],
)
def test_hosted_ci_rejects_bad_pip_evidence_before_osv(tmp_path: Path, raw_payload: object) -> None:
    commands: list[list[str]] = []
    connection_attempts = 0

    def forbidden_connection(*_: object, **__: object) -> None:
        nonlocal connection_attempts
        connection_attempts += 1
        raise AssertionError("OSV must not be contacted")

    with pytest.raises(ValueError):
        CI_RUN_PREFLIGHT(
            Path.cwd(),
            tmp_path,
            runner=_ci_runner_with_raw_audit(raw_payload, commands),
            torch_validator=lambda _: None,
            connection_factory=forbidden_connection,
            clock=_clock_pair(),
        )

    assert sum("pip-audit" in command for command in commands) == 1
    assert connection_attempts == 0
    assert (tmp_path / "pip-audit.raw.json").is_file()
    assert not (tmp_path / "osv-torch-response.raw.json").exists()


@pytest.mark.parametrize(
    ("status", "body"),
    [
        (302, b"{}"),
        (200, b"not-json"),
        (200, b'{"vulns":[{"id":"OSV-TEST"}]}'),
        (200, b'{"vulns":[],"nextPageToken":"more"}'),
    ],
)
def test_hosted_ci_osv_call_is_nonredirecting_and_fail_closed(
    tmp_path: Path, status: int, body: bytes
) -> None:
    response_path = tmp_path / "response.json"
    acquisition_path = tmp_path / "acquisition.json"
    connection = _FakeHttpsConnection(status=status, body=body)

    with pytest.raises(ValueError):
        CI_ACQUIRE_OSV(
            response_path,
            acquisition_path,
            connection_factory=lambda *args, **kwargs: connection,
            clock=_clock_pair(),
        )

    assert len(connection.requests) == 1
    assert connection.close_count == 1
    assert response_path.read_bytes() == body
    assert not acquisition_path.exists()


def test_dependency_workflow_binds_exact_fallback_for_pr_and_post_merge() -> None:
    workflow = Path(".github/workflows/dependency-audit.yml").read_text(encoding="utf-8")
    source = textwrap.dedent(
        workflow.partition("$preflightSource = @'\n")[2].partition("\n          '@\n")[0]
    )

    assert "pull_request:" in workflow
    assert 'branches: ["main"]' in workflow
    assert workflow.count("Acquire advisory evidence and audit the dependency graph") == 1
    assert "github.event_name == 'pull_request' && github.head_ref || github.ref_name" in workflow
    assert (
        "github.event_name == 'pull_request' && github.event.pull_request.head.sha || github.sha"
        in workflow
    )
    for parameter in (
        "-PreservedAuditEvidencePath",
        "-PreservedOsvResponsePath",
        "-OsvAcquisitionRecordPath",
    ):
        assert workflow.count(parameter) == 1
    assert source.count('"pip-audit",') == 1
    assert source.count("connection.request(") == 1
    assert "urllib" not in source
    assert "retry" not in source.casefold().replace('"retry_count": 0', "")
    assert CI_ADVISORY_PREFLIGHT["OSV_URL"] == "https://api.osv.dev/v1/query"
    assert CI_ADVISORY_PREFLIGHT["OSV_REQUEST_BODY"] == OSV_REQUEST_BODY.encode()
    assert len(cast(bytes, CI_ADVISORY_PREFLIGHT["OSV_REQUEST_BODY"])) == 66
    assert hashlib.sha256(cast(bytes, CI_ADVISORY_PREFLIGHT["OSV_REQUEST_BODY"])).hexdigest() == (
        "e0374b4e37becf07c6c0857fc16bec5438b256470f1bc77230155a0f9bf480a2"
    )
    assert CI_ADVISORY_PREFLIGHT["TORCH_ARTIFACT"] == {
        "name": "torch",
        "version": "2.13.0+cpu",
        "source_registry": "https://download.pytorch.org/whl/cpu",
        "wheel_url": TORCH_BINDING["wheel_url"],
        "wheel_sha256": TORCH_BINDING["wheel_sha256"],
    }


def test_unapproved_spdx_identifier_fails_closed() -> None:
    with pytest.raises(ValueError, match="outside the approved SPDX-expression grammar"):
        LICENSE_VALIDATOR("GPL-3.0-only")


def test_unapproved_spdx_identifier_in_and_expression_fails_closed() -> None:
    with pytest.raises(ValueError, match="outside the approved SPDX-expression grammar"):
        LICENSE_VALIDATOR("MIT AND GPL-3.0-only")


@pytest.mark.parametrize(
    "expression",
    [
        "",
        " MIT",
        "MIT ",
        "MIT AND",
        "MIT BSD-3-Clause",
        "MIT and BSD-3-Clause",
        "MIT OR OR BSD-3-Clause",
        "(MIT)",
    ],
)
def test_malformed_spdx_expressions_fail_closed(expression: str) -> None:
    with pytest.raises(ValueError):
        LICENSE_VALIDATOR(expression)


@pytest.mark.parametrize(
    "expression",
    [
        "BSD-*",
        "BSD",
        "BSD-3-Clause-extra",
        "MITLicense",
        "numpy",
        "OSI Approved",
        "permissive",
        "License :: OSI Approved :: BSD License",
    ],
)
def test_spdx_allowlist_has_no_generic_or_partial_match_bypass(expression: str) -> None:
    with pytest.raises(ValueError):
        LICENSE_VALIDATOR(expression)


POWERSHELL_ENTRYPOINTS = (
    "bootstrap.ps1",
    "dependency-audit.ps1",
    "quality.ps1",
    "smoke-compose.ps1",
    "test-infrastructure-contract.ps1",
    "test.ps1",
    "validate-compose.ps1",
    "validate-environment.ps1",
)


def test_every_powershell_entrypoint_runs_the_shared_runtime_preflight_first() -> None:
    preflight_call = '. (Join-Path $PSScriptRoot "assert-pwsh-runtime.ps1") -Quiet'

    for name in POWERSHELL_ENTRYPOINTS:
        source = Path("scripts", name).read_text(encoding="utf-8")
        preflight_index = source.index(preflight_call)
        error_preference_index = source.index('$ErrorActionPreference = "Stop"')
        assert preflight_index > error_preference_index
        assert preflight_index < source.index("$repositoryRoot", preflight_index)


def test_powershell_runtime_contract_is_exact_and_executable() -> None:
    preflight = Path("scripts/assert-pwsh-runtime.ps1").read_text(encoding="utf-8")
    harness = Path("scripts/test-infrastructure-contract.ps1").read_text(encoding="utf-8")

    assert "[System.Management.Automation.SemanticVersion]$Version" in preflight
    assert "$actualVersion = $PSVersionTable.PSVersion" in preflight
    assert "[version]$PSVersionTable.PSVersion" not in preflight
    assert "$Version.PreReleaseLabel" in preflight
    assert "$Version.Major -ne 7" in preflight
    assert "$Version.Minor -ne 6" in preflight
    assert "$Version.Patch -lt 4" in preflight
    assert '$Edition -cne "Core"' in preflight
    assert '$executableName -ine "pwsh"' in preflight
    assert '$executableName -ine "pwsh.exe"' in preflight
    assert "[Environment]::ProcessPath" in preflight
    assert "RuntimePreflightOnly" in harness
    assert "runtime-core-7.6.4-lower-bound" in harness
    assert "runtime-core-7.6.5-stable" in harness
    assert "runtime-rejects-preview-release" in harness
    assert "runtime-rejects-release-candidate" in harness
    assert "runtime-rejects-windows-powershell-edition" in harness
    assert "runtime-rejects-version-before-7.6.4" in harness
    assert "runtime-rejects-version-7.7.0" in harness
    assert "runtime-rejects-unsupported-executable" in harness


def test_active_repository_commands_use_only_pwsh() -> None:
    makefile = Path("Makefile").read_text(encoding="utf-8")
    readme = Path("README.md").read_text(encoding="utf-8")
    workflows = "\n".join(
        path.read_text(encoding="utf-8") for path in sorted(Path(".github/workflows").glob("*.yml"))
    )
    setup = Path("scripts/setup-pwsh-ci.sh").read_text(encoding="utf-8")

    assert "powershell.exe" not in makefile.casefold()
    assert "shell: powershell" not in workflows.casefold()
    assert "powershell.exe" not in workflows.casefold()
    assert "powershell.exe" not in setup.casefold()
    assert "pwsh -NoLogo -NoProfile -File" in makefile
    assert "pwsh -NoLogo -NoProfile -File" in readme
    assert readme.count("`powershell.exe`") == 1
    assert "Windows PowerShell 5.1" in " ".join(readme.split())

    script_mentions: dict[str, list[str]] = {}
    for path in sorted(Path("scripts").glob("*.ps1")):
        mentions = [
            line.strip()
            for line in path.read_text(encoding="utf-8").splitlines()
            if "powershell.exe" in line.casefold()
        ]
        if mentions:
            script_mentions[path.name] = mentions
    assert script_mentions == {
        "test-infrastructure-contract.ps1": [
            '-ExecutablePath "powershell.exe"',
            '-ExecutablePath "powershell.exe"',
        ]
    }


def test_ci_installs_and_checks_the_frozen_official_powershell_assets() -> None:
    quality = Path(".github/workflows/quality.yml").read_text(encoding="utf-8")
    dependency = Path(".github/workflows/dependency-audit.yml").read_text(encoding="utf-8")
    setup = Path("scripts/setup-pwsh-ci.sh").read_text(encoding="utf-8")

    assert quality.count("./scripts/setup-pwsh-ci.sh") == 2
    assert dependency.count("./scripts/setup-pwsh-ci.sh") == 1
    assert quality.count("shell: pwsh") == 6
    assert dependency.count("shell: pwsh") == 2
    assert quality.count("./scripts/assert-pwsh-runtime.ps1 -Quiet") == 6
    assert dependency.count("./scripts/assert-pwsh-runtime.ps1 -Quiet") == 2
    assert 'POWERSHELL_VERSION="7.6.4"' in setup
    assert "powershell-7.6.4-linux-x64.tar.gz" in setup
    assert "PowerShell-7.6.4-win-x64.zip" in setup
    assert "4471b5a36bfe86ec7af8525d36bb1cacba0128e7aac22d05cc064bc00e604721" in setup
    assert "80832551c52809301e6071c8bac977beb5a2f1ec953eb4db9f94deb953333793" in setup
    assert "sha256sum --check --strict" in setup
    assert "/c/Windows/System32/tar.exe" in setup
    assert '"${pwsh_path}" -NoLogo -NoProfile -File ./scripts/assert-pwsh-runtime.ps1' in setup
