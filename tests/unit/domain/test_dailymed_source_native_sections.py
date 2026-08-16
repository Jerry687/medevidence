from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from medevidence.domain import DailyMedSourceNativeSectionV1

SETID = "11111111-1111-1111-1111-111111111111"


def _section(**changes: Any) -> DailyMedSourceNativeSectionV1:
    values: dict[str, Any] = {
        "setid": SETID,
        "spl_version": "3",
        "code_system_oid": "2.16.840.1.113883.6.1",
        "section_code": "34084-4",
        "normalized_section_name": "FDA package insert Adverse reactions section",
        "provider_title": "6.1 Clinical Trials Experience",
        "section_ordinal": 4,
        "parent_section_ordinal": 3,
        "xml_path": "/document/component[1]/structuredBody[1]/component[4]/section[1]",
        "extracted_text": "Exact source text",
    }
    values.update(changes)
    return DailyMedSourceNativeSectionV1.create(**values)


def test_source_native_model_separates_normalized_name_and_provider_title() -> None:
    section = _section()

    assert section.normalized_section_name == "FDA package insert Adverse reactions section"
    assert section.provider_title == "6.1 Clinical Trials Experience"
    assert section.retrieval_eligible is True
    assert section.is_structural_container is False


def test_source_native_model_rejects_normalized_name_and_digest_drift() -> None:
    with pytest.raises(ValidationError, match="frozen LOINC name"):
        _section(normalized_section_name="6 ADVERSE REACTIONS")

    section = _section()
    drifted = section.model_dump(mode="python")
    drifted["text_sha256"] = "sha256:" + ("0" * 64)
    with pytest.raises(ValidationError, match="text digest"):
        DailyMedSourceNativeSectionV1.model_validate(drifted)

    with pytest.raises(ValidationError, match="code_system_oid"):
        _section(code_system_oid="http://loinc.org")


def test_source_native_model_requires_explicit_code_system_oid() -> None:
    section = _section()
    values = section.model_dump(
        mode="python",
        exclude={
            "section_occurrence_id",
            "code_system_oid",
            "text_sha256",
            "is_structural_container",
            "retrieval_eligible",
        },
    )

    with pytest.raises(ValidationError, match="code_system_oid"):
        DailyMedSourceNativeSectionV1.create(**values)


def test_source_native_model_rejects_occurrence_identity_drift() -> None:
    section = _section()
    drifted = section.model_dump(mode="python")
    drifted["xml_path"] = "/document/component[1]/structuredBody[1]/component[5]/section[1]"

    with pytest.raises(ValidationError, match="section_occurrence_id"):
        DailyMedSourceNativeSectionV1.model_validate(drifted)


def test_empty_source_native_text_is_explicitly_structural_and_not_retrievable() -> None:
    section = _section(extracted_text="")

    assert section.is_structural_container is True
    assert section.retrieval_eligible is False
    assert section.text_sha256 == (
        "sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    )

    whitespace = _section(extracted_text="  \n")
    assert whitespace.extracted_text == "  \n"
    assert whitespace.is_structural_container is True
    assert whitespace.retrieval_eligible is False


def test_source_native_model_rejects_nonpreceding_parent() -> None:
    with pytest.raises(ValidationError, match="must precede"):
        _section(parent_section_ordinal=4)
