"""Import and dependency-boundary checks for source-neutral domain contracts."""

from __future__ import annotations

import ast
import copy
import hashlib
import json
import sys
import tomllib
from collections.abc import Callable
from pathlib import Path
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


DEPENDENCY_HELPER = _load_dependency_helper()
LICENSE_VALIDATOR = cast(
    Callable[[object], str | None], DEPENDENCY_HELPER["validate_license_expression"]
)
LICENSE_METADATA_RESOLVER = cast(
    Callable[[object, object, object], tuple[str | None, tuple[str, ...]]],
    DEPENDENCY_HELPER["resolve_license_metadata"],
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
FINALIZE_ADVISORY_DISPOSITIONS = cast(
    Callable[
        [Any, Any, Any, list[dict[str, str]], dict[str, Any] | None],
        tuple[list[dict[str, str]], dict[str, int]],
    ],
    DEPENDENCY_HELPER["finalize_advisory_dispositions"],
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


def test_audit_reconciliation_accounts_for_exact_84_plus_1_plus_1(
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
        "pip_audit_pass": 84,
        "audited_via_exact_public_version_fallback": 1,
        "marker_inactive_target_not_executable": 1,
    }
    assert len(finalized) == 86
    assert {
        (item["version"], item["disposition"]) for item in finalized if item["name"] == "torch"
    } == {
        ("2.13.0+cpu", "audited_via_exact_public_version_fallback"),
        ("2.13.0", "marker_inactive_target_not_executable"),
    }


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
    assert dependency.count("shell: pwsh") == 3
    assert quality.count("./scripts/assert-pwsh-runtime.ps1 -Quiet") == 6
    assert dependency.count("./scripts/assert-pwsh-runtime.ps1 -Quiet") == 3
    assert 'POWERSHELL_VERSION="7.6.4"' in setup
    assert "powershell-7.6.4-linux-x64.tar.gz" in setup
    assert "PowerShell-7.6.4-win-x64.zip" in setup
    assert "4471b5a36bfe86ec7af8525d36bb1cacba0128e7aac22d05cc064bc00e604721" in setup
    assert "80832551c52809301e6071c8bac977beb5a2f1ec953eb4db9f94deb953333793" in setup
    assert "sha256sum --check --strict" in setup
    assert "/c/Windows/System32/tar.exe" in setup
    assert '"${pwsh_path}" -NoLogo -NoProfile -File ./scripts/assert-pwsh-runtime.ps1' in setup
