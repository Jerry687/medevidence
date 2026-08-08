"""Immutable, integrity-checked M1A production concept catalog."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
from types import MappingProxyType
from typing import Final, cast

from pydantic import BaseModel, ConfigDict

from medevidence.domain import AdverseEventConcept, DrugConcept, ResearchScope
from medevidence.tools import ResolvedConceptCatalog

CATALOG_BYTES: Final = (
    b'{"adverse_events":[{"concept_id":"m1a.event.gastrointestinal","preferred_term"'
    b':"gastrointestinal"},{"concept_id":"synthetic.event.beta","preferred_term":"test '
    b'event beta"}],"catalog_version":"m1a-concepts-v1","drugs":[{"concept_id":"m1a.'
    b'drug.semaglutide","preferred_term":"semaglutide"},{"concept_id":"m1a.drug.'
    b'tirzepatide","preferred_term":"tirzepatide"},{"concept_id":"synthetic.drug.alpha"'
    b',"preferred_term":"test compound alpha"}],"schema_version":"1.0"}\n'
)
CATALOG_BYTE_COUNT: Final = 458
CATALOG_SHA256: Final = "eaffc3ee01ecd46a134578838b0304474642bf5e4a0c6e87302825d52be7682e"
CATALOG_CONTENT_HASH: Final = f"sha256:{CATALOG_SHA256}"


class _CatalogConcept(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    concept_id: str
    preferred_term: str


class _CatalogDocument(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: str
    catalog_version: str
    drugs: tuple[_CatalogConcept, ...]
    adverse_events: tuple[_CatalogConcept, ...]


@dataclass(frozen=True, slots=True)
class ProductionCatalog:
    """Verified catalog with exact case-sensitive concept lookup."""

    drugs: Mapping[str, DrugConcept]
    adverse_events: Mapping[str, AdverseEventConcept]

    def resolve_scope(self, scope: ResearchScope) -> ResolvedConceptCatalog:
        """Resolve one already validated scope without aliases or fallback terms."""

        try:
            drugs = tuple(self.drugs[item.concept_id] for item in scope.drugs)
            events = tuple(self.adverse_events[item.concept_id] for item in scope.adverse_reactions)
        except KeyError as error:
            raise ValueError("scope contains an unknown production catalog concept") from error
        if drugs != scope.drugs or events != scope.adverse_reactions:
            raise ValueError("scope concepts differ from the production catalog")
        return ResolvedConceptCatalog(
            catalog_content_hash=CATALOG_CONTENT_HASH,
            drugs=drugs,
            adverse_reactions=events,
        )


def load_production_catalog() -> ProductionCatalog:
    """Verify the frozen bytes and return strict immutable catalog contracts."""

    if len(CATALOG_BYTES) != CATALOG_BYTE_COUNT:
        raise RuntimeError("production catalog byte count failed integrity validation")
    if sha256(CATALOG_BYTES).hexdigest() != CATALOG_SHA256:
        raise RuntimeError("production catalog digest failed integrity validation")
    document = _CatalogDocument.model_validate_json(CATALOG_BYTES, strict=True)
    if document.schema_version != "1.0" or document.catalog_version != "m1a-concepts-v1":
        raise RuntimeError("production catalog identity is invalid")
    drug_map = {
        item.concept_id: DrugConcept(
            concept_id=item.concept_id,
            preferred_term=item.preferred_term,
        )
        for item in document.drugs
    }
    event_map = {
        item.concept_id: AdverseEventConcept(
            concept_id=item.concept_id,
            preferred_term=item.preferred_term,
        )
        for item in document.adverse_events
    }
    if tuple(drug_map) != tuple(sorted(drug_map)) or tuple(event_map) != tuple(sorted(event_map)):
        raise RuntimeError("production catalog concepts are not canonical")
    return ProductionCatalog(
        drugs=cast(Mapping[str, DrugConcept], MappingProxyType(drug_map)),
        adverse_events=cast(
            Mapping[str, AdverseEventConcept],
            MappingProxyType(event_map),
        ),
    )


__all__ = [
    "CATALOG_BYTES",
    "CATALOG_BYTE_COUNT",
    "CATALOG_CONTENT_HASH",
    "CATALOG_SHA256",
    "ProductionCatalog",
    "load_production_catalog",
]
