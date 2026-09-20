"""Closed research-job schema and deterministic allocated identities."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable
from tests.unit.orchestration.test_workflow import _scope

from medevidence.persistence.research_jobs import allocated_ids, m3_research_jobs

KEY = "sha256:" + "a" * 64


def test_job_identities_are_stable_and_bounded() -> None:
    first = allocated_ids(KEY)
    assert first == allocated_ids(KEY)
    assert first["run_id"].startswith("run:")
    assert first["report_id"].startswith("report:sha256:")
    assert first["checkpoint_id"].startswith("checkpoint:sha256:")
    assert first["destination_id"].startswith("destination:sha256:")
    assert all(len(value) <= 96 for value in first.values())
    with pytest.raises(ValueError):
        allocated_ids("sha256:foreign")


def test_job_migration_frozen_after_evidence_provenance_head() -> None:
    path = Path("alembic/versions/20260914_04_m3_research_jobs.py")
    spec = importlib.util.spec_from_file_location("m3researchjob_revision", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.revision == "m3researchjob001"
    assert module.down_revision == "m3evidenceprov001"
    assert module.TABLE_ORDER == ("m3_research_jobs",)
    assert module._statements(module._UPGRADE_B85, module._UPGRADE_SHA256) == (
        str(CreateTable(m3_research_jobs).compile(dialect=postgresql.dialect())),
    )
    assert module._statements(module._DOWNGRADE_B85, module._DOWNGRADE_SHA256) == (
        "DROP TABLE medevidence.m3_research_jobs",
    )


def test_scope_fixture_has_no_patient_content_and_job_metadata_is_separate() -> None:
    scope = _scope()
    assert scope.scope_id.startswith("scope:sha256:")
    assert m3_research_jobs.c.scope_payload.type.__class__.__name__ == "JSONB"
    assert m3_research_jobs.c.scope_payload.nullable is False
