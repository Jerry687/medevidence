"""Import and dependency-boundary checks for source-neutral domain contracts."""

from __future__ import annotations

import ast
import sys
import tomllib
from collections.abc import Callable
from pathlib import Path
from typing import cast

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


def _load_dependency_license_validator() -> Callable[[object], str | None]:
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
    return cast(Callable[[object], str | None], namespace["validate_license_expression"])


LICENSE_VALIDATOR = _load_dependency_license_validator()


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
    ]
    assert not any(
        dependency.casefold().startswith(("numpy", "scikit-learn"))
        for dependency in project["project"]["dependencies"]
    )
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
    assert '["numpy==2.5.1", "scikit-learn==1.9.0"]' in dependency_audit
    assert '"retrieval": sorted(retrieval' in dependency_audit
    assert '"export", "--locked", "--all-groups"' in dependency_audit


def test_numpy_2_5_1_spdx_expression_is_accepted_exactly() -> None:
    expression = "BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0"

    assert LICENSE_VALIDATOR(expression) == expression


@pytest.mark.parametrize("expression", ["0BSD", "Zlib", "CC0-1.0"])
def test_newly_approved_spdx_identifiers_are_accepted_exactly(expression: str) -> None:
    assert LICENSE_VALIDATOR(expression) == expression


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
