"""Import and dependency-boundary checks for source-neutral domain contracts."""

from __future__ import annotations

import ast
import sys
import tomllib
from pathlib import Path

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
    lock_text = Path("uv.lock").read_text(encoding="utf-8").casefold()
    assert 'name = "uvicorn"' not in lock_text
    assert not any(item.startswith("fastapi[") for item in project["project"]["dependencies"])
