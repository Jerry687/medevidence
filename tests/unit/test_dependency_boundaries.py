"""Import and dependency-boundary checks for source-neutral domain contracts."""

from __future__ import annotations

import ast
import sys
import tomllib
from pathlib import Path

DOMAIN_ROOT = Path("src/medevidence/domain")
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


def test_only_owner_approved_direct_dependencies_are_present() -> None:
    project = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    assert project["project"]["dependencies"] == ["pydantic==2.13.4"]
    assert set(project["dependency-groups"]["dev"]) == {
        "coverage==7.15.2",
        "mypy==2.3.0",
        "pip-audit==2.10.1",
        "pytest==9.1.1",
        "pytest-cov==7.1.0",
        "pytest-socket==0.8.0",
        "ruff==0.15.22",
    }
