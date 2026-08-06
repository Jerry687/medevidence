"""Import and dependency-boundary checks for source-neutral domain contracts."""

from __future__ import annotations

import ast
import sys
import tomllib
from pathlib import Path

import pytest

DOMAIN_ROOT = Path("src/medevidence/domain")
CONNECTOR_ROOT = Path("src/medevidence/connectors")
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
        "defusedxml==0.7.1",
        "httpx==0.28.1",
        "pydantic==2.13.4",
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
