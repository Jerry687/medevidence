"""Selected PostgreSQL tests for immutable DM002 DailyMed metadata."""

from __future__ import annotations

import os
from datetime import UTC, date, datetime
from uuid import UUID

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config

from medevidence.domain import DailyMedLabelVersion, DailyMedMarketingState, LabelSection
from medevidence.persistence import PersistenceConflict, PersistenceRepository, PersistenceSettings
from medevidence.persistence.config import DATABASE_URL_ENV
from medevidence.persistence.models import (
    m1b_artifacts,
    m1b_dailymed_label_supersession,
    m1b_dailymed_label_versions,
    m1b_dailymed_sections,
)

SETID = UUID("11111111-1111-1111-1111-111111111111")
HASH = "sha256:" + "a" * 64


def _url() -> str:
    value = os.environ.get(DATABASE_URL_ENV)
    if value is None:
        pytest.skip(f"{DATABASE_URL_ENV} is required for selected PostgreSQL tests")
    return value


def _artifact() -> dict[str, object]:
    return {
        "artifact_id": HASH,
        "artifact_kind": "dailymed_spl_xml",
        "source_partition": "dailymed",
        "content_hash": HASH,
        "byte_size": 128,
        "media_type": "application/xml",
        "relative_storage_label": f"dailymed/sha256/{'a' * 64}.xml",
        "schema_version": "m1b.dailymed.spl-artifact.v1",
        "created_at_utc": datetime(2026, 1, 1, tzinfo=UTC),
        "corpus_id": None,
        "corpus_version": None,
        "split": None,
    }


def _version(*, spl_version: int = 3) -> dict[str, object]:
    values = DailyMedLabelVersion.create(
        setid=str(SETID),
        spl_version=str(spl_version),
        marketing_state=DailyMedMarketingState.ACTIVE,
        effective_date=date(2026, 1, 1),
        published_date=date(2026, 1, 2),
        content_hash=HASH,
        spl_artifact_id=HASH,
    ).model_dump(mode="python")
    values["source"] = "dailymed"
    values["setid"] = SETID
    values["spl_version"] = spl_version
    values["marketing_state"] = "active"
    return values


VERSION_ID = _version()["label_version_id"]


def _section() -> dict[str, object]:
    values = LabelSection.create(
        setid=str(SETID),
        label_version_id=VERSION_ID,
        spl_version="3",
        section_ordinal=0,
        section_code="34084-4",
        title="FDA package insert Adverse reactions section",
        parent_section_id=None,
        xml_path="/document/component/structuredBody/component[1]/section",
        text_start=0,
        text_end=12,
        text_hash="sha256:" + "c" * 64,
        spl_artifact_id=HASH,
    ).model_dump(mode="python")
    values["source"] = "dailymed"
    values["setid"] = SETID
    values["spl_version"] = 3
    return values


def test_dailymed_version_insert_or_verify_and_conflict() -> None:
    url = _url()
    command.upgrade(Config("alembic.ini"), "head")
    repository = PersistenceRepository(PersistenceSettings(url))
    engine = sa.create_engine(url)
    try:
        artifact = repository.insert_or_verify_m1b_artifact(_artifact())
        version = repository.insert_or_verify_dailymed_label_version(_version())
        assert repository.insert_or_verify_m1b_artifact(_artifact()) == artifact
        assert repository.insert_or_verify_dailymed_label_version(_version()) == version

        drift = {**_version(), "marketing_state": "archived"}
        with pytest.raises(PersistenceConflict):
            repository.insert_or_verify_dailymed_label_version(drift)

        with engine.begin() as connection:
            stored = (
                connection.execute(
                    sa.select(m1b_dailymed_label_versions).where(
                        m1b_dailymed_label_versions.c.label_version_id == VERSION_ID
                    )
                )
                .mappings()
                .one()
            )
            assert stored["spl_version"] == 3
            connection.execute(
                m1b_dailymed_label_versions.delete().where(
                    m1b_dailymed_label_versions.c.label_version_id == VERSION_ID
                )
            )
            connection.execute(m1b_artifacts.delete().where(m1b_artifacts.c.artifact_id == HASH))
    finally:
        repository.close()
        engine.dispose()


