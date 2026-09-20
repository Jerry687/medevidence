"""Deterministic source-native SPL chunking without text normalization."""

from __future__ import annotations

import pytest

from medevidence.domain import DailyMedSourceNativeSectionV1, sha256_digest
from medevidence.tools.dailymed_v2_material import (
    admit_dailymed_v2_task_chunks,
    build_dailymed_v2_chunks,
)


def _section(text: str, ordinal: int = 0) -> DailyMedSourceNativeSectionV1:
    return DailyMedSourceNativeSectionV1.create(
        setid="11111111-1111-1111-1111-111111111111",
        spl_version="3",
        code_system_oid="2.16.840.1.113883.6.1",
        section_code="34084-4",
        normalized_section_name="FDA package insert Adverse reactions section",
        provider_title="Adverse reactions",
        section_ordinal=ordinal,
        parent_section_ordinal=None,
        xml_path=f"/document/component[{ordinal + 1}]/section",
        extracted_text=text,
    )


def test_unicode_codepoint_slices_are_contiguous_and_registry_valid() -> None:
    text = "x" * 4096 + "🙂" + " y"
    chunks = build_dailymed_v2_chunks(
        run_id="run:00000000-0000-4000-8000-000000000002",
        snapshot_id="snapshot:dailymed-test",
        source_version="dailymed-label-version:sha256:" + "a" * 64,
        sections=(_section(text),),
    )
    assert tuple((item.start_codepoint, item.end_codepoint) for item in chunks) == (
        (0, 4096),
        (4096, len(text)),
    )
    assert "".join(item.chunk_text for item in chunks) == text
    assert all(item.full_section_hash == sha256_digest(text) for item in chunks)
    assert all(item.evidence().numerical_facts == () for item in chunks)
    assert chunks[1].chunk_text == "🙂 y"


def test_no_text_parent_produces_no_retrieval_evidence() -> None:
    assert (
        build_dailymed_v2_chunks(
            run_id="run:00000000-0000-4000-8000-000000000002",
            snapshot_id="snapshot:dailymed-test",
            source_version="dailymed-label-version:sha256:" + "a" * 64,
            sections=(_section(" \n"),),
        )
        == ()
    )


def test_101st_chunk_blocks_label_before_any_partial_evidence_return() -> None:
    with pytest.raises(ValueError, match="chunk_cap_exceeded"):
        build_dailymed_v2_chunks(
            run_id="run:00000000-0000-4000-8000-000000000002",
            snapshot_id="snapshot:dailymed-test",
            source_version="dailymed-label-version:sha256:" + "a" * 64,
            sections=(
                _section("x" * (4096 * 64), 0),
                _section("y" * (4096 * 37), 1),
            ),
        )


def test_two_valid_labels_exceed_task_cap_without_partial_admission() -> None:
    common = {
        "run_id": "run:00000000-0000-4000-8000-000000000002",
        "snapshot_id": "snapshot:dailymed-test",
        "source_version": "dailymed-label-version:sha256:" + "a" * 64,
    }
    first = build_dailymed_v2_chunks(**common, sections=(_section("x" * (4096 * 60), 0),))
    second = build_dailymed_v2_chunks(**common, sections=(_section("y" * (4096 * 41), 1),))
    assert len(first) == 60 and len(second) == 41
    with pytest.raises(ValueError, match="task_chunk_cap_exceeded"):
        admit_dailymed_v2_task_chunks((first, second))
    assert admit_dailymed_v2_task_chunks((first, second[:-1])) == first + second[:-1]
