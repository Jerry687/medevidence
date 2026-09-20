from __future__ import annotations

import pytest
from tests.unit.tools.test_faers import _execution, _request

from medevidence.tools.report_validation import _copy_evidence, canonical_evidence_id
from medevidence.tools.source_evidence_material import (
    canonical_faers_bucket_bytes,
    canonical_faers_bucket_evidence,
)


def test_faers_bucket_material_is_exact_numeric_source_evidence() -> None:
    execution = _execution(_request())
    evidence = canonical_faers_bucket_evidence(execution, 0)
    assert evidence.evidence_id == canonical_evidence_id(evidence)
    assert evidence.numerical_facts[0].exact_text in evidence.normalized_excerpt
    assert "reaction_pt=NAUSEA" in evidence.normalized_excerpt
    assert "2025-01-01/2025-01-31" in evidence.normalized_excerpt
    assert _copy_evidence(evidence) == evidence
    assert evidence.numerical_facts[0].value == "7"
    assert evidence.numerical_facts[0].unit == "provider_count_occurrence"
    assert evidence.numerical_facts[0].denominator == "no exposure denominator"
    assert b'"report_count":7' in canonical_faers_bucket_bytes(execution, 0)


def test_faers_bucket_material_rejects_foreign_or_tampered_order() -> None:
    execution = _execution(_request())
    with pytest.raises(ValueError, match="ordinal"):
        canonical_faers_bucket_evidence(execution, 1)
    bucket = execution.result.buckets[0].model_copy(update={"bucket_ordinal": 1})
    tampered = execution.model_copy(
        update={"result": execution.result.model_copy(update={"buckets": (bucket,)})}
    )
    with pytest.raises(ValueError):
        canonical_faers_bucket_evidence(tampered, 0)