def test_m1b_artifact_repository_rejects_zero_byte_structural_artifact() -> None:
    repository = PersistenceRepository(PersistenceSettings(_url()))
    try:
        with pytest.raises(ValueError, match="source-response"):
            repository.insert_or_verify_m1b_artifact({**_artifact(), "byte_size": 0})
    finally:
        repository.close()


def test_dailymed_repository_rejects_stable_identity_and_path_drift() -> None:
    repository = PersistenceRepository(PersistenceSettings(_url()))
    try:
        with pytest.raises(ValueError, match="artifact identity/path"):
            repository.insert_or_verify_m1b_artifact(
                {**_artifact(), "relative_storage_label": "dailymed/run/scoped.xml"}
            )
        with pytest.raises(ValueError, match="label_version_id"):
            repository.insert_or_verify_dailymed_label_version(
                {**_version(), "label_version_id": "dailymed-label-version:sha256:" + "f" * 64}
            )
        with pytest.raises(ValueError, match="section_id"):
            repository.insert_or_verify_dailymed_section(
                {**_section(), "section_id": "dailymed-label-section:sha256:" + "f" * 64}
            )
    finally:
        repository.close()


def test_dailymed_section_insert_or_verify_binds_exact_version() -> None:
    url = _url()
    command.upgrade(Config("alembic.ini"), "head")
    repository = PersistenceRepository(PersistenceSettings(url))
    engine = sa.create_engine(url)
    try:
        repository.insert_or_verify_m1b_artifact(_artifact())
        repository.insert_or_verify_dailymed_label_version(_version())
        section = repository.insert_or_verify_dailymed_section(_section())
        assert repository.insert_or_verify_dailymed_section(_section()) == section
        with engine.begin() as connection:
            connection.execute(
                m1b_dailymed_sections.delete().where(
                    m1b_dailymed_sections.c.label_version_id == VERSION_ID
                )
            )
            connection.execute(
                m1b_dailymed_label_versions.delete().where(
                    m1b_dailymed_label_versions.c.label_version_id == VERSION_ID
                )
            )
            connection.execute(m1b_artifacts.delete().where(m1b_artifacts.c.artifact_id == HASH))
    finally:
        repository.close()
        engine.dispose()


def test_dailymed_supersession_repository_rejects_long_cycle() -> None:
    url = _url()
    command.upgrade(Config("alembic.ini"), "head")
    repository = PersistenceRepository(PersistenceSettings(url))
    engine = sa.create_engine(url)
    versions = [_version(spl_version=spl_version) for spl_version in range(1, 4)]
    version_ids = [str(version["label_version_id"]) for version in versions]
    try:
        repository.insert_or_verify_m1b_artifact(_artifact())
        for version in versions:
            repository.insert_or_verify_dailymed_label_version(version)

        def edge(predecessor: str, successor: str) -> dict[str, object]:
            return {
                "source": "dailymed",
                "setid": SETID,
                "predecessor_label_version_id": predecessor,
                "successor_label_version_id": successor,
                "observed_run_id": None,
                "observed_acquisition_id": None,
                "observed_acquisition_ordinal": None,
                "observed_acquisition_intent_id": None,
                "observed_operation": None,
                "observed_query_id": None,
                "observed_snapshot_id": None,
                "observed_manifest_id": None,
                "schema_version": "m1b.dailymed.label-supersession.v1",
            }

        first = repository.insert_or_verify_dailymed_supersession(
            edge(version_ids[0], version_ids[1])
        )
        assert (
            repository.insert_or_verify_dailymed_supersession(edge(version_ids[0], version_ids[1]))
            == first
        )
        repository.insert_or_verify_dailymed_supersession(edge(version_ids[1], version_ids[2]))
        with pytest.raises(ValueError, match="create a cycle"):
            repository.insert_or_verify_dailymed_supersession(edge(version_ids[2], version_ids[0]))
    finally:
        with engine.begin() as connection:
            connection.execute(
                m1b_dailymed_label_supersession.delete().where(
                    m1b_dailymed_label_supersession.c.setid == SETID
                )
            )
            connection.execute(
                m1b_dailymed_label_versions.delete().where(
                    m1b_dailymed_label_versions.c.label_version_id.in_(version_ids)
                )
            )
            connection.execute(m1b_artifacts.delete().where(m1b_artifacts.c.artifact_id == HASH))
        repository.close()
        engine.dispose()
