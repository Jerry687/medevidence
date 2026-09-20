"""A lossy schema downgrade stops before its first DDL operation."""

import importlib.util
from pathlib import Path
from unittest.mock import Mock

import pytest


@pytest.mark.parametrize("duplicate", (None, 1))
def test_downgrade_never_merges_outcome_occurrences(duplicate: int | None) -> None:
    path = Path("alembic/versions/20260920_01_m1b_source_outcome_occurrence.py")
    spec = importlib.util.spec_from_file_location("outcome_migration", path)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    operations = Mock()
    operations.get_bind.return_value.execute.return_value.scalar_one_or_none.return_value = (
        duplicate
    )
    migration.op = operations
    if duplicate is not None:
        with pytest.raises(RuntimeError, match="distinct occurrences"):
            migration.downgrade()
        operations.drop_constraint.assert_not_called()
        operations.create_primary_key.assert_not_called()
    else:
        migration.downgrade()
        operations.drop_constraint.assert_called_once()
        operations.create_primary_key.assert_called_once_with(
            "pk_m1b_source_outcomes",
            "m1b_source_outcomes",
            ("source_outcome_id",),
            schema="medevidence",
        )
