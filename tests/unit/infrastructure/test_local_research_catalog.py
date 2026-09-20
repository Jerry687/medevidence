"""Exact local/M1A catalog identity separation and pure scope resolution."""

from datetime import date

import pytest
from pydantic import ValidationError
from tests.unit.infrastructure.test_research_scope_safety import _scope

from medevidence.domain.catalogs import (
    LOCAL_RESEARCH_CATALOG_HASH,
    M1A_CATALOG_HASH,
    validate_catalog_identity,
)
from medevidence.infrastructure.local_research_catalog import LocalResearchCatalogAdapter
from medevidence.tools.contracts import ResolvedConceptCatalog


def test_new_scope_resolution_preserves_local_ids_and_named_identity() -> None:
    scope = _scope(drug="SEMAGLUTIDE", reaction="nausea")
    adapter = LocalResearchCatalogAdapter(scope, today=lambda: date(2026, 9, 15))
    resolved = adapter.resolve(scope.scope_id)
    assert resolved.catalog_version == "m3.local-research-input.v1"
    assert resolved.catalog_content_hash == LOCAL_RESEARCH_CATALOG_HASH
    assert resolved.drugs == scope.drugs
    assert resolved.adverse_reactions == scope.adverse_reactions
    assert ResolvedConceptCatalog.model_validate_json(resolved.model_dump_json()) == resolved
    with pytest.raises(ValueError, match="another scope"):
        adapter.resolve("scope:sha256:" + "0" * 64)


@pytest.mark.parametrize("term", ("Aspirin", "\u017femaglutide", "patient synthetic"))
def test_unsupported_or_patient_terms_never_resolve(term: str) -> None:
    with pytest.raises(ValueError):
        LocalResearchCatalogAdapter(_scope(drug=term))


@pytest.mark.parametrize(
    "version,digest",
    (
        ("m1a-concepts-v1", LOCAL_RESEARCH_CATALOG_HASH),
        ("m3.local-research-input.v1", M1A_CATALOG_HASH),
        ("unknown", M1A_CATALOG_HASH),
        ("m3.local-research-input.v1", "sha256:" + "0" * 64),
    ),
)
def test_catalog_hash_cannot_be_relabelled(version: str, digest: str) -> None:
    with pytest.raises(ValueError):
        validate_catalog_identity(version, digest)
    scope = _scope()
    with pytest.raises(ValidationError):
        ResolvedConceptCatalog(
            catalog_version=version,  # type: ignore[arg-type]
            catalog_content_hash=digest,
            drugs=scope.drugs,
            adverse_reactions=scope.adverse_reactions,
        )
