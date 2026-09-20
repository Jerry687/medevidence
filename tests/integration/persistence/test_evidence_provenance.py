"""Disposable PostgreSQL anchor for a real synthetic SnapshotStore envelope."""

from __future__ import annotations

import os
from pathlib import Path
from typing import cast

import pytest
from alembic import command
from alembic.config import Config
from tests.unit.infrastructure.test_evidence_provenance import _case

from medevidence.domain.provenance import EvidenceProvenanceEnvelopeV1
from medevidence.infrastructure.evidence_provenance import VerifiedEvidenceProvenanceStore
from medevidence.persistence import PersistenceConflict, PersistenceRepository, PersistenceSettings
from medevidence.persistence.config import DATABASE_URL_ENV


def test_insert_or_verify_and_read_exact_provenance_anchor(tmp_path: Path) -> None:
    if not os.environ.get(DATABASE_URL_ENV):
        pytest.skip(f"{DATABASE_URL_ENV} is required")
    command.upgrade(Config("alembic.ini"), "head")
    reader, source_metadata, proof, snapshots = _case(tmp_path)
    # The unit fixture published actual verified manifest/raw/normalized files;
    # this PG test exercises only the independent immutable anchor transaction.
    envelope = reader.publish_pubmed(proof)
    repository = PersistenceRepository(PersistenceSettings.from_env())
    try:
        saved = repository.insert_or_verify_evidence_provenance(envelope)
        assert repository.insert_or_verify_evidence_provenance(envelope) == saved
        loaded = repository.get_evidence_provenance_anchor(
            run_id=envelope.run_id, evidence_id=envelope.evidence_id
        )
        assert loaded is not None
        assert loaded["envelope_id"] == envelope.envelope_id
        assert loaded["envelope_hash"] == envelope.envelope_hash
        assert loaded["source"] == "pubmed"

        class PgAnchoredSourceMetadata:
            def get_snapshot(self, snapshot_id: str):
                return source_metadata.get_snapshot(snapshot_id)

            def get_evidence_provenance_anchor(self, *, run_id: str, evidence_id: str):
                return repository.get_evidence_provenance_anchor(
                    run_id=run_id, evidence_id=evidence_id
                )

        pg_reader = VerifiedEvidenceProvenanceStore(
            snapshots=snapshots,
            repository=cast(PersistenceRepository, cast(object, PgAnchoredSourceMetadata())),
        )
        verified = pg_reader.load_verified_provenance(
            run_id=envelope.run_id,
            evidence_id=envelope.evidence_id,
            source=envelope.source,
            source_record_id=envelope.source_record_id,
            source_version=envelope.source_version,
            snapshot_id=envelope.snapshot_id,
            content_hash=envelope.content_hash,
        )
        assert verified is not None and verified.lookup_key == envelope.lookup_key
        altered = EvidenceProvenanceEnvelopeV1.create(
            **{
                **envelope.model_dump(mode="python", exclude={"envelope_id", "envelope_hash"}),
                "lookup_key": "pmid:foreign",
            }
        )
        with pytest.raises(PersistenceConflict):
            repository.insert_or_verify_evidence_provenance(altered)
        with pytest.raises(ValueError):
            repository.get_evidence_provenance_anchor(
                run_id="../foreign", evidence_id=envelope.evidence_id
            )
    finally:
        repository.close()
