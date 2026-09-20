from __future__ import annotations

import importlib.util
from pathlib import Path

import sqlalchemy as sa

from medevidence.persistence import models


def test_running_m1b_run_is_explicit_and_requires_null_completion() -> None:
    check = next(
        item
        for item in models.m1b_runs.constraints
        if isinstance(item, sa.CheckConstraint) and item.name == "ck_m1b_runs_status"
    )
    assert str(check.sqltext) == (
        "status IN ('running','completed','degraded','failed') AND "
        "(status<>'running' OR completed_at_utc IS NULL)"
    )


def test_source_lifecycle_migration_is_chained_after_local_catalog() -> None:
    path = (
        Path(__file__).resolve().parents[3]
        / "alembic"
        / "versions"
        / "20260915_03_m1b_source_lifecycle.py"
    )
    spec = importlib.util.spec_from_file_location("m1b_source_lifecycle_migration", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.revision == "m3sourcelifecycle001"
    assert module.down_revision == "m3localcatalog001"
    assert "'running'" in module._UPGRADE_SQL
