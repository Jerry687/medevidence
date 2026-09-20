"""Typed application boundary for source-verified PubMed material selections."""

from __future__ import annotations

from typing import Protocol

from medevidence.domain import PublicationRecord, ResearchScope

from .contracts import ResolvedConceptCatalog
from .ports import PersistedPublicationBinding
from .pubmed_material import PubMedMaterialSelection


class VerifiedPubMedMaterialPort(Protocol):
    """Persist and rederive one exact fetched publication's included or excluded material."""

    def materialize(
        self,
        *,
        run_id: str,
        scope: ResearchScope,
        catalog: ResolvedConceptCatalog,
        publication: PublicationRecord,
        binding: PersistedPublicationBinding,
    ) -> PubMedMaterialSelection: ...

    def load_verified_selection(
        self,
        *,
        run_id: str,
        scope: ResearchScope,
        catalog: ResolvedConceptCatalog,
        publication_version_id: str,
        snapshot_id: str,
    ) -> PubMedMaterialSelection | None: ...
